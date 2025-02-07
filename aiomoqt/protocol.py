import inspect
import asyncio
from typing import Optional, Dict, Any, Callable
from collections import defaultdict
import pylsqpack

from aioquic.buffer import Buffer, UINT_VAR_MAX
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3Connection, H3Stream
from aioquic.quic.connection import QuicConnection
from aioquic.quic.events import QuicEvent, StreamDataReceived
from aioquic.h3.events import HeadersReceived, DataReceived
from aioquic.quic.logger import QuicLoggerTrace

from .messages import MOQTMessageHandler
from .types import SessionCloseCode
from .utils.logger import get_logger

logger = get_logger(__name__)


class H3CustomConnection(H3Connection):
    """Custom H3Connection wrapper to support alternate SETTINGS"""

    def __init__(self, quic: QuicConnection, enable_webtransport: bool = False, table_capacity: int = 0) -> None:
        # settings table capacity can be overridden - this should be generalized
        self._max_table_capacity = table_capacity
        self._blocked_streams = 16
        self._enable_webtransport = enable_webtransport

        self._is_client = quic.configuration.is_client
        self._is_done = False
        self._quic = quic
        self._quic_logger: Optional[QuicLoggerTrace] = quic._quic_logger
        self._decoder = pylsqpack.Decoder(
            self._max_table_capacity, self._blocked_streams
        )
        self._decoder_bytes_received = 0
        self._decoder_bytes_sent = 0
        self._encoder = pylsqpack.Encoder()
        self._encoder_bytes_received = 0
        self._encoder_bytes_sent = 0
        self._settings_received = False
        self._stream: Dict[int, H3Stream] = {}

        self._max_push_id: Optional[int] = 8 if self._is_client else None
        self._next_push_id: int = 0

        self._local_control_stream_id: Optional[int] = None
        self._local_decoder_stream_id: Optional[int] = None
        self._local_encoder_stream_id: Optional[int] = None

        self._peer_control_stream_id: Optional[int] = None
        self._peer_decoder_stream_id: Optional[int] = None
        self._peer_encoder_stream_id: Optional[int] = None
        self._received_settings: Optional[Dict[int, int]] = None
        self._sent_settings: Optional[Dict[int, int]] = None

        self._init_connection()
        # report sent settings
        settings = self.sent_settings
        if settings is not None:
            logger.debug("H3 SETTINGS sent:")
            for setting_id, value in settings.items():
                logger.debug(f"  Setting 0x{setting_id:x} = {value}")


class MOQTProtocol(QuicConnectionProtocol):
    """Base MOQT protocol implementation."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._h3: Optional[H3Connection] = None
        self._session_id: Optional[int] = None
        self._control_stream_id: Optional[int] = None
        self._streams: Dict[int, Dict] = {}
        self._groups = defaultdict(lambda: {'objects': 0, 'subgroups': set()})
        self._wt_session = asyncio.Event()
        self._moqt_session = asyncio.Event()
        # Initialize message handling
        self.message_handler = MOQTMessageHandler(self)
        
    def transmit(self) -> None:
        """Transmit pending data."""
        logger.debug("Transmitting data")
        super().transmit()

    def connection_made(self, transport):
        """Called when QUIC connection is established."""
        super().connection_made(transport)
        self._h3 = H3CustomConnection(self._quic, enable_webtransport=True)
        logger.info("H3 connection initialized")

    def quic_event_received(self, event: QuicEvent) -> None:
        """Handle incoming QUIC events."""
        # Log any errors
        if hasattr(event, 'error_code'):
            reason = getattr(event, 'reason_phrase', 'unknown')
            logger.error(
                f"QUIC event: error: {event.error_code} reason: {reason}")
            return

        stream_id = getattr(event, 'stream_id', 'unknown')
        logger.debug(
            f"QUIC event: stream {stream_id}: {event.__class__.__name__}")

        # Debug log any data
        if hasattr(event, 'data'):
            logger.debug(
                f"QUIC event: stream {stream_id}: 0x{event.data.hex()}")

        # Handle MOQT control/data messages
        if isinstance(event, StreamDataReceived):
            if event.stream_id == self._control_stream_id:
                self.message_handler.handle_control_message(event.data)
                return
            elif event.stream_id in self._streams:
                self.message_handler.handle_data_message(event.stream_id, event.data)
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
                            logger.debug(
                                f"  Setting 0x{setting_id:x} = {value}")

            except Exception as e:
                logger.error(f"QUIC event: error handling event: {e}")
                raise
        else:
            logger.error(
                f"QUIC event: stream {stream_id}: event not handled({event.__class__.__name__})")

    def _h3_event_received(self, event: QuicEvent) -> None:
        """Handle H3-specific events."""
        if isinstance(event, HeadersReceived):
            self._h3_handle_headers_received(event)
        elif isinstance(event, DataReceived):
            self._h3_handle_data_received(event)
        else:
            logger.error(
                f"H3 event: stream {event.stream_id}: {event.__class__.__name__}: event not handled")
            if hasattr(event, 'data') and event.data is not None:
                logger.debug(
                    f"H3 event: stream {event.stream_id}: 0x{event.data.hex()}")

    def _h3_handle_headers_received(self, event: HeadersReceived) -> None:
        """Process incoming H3 headers."""
        status = None
        logger.info(f"H3 event: stream {event.stream_id} HeadersReceived:")

        for name, value in event.headers:
            logger.info(f"  {name.decode()}: {value.decode()}")
            if name == b':status':
                status = value

        stream_id = event.stream_id
        msg = f"H3 event: stream {stream_id}: "
        if status == b"200":
            logger.info(msg + "WebTransport session established")
        else:
            error = f"WebTransport session setup failed ({status})"
            logger.error(msg + error)
            raise Exception(error)
        # signal WebTransport session established event
        self._wt_session.set()

    def _h3_handle_data_received(self, event: DataReceived) -> None:
        """Process incoming H3 data MOQT data is not expected to arrive like this"""
        logger.warning(f"H3 event: stream {event.stream_id}: DataReceived")
        if hasattr(event, 'data'):
            logger.debug(
                f"H3 event: stream {event.stream_id}: data: 0x{event.data.hex()}")

    def register_handler(self, msg_type: int, handler: Callable) -> None:
        """Register a custom message handler."""
        self._custom_handlers[msg_type] = handler

    def send_control_message(self, data: bytes) -> None:
        """Send a MOQT message on the control stream."""
        if self._quic is None or self._control_stream_id is None:
            raise RuntimeError("Control stream not initialized")
        self._quic.send_stream_data(
            stream_id=self._control_stream_id,
            data=data,
            end_stream=False
        )
        self.transmit()

    async def initialize(self, **kwargs) -> None:
        """Initialize the MOQT session. Override in implementation."""
        raise NotImplementedError()

    def close(self, error_code: SessionCloseCode = SessionCloseCode.NO_ERROR,
              reason_phrase: str = "Normal closure") -> None:
        """Close the MOQT session."""
        logger.info(f"Closing MOQT session: {reason_phrase} ({error_code})")

        if self._session_id is not None:
            logger.debug(f"Closing H3 session: stream {self._session_id}")
            self._h3.send_data(self._session_id, b"", end_stream=True)
            self._session_id = None
            self.transmit()

        self._h3 = None

        super().close(error_code, reason_phrase)
        self.transmit()
