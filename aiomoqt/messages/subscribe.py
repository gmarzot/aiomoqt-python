from ..types import *
from typing import Tuple, Dict, Optional
from dataclasses import dataclass
from aioquic.buffer import Buffer
from .base import MOQTMessage, BUF_SIZE

from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TrackStatusRequest(MOQTMessage):
    namespace: Tuple[bytes, ...] = None  # Tuple encoded
    track_name: bytes = None

    def __post_init__(self):
        self.type = MOQTMessageType.TRACK_STATUS_REQUEST

    def serialize(self) -> bytes:
        # Write namespace as tuple
        if not isinstance(self.namespace, tuple):
            raise ValueError("namespace must be a tuple of bytes")
        payload = Buffer()
        payload.push_uint_var(len(self.namespace))
        for part in self.namespace:
            if not isinstance(part, bytes):
                raise ValueError("namespace parts must be bytes")
            payload.push_uint_var(len(part))
            payload.push_bytes(part)
        
        # Write track name
        if not isinstance(self.track_name, bytes):
            raise ValueError("track_name must be bytes")
        payload.push_uint_var(len(self.track_name))
        payload.push_bytes(self.track_name)

        # Create final message
        buf = Buffer()  # Extra space for header
        buf.push_uint_var(self.type)
        buf.push_uint_var(payload.tell())
        buf.push_bytes(payload.data)

        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'TrackStatusRequest':
        # Parse namespace tuple
        namespace_parts = []
        num_parts = buffer.pull_uint_var()
        for _ in range(num_parts):
            part_len = buffer.pull_uint_var()
            part = buffer.pull_bytes(part_len)
            namespace_parts.append(part)
        namespace = b'/'.join(namespace_parts)

        # Parse track name
        track_name_len = buffer.pull_uint_var()
        track_name = buffer.pull_bytes(track_name_len)

        return cls(namespace=namespace, track_name=track_name)


@dataclass
class TrackStatus(MOQTMessage):
    namespace: Tuple[bytes, ...]  # Tuple encoded
    track_name: bytes
    status_code: TrackStatusCode
    last_group_id: int
    last_object_id: int

    def __post_init__(self):
        self.type = MOQTMessageType.TRACK_STATUS

    def serialize(self) -> bytes:
        # First encode the payload
        payload = Buffer(capacity=BUF_SIZE)
        
        # Write namespace as tuple
        if not isinstance(self.namespace, tuple):
            raise ValueError("namespace must be a tuple of bytes")
        payload.push_uint_var(len(self.namespace))
        for part in self.namespace:
            if not isinstance(part, bytes):
                raise ValueError("namespace parts must be bytes")
            payload.push_uint_var(len(part))
            payload.push_bytes(part)
        
        # Write track name
        if not isinstance(self.track_name, bytes):
            raise ValueError("track_name must be bytes")
        payload.push_uint_var(len(self.track_name))
        payload.push_bytes(self.track_name)

        # Write status info
        if not isinstance(self.status_code, TrackStatusCode):
            raise ValueError("status_code must be TrackStatusCode enum")
        payload.push_uint_var(self.status_code.value)
        payload.push_uint_var(self.last_group_id)
        payload.push_uint_var(self.last_object_id)

        # Create final message
        buf = Buffer(capacity=BUF_SIZE)
        buf.push_uint_var(self.type)
        buf.push_uint_var(payload.tell())
        buf.push_bytes(payload.data)

        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'TrackStatus':
        # Parse namespace tuple
        namespace_parts = []
        num_parts = buffer.pull_uint_var()
        for _ in range(num_parts):
            part_len = buffer.pull_uint_var()
            part = buffer.pull_bytes(part_len)
            namespace_parts.append(part)
        namespace = b'/'.join(namespace_parts)

        # Parse track name
        track_name_len = buffer.pull_uint_var()
        track_name = buffer.pull_bytes(track_name_len)

        # Parse status info
        status_code = TrackStatusCode(buffer.pull_uint_var())
        last_group_id = buffer.pull_uint_var()
        last_object_id = buffer.pull_uint_var()

        return cls(
            namespace=namespace,
            track_name=track_name,
            status_code=status_code,
            last_group_id=last_group_id,
            last_object_id=last_object_id
        )


@dataclass
class Subscribe(MOQTMessage):
    """SUBSCRIBE message for requesting track data."""
    subscribe_id: int
    track_alias: int
    namespace: Tuple[bytes, ...]
    track_name: bytes
    priority: int
    direction: int  # Ascending/Descending
    filter_type: int
    start_group: Optional[int] = None
    start_object: Optional[int] = None
    end_group: Optional[int] = None
    parameters: Optional[Dict[int, bytes]] = None
    response: Optional['SubscribeOk'] = None

    def __post_init__(self):
        self.type = MOQTMessageType.SUBSCRIBE

    def serialize(self) -> bytes:
        buf = Buffer(capacity=BUF_SIZE)
        payload = Buffer(capacity=BUF_SIZE)

        payload.push_uint_var(self.subscribe_id)
        payload.push_uint_var(self.track_alias)

        # Add namespace as tuple
        payload.push_uint_var(len(self.namespace))
        for part in self.namespace:
            payload.push_uint_var(len(part))
            payload.push_bytes(part)

        payload.push_uint_var(len(self.track_name))
        payload.push_bytes(self.track_name)
        payload.push_uint8(self.priority)
        payload.push_uint8(self.direction)
        payload.push_uint_var(self.filter_type)

        # Add optional start/end fields based on filter type
        if self.filter_type in (3, 4):  # ABSOLUTE_START or ABSOLUTE_RANGE
            payload.push_uint_var(self.start_group or 0)
            payload.push_uint_var(self.start_object or 0)

        if self.filter_type == 4:  # ABSOLUTE_RANGE
            payload.push_uint_var(self.end_group or 0)

        # Add parameters
        parameters = self.parameters or {}
        payload.push_uint_var(len(parameters))
        for param_id, param_value in parameters.items():
            payload.push_uint_var(param_id)
            param_value = MOQTMessage._bytes_encode(param_value)
            payload.push_uint_var(len(param_value))
            payload.push_bytes(param_value)

        buf.push_uint_var(self.type)
        buf.push_uint_var(len(payload.data))
        buf.push_bytes(payload.data)
        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'Subscribe':
        subscribe_id = buffer.pull_uint_var()
        track_alias = buffer.pull_uint_var()

        # Deserialize namespace tuple
        tuple_len = buffer.pull_uint_var()
        namespace = []
        for _ in range(tuple_len):
            part_len = buffer.pull_uint_var()
            namespace.append(buffer.pull_bytes(part_len))
        namespace = tuple(namespace)

        # Track name
        track_name_len = buffer.pull_uint_var()
        track_name = buffer.pull_bytes(track_name_len)

        priority = buffer.pull_uint8()
        direction = buffer.pull_uint8()
        filter_type = buffer.pull_uint_var()

        # Handle optional fields based on filter type
        start_group = None
        start_object = None
        end_group = None
        if filter_type in (3, 4):  # ABSOLUTE_START or ABSOLUTE_RANGE
            start_group = buffer.pull_uint_var()
            start_object = buffer.pull_uint_var()

        if filter_type == 4:  # ABSOLUTE_RANGE
            end_group = buffer.pull_uint_var()

        # Deserialize parameters
        params = {}
        param_count = buffer.pull_uint_var()
        for _ in range(param_count):
            param_id = buffer.pull_uint_var()
            param_len = buffer.pull_uint_var()
            param_value = buffer.pull_bytes(param_len)
            params[param_id] = param_value

        return cls(
            subscribe_id=subscribe_id,
            track_alias=track_alias,
            namespace=namespace,
            track_name=track_name,
            priority=priority,
            direction=direction,
            filter_type=filter_type,
            start_group=start_group,
            start_object=start_object,
            end_group=end_group,
            parameters=params
        )


@dataclass
class Unsubscribe(MOQTMessage):
    """UNSUBSCRIBE message for ending track subscription."""
    subscribe_id: int

    def __post_init__(self):
        self.type = MOQTMessageType.UNSUBSCRIBE

    def serialize(self) -> bytes:
        buf = Buffer(capacity=BUF_SIZE)

        payload = MOQTMessage._varint_encode(self.subscribe_id)

        buf.push_uint_var(self.type)
        buf.push_uint_var(len(payload))
        buf.push_bytes(payload)
        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'Unsubscribe':
        subscribe_id = buffer.pull_uint_var()
        return cls(subscribe_id=subscribe_id)


@dataclass
class SubscribeDone(MOQTMessage):
    """SUBSCRIBE_DONE message indicating subscription completion."""
    subscribe_id: int
    status_code: int  # SubscribeDoneCode
    stream_count: int
    reason: str

    def __post_init__(self):
        self.type = MOQTMessageType.SUBSCRIBE_DONE

    def serialize(self) -> bytes:
        # First encode the payload
        payload = Buffer(capacity=BUF_SIZE)
        
        # Write payload fields
        payload.push_uint_var(self.subscribe_id)
        if not isinstance(self.status_code, SubscribeDoneCode):
            raise ValueError("status_code must be SubscribeDoneCode enum")
        payload.push_uint_var(self.status_code.value)
        payload.push_uint_var(self.stream_count)

        # Convert and write reason string
        if not isinstance(self.reason, str):
            raise ValueError("reason must be str")
        reason_bytes = self.reason.encode()
        payload.push_uint_var(len(reason_bytes))
        payload.push_bytes(reason_bytes)

        # Create final message
        buf = Buffer(capacity=BUF_SIZE)
        buf.push_uint_var(self.type)
        buf.push_uint_var(payload.tell())
        buf.push_bytes(payload.data)

        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'SubscribeDone':
        subscribe_id = buffer.pull_uint_var()
        status_code = buffer.pull_uint_var()
        stream_count = buffer.pull_uint_var()
        try:
            reason_len = buffer.pull_uint_var()
            if reason_len > buffer.capacity - buffer.tell():
                raise ValueError(f"Invalid reason length {reason_len}")
            reason = buffer.pull_bytes(reason_len).decode()
        except Exception as e:
            logger.error(f"Error parsing SUBSCRIBE_DONE reason: {e}")
            reason = f"parsing error: len: {reason_len}" 

        return cls(
            subscribe_id=subscribe_id,
            status_code=status_code,
            stream_count=stream_count,
            reason=reason
        )


@dataclass
class MaxSubscribeId(MOQTMessage):
    """MAX_SUBSCRIBE_ID message setting maximum subscribe ID."""
    subscribe_id: int

    def __post_init__(self):
        self.type = MOQTMessageType.MAX_SUBSCRIBE_ID

    def serialize(self) -> bytes:
        buf = Buffer(capacity=BUF_SIZE)

        payload = MOQTMessage._varint_encode(self.subscribe_id)  # subscribe_id varint

        buf.push_uint_var(self.type)
        buf.push_uint_var(len(payload))
        buf.push_uint_var(payload)

        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'MaxSubscribeId':
        subscribe_id = buffer.pull_uint_var()
        return cls(subscribe_id=subscribe_id)


@dataclass
class SubscribesBlocked(MOQTMessage):
    """SUBSCRIBES_BLOCKED message indicating subscriber is blocked."""
    maximum_subscribe_id: int

    def __post_init__(self):
        self.type = MOQTMessageType.SUBSCRIBES_BLOCKED

    def serialize(self) -> bytes:
        buf = Buffer(capacity=16)

        payload_size = 1  # maximum_subscribe_id varint

        buf.push_uint_var(self.type)
        buf.push_uint_var(payload_size)
        buf.push_uint_var(self.maximum_subscribe_id)

        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'SubscribesBlocked':
        maximum_subscribe_id = buffer.pull_uint_var()
        return cls(maximum_subscribe_id=maximum_subscribe_id)


@dataclass
class SubscribeOk(MOQTMessage):
    """SUBSCRIBE_OK message indicating successful subscription."""
    subscribe_id: int
    expires: int
    group_order: GroupOrder  # 0x1=Ascending, 0x2=Descending
    content_exists: ContentExistsCode  # 0x0=No Content or 0x1=Exists
    largest_group_id: Optional[int] = None  # Only if content exists
    largest_object_id: Optional[int] = None  # Only if content exists
    parameters: Optional[Dict[int, bytes]] = None

    def __post_init__(self):
        self.type = MOQTMessageType.SUBSCRIBE_OK

    def serialize(self) -> bytes:
        # First encode the payload
        payload = Buffer(capacity=BUF_SIZE)
        
        # Required fields
        payload.push_uint_var(self.subscribe_id)
        payload.push_uint_var(self.expires)
        payload.push_uint8(self.group_order.value)
        payload.push_uint8(self.content_exists)

        # Largest group/object IDs only present if content_exists=1
        if self.content_exists == ContentExistsCode.EXISTS:
            if self.largest_group_id is None or self.largest_object_id is None:
                raise ValueError("largest_group_id and largest_object_id required when content_exists=1")
            payload.push_uint_var(self.largest_group_id)
            payload.push_uint_var(self.largest_object_id)

        # Parameters
        parameters = self.parameters or {}
        payload.push_uint_var(len(parameters))
        for param_type, param_value in parameters.items():
            payload.push_uint_var(param_type)
            param_value = MOQTMessage._bytes_encode(param_value)
            payload.push_uint_var(len(param_value))
            payload.push_bytes(param_value)

        # Create final message
        buf = Buffer(capacity=BUF_SIZE)
        buf.push_uint_var(self.type)
        buf.push_uint_var(len(payload.data))
        buf.push_bytes(payload.data)

        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'SubscribeOk':
        subscribe_id = buffer.pull_uint_var()
        expires = buffer.pull_uint_var()
        group_order = GroupOrder(buffer.pull_uint8())
        content_exists = buffer.pull_uint8()

        largest_group_id = None
        largest_object_id = None
        if content_exists == ContentExistsCode.EXISTS:
            largest_group_id = buffer.pull_uint_var()
            largest_object_id = buffer.pull_uint_var()

        parameters = {}
        param_count = buffer.pull_uint_var()
        for _ in range(param_count):
            param_id = buffer.pull_uint_var()
            param_len = buffer.pull_uint_var()
            param_value = buffer.pull_bytes(param_len)
            parameters[ParamType(param_id)] = param_value

        return cls(
            subscribe_id=subscribe_id,
            expires=expires,
            group_order=group_order,
            content_exists=content_exists,
            largest_group_id=largest_group_id,
            largest_object_id=largest_object_id,
            parameters=parameters
        )

@dataclass
class SubscribeError(MOQTMessage):
    """SUBSCRIBE_ERROR message indicating subscription failure."""
    subscribe_id: int
    error_code: int  # SubscribeErrorCode
    reason: str
    track_alias: int

    def __post_init__(self):
        self.type = MOQTMessageType.SUBSCRIBE_ERROR

    def serialize(self) -> bytes:
        # First encode the payload
        payload = Buffer(capacity=BUF_SIZE)
        
        payload.push_uint_var(self.subscribe_id)
        if not isinstance(self.error_code, SubscribeErrorCode):
            raise ValueError("error_code must be SubscribeErrorCode enum")
        payload.push_uint_var(self.error_code.value)

        # Convert and write reason string
        if not isinstance(self.reason, str):
            raise ValueError("reason must be str")
        reason_bytes = self.reason.encode()
        payload.push_uint_var(len(reason_bytes))
        payload.push_bytes(reason_bytes)
        
        payload.push_uint_var(self.track_alias)

        # Create final message
        buf = Buffer(capacity=BUF_SIZE)
        buf.push_uint_var(self.type)
        buf.push_uint_var(payload.tell())
        buf.push_bytes(payload.data)

        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'SubscribeError':
        subscribe_id = buffer.pull_uint_var()
        error_code = buffer.pull_uint_var()
        reason_len = buffer.pull_uint_var()
        reason = buffer.pull_bytes(reason_len).decode()
        track_alias = buffer.pull_uint_var()

        return cls(
            subscribe_id=subscribe_id,
            error_code=error_code,
            reason=reason,
            track_alias=track_alias
        )


@dataclass
class SubscribeUpdate(MOQTMessage):
    """SUBSCRIBE_UPDATE message for modifying an existing subscription."""
    subscribe_id: int
    start_group: int
    start_object: int
    end_group: int
    priority: int
    parameters: Optional[Dict[int, bytes]] = None

    def __post_init__(self):
        self.type = MOQTMessageType.SUBSCRIBE_UPDATE

    def serialize(self) -> bytes:
        # First encode the payload
        payload = Buffer(capacity=BUF_SIZE)
        
        # Write payload fields
        payload.push_uint_var(self.subscribe_id)
        payload.push_uint_var(self.start_group)
        payload.push_uint_var(self.start_object)
        payload.push_uint_var(self.end_group)
        
        if not isinstance(self.priority, int) or not 0 <= self.priority <= 255:
            raise ValueError("priority must be uint8 (0-255)")
        payload.push_uint8(self.priority)

        # Write parameters
        parameters = self.parameters or {}
        payload.push_uint_var(len(parameters))
        for param_id, param_value in parameters.items():
            payload.push_uint_var(param_id.value)
            param_value = MOQTMessage._bytes_encode(param_value)
            payload.push_uint_var(len(param_value))
            payload.push_bytes(param_value)

        # Create final message
        buf = Buffer(capacity=BUF_SIZE)
        buf.push_uint_var(self.type)
        buf.push_uint_var(payload.tell())
        buf.push_bytes(payload.data)

        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'SubscribeUpdate':
        subscribe_id = buffer.pull_uint_var()
        start_group = buffer.pull_uint_var()
        start_object = buffer.pull_uint_var()
        end_group = buffer.pull_uint_var()
        priority = buffer.pull_uint8()

        param_count = buffer.pull_uint_var()
        parameters = {}
        for _ in range(param_count):
            param_id = buffer.pull_uint_var()
            param_len = buffer.pull_uint_var()
            param_value = buffer.pull_bytes(param_len)
            parameters[param_id] = param_value

        return cls(
            subscribe_id=subscribe_id,
            start_group=start_group,
            start_object=start_object,
            end_group=end_group,
            priority=priority,
            parameters=parameters
        )
