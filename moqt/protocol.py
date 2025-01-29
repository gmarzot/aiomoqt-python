import logging
import asyncio
from typing import Optional, Dict, Any, Callable
from collections import defaultdict

from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3Connection
from aioquic.quic.events import QuicEvent, StreamDataReceived
from aioquic.h3.events import HeadersReceived, DataReceived

from .utils.buffer import Buffer
from .utils.logger import get_logger
from .messages import MessageTypes, MessageBuilder, MessageHandler
from .moqtypes import SessionCloseCode, StreamType, ObjectStatus

logger = get_logger(__name__)


class MOQTProtocol(QuicConnectionProtocol):
    """Base MOQT protocol implementation."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._h3: Optional[H3Connection] = None
        self._control_stream_id: Optional[int] = None
        self._streams: Dict[int, Dict] = {}
        self._groups = defaultdict(lambda: {'objects': 0, 'subgroups': set()})
        self._wt_session = asyncio.Event()
        self._moqt_session = asyncio.Event()

        # Initialize message handling
        self.message_builder = MessageBuilder()
        self.message_handler = MessageHandler(self)
        self._custom_handlers: Dict[int, Callable] = {}

    def connection_made(self, transport):
        """Called when QUIC connection is established."""
        super().connection_made(transport)
        self._h3 = H3Connection(self._quic, enable_webtransport=True)
        logger.info("H3 connection initialized")

    def quic_event_received(self, event: QuicEvent) -> None:
        """Handle incoming QUIC events."""
        # Log any errors
        if hasattr(event, 'error_code'):
            reason = getattr(event, 'reason_phrase', 'unknown')
            logger.error(f"QUIC EVENT: error: {
                         event.error_code} reason: {reason}")
            return

        stream_id = getattr(event, 'stream_id', 'unknown')
        logger.info(f"QUIC EVENT: stream {stream_id}")

        # Debug log any data
        if hasattr(event, 'data'):
            logger.debug(f"QUIC EVENT: stream {
                         stream_id} data: 0x{event.data.hex()}")

        # Handle data on control/data streams
        if isinstance(event, StreamDataReceived):
            if event.stream_id == self._control_stream_id:
                logger.debug(f"QUIC EVENT: control stream {
                             event.stream_id}: data: 0x{event.data.hex()}")
                self.message_handler.handle_message(event.data)
                return
            elif event.stream_id in self._streams:
                logger.debug(f"QUIC EVENT: data stream {
                             event.stream_id}: data: 0x{event.data.hex()}")
                self._handle_data_message(event.stream_id, event.data)
                return

        # Pass remaining events to H3
        if self._h3 is not None:
            try:
                for h3_event in self._h3.handle_event(event):
                    self._h3_event_received(h3_event)
            except Exception as e:
                logger.error(f"QUIC EVENT: error handling event: {e}")
                raise
        else:
            logger.error(f"QUIC EVENT: stream {
                         stream_id}: event not handled ({event.__class__})")

    def _h3_event_received(self, event: QuicEvent) -> None:
        """Handle H3-specific events."""
        if isinstance(event, HeadersReceived):
            self._handle_headers_received(event)
        elif isinstance(event, DataReceived):
            self._handle_data_received(event)
        else:
            logger.error(f"H3 EVENT: stream {
                         event.stream_id}: event not handled ({event.__class__})")
            if hasattr(event, 'data'):
                logger.debug(f"H3 EVENT: stream {
                             event.stream_id}: data: 0x{event.data.hex()}")

    def _handle_headers_received(self, event: HeadersReceived) -> None:
        """Process incoming H3 headers."""
        status = None
        logger.info(f"H3 EVENT: stream {event.stream_id} HeadersReceived:")

        for name, value in event.headers:
            logger.info(f"  {name.decode()}: {value.decode()}")
            if name == b':status':
                status = value

        if status == b"200":
            logger.info(f"H3 EVENT: stream {
                        event.stream_id}: WebTransport session established")
            self._wt_session.set()
        else:
            error = f"H3 EVENT: stream {
                event.stream_id}: WebTransport session setup failed ({status})"
            logger.error(error)
            raise Exception(error)

    def _handle_data_received(self, event: DataReceived) -> None:
        """Process incoming H3 data."""
        logger.info(f"H3 EVENT: stream {event.stream_id}: DataReceived")
        if hasattr(event, 'data'):
            logger.debug(f"H3 EVENT: stream {
                         event.stream_id}: data: 0x{event.data.hex()}")

    def _handle_data_message(self, stream_id: int, data: bytes) -> None:
        """Process incoming data messages (not control messages)."""
        if not data:
            logger.error(f'MOQT: stream {stream_id}: message contains no data')
            return

        try:
            # Handle STREAM_HEADER messages
            if len(data) > 0:
                stream_type = data[0]
                logger.info(f"MOQT: stream {stream_id}: type: {
                            hex(stream_type)}")

                if stream_type == StreamType.STREAM_HEADER_SUBGROUP:
                    self._handle_subgroup_header(data)
                    return

            # Handle object data
            self._handle_object_data(data)

        except Exception as e:
            logger.error(f"Error processing data message: {e}")

    def _handle_subgroup_header(self, data: bytes) -> None:
        """Process subgroup header messages."""
        if len(data) >= 13:
            group_id = int.from_bytes(data[1:5], 'big')
            subgroup_id = int.from_bytes(data[5:9], 'big')
            priority = data[9]
            logger.info("  Message type: STREAM_HEADER_SUBGROUP")
            logger.info(f"  Group: {group_id}")
            logger.info(f"  Subgroup: {subgroup_id}")
            logger.info(f"  Priority: {priority}")

    def _handle_object_data(self, data: bytes) -> None:
        """Process object data messages."""
        group_id = int.from_bytes(data[0:4], 'big')
        subgroup_id = int.from_bytes(data[4:8], 'big')
        object_id = int.from_bytes(data[8:12], 'big')
        payload = data[12:]

        # Update statistics
        self._groups[group_id]['objects'] += 1
        self._groups[group_id]['subgroups'].add(subgroup_id)

        logger.info("  Object received:")
        logger.info(f"    Group: {group_id}")
        logger.info(f"    Subgroup: {subgroup_id}")
        logger.info(f"    Object: {object_id}")
        logger.info(f"    Payload size: {len(payload)}")

    async def send_message(self, data: bytes) -> None:
        """Send a MOQT message on the control stream."""
        if not self._control_stream_id:
            raise RuntimeError("Control stream not initialized")

        self._h3._quic.send_stream_data(
            stream_id=self._control_stream_id,
            data=data,
            end_stream=False
        )
        self.transmit()

    def register_handler(self, msg_type: int, handler: Callable) -> None:
        """Register a custom message handler."""
        self._custom_handlers[msg_type] = handler

    def transmit(self) -> None:
        """Transmit pending data."""
        logger.debug("Transmitting data")
        super().transmit()

    async def initialize(self, **kwargs) -> None:
        """Initialize the MOQT session. Override in implementation."""
        raise NotImplementedError()

    def close(self, error_code: SessionCloseCode = SessionCloseCode.NO_ERROR,
              reason_phrase: str = "Normal closure") -> None:
        """Close the MOQT session."""
        if self._quic:
            self._quic.close(error_code=error_code,
                             reason_phrase=reason_phrase)
