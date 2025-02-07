import asyncio
import ssl
from importlib.metadata import version
from typing import Optional, Union, Tuple, Dict, AsyncContextManager

from aioquic.quic.configuration import QuicConfiguration
from aioquic.asyncio.client import connect
from aioquic.h3.connection import H3_ALPN

from .protocol import MOQTProtocol
from .types import FilterType, GroupOrder, SessionCloseCode, MOQTMessageType, SubscribeErrorCode
from .messages.setup import *
from .messages.announce import *
from .messages.subscribe import *
from .utils.logger import get_logger, QuicDebugLogger

logger = get_logger(__name__)

USER_AGENT = f"aiomoqt-client/{version('aiomoqt')}"


class MOQTClientProtocol(MOQTProtocol):
    """MOQT client implementation."""

    def __init__(self, *args, client: 'MOQTClient', **kwargs):
        super().__init__(*args, **kwargs)
        self._client = client

        # Register handler using closure to capture self
        async def handle_server_setup(msg: MOQTMessage) -> None:
            assert isinstance(msg, ServerSetup)
            logger.info(f"Received ServerSetup: {msg}")

            if self._moqt_session.is_set():
                error = "Received multiple SERVER_SETUP message"
                logger.error(error)
                self.close(
                    error_code=SessionCloseCode.PROTOCOL_VIOLATION,
                    reason_phrase=error
                )
                raise RuntimeError(error)
            # indicate moqt session setup is complete
            self._moqt_session.set()

        # Register the closure as the handler
        self.message_handler.register_handler(
            MOQTMessageType.SERVER_SETUP,
            handle_server_setup
        )

        # Register handler using closure to capture self
        async def handle_subscribe(msg: MOQTMessage) -> None:
            assert isinstance(msg, Subscribe)
            logger.info(f"Received Subscribe: {msg}")

            self.subscribe_ok(msg.subscribe_id)

        # Register the closure as the handler
        self.message_handler.register_handler(
            MOQTMessageType.SUBSCRIBE,
            handle_subscribe
        )

    async def initialize(self) -> None:
        """Initialize WebTransport and MOQT session."""
        # Create WebTransport session
        self._session_id = self._h3._quic.get_next_available_stream_id(
            is_unidirectional=False
        )

        headers = [
            (b":method", b"CONNECT"),
            (b":protocol", b"webtransport"),
            (b":scheme", b"https"),
            (b":authority",
             f"{self._client.host}:{self._client.port}".encode()),
            (b":path", f"/{self._client.endpoint}".encode()),
            (b"sec-webtransport-http3-draft", b"draft02"),
            (b"user-agent", USER_AGENT.encode()),
        ]

        logger.info(
            f"WebTransport connect send: (stream: {self._session_id})")
        self._h3.send_headers(stream_id=self._session_id,
                              headers=headers, end_stream=False)
        self.transmit()
        # Wait for WebTransport session establishment
        try:
            await asyncio.wait_for(self._wt_session.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            logger.error("WebTransport session establishment timeout")
            raise

        # Create MOQT control stream
        self._control_stream_id = self._h3.create_webtransport_stream(
            session_id=self._session_id
        )
        logger.info(f"Created control stream: {self._control_stream_id}")

        # Send CLIENT_SETUP
        logger.info("Sending CLIENT_SETUP")
        self.send_control_message(
            ClientSetup(
                versions=[0xff000007],
                parameters={}
            ).serialize()
        )
        # Wait for SERVER_SETUP
        try:
            await asyncio.wait_for(self._moqt_session.wait(), timeout=10)
            logger.info("MOQT session setup complete")
        except asyncio.TimeoutError:
            logger.error("MOQT session setup timeout")
            raise

    @classmethod
    def _make_namespace_tuple(cls, namespace: Union[str, Tuple[str, ...]]) -> Tuple[bytes, ...]:
        """Convert string or tuple into bytes tuple."""
        if isinstance(namespace, str):
            return tuple(part.encode() for part in namespace.split('/'))
        elif isinstance(namespace, tuple):
            if all(isinstance(x, bytes) for x in namespace):
                return namespace
            return tuple(part.encode() if isinstance(part, str) else part
                         for part in namespace)
        raise ValueError(
            "namespace must be string with '/' delimiters or tuple")

    def subscribe(
        self,
        namespace: str,
        track_name: str,
        subscribe_id: int = 1,
        track_alias: int = 1,
        priority: int = 128,
        group_order: GroupOrder = GroupOrder.ASCENDING,
        filter_type: FilterType = FilterType.LATEST_GROUP,
        start_group: Optional[int] = None,
        start_object: Optional[int] = None,
        end_group: Optional[int] = None,
        parameters: Optional[Dict[int, bytes]] = None
    ) -> None:
        """Subscribe to a track with configurable options."""
        logger.info(f"Subscribing to {namespace}/{track_name}")

        if parameters is None:
            parameters = {}
        namespace_tuple = self._make_namespace_tuple(namespace)
        self.send_control_message(
            Subscribe(
                subscribe_id=subscribe_id,
                track_alias=track_alias,
                namespace=namespace_tuple,
                track_name=track_name.encode(),
                priority=priority,
                direction=group_order,
                filter_type=filter_type,
                start_group=start_group,
                start_object=start_object,
                end_group=end_group,
                parameters=parameters
            ).serialize()
        )

    def subscribe_ok(
        self,
        subscribe_id: int,
        expires: int = 0,  # 0 means no expiry
        group_order: int = GroupOrder.ASCENDING,
        content_exists: int = 0,
        largest_group_id: Optional[int] = None,
        largest_object_id: Optional[int] = None,
        parameters: Optional[Dict[int, bytes]] = None
    ) -> SubscribeOk:
        """Create and send a SUBSCRIBE_OK response."""
        logger.info(f"Sending SUBSCRIBE_OK for subscription {subscribe_id}")

        message = SubscribeOk(
            subscribe_id=subscribe_id,
            expires=expires,
            group_order=group_order,
            content_exists=content_exists,
            largest_group_id=largest_group_id,
            largest_object_id=largest_object_id,
            parameters=parameters or {}
        )
        self.send_control_message(message.serialize())
        return message

    def subscribe_error(
        self,
        subscribe_id: int,
        error_code: int = SubscribeErrorCode.INTERNAL_ERROR,
        reason: str = "Internal error",
        track_alias: Optional[int] = None
    ) -> SubscribeError:
        """Create and send a SUBSCRIBE_ERROR response."""
        logger.info(
            f"Sending SUBSCRIBE_ERROR: sub-id {subscribe_id}: {reason} ({error_code})")

        message = SubscribeError(
            subscribe_id=subscribe_id,
            error_code=error_code,
            reason=reason,
            track_alias=track_alias
        )
        self.send_control_message(message.serialize())
        return message

    def announce(
        self,
        namespace: Union[str, Tuple[str, ...]],
        parameters: Optional[Dict[int, bytes]] = None
    ) -> Announce:
        """Announce track namespace availability."""
        namespace_tuple = self._make_namespace_tuple(namespace)
        logger.info(f"Announcing namespace: {namespace_tuple}")

        message = Announce(
            namespace=namespace_tuple,
            parameters=parameters or {}
        )
        self.send_control_message(message.serialize())
        return message

    def unannounce(
        self,
        namespace: Tuple[bytes, ...]
    ) -> None:
        """Withdraw track namespace announcement."""
        logger.info(f"Unannouncing namespace: {namespace}")

        self.send_control_message(
            Unannounce(
                namespace=namespace
            ).serialize()
        )

    def unsubscribe(
        self,
        subscribe_id: int
    ) -> None:
        """Unsubscribe from a track."""
        logger.info(f"Unsubscribing from subscription {subscribe_id}")

        self.send_control_message(
            Unsubscribe(
                subscribe_id=subscribe_id
            ).serialize()
        )

    def subscribe_announces(
        self,
        namespace_prefix: str,
        parameters: Optional[Dict[int, bytes]] = None
    ) -> None:
        """Subscribe to announcements for a namespace prefix."""
        logger.info(f"Subscribe announces: prefix {namespace_prefix}")

        if parameters is None:
            parameters = {}
        prefix = self._make_namespace_tuple(namespace_prefix)
        self.send_control_message(
            SubscribeAnnounces(
                namespace_prefix=prefix,
                parameters=parameters
            ).serialize()
        )

    def unsubscribe_announces(
        self,
        namespace_prefix: str
    ) -> None:
        """Unsubscribe from announcements for a namespace prefix."""
        logger.info(f"Unsubscribe announces: prefix {namespace_prefix}")
        prefix = self._make_namespace_tuple(namespace_prefix)
        self.send_control_message(
            UnsubscribeAnnounces(
                namespace_prefix=prefix
            ).serialize()
        )


class MOQTClient:  # New connection manager class
    def __init__(
        self,
        host: str,
        port: int,
        endpoint: Optional[str] = None,
        configuration: Optional[QuicConfiguration] = None,
        debug: bool = False
    ):
        self.host = host
        self.port = port
        self.debug = debug
        self.endpoint = endpoint
        if configuration is None:
            configuration = QuicConfiguration(
                alpn_protocols=H3_ALPN,
                is_client=True,
                verify_mode=ssl.CERT_NONE,
                quic_logger=QuicDebugLogger() if debug else None,
                secrets_log_file=open(
                    "/tmp/keylog.client.txt", "a") if debug else None
            )
        self.configuration = configuration
        logger.debug(f"quic_logger: {configuration.quic_logger.__class__}")

    def connect(self) -> AsyncContextManager[MOQTClientProtocol]:
        """Return a context manager that creates MOQTClientProtocol instance."""
        logger.debug(f"MOQTClient: connect: {self.__class__}")
        return connect(
            self.host,
            self.port,
            configuration=self.configuration,
            create_protocol=lambda *args, **kwargs: MOQTClientProtocol(
                *args, **kwargs, client=self)
        )
