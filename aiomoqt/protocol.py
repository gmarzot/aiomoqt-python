import asyncio
from asyncio import Future
from typing import Optional, Type, Union, List, Tuple, Dict, Callable
from importlib.metadata import version

from aioquic.buffer import Buffer, UINT_VAR_MAX
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.connection import QuicConnection, QuicConnectionError, QuicErrorCode, stream_is_unidirectional
from aioquic.quic.events import QuicEvent, StreamDataReceived, ProtocolNegotiated, DatagramFrameReceived
from aioquic.h3.connection import H3Connection, ErrorCode, H3_ALPN
from aioquic.h3.events import HeadersReceived

from .types import *
from .messages import *
from .utils.logger import get_logger

logger = get_logger(__name__)

USER_AGENT = f"aiomoqt/{version('aiomoqt')}"
MOQT_VERSIONS = [0xff000008, 0xff080009]
MOQT_CUR_VERSION = 0xff000008


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
        self._max_table_capacity_cfg = table_capacity
        super().__init__(quic, **kwargs)
        # report sent settings
        settings = self.sent_settings
        if settings is not None:
            logger.debug("H3 SETTINGS sent:")
            for setting_id, value in settings.items():
                logger.debug(f"  Setting 0x{setting_id:x} = {value}")

    @property
    def _max_table_capacity(self):
        return self._max_table_capacity_cfg

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
        self._session: MOQTSession = session  # backref to session object with config
        self._h3: Optional[H3Connection] = None
        self._session_id: Optional[int] = None
        self._control_stream_id: Optional[int] = None
        self._loop = asyncio.get_running_loop()
        self._wt_session_setup:Future[bool] = self._loop.create_future()
        self._moqt_session_setup:Future[bool] = self._loop.create_future()
        self._moqt_session_closed:Future[Tuple[int,str]] = self._loop.create_future()
        self._next_subscribe_id = 1  # prime subscribe id generator
        self._next_track_alias = 1  # prime track alias generator
        self._tasks = set()
        self._close_err = None  # tuple holding latest (error_code, Reason_phrase)
        
        self._data_streams: Dict[int, int] = {}  # keep track of active data streams
        self._track_aliases: Dict[int, int] = {}  # map alias to subscription_id
        self._subscriptions: Dict[int, Union[Subscribe, Fetch]] = {}  # map subscription_id to request
        self._announce_responses: Dict[int, Future[MOQTMessage]] = {}
        self._subscribe_responses: Dict[int, Future[MOQTMessage]] = {}
        self._unsubscribe_responses: Dict[int, Future[MOQTMessage]] = {}
        self._fetch_responses: Dict[int, Future[MOQTMessage]] = {}
        
        self._control_msg_registry = dict(MOQTSessionProtocol.MOQT_CONTROL_MESSAGE_REGISTRY)
        self._stream_data_registry = dict(MOQTSessionProtocol.MOQT_STREAM_DATA_REGISTRY)
        self._dgram_data_registry = dict(MOQTSessionProtocol.MOQT_DGRAM_DATA_REGISTRY)

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

    def _allocate_track_alias(self, subscribe_id: int = 1) -> int:
        """Get next available track alias."""
        track_alias = self._next_track_alias
        self._next_track_alias += 1
        self._track_aliases[track_alias] = subscribe_id
        return track_alias

    async def client_session_init(self, timeout: int = 10) -> None:
        """Initialize WebTransport and MOQT client session."""
        # Create WebTransport session
        self._session_id = self._h3._quic.get_next_available_stream_id(is_unidirectional=False)

        headers = [
            (b":method", b"CONNECT"),
            (b":protocol", b"webtransport"),
            (b":scheme", b"https"),
            (b":authority",
             f"{self._session.host}:{self._session.port}".encode()),
            (b":path", f"/{self._session.endpoint}".encode()),
            (b"sec-webtransport-http3-draft", b"draft02"),
            (b"user-agent", USER_AGENT.encode()),
        ]

        logger.info(f"H3 send: WebTransport CONNECT: session id: {self._session_id}")
        for name, value in headers:
            logger.debug(f"  {name.decode()}: {value.decode()}")
            
        self._h3.send_headers(stream_id=self._session_id, headers=headers, end_stream=False)
        self.transmit()
        # Wait for WebTransport session establishment
        try:
            async with asyncio.timeout(timeout):
                result = await self._wt_session_setup
            result = "SUCCESS" if result else "FAILED"
            status = "False" if self._close_err is None else f"True ({self._close_err})"
            logger.debug(f"H3 event: WebTransport setup: {result} closed: {status}")
        except asyncio.TimeoutError:
            logger.error("WebTransport session establishment timeout")
            raise

        # Check for H3 connection close
        if self._close_err:
            raise RuntimeError(self._close_err)
        
        # Create MOQT control stream
        self._control_stream_id = self._h3.create_webtransport_stream(session_id=self._session_id)
        logger.info(f"MOQT: control stream created stream id: {self._control_stream_id}")

        # Send CLIENT_SETUP
        client_setup = self.client_setup(
            versions=MOQT_VERSIONS,
            parameters={SetupParamType.MAX_SUBSCRIBER_ID: MOQTMessage._varint_encode(1000)}
        )

        # Wait for SERVER_SETUP
        session_setup = None
        try: 
            async with asyncio.timeout(timeout):
                session_setup = await self._moqt_session_setup
        except asyncio.TimeoutError:
            error = "timeout waiting for SERVER_SETUP"
            logger.error("MOQT error: " + error)
            self._close_session(SessionCloseCode.CONTROL_MESSAGE_TIMEOUT, error)
            raise
        
        if not session_setup:
            raise MOQTException(*self._close_err)
        
        logger.info(f"MOQT session: setup complete: {result}")


    def default_message_handler(self, type: int,  msg: MOQTMessage) -> None:
        """Call the standard message handler"""
        _, handler = self.MOQT_CONTROL_MESSAGE_REGISTRY[type]
        # Schedule handler if one exists
        logger.info(f"calling standard handler: {handler}")
        if handler is not None:
            task = asyncio.create_task(handler(self, msg))
            task.add_done_callback(lambda t: self._tasks.discard(t))
            self._tasks.add(task)
                

    def register_handler(self, msg_type: int, handler: Callable) -> None:
        """Register a custom message handler."""
        (msg_class, _) = self._control_msg_registry[msg_type]
        self._control_msg_registry[msg_type] = (msg_class, handler)

    def send_control_message(self, buf: Buffer) -> None:
        """Send a MOQT message on the control stream."""
        if self._quic is None or self._control_stream_id is None:
            raise RuntimeError("Control stream not initialized")
        
        logger.debug(f"QUIC send: control message: {buf.capacity} bytes")

        self._quic.send_stream_data(
            stream_id=self._control_stream_id,
            data=buf.data,
            end_stream=False
        )
        self.transmit()

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
        # QUIC errors terminate the session
        event_class = event.__class__.__name__
        if hasattr(event, 'error_code'):  # Log any errors
            error = getattr(event, 'error_code', QuicErrorCode.INTERNAL_ERROR)
            reason = getattr(event, 'reason_phrase', event_class)
            logger.error(f"QUIC error: code: {error} reason: {reason}")
            self._close_session(error,reason)
            return
        # debug output    
        stream_id = getattr(event, 'stream_id', 'unknown')
        data = getattr(event, 'data', None)
        hex_data = f"0x{data.hex()}" if data else "<no data>"
        logger.debug(f"QUIC event: stream {stream_id}: {event_class}: {hex_data}")
        
        if isinstance(event, ProtocolNegotiated):
            # Instantiate the H3 Connection
            if event.alpn_protocol in H3_ALPN and self._h3 is None:
                logger.debug(f"QUIC event: Creating H3 Connection")
                self._h3 = H3CustomConnection(self._quic, enable_webtransport=True)
        elif isinstance(event, StreamDataReceived) and self._wt_session_setup.done():
            # Detect abrupt closure of critical streams
            if (event.end_stream and len(event.data) == 0 and
                stream_id in [self._control_stream_id, self._session_id]):
                self._close_session(
                    SessionCloseCode.INTERNAL_ERROR, 
                    f"critical stream closed by remote peer: {stream_id}"
                )
                return
            if self._closed.is_set() or self._close_err is not None:
                logger.warning(f"QUIC event: event received after close: {self._close_err} {self._closed.is_set()}")
                return
            msg_buf = Buffer(data=event.data)
            msg_len = msg_buf.capacity
            # Assume first bidi stream is MOQT control stream
            if self._control_stream_id is None and not stream_is_unidirectional(stream_id):
                self._control_stream_id = stream_id
                # XXX - Strip of initial stream identifier
                # logger.debug(f"MOQT event: stripping off control stream id: {stream_id}")
                msg_buf.pull_uint_var()
                msg_buf.pull_uint_var()
                                    
            # Handle MOQT Control messages
            if stream_id == self._control_stream_id:
                while msg_buf.tell() < msg_len:
                    msg = self._moqt_handle_control_message(msg_buf)
                    if msg is None:
                        error = f"control stream: parsing failed at position: {msg_buf.tell()} of {msg_len} bytes"
                        logger.error(f"MOQT error: " + error)
                        self._close_session(SessionCloseCode.PROTOCOL_VIOLATION, error)
                        break
                return
            
            # Handle MOQT Data messages
            if stream_is_unidirectional(stream_id):
                if stream_id not in self._data_streams:
                    # XXX - Strip of initial stream identifier - there has to be a better way
                    if stream_id not in self._data_streams:
                        # logger.debug(f"MOQT event: stripping off data stream id: {stream_id}")
                        msg_buf.pull_uint_var()
                        msg_buf.pull_uint_var()
                        self._data_streams[stream_id] = 0

                
                while msg_buf.tell() < msg_len:
                    data_msg = self._moqt_handle_data_stream(stream_id, msg_buf)
                    if isinstance(data_msg, ObjectHeader) and data_msg.status != ObjectStatus.NORMAL:
                        logger.debug(f"MOQT stream: object status: {data_msg.status}")
                        break
                    if data_msg is None:
                        error = f"control stream: parsing failed at position: {msg_buf.tell()}"
                        logger.error(f"MOQT error: " + error)
                        self._close_session(SessionCloseCode.PROTOCOL_VIOLATION, error)
                return
        elif isinstance(event, DatagramFrameReceived):
            msg_buf = Buffer(data=event.data)
            # XXX handle MOQT datagram data
                
        # Pass remaining events to H3
        if self._h3 is not None:
            settings = self._h3.received_settings
            try:
                for h3_event in self._h3.handle_event(event):
                    self._h3_handle_event(h3_event)
                # Check if settings just received
                if self._h3.received_settings != settings:
                    settings = self._h3.received_settings
                    logger.debug(f"H3 event: SETTINGS received: stream {stream_id}")
                    if settings is not None:
                        for setting_id, value in settings.items():
                            logger.debug(f"  Setting 0x{setting_id:x} = {value}")
            except Exception as e:
                logger.error(f"H3 error: error handling event: {e}")
                raise
        else:
            logger.error(f"QUIC event: stream {stream_id}: event not handled({event_class})")

    def _moqt_handle_control_message(self, buffer: Buffer) -> Optional[MOQTMessage]:
        """Process an incoming message."""
        buf_len = buffer.capacity
        if buf_len == 0:
            logger.warning("MOQT event: handle control message: no data")
            return None

        logger.debug(f"MOQT event: handle control message: ({buf_len} bytes)")
        try:
            start_pos = buffer.tell()
            msg_type = buffer.pull_uint_var()
            msg_len = buffer.pull_uint_var()
            hdr_len = buffer.tell() - start_pos
            end_pos = start_pos + hdr_len + msg_len
            assert buffer.tell() + msg_len <= buf_len
            # Check that msg_type exists
            try:
                msg_type = MOQTMessageType(msg_type)
            except ValueError:
                logger.error(f"MOQT error: unknown control message: type: {hex(msg_type)} start: {start_pos} len: {msg_len}")
                # Skip the rest of this message if possible
                buffer.seek(end_pos)
                return
            # Look up message class
            message_class, handler = self._control_msg_registry[msg_type]
            logger.debug(f"MOQT event: control message: {message_class.__name__} ({msg_len} bytes)")
            # Deserialize message
            msg = message_class.deserialize(buffer)
            msg_len += hdr_len
            if end_pos > buffer.tell():
                logger.debug(f"MOQT event: control message: seeking msg end: {end_pos}")
                buffer.seek(end_pos)
            #assert start_pos + msg_len == (buffer.tell())
            logger.info(f"MOQT event: control message parsed: {msg})")

            # Schedule handler if one exists
            if handler is not None:
                logger.debug(f"MOQT event: creating handler task: {handler.__name__}")
                task = asyncio.create_task(handler(self, msg))
                task.add_done_callback(lambda t: self._tasks.discard(t))
                self._tasks.add(task)
                
            return msg

        except Exception as e:
            logger.error(f"handle_control_message: error handling control message: {e}")
            raise

    def _moqt_handle_data_stream(self, stream_id: int, buffer: Buffer) -> MOQTMessage:
        """Process incoming data messages (not control messages)."""
        if buffer.capacity == 0 or buffer.tell() >= buffer.capacity:
            logger.error(f"MOQT stream data: stream {stream_id}: no data {buffer.tell()}")
            return
        
        logger.debug(f"MOQT stream data: stream {stream_id}: 0x{buffer.data_slice(0,buffer.capacity)}")

        try:
            msg_header = None
            if self._data_streams.get(stream_id):
                msg_header = ObjectHeader.deserialize(buffer)
                if msg_header is None:
                    error = f"data stream ({stream_id}) parsing failed at: {buffer.tell()}"
                    logger.error(f"MOQT error: " + error)
                    self._close_session(SessionCloseCode.PROTOCOL_VIOLATION, error)
                    return
                logger.debug(f"MOQT stream data continued: stream {stream_id}: {msg_header}")
            else:
                # Get stream type from first byte
                stream_type = buffer.pull_uint_var()
                assert stream_type == DataStreamType.SUBGROUP_HEADER
                msg_header = SubgroupHeader.deserialize(buffer)           
                self._data_streams[stream_id] = msg_header.track_alias

                # # Process remaining buffer as object data
                # if handler is not None:
                #     logger.debug(f"MOQT event: handler task: {handler.__name__}")
                #     task = asyncio.create_task(handler(self, msg_header, buffer))
                #     task.add_done_callback(lambda t: self._tasks.discard(t))
                #     self._tasks.add(task)
                    
            return msg_header

        except Exception as e:
            logger.error(f"_moqt_handle_data_stream: error handling data message: {e}")

    def _h3_handle_event(self, event: QuicEvent) -> None:
        """Handle H3-specific events."""
        logger.debug(f"H3 event: {event}")
        if isinstance(event, HeadersReceived):
            return self._h3_handle_headers_received(event)

        msg_class = event.__class__.__name__
        data = getattr(event, 'data', None)
        hex_data = f"0x{data.hex()}" if data is not None else "<no data>"
        logger.debug(f"H3 event: stream {event.stream_id}: {msg_class}: {hex_data}")
        self._h3.handle_event(event)

    def _h3_handle_headers_received(self, event: HeadersReceived) -> None:
        """Process incoming H3 headers."""
        method = None
        protocol = None
        path = None
        authority = None
        status = None
        is_client = self._quic.configuration.is_client
        stream_id = event.stream_id
        logger.info(f"H3 event: HeadersReceived: session id: {stream_id} is_client: {is_client} ")
        for name, value in event.headers:
            logger.debug(f"  {name.decode()}: {value.decode()}")
            if name == b":method":
                method = value
            elif name == b":protocol":
                protocol = value
            elif name == b":path":
                path = value
            elif name == b":authority":
                authority = value
            elif name == b':status':
                status = value
                
        if is_client:
            if status == b"200":
                logger.info(f"H3 event: WebTransport client session setup: session id: {stream_id}")
                self._wt_session_setup.set_result(True)
            else:
                error = f"WebTransport session setup failed ({status})"
                logger.error(f"H3 error: stream {stream_id}: " + error)
                self._close_session(ErrorCode.H3_CONNECT_ERROR, error)
        else:
            # Server: Handle incoming WebTransport CONNECT request - XXX check endpoint
            if method == b"CONNECT" and protocol == b"webtransport":
                self._session_id = stream_id
                # Send 200 response with WebTransport headers
                response_headers = [
                    (b":status", b"200"),
                    (b"server", USER_AGENT.encode()),
                    (b"sec-webtransport-http3-draft", b"draft02"),
                ]
                self._h3.send_headers(
                    stream_id=stream_id,
                    headers=response_headers,
                    end_stream=False
                )
                self.transmit()
                logger.info(f"H3 event: WebTransport server session setup: session id: {stream_id}")
                self._wt_session_setup.set_result(True)
            else:
                error = f"Invalid WebTransport request"
                logger.error(f"H3 error: stream {event.stream_id}: " + error)
                self._close_session(ErrorCode.H3_CONNECT_ERROR, error)
                
    def _close_session(self, 
              error_code: SessionCloseCode = SessionCloseCode.NO_ERROR, 
              reason_phrase: str = "no error") -> None:
        """Close the MOQT session."""
        logger.error(f"MOQT error: closing: {reason_phrase} ({error_code})")
        self._close_err = (error_code, reason_phrase)
        if not self._wt_session_setup.done():
            self._wt_session_setup.set_result(False)
        if not self._moqt_session_setup.done():
            self._moqt_session_setup.set_result(False)
        if not self._moqt_session_closed.done():
            self._moqt_session_closed.set_result((error_code, reason_phrase))
        
    def close(self, 
              error_code: SessionCloseCode = SessionCloseCode.NO_ERROR, 
              reason_phrase: str = "no error"
        ) -> None:
        """Session Protocol Close"""
        if self._close_err is not None:
            error_code, reason_phrase =  self._close_err
        logger.info(f"MOQT session: closing: {reason_phrase} ({error_code})")
        if self._session_id is not None:
            logger.debug(f"H3 session: closing: {self._h3.__class__.__name__} ({self._session_id})")
            self._h3.send_data(self._session_id, b"", end_stream=True)
            self._session_id = None
        # drop H3 session
        self._h3 = None
        # set the exit condition for the async with session
        if not self._moqt_session_closed.done():
            self._moqt_session_closed.set_result((error_code, reason_phrase))
        # call parent close and transmit all
        super().close(error_code=error_code, reason_phrase=reason_phrase)
        self.transmit()
        
    async def async_closed(self) -> bool:
        if not self._moqt_session_closed.done():
            self._close_err = await self._moqt_session_closed
        return True

    ################################################################################################
    #  Outbound control message API - note: awaitable messages support 'wait_response' param       #
    ################################################################################################
    
    def client_setup(
        self,
        versions: List[int] = MOQT_VERSIONS,
        parameters: Optional[Dict[int, bytes]] = None,
    ) -> None:
        """Send CLIENT_SETUP message and optionally wait for SERVER_SETUP response."""
        if parameters is None:
            parameters = {}
        
        message = ClientSetup(
            versions=versions,
            parameters=parameters
        )
        logger.info(f"MOQT send: {message}")
        self.send_control_message(message.serialize())
        
        return message

    def server_setup(
        self,
        selected_version: int = MOQT_CUR_VERSION,
        parameters: Optional[Dict[int, bytes]] = None
    ) -> ServerSetup:
        """Send SERVER_SETUP message in response to CLIENT_SETUP."""
        if parameters is None:
            parameters = {}
        
        message = ServerSetup(
            selected_version=selected_version,
            parameters=parameters
        )
        logger.info(f"MOQT send: {message}")
        self.send_control_message(message.serialize())
        return message
    
    
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
        track_alias = self._allocate_track_alias(subscribe_id) if track_alias is None else track_alias
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
        self._subscriptions[subscribe_id] = message
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
                logger.debug(f"MOQT: removing subscribe response future: {subscribe_id}")
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
        message = SubscribeAnnouncesOk(namespace_prefix=namespace_tuple)
        logger.info(f"MOQT send: {message}")
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
        logger.info(f"MOQT event: handle {msg}")

        if not self._quic.configuration.is_client:
            error = "MOQT event: received SERVER_SETUP message as server"
            logger.debug(error)
            self._close_session(
                error_code=SessionCloseCode.PROTOCOL_VIOLATION,
                reason_phrase=error
            )
            # raise RuntimeError(error)
        elif self._moqt_session_setup.done():
            error = "MOQT event: received multiple SERVER_SETUP messages"
            logger.debug(error)
            self._close_session(
                error_code=SessionCloseCode.PROTOCOL_VIOLATION,
                reason_phrase=error
            )
            #raise RuntimeError(error)
        else:    
            # indicate moqt session setup is complete
            self._moqt_session_setup.set_result(True)

    async def _handle_client_setup(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, ClientSetup)
        logger.info(f"MOQT event: handle {msg}")
        # Send SERVER_SETUP in response
        if self._quic.configuration.is_client:
            error = "MOQT event: received CLIENT_SETUP message as client"
            logger.error(error)
            self._close_session(
                error_code=SessionCloseCode.PROTOCOL_VIOLATION,
                reason_phrase=error
            )
            # raise RuntimeError(error)
        elif self._moqt_session_setup.done():
            error = "MOQT event: received multiple CLIENT_SETUP messages"
            logger.error(error)
            self.close(
                error_code=SessionCloseCode.PROTOCOL_VIOLATION,
                reason_phrase=error
            )
            # raise RuntimeError(error)
        else:
            # indicate moqt session setup is complete
            if MOQT_CUR_VERSION in msg.versions:
                self.server_setup()
                self._moqt_session_setup.set_result(True)
        
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
        logger.info(f"MOQT event: handle {msg}")
        # Handle subscription update

    async def _handle_subscribe_ok(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, SubscribeOk)
        logger.info(f"MOQT event: handle {msg}")
        # Set future result for subscriber waiting for response
        future = self._subscribe_responses.get(msg.subscribe_id)
        if future and not future.done():
            future.set_result(msg)
        self._subscriptions[msg.subscribe_id] = msg

    async def _handle_subscribe_error(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, SubscribeError)
        logger.info(f"MOQT event: handle {msg}")
        # Set future result for subscriber waiting for response
        future = self._subscribe_responses.get(msg.subscribe_id)
        if future and not future.done():
            future.set_result(msg)

    async def _handle_announce_ok(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, AnnounceOk)
        logger.info(f"MOQT event: handle {msg}")
        # Set future result for announcer waiting for response
        future = self._announce_responses.get(msg.namespace)
        if future and not future.done():
            future.set_result(msg)

    async def _handle_announce_error(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, AnnounceError)
        logger.info(f"MOQT event: handle {msg}")
        # Set future result for announcer waiting for response
        future = self._announce_responses.get(msg.namespace)
        if future and not future.done():
            future.set_result(msg)

    async def _handle_unannounce(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, Unannounce)
        logger.info(f"MOQT event: handle {msg}")
        self.announce_ok(msg.namespace)

    async def _handle_announce_cancel(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, AnnounceCancel)
        logger.info(f"MOQT event: handle {msg}")
        # Handle announcement cancellation

    async def _handle_unsubscribe(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, Unsubscribe)
        logger.info(f"MOQT event: handle {msg}")
        # Handle unsubscribe request

    async def _handle_subscribe_done(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, SubscribeDone)
        logger.info(f"MOQT event: handle {msg}")
        # Set future result for subscriber waiting for completion
        future = self._subscribe_responses.get(msg.subscribe_id)
        if future and not future.done():
            future.set_result(msg)

    async def _handle_max_subscribe_id(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, MaxSubscribeId)
        logger.info(f"MOQT event: handle {msg}")
        # Update maximum subscribe ID

    async def _handle_subscribes_blocked(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, SubscribesBlocked)
        logger.info(f"MOQT event: handle {msg}")
        # Handle subscribes blocked notification

    async def _handle_track_status_request(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, TrackStatusRequest)
        logger.info(f"MOQT event: handle {msg}")
        # Send track status in response

    async def _handle_track_status(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, TrackStatus)
        logger.info(f"MOQT event: handle {msg}")
        # Handle track status update

    async def _handle_goaway(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, GoAway)
        logger.info(f"MOQT event: handle {msg}")
        # Handle session migration request

    async def _handle_subscribe_announces(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, SubscribeAnnounces)
        logger.info(f"MOQT event: handle {msg}")
        self.subscribe_announces_ok(msg.namespace_prefix)
           
    async def _handle_subscribe_announces_ok(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, SubscribeAnnouncesOk)
        logger.info(f"MOQT event: handle {msg}")
        # Set future result for subscriber waiting for response
        future = self._subscribe_responses.get(msg.namespace_prefix)
        if future and not future.done():
            future.set_result(msg)
        logger.debug(f"_handle_subscribe_announces_ok: {future} {future.done()}")

    async def _handle_subscribe_announces_error(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, SubscribeAnnouncesError)
        logger.info(f"MOQT event: handle {msg}")
        # Set future result for subscriber waiting for response
        future = self._subscribe_responses.get(msg.namespace_prefix)
        if future and not future.done():
            future.set_result(msg)

    async def _handle_unsubscribe_announces(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, UnsubscribeAnnounces)
        logger.info(f"MOQT event: handle {msg}")
        self.subscribe_announces_ok(msg.namespace_prefix)

    async def _handle_fetch(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, Fetch)
        logger.info(f"MOQT event: handle {msg}")
        self.fetch_ok(msg.subscribe_id)

    async def _handle_fetch_cancel(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, FetchCancel)
        logger.info(f"MOQT event: handle {msg}")
        # Handle fetch cancellation

    async def _handle_fetch_ok(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, FetchOk)
        logger.info(f"MOQT event: handle {msg}")
        # Set future result for fetcher waiting for response
        future = self._fetch_responses.get(msg.subscribe_id)
        if future and not future.done():
            future.set_result(msg)

    async def _handle_fetch_error(self, msg: MOQTMessage) -> None:
        assert isinstance(msg, FetchError)
        logger.info(f"MOQT event: handle {msg}")
        # Set future result for fetcher waiting for response
        future = self._fetch_responses.get(msg.subscribe_id)
        if future and not future.done():
            future.set_result(msg)
            
    async def _handle_subgroup_header(self, msg: MOQTMessage, buf: Buffer) -> None:
        """Handle subgroup header message."""
        assert isinstance(msg, SubgroupHeader)
        logger.info(f"MOQT event: handle {msg}")
        # Process subgroup header
        # Store stream information
        sub_id = self._track_aliases.get(msg.track_alias)
        if sub_id is not None:
            req = self._subscriptions[sub_id]
            #req._groups[(msg.group_id,msg.subgroup_id)] = []
        else:
            logger.error(f"MOQT error: unrecognized track alias: {msg}")

    async def _handle_fetch_header(self, msg: FetchHeader) -> None:
        """Handle fetch header message."""
        assert isinstance(msg, FetchHeader)
        logger.info(f"MOQT event: handle {msg}")
        # Process fetch header
        # Validate subscribe_id exists
        if msg.subscribe_id not in self._subscriptions:
            logger.error(f"MOQT error: fetch for unknown subscription: {msg.subscribe_id}")
            self.close(
                error_code=SessionCloseCode.PROTOCOL_VIOLATION,
                reason_phrase="Invalid subscription ID in fetch"
            )
        return

    async def _handle_object_datagram(self, msg: ObjectDatagram) -> None:
        """Handle object datagram message."""
        assert isinstance(msg, ObjectDatagram)
        logger.info(f"MOQT event: handle {msg}")
        # Process object datagram
        # Validate track alias exists
        subscibe_id = self._track_aliases.get(msg.track_alias)
        if subscibe_id is None:
            logger.error(f"MOQT error: datagram for unknown track: {msg.track_alias}")
            self._close_session(
                error_code=SessionCloseCode.PROTOCOL_VIOLATION,
                reason_phrase="Invalid track alias in datagram"
            )
            return
        # Process object data
        # Could add to local storage or forward to subscribers

    async def _handle_object_datagram_status(self, msg: ObjectDatagramStatus) -> None:
        """Handle object datagram status message."""
        assert isinstance(msg, ObjectDatagramStatus)
        logger.info(f"MOQT event: handle {msg}")
        # Process object status
        # Update status in local tracking
        subscibe_id = self._track_aliases.get(msg.track_alias)
        if subscibe_id is None:
            logger.error(f"MOQT error: datagram status for unknown track: {msg.track_alias}")
            self._close_session(
                error_code=SessionCloseCode.PROTOCOL_VIOLATION,
                reason_phrase="Invalid track alias in status"
            )
            return
        # Update object status in local storage or notify subscribers            


    # MoQT message classes for serialize/deserialize, message handler methods (unbound)       
    MOQT_CONTROL_MESSAGE_REGISTRY: Dict[MOQTMessageType, Tuple[Type[MOQTMessage], Callable]] = {
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

    # Stream data message types    
    MOQT_STREAM_DATA_REGISTRY: Dict[DataStreamType, Tuple[Type[MOQTMessage], Callable]] = {
        DataStreamType.SUBGROUP_HEADER: (SubgroupHeader, _handle_subgroup_header),
        DataStreamType.FETCH_HEADER: (FetchHeader, _handle_fetch_header),
    }
    
    # Datagram data message types
    MOQT_DGRAM_DATA_REGISTRY: Dict[DataStreamType, Tuple[Type[MOQTMessage], Callable]] = {
        DatagramType.OBJECT_DATAGRAM: (ObjectDatagram, _handle_object_datagram),
        DatagramType.OBJECT_DATAGRAM_STATUS: (ObjectDatagramStatus, _handle_object_datagram_status),
    }