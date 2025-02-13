from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple
from aioquic.buffer import Buffer
from .base import MOQTMessage 
from ..types import MOQTMessageType
from ..utils.logger import get_logger

logger = get_logger(__name__)

@dataclass
class Fetch(MOQTMessage):
    """FETCH message to request a range of objects."""
    subscribe_id: int
    namespace: Tuple[bytes, ...]
    track_name: bytes
    subscriber_priority: int
    group_order: int
    start_group: int
    start_object: int
    end_group: int
    end_object: int
    parameters: Dict[int, bytes]

    def __post_init__(self):
        self.type = MOQTMessageType.FETCH

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)
        payload = Buffer(capacity=32)

        payload.push_uint_var(self.subscribe_id)

        # Namespace tuple
        payload.push_uint_var(len(self.namespace))
        for part in self.namespace:
            payload.push_uint_var(len(part))
            payload.push_bytes(part)

        # Track name
        payload.push_uint_var(len(self.track_name))
        payload.push_bytes(self.track_name)

        payload.push_uint8(self.subscriber_priority)
        payload.push_uint8(self.group_order)
        payload.push_uint_var(self.start_group)
        payload.push_uint_var(self.start_object)
        payload.push_uint_var(self.end_group)
        payload.push_uint_var(self.end_object)

        # Parameters
        payload.push_uint_var(len(self.parameters))
        for param_id, param_value in self.parameters.items():
            payload.push_uint_var(param_id)
            payload.push_uint_var(len(param_value))
            payload.push_bytes(param_value)

        buf.push_uint_var(self.type)
        buf.push_uint_var(len(payload.data))
        buf.push_bytes(payload.data)
        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'Fetch':
        subscribe_id = buffer.pull_uint_var()

        # Namespace tuple
        tuple_len = buffer.pull_uint_var()
        namespace = []
        for _ in range(tuple_len):
            part_len = buffer.pull_uint_var()
            namespace.append(buffer.pull_bytes(part_len))

        # Track name
        track_name_len = buffer.pull_uint_var()
        track_name = buffer.pull_bytes(track_name_len)

        subscriber_priority = buffer.pull_uint8()
        group_order = buffer.pull_uint8()
        start_group = buffer.pull_uint_var()
        start_object = buffer.pull_uint_var()
        end_group = buffer.pull_uint_var()
        end_object = buffer.pull_uint_var()

        # Parameters
        params = {}
        param_count = buffer.pull_uint_var()
        for _ in range(param_count):
            param_id = buffer.pull_uint_var()
            param_len = buffer.pull_uint_var()
            param_value = buffer.pull_bytes(param_len)
            params[param_id] = param_value

        return cls(
            subscribe_id=subscribe_id,
            namespace=tuple(namespace),
            track_name=track_name,
            subscriber_priority=subscriber_priority,
            group_order=group_order,
            start_group=start_group,
            start_object=start_object,
            end_group=end_group,
            end_object=end_object,
            parameters=params
        )

@dataclass
class FetchCancel(MOQTMessage):
    """FETCH_CANCEL message to cancel an ongoing fetch."""
    subscribe_id: int

    def __post_init__(self):
        self.type = MOQTMessageType.FETCH_CANCEL

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)
        payload = Buffer(capacity=32)

        payload.push_uint_var(self.subscribe_id)

        buf.push_uint_var(self.type)
        buf.push_uint_var(len(payload.data))
        buf.push_bytes(payload.data)
        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'FetchCancel':
        subscribe_id = buffer.pull_uint_var()
        return cls(subscribe_id=subscribe_id)

@dataclass
class FetchOk(MOQTMessage):
    """FETCH_OK response message."""
    subscribe_id: int
    group_order: int
    end_of_track: int
    largest_group_id: int
    largest_object_id: int
    parameters: Dict[int, bytes]

    def __post_init__(self):
        self.type = MOQTMessageType.FETCH_OK

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)
        payload = Buffer(capacity=32)

        payload.push_uint_var(self.subscribe_id)
        payload.push_uint8(self.group_order)
        payload.push_uint8(self.end_of_track)
        payload.push_uint_var(self.largest_group_id)
        payload.push_uint_var(self.largest_object_id)

        # Parameters
        payload.push_uint_var(len(self.parameters))
        for param_id, param_value in self.parameters.items():
            payload.push_uint_var(param_id)
            payload.push_uint_var(len(param_value))
            payload.push_bytes(param_value)

        buf.push_uint_var(self.type)
        buf.push_uint_var(len(payload.data))
        buf.push_bytes(payload.data)
        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'FetchOk':
        subscribe_id = buffer.pull_uint_var()
        group_order = buffer.pull_uint8()
        end_of_track = buffer.pull_uint8()
        largest_group_id = buffer.pull_uint_var()
        largest_object_id = buffer.pull_uint_var()

        params = {}
        param_count = buffer.pull_uint_var()
        for _ in range(param_count):
            param_id = buffer.pull_uint_var()
            param_len = buffer.pull_uint_var()
            param_value = buffer.pull_bytes(param_len)
            params[param_id] = param_value

        return cls(
            subscribe_id=subscribe_id,
            group_order=group_order,
            end_of_track=end_of_track,
            largest_group_id=largest_group_id,
            largest_object_id=largest_object_id,
            parameters=params
        )

@dataclass
class FetchError(MOQTMessage):
    """FETCH_ERROR response message."""
    subscribe_id: int
    error_code: int
    reason: str

    def __post_init__(self):
        self.type = MOQTMessageType.FETCH_ERROR

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)
        payload = Buffer(capacity=32)

        payload.push_uint_var(self.subscribe_id)
        payload.push_uint_var(self.error_code)
        
        reason_bytes = self.reason.encode()
        payload.push_uint_var(len(reason_bytes))
        payload.push_bytes(reason_bytes)

        buf.push_uint_var(self.type)
        buf.push_uint_var(len(payload.data))
        buf.push_bytes(payload.data)
        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'FetchError':
        subscribe_id = buffer.pull_uint_var()
        error_code = buffer.pull_uint_var()
        reason_len = buffer.pull_uint_var()
        reason = buffer.pull_bytes(reason_len).decode()
        
        return cls(
            subscribe_id=subscribe_id,
            error_code=error_code,
            reason=reason
        )