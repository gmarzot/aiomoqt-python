import asyncio
import ssl
from importlib.metadata import version
from typing import Optional, Dict, AsyncContextManager

from aioquic.quic.configuration import QuicConfiguration
from aioquic.asyncio.client import connect
from aioquic.h3.connection import H3_ALPN

from .protocol import MOQTProtocol
from .types import FilterType, GroupOrder, SessionCloseCode, MessageTypes
from .messages.setup import *
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
                error = "Received duplicate SERVER_SETUP message"
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
            MessageTypes.SERVER_SETUP,
            handle_server_setup
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

        self.send_control_message(
            Subscribe(
                subscribe_id=subscribe_id,
                track_alias=track_alias,
                namespace=namespace.encode(),
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
