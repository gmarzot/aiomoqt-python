import asyncio
from asyncio import Future
from typing import Optional, Union, Tuple, Dict, Callable
from importlib.metadata import version

from aioquic.buffer import Buffer, UINT_VAR_MAX
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.connection import QuicConnection
from aioquic.quic.events import QuicEvent, StreamDataReceived
from aioquic.h3.connection import H3Connection, ErrorCode
from aioquic.h3.events import HeadersReceived, DataReceived

from .types import *
from .messages import *
from .utils.logger import get_logger

logger = get_logger(__name__)

USER_AGENT = f"aiomoqt-client/{version('aiomoqt')}"

class MOQTException(Exception):
    def __init__(self, error_code: SessionCloseCode, reason_phrase: str):
        self.error_code = error_code
        self.reason_phrase = reason_phrase
        super().__init__(f"{reason_phrase} ({error_code})")
        

class H3CustomConnection(H3Connection):
    """Custom H3Connection wrapper to support alternate SETTINGS"""
    
    def __init__(self, quic: QuicConnection, table_capacity: int = 0, **kwargs) -> None:
        # settings table capacity can be overridden - this should be generalized
        self._max_table_capacity = table_capacity
        self._max_table_capacity_arg = table_capacity
        super().__init__(quic, **kwargs)
        # report sent settings
        settings = self.sent_settings
        if settings is not None:
            logger.debug("H3 SETTINGS sent:")
            for setting_id, value in settings.items():
                logger.debug(f"  Setting 0x{setting_id:x} = {value}")

    @property
    def _max_table_capacity(self):
        return self._max_table_capacity_arg

    @_max_table_capacity.setter
    def _max_table_capacity(self, value):
        # Ignore the parent class attempt to set it
        pass
    

# base class for client and server session objects
class MOQTSession:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError()


class MOQTSessionProtocol(QuicConnectionProtocol):
    """MOQT session protocol implementation."""

    def __init__(self, *args, session: 'MOQTSession', **kwargs):
        super().__init__(*args, **kwargs)
        self._session_cfg = session  # backref to session object with config
        self._h3: Optional[H3Connection] = None
        self._session_id: Optional[int] = None
        self._control_stream_id: Optional[int] = None
        self._streams: Dict[int, Dict] = {}
        self._tasks = set()
        self._loop = asyncio.get_running_loop()
        self._wt_session_fut = self._loop.create_future()
        self._moqt_session_fut = self._loop.create_future()
        self._moqt_session_close = self._loop.create_future()
        self._next_subscribe_id = 1  # prime subscribe id generator
        self._next_track_alias = 1  # prime track alias generator
        self._announce_responses: Dict[int, Future[MOQTMessage]] = {}
        self._subscribe_responses: Dict[int, Future[MOQTMessage]] = {}
        self._unsubscribe_responses: Dict[int, Future[MOQTMessage]] = {}
        self._fetch_responses: Dict[int, Future[MOQTMessage]] = {}
        self._message_registry = dict(MOQTSessionProtocol.MOQT_MESSAGE_REGISTRY)
        self._close = None

    @staticmethod
    def _make_namespace_tuple(namespace: Union[str, Tuple[str, ...]]) -> Tuple[bytes, ...]:
        """Convert string or tuple into bytes tuple."""
        if isinstance(namespace, str):
            return tuple(part.encode() for part in namespace.split('/'))
        elif isinstance(namespace, tuple):
            if all(isinstance(x, bytes) for x in namespace):
                return namespace
            return tuple(part.encode() if isinstance(part, str) else part for part in namespace)
        raise ValueError("namespace must be string with '/' delimiters or tuple")

    def _allocate_subscribe_id(self) -> int:
        """Get next available subscribe ID."""
        subscribe_id = self._next_subscribe_id
        self._next_subscribe_id += 1
        return subscribe_id

    def _allocate_track_alias(self) -> int:
        """Get next available track alias."""
        track_alias = self._next_track_alias
        self._next_track_alias += 1
        return track_alias

    async def initialize(self, timeout: int = 10) -> None:
        """Initialize WebTransport and MOQT session."""
        # Create WebTransport session
        self._session_id = self._h3._quic.get_next_available_stream_id(is_unidirectional=False)

        headers = [
            (b":method", b"CONNECT"),
            (b":protocol", b"webtransport"),
            (b":scheme", b"https"),
            (b":authority",
             f"{self._session_cfg.host}:{self._session_cfg.port}".encode()),
            (b":path", f"/{self._session_cfg.endpoint}".encode()),
            (b"sec-webtransport-http3-draft", b"draft02"),
            (b"user-agent", USER_AGENT.encode()),
        ]

        logger.info(f"H3 send: WebTransport CONNECT: (session id: {self._session_id})")
        for name, value in headers:
            logger.debug(f"  {name.decode()}: {value.decode()}")
            
        self._h3.send_headers(stream_id=self._session_id, headers=headers, end_stream=False)
        self.transmit()
        # Wait for WebTransport session establishment
        try:
            async with asyncio.timeout(timeout):
                result = await self._wt_session_fut
            logger.debug(f"H3 event: WebTransport setup: {result} ({self._close})")
        except asyncio.TimeoutError:
            logger.error("WebTransport session establishment timeout")
            raise

        # check for H3 connection close
        if self._close:
            raise RuntimeError(self._close)
    
        # Create MOQT control stream
        self._control_stream_id = self._h3.create_webtransport_stream(session_id=self._session_id)
        logger.info(f"MOQT: Created control stream: (stream id: {self._control_stream_id})")

        # Send CLIENT_SETUP
        client_setup = ClientSetup(
            versions=[0xff000007],
            parameters={SetupParamType.MAX_SUBSCRIBER_ID: MOQTMessage._varint_encode(1000)}
        )
        logger.info(f"MOQT send: {client_setup}")
        self.send_control_message(client_setup.serialize()
        )
        # Wait for SERVER_SETUP
        try:
            result = await self._moqt_session_fut
            logger.info(f"MOQT session setup complete: {result}")
        except asyncio.TimeoutError:
            logger.error("MOQT session setup timeout")
            raise

    # def transmit(self) -> None:
    #     """Transmit pending data."""
    #     logger.debug("Transmitting data")
    #     super().transmit()

    def connection_made(self, transport):
        """Called when QUIC connection is established."""
        super().connection_made(transport)
        self._h3 = H3CustomConnection(self._quic, enable_webtransport=True)
        logger.info("H3 connection initialized")

    def quic_event_received(self, event: QuicEvent) -> None:
        """Handle incoming QUIC events."""
        # Log any errors
        if hasattr(event, 'error_code'):
            error = getattr(event, 'error_code')
            reason = getattr(event, 'reason_phrase')
            logger.error(f"QUIC event: error: {error} reason: {reason}")
            return

        stream_id = getattr(event, 'stream_id', 'unknown')
        classname = event.__class__.__name__
        data = "0x" + event.data.hex() if (hasattr(event, 'data') and event.data is not None) else ""
        logger.debug(f"QUIC event: stream {stream_id}: {classname}: {data}")

        # Handle MOQT control and data messages
        if isinstance(event, StreamDataReceived):
            if stream_id == self._control_stream_id:
                msgbuf = Buffer(data=event.data)
                while msgbuf.tell() < msgbuf.capacity:
                    msg = self.handle_control_message(msgbuf)
                    logger.debug(f"MOQT event: control message processed: {msg} {msgbuf.tell()}")
                return
            elif stream_id in self._streams:
                self.handle_data_message(stream_id, event.data)
                return

        # Pass remaining events to H3
        if self._h3 is not None:
            try:
                for h3_event in self._h3.handle_event(event):
                    self._h3_event_received(h3_event)

                if (isinstance(event, StreamDataReceived) and hasattr(event, 'data') and
                    event.data is not None and event.data[:2] == b'\x00\x04'):
                    logger.debug("H3 SETTINGS received:")
                    # Check received settings
                    settings = self._h3.received_settings
                    if settings is not None:
                        for setting_id, value in settings.items():
                            logger.debug(f"  Setting 0x{setting_id:x} = {value}")

            except Exception as e:
                logger.error(f"H3 error: error handling event: {e}")
                raise
        else:
            logger.error(f"QUIC event: stream {stream_id}: event not handled({classname})")

    def handle_control_message(self, buffer: Buffer) -> Optional[MOQTMessage]:
        """Process an incoming message."""
        if buffer.capacity <= 0:
            logger.warning("handle_control_message: no data")
            return None

        try:
            start_pos = buffer.tell()
            msg_type = buffer.pull_uint_var()
            msg_len = buffer.pull_uint_var()
            hdr_len = buffer.tell() - start_pos
            # Look up message class
            message_class, handler = self._message_registry.get(msg_type)
            if message_class is None:
                logger.error(f"MOQT error: unknown control message ({hex(msg_type)})")
                return None

            # Deserialize message
            msg = message_class.deserialize(buffer)
            msg_len += hdr_len
            assert (start_pos + msg_len == buffer.tell())
            logger.info(f"MOQT event: control message: {msg} ({msg_len} bytes)")

            # Schedule handler if one exists
            if handler:
                task = asyncio.create_task(handler(self, msg))
                task.add_done_callback(lambda t: self._tasks.discard(t))
                self._tasks.add(task)


            return msg

        except Exception as e:
            logger.error(f"handle_control_message: error handling control message: {e}")
            raise

    def handle_data_message(self, stream_id: int, buffer: Buffer) -> None:
        """Process incoming data messages (not control messages)."""
        if buffer.capacity <= 0:
            logger.error(f"MOQT event: stream {stream_id}: message contains no data")
            return

        try:
            # Get stream type from first byte
            stream_type = buffer.pull_uint_var()
            logger.info(f"MOQT: stream {stream_id}: type: {hex(stream_type)}")

            # Look up stream message class
            message_class = self._stream_types.get(stream_type)
            if message_class is None:
                logger.error(f"MOQT error: unknown stream type ({hex(stream_type)})")
                return

            if stream_type == StreamType.STREAM_HEADER_SUBGROUP:
                msg = message_class.deserialize(buffer)
                logger.info(f"MOQT event: stream message: {msg}")
                self._handle_subgroup_header(msg)
                return

            # Process remaining buffer as object data
            self._handle_object_data(buffer)

        except Exception as e:
            logger.error(f"handle_data_message: error handling data message: {e}")


    def _h3_event_received(self, event: QuicEvent) -> None:
        """Handle H3-specific events."""
        if isinstance(event, HeadersReceived):
            self._h3_handle_headers_received(event)
        elif isinstance(event, DataReceived):
            self._h3_handle_data_received(event)
        else:
            msg_class = event.__class__.__name__
            data = "0x" + event.data.hex() if (hasattr(event, 'data') and event.data is not None) else ""
            logger.error(f"H3 error: stream {event.stream_id}: {msg_class}: {data}")

    def _h3_handle_headers_received(self, event: HeadersReceived) -> None:
        """Process incoming H3 headers."""
        status = None
        logger.info(f"H3 event: HeadersReceived: (session id: {event.stream_id})")
        for name, value in event.headers:
            logger.debug(f"  {name.decode()}: {value.decode()}")
            if name == b':status':
                status = value

        stream_id = event.stream_id
        if status == b"200":
            logger.info(f"H3 event: WebTransport session established: (session id: {stream_id})")
            self._wt_session_fut.set_result(True)
        else:
            error = f"WebTransport session setup failed ({status})"
            logger.error(f"H3 error: stream {stream_id}: " + error)
            self._close = (ErrorCode.H3_CONNECT_ERROR, error)
            self._wt_session_fut.set_result(False)

    def _h3_handle_data_received(self, event: DataReceived) -> None:
        """Process incoming H3 data MOQT data is not expected to arrive like this"""
        logger.warning(f"H3 event: stream {event.stream_id}: DataReceived")
        if hasattr(event, 'data'):
            logger.debug(f"H3 event: stream {event.stream_id}: data: 0x{event.data.hex()}")

    def register_handler(self, msg_type: int, handler: Callable) -> None:
        """Register a custom message handler."""
        self._custom_handlers[msg_type] = handler

    def send_control_message(self, buf: Buffer) -> None:
        """Send a MOQT message on the control stream."""
        if self._quic is None or self._control_stream_id is None:
            raise RuntimeError("Control stream not initialized")

        self._quic.send_stream_data(
            stream_id=self._control_stream_id,
            data=buf.data,
            end_stream=False
        )
        self.transmit()

    def close(self, error_code: SessionCloseCode = SessionCloseCode.NO_ERROR, reason_phrase: str = "MOQT Session Close") -> None:
        """Close the MOQT session."""
        logger.info(f"MOQT session: Closing: {reason_phrase} ({error_code})")
        if self._session_id is not None:
            logger.debug(f"H3 session: Closing: stream {self._session_id}")
            self._h3.send_data(self._session_id, b"", end_stream=True)
            self._session_id = None
        self._h3 = None
        # set the exit condition for the async with session
        if not self._moqt_session_close.done:
            self._moqt_session_close.set_result(True)
        # call parent close and transmit all
        super().close(error_code=error_code, reason_phrase=reason_phrase)
        self.transmit()


    ################################################################################################
    #  Outbound MoQT control message API - note: awaitable messages support 'wait_response' param  #
    ################################################################################################
    def subscribe(
        self,
        namespace: str,
        track_name: str,
        subscribe_id: int = None,
        track_alias: int = None,
        priority: int = 128,
        group_order: GroupOrder = GroupOrder.ASCENDING,
        filter_type: FilterType = FilterType.LATEST_GROUP,
        start_group: Optional[int] = 0,
        start_object: Optional[int] = 0,
        end_group: Optional[int] = 0,
        parameters: Optional[Dict[int, bytes]] = None,
        wait_response: Optional[bool] = False,
    ) -> None:
        """Subscribe to a track with configurable options."""
        if parameters is None:
            parameters = {}
        subscribe_id = self._allocate_subscribe_id() if subscribe_id is None else subscribe_id
        track_alias = self._allocate_track_alias() if track_alias is None else track_alias
        namespace_tuple = self._make_namespace_tuple(namespace)
        message = Subscribe(
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
        )
        logger.info(f"MOQT send: {message}")
        self.send_control_message(message.serialize())

        if not wait_response:
            return message

        # Create future for response
        subscribe_fut = self._loop.create_future()
        self._subscribe_responses[subscribe_id] = subscribe_fut

        async def wait_for_response():
            try:
                async with asyncio.timeout(10):
                    response = await subscribe_fut
            except asyncio.TimeoutError:
                # Create synthetic error response
                response = SubscribeError(
                    subscribe_id=subscribe_id,
                    error_code=0x5,  # TIMEOUT error code
                    reason="Subscribe Response Timeout",
                    track_alias=0
                )
                logger.error(f"Timeout waiting for subscribe response")
            finally:
                logger.error(f"Popping off subscribe response future: {subscribe_id}")
                self._subscribe_responses.pop(subscribe_id, None)    
            return response

        return wait_for_response()

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
        message = SubscribeOk(
            subscribe_id=subscribe_id,
            expires=expires,
            group_order=group_order,
            content_exists=content_exists,
            largest_group_id=largest_group_id,
            largest_object_id=largest_object_id,
            parameters=parameters or {}
        )
        logger.info(f"MOQT send: {message}")
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
        message = SubscribeError(
            subscribe_id=subscribe_id,
            error_code=error_code,
            reason=reason,
            track_alias=track_alias
        )
        logger.info(f"MOQT send: {message}")
        self.send_control_message(message.serialize())
        return message

    def announce(
        self,
        namespace: Union[str, Tuple[str, ...]],
        parameters: Optional[Dict[int, bytes]] = None,
        wait_response: Optional[bool] = False
    ) -> Announce:
        """Announce track namespace availability."""
        namespace_tuple = self._make_namespace_tuple(namespace)
        message = Announce(
            namespace=namespace_tuple,
            parameters=parameters or {}
        )
        logger.info(f"MOQT send: {message}")
        self.send_control_message(message.serialize())

        if not wait_response:
            return message

        # Create future for response
        announce_fut = self._loop.create_future()
        self._announce_responses[namespace_tuple] = announce_fut

        async def wait_for_response():
            try:
                async with asyncio.timeout(10):
                    response = await announce_fut
            except asyncio.TimeoutError:
                # Create synthetic error response
                response = AnnounceError(
                    namespace=namespace,
                    error_code=0x5,  # TIMEOUT error code
                    reason="Response timeout"
                )
                logger.error(f"Timeout waiting for announce response")
            finally:
                self._announce_responses.pop(namespace, None)
            return response

        return wait_for_response()

    def announce_ok(
        self,
        namespace: Union[str, Tuple[str, ...]],
    ) -> AnnounceOk:
        """Create and send a ANNOUNCE_OK response."""
        namespace_tuple = self._make_namespace_tuple(namespace)
        message = AnnounceOk(
            namespace=namespace_tuple,
        )
        logger.info(f"MOQT send: {message}")
        self.send_control_message(message.serialize())
        return message

    def unannounce(
        self,
        namespace: Tuple[bytes, ...]
    ) -> None:
        """Withdraw track namespace announcement. (no reply expected)"""        
        message =  Unannounce(namespace=namespace)
        logger.info(f"MOQT send: {message}")
        self.send_control_message(message.serialize())
        return message
    
    def unsubscribe(
        self,
        subscribe_id: int,
        wait_response: Optional[bool] = False
    ) -> None:
        """Unsubscribe from a track."""
        message = Unsubscribe(subscribe_id=subscribe_id)
        logger.info(f"MOQT send: {message}")
        self.send_control_message(message.serialize())
 
        if not wait_response:
            return message       

        # Create future for response
        unsubscribe_fut = self._loop.create_future()
        self._unsubscribe_responses[subscribe_id] = unsubscribe_fut

        async def wait_for_response():
            try:
                async with asyncio.timeout(10):
                    response = await unsubscribe_fut
            except asyncio.TimeoutError:
                # Create synthetic error response
                response = SubscribeDone(
                    subscribe_id=subscribe_id,
                    stream_count=0,  # XXX what to do
                    status_code=SubscribeDoneCode.INTERNAL_ERROR,  # TIMEOUT error code
                    reason="Unsubscribe Response Timeout"
                )
                logger.error(f"Timeout waiting for announce response")
            finally:
                self._unsubscribe_responses.pop(subscribe_id, None)
            return response

        return wait_for_response()

    def subscribe_announces(
        self,
        namespace_prefix: str,
        parameters: Optional[Dict[int, bytes]] = None,
        wait_response: Optional[bool] = False
    ) -> None:
        """Subscribe to announcements for a namespace prefix."""
        if parameters is None:
            parameters = {}

        prefix = self._make_namespace_tuple(namespace_prefix)
        message = SubscribeAnnounces(
            namespace_prefix=prefix,
            parameters=parameters
        )
        logger.info(f"MOQT send: {message}")
        self.send_control_message(message.serialize())

        if not wait_response:
            return message

        # Create future for response
        sub_announces_fut = self._loop.create_future()
        self._subscribe_responses[prefix] = sub_announces_fut

        async def wait_for_response():
            try:
                async with asyncio.timeout(10):
                    response = await sub_announces_fut
            except asyncio.TimeoutError:
                # Create synthetic error response
                response = SubscribeAnnouncesError(
                    namespace_prefix=prefix,
                    error_code=0x5,  # TIMEOUT error code
                    reason="Response timeout"
                )
                logger.error(f"Timeout waiting for announce subscribe response")
            finally:
                self._subscribe_responses.pop(prefix, None)
            
            return response

        return wait_for_response()

    def subscribe_announces_ok(
        self,
        namespace_prefix: Union[str, Tuple[str, ...]],
    ) -> SubscribeAnnouncesOk:
        """Create and send a SUBSCRIBE_ANNOUNCES_OK response."""
        namespace_tuple = self._make_namespace_tuple(namespace_prefix)
        logger.info(f"MOQT send: {message}")
        message = SubscribeAnnouncesOk(namespace_prefix=namespace_tuple)
        self.send_control_message(message.serialize())
        return message

    def unsubscribe_announces(
        self,
        namespace_prefix: str
    ) -> None:
        """Unsubscribe from announcements for a namespace prefix."""        
        prefix = self._make_namespace_tuple(namespace_prefix)
        message = UnsubscribeAnnounces(namespace_prefix=prefix)
        logger.info(f"MOQT send: {message}")
        self.send_control_message(message.serialize())
        return message


    ###############################################################################################
    #  Inbound MoQT message handlers                                                              #
    ###############################################################################################
    async def _handle_server_setup(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, ServerSetup)
        logger.info(f"MOQT handle: {msg}")

        if self._moqt_session_fut.done():
            error = "Received multiple SERVER_SETUP message"
            logger.error(error)
            self.close(
                error_code=SessionCloseCode.PROTOCOL_VIOLATION,
                reason_phrase=error
            )
            raise RuntimeError(error)
        # indicate moqt session setup is complete
        self._moqt_session_fut.set_result(True)

    async def _handle_client_setup(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, ClientSetup)
        logger.info(f"MOQT handle: {msg}")
        # Send SERVER_SETUP in response

    async def _handle_subscribe(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, Subscribe)
        logger.info(f"MOQT receive: {msg}")
        self.subscribe_ok(msg.subscribe_id)

    async def _handle_announce(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, Announce)
        logger.info(f"MOQT receive: {msg}")
        self.announce_ok(msg.namespace)

    async def _handle_subscribe_update(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, SubscribeUpdate)
        logger.info(f"MOQT handle: {msg}")
        # Handle subscription update

    async def _handle_subscribe_ok(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, SubscribeOk)
        logger.info(f"MOQT handle: {msg}")
        # Set future result for subscriber waiting for response
        future = self._subscribe_responses.get(msg.subscribe_id)
        logger.debug(f"_handle_subscribe_ok: looking up future: {msg.subscribe_id}: {future}")
        if future and not future.done():
            logger.debug(f"_handle_subscribe_ok: looking up future: {msg.subscribe_id}: {future}")
            future.set_result(msg)

    async def _handle_subscribe_error(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, SubscribeError)
        logger.info(f"MOQT handle: {msg}")
        # Set future result for subscriber waiting for response
        future = self._subscribe_responses.get(msg.subscribe_id)
        if future and not future.done():
            future.set_result(msg)

    async def _handle_announce_ok(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, AnnounceOk)
        logger.info(f"MOQT handle: {msg}")
        # Set future result for announcer waiting for response
        future = self._announce_responses.get(msg.namespace)
        logger.debug(f"_handle_announce_ok: looking up future: {msg.namespace}: {future}")
        if future and not future.done():
            future.set_result(msg)

    async def _handle_announce_error(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, AnnounceError)
        logger.info(f"MOQT handle: {msg}")
        # Set future result for announcer waiting for response
        future = self._announce_responses.get(msg.namespace)
        if future and not future.done():
            future.set_result(msg)

    async def _handle_unannounce(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, Unannounce)
        logger.info(f"MOQT handle: {msg}")
        self.announce_ok(msg.namespace)

    async def _handle_announce_cancel(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, AnnounceCancel)
        logger.info(f"MOQT handle: {msg}")
        # Handle announcement cancellation

    async def _handle_unsubscribe(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, Unsubscribe)
        logger.info(f"MOQT handle: {msg}")
        # Handle unsubscribe request

    async def _handle_subscribe_done(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, SubscribeDone)
        logger.info(f"MOQT handle: {msg}")
        # Set future result for subscriber waiting for completion
        future = self._subscribe_responses.get(msg.subscribe_id)
        if future and not future.done():
            future.set_result(msg)

    async def _handle_max_subscribe_id(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, MaxSubscribeId)
        logger.info(f"MOQT handle: {msg}")
        # Update maximum subscribe ID

    async def _handle_subscribes_blocked(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, SubscribesBlocked)
        logger.info(f"MOQT handle: {msg}")
        # Handle subscribes blocked notification

    async def _handle_track_status_request(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, TrackStatusRequest)
        logger.info(f"MOQT handle: {msg}")
        # Send track status in response

    async def _handle_track_status(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, TrackStatus)
        logger.info(f"MOQT handle: {msg}")
        # Handle track status update

    async def _handle_goaway(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, GoAway)
        logger.info(f"MOQT handle: {msg}")
        # Handle session migration request

    async def _handle_subscribe_announces(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, SubscribeAnnounces)
        logger.info(f"MOQT handle: {msg}")
        self.subscribe_announces_ok(msg.namespace_prefix)
           
    async def _handle_subscribe_announces_ok(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, SubscribeAnnouncesOk)
        logger.info(f"MOQT handle: {msg}")
        # Set future result for subscriber waiting for response
        future = self._subscribe_responses.get(msg.namespace_prefix)
        if future and not future.done():
            future.set_result(msg)

    async def _handle_subscribe_announces_error(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, SubscribeAnnouncesError)
        logger.info(f"MOQT handle: {msg}")
        # Set future result for subscriber waiting for response
        future = self._subscribe_responses.get(msg.namespace_prefix)
        if future and not future.done():
            future.set_result(msg)

    async def _handle_unsubscribe_announces(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, UnsubscribeAnnounces)
        logger.info(f"MOQT handle: {msg}")
        self.subscribe_announces_ok(msg.namespace_prefix)

    async def _handle_fetch(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, Fetch)
        logger.info(f"MOQT handle: {msg}")
        self.fetch_ok(msg.subscribe_id)

    async def _handle_fetch_cancel(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, FetchCancel)
        logger.info(f"MOQT handle: {msg}")
        # Handle fetch cancellation

    async def _handle_fetch_ok(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, FetchOk)
        logger.info(f"MOQT handle: {msg}")
        # Set future result for fetcher waiting for response
        future = self._fetch_responses.get(msg.subscribe_id)
        if future and not future.done():
            future.set_result(msg)

    async def _handle_fetch_error(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, FetchError)
        logger.info(f"MOQT handle: {msg}")
        # Set future result for fetcher waiting for response
        future = self._fetch_responses.get(msg.subscribe_id)
        if future and not future.done():
            future.set_result(msg)

    # MoQT message classes for serialize/deserialize, message handler methods (unbound)       
    MOQT_MESSAGE_REGISTRY = {
       # Setup messages
       MOQTMessageType.CLIENT_SETUP: (ClientSetup, _handle_client_setup),
       MOQTMessageType.SERVER_SETUP: (ServerSetup, _handle_server_setup),

       # Subscribe messages
       MOQTMessageType.SUBSCRIBE_UPDATE: (SubscribeUpdate, _handle_subscribe_update),
       MOQTMessageType.SUBSCRIBE: (Subscribe, _handle_subscribe),
       MOQTMessageType.SUBSCRIBE_OK: (SubscribeOk, _handle_subscribe_ok), 
       MOQTMessageType.SUBSCRIBE_ERROR: (SubscribeError, _handle_subscribe_error),

       # Announce messages
       MOQTMessageType.ANNOUNCE: (Announce, _handle_announce),
       MOQTMessageType.ANNOUNCE_OK: (AnnounceOk, _handle_announce_ok),
       MOQTMessageType.ANNOUNCE_ERROR: (AnnounceError, _handle_announce_error),
       MOQTMessageType.UNANNOUNCE: (Unannounce, _handle_unannounce),
       MOQTMessageType.ANNOUNCE_CANCEL: (AnnounceCancel, _handle_announce_cancel),

       # Subscribe control messages
       MOQTMessageType.UNSUBSCRIBE: (Unsubscribe, _handle_unsubscribe),
       MOQTMessageType.SUBSCRIBE_DONE: (SubscribeDone, _handle_subscribe_done),
       MOQTMessageType.MAX_SUBSCRIBE_ID: (MaxSubscribeId, _handle_max_subscribe_id),
       MOQTMessageType.SUBSCRIBES_BLOCKED: (SubscribesBlocked, _handle_subscribes_blocked),

       # Status messages
       MOQTMessageType.TRACK_STATUS_REQUEST: (TrackStatusRequest, _handle_track_status_request),
       MOQTMessageType.TRACK_STATUS: (TrackStatus, _handle_track_status),

       # Session control messages
       MOQTMessageType.GOAWAY: (GoAway, _handle_goaway),

       # Subscribe announces messages
       MOQTMessageType.SUBSCRIBE_ANNOUNCES: (SubscribeAnnounces, _handle_subscribe_announces),
       MOQTMessageType.SUBSCRIBE_ANNOUNCES_OK: (SubscribeAnnouncesOk, _handle_subscribe_announces_ok),
       MOQTMessageType.SUBSCRIBE_ANNOUNCES_ERROR: (SubscribeAnnouncesError, _handle_subscribe_announces_error),
       MOQTMessageType.UNSUBSCRIBE_ANNOUNCES: (UnsubscribeAnnounces, _handle_unsubscribe_announces),

       # Fetch messages
       MOQTMessageType.FETCH: (Fetch, _handle_fetch),
       MOQTMessageType.FETCH_CANCEL: (FetchCancel, _handle_fetch_cancel),
       MOQTMessageType.FETCH_OK: (FetchOk, _handle_fetch_ok),
       MOQTMessageType.FETCH_ERROR: (FetchError, _handle_fetch_error),
   }