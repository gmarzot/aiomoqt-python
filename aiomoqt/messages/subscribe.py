from ..types import MOQTMessageType, TrackStatusCode
from typing import Tuple, Dict, Optional
from dataclasses import dataclass
from aioquic.buffer import Buffer
from .base import MOQTMessage

from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TrackStatusRequest(MOQTMessage):
    namespace: Tuple[bytes, ...] = None  # Tuple encoded
    track_name: bytes = None

    def __post_init__(self):
        self.type = MOQTMessageType.TRACK_STATUS_REQUEST

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)

        # Calculate payload size
        payload_size = 0
        namespace_parts = self.namespace.split(b'/')
        payload_size += 1  # num parts varint
        for part in namespace_parts:
            payload_size += 1  # part length varint
            payload_size += len(part)  # part bytes
        payload_size += 1  # track name length varint
        payload_size += len(self.track_name)  # track name bytes

        # Write message
        buf.push_uint_var(self.type)
        buf.push_uint_var(payload_size)

        # Write namespace as tuple
        buf.push_uint_var(len(namespace_parts))
        for part in namespace_parts:
            buf.push_uint_var(len(part))
            buf.push_bytes(part)

        # Write track name
        buf.push_uint_var(len(self.track_name))
        buf.push_bytes(self.track_name)

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
        buf = Buffer(capacity=32)

        # Calculate payload size
        payload_size = 0
        namespace_parts = self.namespace.split(b'/')
        payload_size += 1  # num parts varint
        for part in namespace_parts:
            payload_size += 1  # part length varint
            payload_size += len(part)  # part bytes
        payload_size += 1  # track name length varint
        payload_size += len(self.track_name)  # track name bytes
        payload_size += 1  # status code varint
        payload_size += 1  # last group id varint
        payload_size += 1  # last object id varint

        # Write message
        buf.push_uint_var(self.type)
        buf.push_uint_var(payload_size)

        # Write namespace as tuple
        buf.push_uint_var(len(namespace_parts))
        for part in namespace_parts:
            buf.push_uint_var(len(part))
            buf.push_bytes(part)

        # Write track name
        buf.push_uint_var(len(self.track_name))
        buf.push_bytes(self.track_name)

        # Write status info
        buf.push_uint_var(self.status_code)
        buf.push_uint_var(self.last_group_id)
        buf.push_uint_var(self.last_object_id)

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

    def __post_init__(self):
        self.type = MOQTMessageType.SUBSCRIBE

    def serialize(self) -> bytes:
        buf = Buffer(capacity=64)
        payload = Buffer(capacity=64)

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
        buf = Buffer(capacity=8)
        payload = Buffer(capacity=8)

        payload.push_uint_var(self.subscribe_id)

        buf.push_uint_var(self.type)
        buf.push_uint_var(len(payload.data))
        buf.push_bytes(payload.data)
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
        buf = Buffer(capacity=32)

        # Write message type and calculate payload size
        payload_size = 0
        payload_size += 1  # subscribe_id varint
        payload_size += 1  # status_code varint
        payload_size += 1  # stream_count varint
        reason_bytes = self.reason.encode()
        payload_size += 1  # reason length varint
        payload_size += len(reason_bytes)  # reason string

        # Write header
        buf.push_uint_var(self.type)
        buf.push_uint_var(payload_size)

        # Write payload
        buf.push_uint_var(self.subscribe_id)
        buf.push_uint_var(self.status_code)
        buf.push_uint_var(self.stream_count)
        buf.push_uint_var(len(reason_bytes))
        buf.push_bytes(reason_bytes)

        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'SubscribeDone':
        subscribe_id = buffer.pull_uint_var()
        status_code = buffer.pull_uint_var()
        stream_count = buffer.pull_uint_var()
        reason_len = buffer.pull_uint_var()
        reason = buffer.pull_bytes(reason_len).decode()

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
        buf = Buffer(capacity=16)

        payload_size = 1  # subscribe_id varint

        buf.push_uint_var(self.type)
        buf.push_uint_var(payload_size)
        buf.push_uint_var(self.subscribe_id)

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
    group_order: int  # 0x1=Ascending, 0x2=Descending
    content_exists: int  # 0 or 1
    largest_group_id: Optional[int] = None  # Only if content_exists=1
    largest_object_id: Optional[int] = None  # Only if content_exists=1
    parameters: Optional[Dict[int, bytes]] = None

    def __post_init__(self):
        self.type = MOQTMessageType.SUBSCRIBE_OK

    def serialize(self) -> bytes:
        buf = Buffer(capacity=64)

        # Calculate payload size
        payload_size = 0
        payload_size += 1  # subscribe_id varint
        payload_size += 1  # expires varint
        payload_size += 1  # group_order uint8
        payload_size += 1  # content_exists uint8

        if self.content_exists == 1:
            payload_size += 1  # largest_group_id varint
            payload_size += 1  # largest_object_id varint

        parameters = self.parameters or {}
        payload_size += 1  # parameter count varint
        for param_id, param_value in parameters.items():
            payload_size += 1  # param id varint
            payload_size += 1  # param length varint
            payload_size += len(param_value)  # param value

        # Write message
        buf.push_uint_var(self.type)
        buf.push_uint_var(payload_size)

        # Write payload fields
        buf.push_uint_var(self.subscribe_id)
        buf.push_uint_var(self.expires)
        buf.push_uint8(self.group_order)
        buf.push_uint8(self.content_exists)

        if self.content_exists == 1:
            buf.push_uint_var(self.largest_group_id or 0)
            buf.push_uint_var(self.largest_object_id or 0)

        # Write parameters
        buf.push_uint_var(len(parameters))
        for param_id, param_value in parameters.items():
            buf.push_uint_var(param_id)
            buf.push_uint_var(len(param_value))
            buf.push_bytes(param_value)

        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'SubscribeOk':
        subscribe_id = buffer.pull_uint_var()
        expires = buffer.pull_uint_var()
        group_order = buffer.pull_uint8()
        content_exists = buffer.pull_uint8()

        largest_group_id = None
        largest_object_id = None
        if content_exists == 1:
            largest_group_id = buffer.pull_uint_var()
            largest_object_id = buffer.pull_uint_var()

        param_count = buffer.pull_uint_var()
        parameters = {}
        for _ in range(param_count):
            param_id = buffer.pull_uint_var()
            param_len = buffer.pull_uint_var()
            param_value = buffer.pull_bytes(param_len)
            parameters[param_id] = param_value

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
        buf = Buffer(capacity=64)

        # Calculate payload size
        reason_bytes = self.reason.encode()
        payload_size = 0
        payload_size += 1  # subscribe_id varint
        payload_size += 1  # error_code varint
        payload_size += 1  # reason length varint
        payload_size += len(reason_bytes)  # reason string
        payload_size += 1  # track_alias varint

        # Write message
        buf.push_uint_var(self.type)
        buf.push_uint_var(payload_size)

        # Write payload fields
        buf.push_uint_var(self.subscribe_id)
        buf.push_uint_var(self.error_code)
        buf.push_uint_var(len(reason_bytes))
        buf.push_bytes(reason_bytes)
        buf.push_uint_var(self.track_alias)

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
        buf = Buffer(capacity=64)

        # Calculate payload size
        payload_size = 0
        payload_size += 1  # subscribe_id varint
        payload_size += 1  # start_group varint
        payload_size += 1  # start_object varint
        payload_size += 1  # end_group varint
        payload_size += 1  # priority uint8

        parameters = self.parameters or {}
        payload_size += 1  # parameter count varint
        for param_id, param_value in parameters.items():
            payload_size += 1  # param id varint
            payload_size += 1  # param length varint
            payload_size += len(param_value)  # param value

        # Write message
        buf.push_uint_var(self.type)
        buf.push_uint_var(payload_size)

        # Write payload fields
        buf.push_uint_var(self.subscribe_id)
        buf.push_uint_var(self.start_group)
        buf.push_uint_var(self.start_object)
        buf.push_uint_var(self.end_group)
        buf.push_uint8(self.priority)

        # Write parameters
        buf.push_uint_var(len(parameters))
        for param_id, param_value in parameters.items():
            buf.push_uint_var(param_id)
            buf.push_uint_var(len(param_value))
            buf.push_bytes(param_value)

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
