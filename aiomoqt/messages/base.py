import inspect
import asyncio
from dataclasses import dataclass, fields
from typing import Type, Any, Dict, ClassVar, Callable, Awaitable, Optional
from aioquic.buffer import Buffer
from ..types import MOQTMessageType, StreamType, DatagramType
from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MOQTMessage:
    """Base class for all MOQT messages."""
    # type: Optional[int] = None - let subclass set it - annoying warnings

    def serialize(self) -> bytes:
        """Convert message to complete wire format."""
        raise NotImplementedError()

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'MOQTMessage':
        """Create message from buffer containing payload."""
        raise NotImplementedError()

    def __str__(self) -> str:
        """Generic string representation showing all fields."""
        parts = []
        class_fields = fields(self.__class__)

        for field in class_fields:
            value = getattr(self, field.name)
            # Special handling for bytes fields
            if isinstance(value, bytes):
                try:
                    str_val = value.decode('utf-8')
                except UnicodeDecodeError:
                    str_val = f"0x{value.hex()}"
            # Special handling for dicts
            elif isinstance(value, dict):
                str_val = "{" + \
                    ", ".join(f"{k}: {v}" for k, v in value.items()) + "}"
            else:
                str_val = str(value)
            parts.append(f"{field.name}={str_val}")

        return f"{self.__class__.__name__}({', '.join(parts)})"


class MOQTMessageHandler:
    """Handles parsing and routing of incoming MOQT messages."""

    # Import concrete message implementations
    from .setup import (
        ClientSetup,
        ServerSetup,
        GoAway
    )

    from .subscribe import (
        Subscribe,
        SubscribeOk,
        SubscribeError,
        SubscribeUpdate,
        Unsubscribe,
        SubscribeDone,
        MaxSubscribeId,
        SubscribesBlocked,
        TrackStatusRequest,
        TrackStatus,
    )

    from .announce import (
        Announce,
        AnnounceOk,
        AnnounceError,
        Unannounce,
        AnnounceCancel,
        SubscribeAnnounces,
        SubscribeAnnouncesOk,
        SubscribeAnnouncesError,
        UnsubscribeAnnounces
    )

    from .fetch import (
        Fetch,
        FetchOk,
        FetchError,
        FetchCancel
    )

    from .data import (
        StreamHeaderSubgroup,
        FetchHeader,
        ObjectDatagram,
        ObjectDatagramStatus
    )

    # MOQT message types to class map
    _message_types: ClassVar[Dict[int, Type[MOQTMessage]]] = {
        # Setup messages (0x40-0x41)
        MOQTMessageType.CLIENT_SETUP: ClientSetup,         # 0x40
        MOQTMessageType.SERVER_SETUP: ServerSetup,         # 0x41

        # Subscribe messages (0x02-0x05)
        MOQTMessageType.SUBSCRIBE_UPDATE: SubscribeUpdate,  # 0x02
        MOQTMessageType.SUBSCRIBE: Subscribe,             # 0x03
        MOQTMessageType.SUBSCRIBE_OK: SubscribeOk,        # 0x04
        MOQTMessageType.SUBSCRIBE_ERROR: SubscribeError,  # 0x05

        # Announce messages (0x06-0x09)
        MOQTMessageType.ANNOUNCE: Announce,               # 0x06
        MOQTMessageType.ANNOUNCE_OK: AnnounceOk,         # 0x07
        MOQTMessageType.ANNOUNCE_ERROR: AnnounceError,   # 0x08
        MOQTMessageType.UNANNOUNCE: Unannounce,         # 0x09

        # Additional subscription messages (0x0A-0x0B)
        MOQTMessageType.UNSUBSCRIBE: Unsubscribe,        # 0x0A
        MOQTMessageType.SUBSCRIBE_DONE: SubscribeDone,   # 0x0B

        # Announce control messages (0x0C)
        MOQTMessageType.ANNOUNCE_CANCEL: AnnounceCancel,  # 0x0C

        # Status messages (0x0D-0x0E)
        MOQTMessageType.TRACK_STATUS_REQUEST: TrackStatusRequest,  # 0x0D
        MOQTMessageType.TRACK_STATUS: TrackStatus,       # 0x0E

        # Session control messages (0x10)
        MOQTMessageType.GOAWAY: GoAway,                  # 0x10

        # Subscription announce messages (0x11-0x14)
        MOQTMessageType.SUBSCRIBE_ANNOUNCES: SubscribeAnnounces,         # 0x11
        MOQTMessageType.SUBSCRIBE_ANNOUNCES_OK: SubscribeAnnouncesOk,    # 0x12
        MOQTMessageType.SUBSCRIBE_ANNOUNCES_ERROR: SubscribeAnnouncesError,  # 0x13
        MOQTMessageType.UNSUBSCRIBE_ANNOUNCES: UnsubscribeAnnounces,    # 0x14

        # Subscribe control messages (0x15, 0x1A)
        MOQTMessageType.MAX_SUBSCRIBE_ID: MaxSubscribeId,      # 0x15
        MOQTMessageType.SUBSCRIBES_BLOCKED: SubscribesBlocked,  # 0x1A

        # Fetch messages (0x16-0x19)
        MOQTMessageType.FETCH: Fetch,                    # 0x16
        MOQTMessageType.FETCH_CANCEL: FetchCancel,       # 0x17
        MOQTMessageType.FETCH_OK: FetchOk,               # 0x18
        MOQTMessageType.FETCH_ERROR: FetchError,         # 0x19
    }

    # Mapping of stream types to message classes
    _stream_types: ClassVar[Dict[int, Type[MOQTMessage]]] = {
        StreamType.STREAM_HEADER_SUBGROUP: StreamHeaderSubgroup,
        StreamType.FETCH_HEADER: FetchHeader,
    }

    # Mapping of datagram types to message classes
    _datagram_types: ClassVar[Dict[int, Type[MOQTMessage]]] = {
        DatagramType.OBJECT_DATAGRAM: ObjectDatagram,
        DatagramType.OBJECT_DATAGRAM_STATUS: ObjectDatagramStatus,
    }

    def __init__(self, protocol: Any):
        self.protocol = protocol
        self._custom_handlers: Dict[int, Callable[[
            MOQTMessage], Awaitable[None]]] = {}
        self._tasks = set()

    def handle_control_message(self, data: bytes) -> Optional[MOQTMessage]:
        """Process an incoming message."""
        if not data:
            logger.warning(
                f"{inspect.currentframe().f_code.co_name}:  empty message data")
            return None

        try:
            buffer = Buffer(data=data)
            msg_type = buffer.pull_uint_var()
            length = buffer.pull_uint_var()

            # Look up message class
            message_class = self._message_types.get(msg_type)
            if message_class is None:
                raise ValueError(
                    f"MOQT event: unknown control message type: {hex(msg_type)}")

            # Deserialize message
            logger.debug(
                f"MOQT event: control message: {message_class} {message_class.__class__} ({hex(msg_type)})")
            message = message_class.deserialize(buffer)
            logger.debug(f"MOQT event: control message: {message}")

            # Schedule handler if one exists
            handler = self._custom_handlers.get(msg_type)
            if handler:
                task = asyncio.create_task(handler(message))
                self._tasks.add(task)

            return message

        except Exception as e:
            logger.error(
                f"{inspect.currentframe().f_code.co_name}: error handling control message: {e}")
            raise

    def handle_data_message(self, stream_id: int, data: bytes) -> None:
        """Process incoming data messages (not control messages)."""
        if not data:
            logger.error(
                f"MOQT event: stream {stream_id}: message contains no data")
            return

        try:
            # Handle STREAM_HEADER messages
            if len(data) > 0:
                stream_type = data[0]
                logger.info(
                    f"MOQT: stream {stream_id}: type: {hex(stream_type)}")

                if stream_type == StreamType.STREAM_HEADER_SUBGROUP:
                    self._handle_subgroup_header(data)
                    return

            # Handle object data
            self._handle_object_data(data)

        except Exception as e:
            logger.error(
                f"{inspect.currentframe().f_code.co_name}: error handling data message: {e}")

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

    def register_handler(self, msg_type: int,
                         handler: Callable[[MOQTMessage], Awaitable[None]]) -> None:
        """Register an async message handler for a specific message type."""
        self._custom_handlers[msg_type] = handler
