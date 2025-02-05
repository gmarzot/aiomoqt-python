from dataclasses import dataclass, fields
from typing import Type, Any, Dict, ClassVar, Callable, Awaitable, Optional
import asyncio
from aioquic.buffer import Buffer
from ..types import MessageTypes
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


class MessageHandler:
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

    # MOQT message types to class map
    _message_types: ClassVar[Dict[int, Type[MOQTMessage]]] = {
        # Setup messages (0x40-0x41)
        MessageTypes.CLIENT_SETUP: ClientSetup,         # 0x40
        MessageTypes.SERVER_SETUP: ServerSetup,         # 0x41

        # Subscribe messages (0x02-0x05)
        MessageTypes.SUBSCRIBE_UPDATE: SubscribeUpdate,  # 0x02
        MessageTypes.SUBSCRIBE: Subscribe,             # 0x03
        MessageTypes.SUBSCRIBE_OK: SubscribeOk,        # 0x04
        MessageTypes.SUBSCRIBE_ERROR: SubscribeError,  # 0x05

        # Announce messages (0x06-0x09)
        MessageTypes.ANNOUNCE: Announce,               # 0x06
        MessageTypes.ANNOUNCE_OK: AnnounceOk,         # 0x07
        MessageTypes.ANNOUNCE_ERROR: AnnounceError,   # 0x08
        MessageTypes.UNANNOUNCE: Unannounce,         # 0x09

        # Additional subscription messages (0x0A-0x0B)
        MessageTypes.UNSUBSCRIBE: Unsubscribe,        # 0x0A
        MessageTypes.SUBSCRIBE_DONE: SubscribeDone,   # 0x0B

        # Announce control messages (0x0C)
        MessageTypes.ANNOUNCE_CANCEL: AnnounceCancel,  # 0x0C

        # Status messages (0x0D-0x0E)
        MessageTypes.TRACK_STATUS_REQUEST: TrackStatusRequest,  # 0x0D
        MessageTypes.TRACK_STATUS: TrackStatus,       # 0x0E

        # Session control messages (0x10)
        MessageTypes.GOAWAY: GoAway,                  # 0x10

        # Subscription announce messages (0x11-0x14)
        MessageTypes.SUBSCRIBE_ANNOUNCES: SubscribeAnnounces,         # 0x11
        MessageTypes.SUBSCRIBE_ANNOUNCES_OK: SubscribeAnnouncesOk,    # 0x12
        MessageTypes.SUBSCRIBE_ANNOUNCES_ERROR: SubscribeAnnouncesError,  # 0x13
        MessageTypes.UNSUBSCRIBE_ANNOUNCES: UnsubscribeAnnounces,    # 0x14

        # Subscribe control messages (0x15, 0x1A)
        MessageTypes.MAX_SUBSCRIBE_ID: MaxSubscribeId,      # 0x15
        MessageTypes.SUBSCRIBES_BLOCKED: SubscribesBlocked,  # 0x1A

        # Fetch messages (0x16-0x19)
        MessageTypes.FETCH: Fetch,                    # 0x16
        MessageTypes.FETCH_CANCEL: FetchCancel,       # 0x17
        MessageTypes.FETCH_OK: FetchOk,               # 0x18
        MessageTypes.FETCH_ERROR: FetchError,         # 0x19
    }

    def __init__(self, protocol: Any):
        self.protocol = protocol
        self._custom_handlers: Dict[int, Callable[[
            MOQTMessage], Awaitable[None]]] = {}
        self._tasks = set()

    def handle_message(self, data: bytes) -> Optional[MOQTMessage]:
        """Process an incoming message."""
        if not data:
            logger.warning("Received empty message data")
            return None

        try:
            buffer = Buffer(data=data)
            msg_type = buffer.pull_uint_var()
            length = buffer.pull_uint_var()

            # Look up message class
            message_class = self._message_types.get(msg_type)
            if not message_class:
                raise ValueError(f"Unknown message type: {hex(msg_type)}")

            # Deserialize message
            message = message_class.deserialize(buffer)
            logger.debug(f"Received message type {hex(msg_type)}: {message}")

            # Schedule handler if one exists
            handler = self._custom_handlers.get(msg_type)
            if handler:
                task = asyncio.create_task(handler(message))
                self._tasks.add(task)

            return message

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            raise

    def register_handler(self, msg_type: int,
                         handler: Callable[[MOQTMessage], Awaitable[None]]) -> None:
        """Register an async message handler for a specific message type."""
        self._custom_handlers[msg_type] = handler
