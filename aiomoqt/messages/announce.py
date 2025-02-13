from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple
from aioquic.buffer import Buffer
from .base import MOQTMessage 
from ..types import MOQTMessageType
from ..utils.logger import get_logger

logger = get_logger(__name__)

@dataclass
class Announce(MOQTMessage):
    """ANNOUNCE message for advertising a track namespace."""
    namespace: Tuple[bytes, ...] = None  # Track namespace as a tuple of bytes
    parameters: Dict[int, bytes] = None  # Optional parameters

    def __post_init__(self):
        self.type = MOQTMessageType.ANNOUNCE

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)
        payload = Buffer(capacity=32)

        # Serialize namespace
        payload.push_uint_var(len(self.namespace))
        for part in self.namespace:
            payload.push_uint_var(len(part))
            payload.push_bytes(part)

        # Serialize parameters
        payload.push_uint_var(len(self.parameters))
        for param_id, param_value in self.parameters.items():
            payload.push_uint_var(param_id)
            payload.push_uint_var(len(param_value))
            payload.push_bytes(param_value)

        # Build final message
        buf.push_uint_var(self.type)
        buf.push_uint_var(len(payload.data))
        buf.push_bytes(payload.data)
        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'Announce':
        # Deserialize namespace tuple
        tuple_len = buffer.pull_uint_var()
        namespace = []
        for _ in range(tuple_len):
            part_len = buffer.pull_uint_var()
            namespace.append(buffer.pull_bytes(part_len))
        namespace = tuple(namespace)  # Convert to tuple
        
        # Deserialize parameters
        params = {}
        param_count = buffer.pull_uint_var()
        for _ in range(param_count):
            param_id = buffer.pull_uint_var()
            param_len = buffer.pull_uint_var()
            param_value = buffer.pull_bytes(param_len)
            params[param_id] = param_value
            
        return cls(namespace=namespace, parameters=params)

@dataclass
class AnnounceOk(MOQTMessage):
    """ANNOUNCE_OK response message."""
    namespace: Tuple[bytes, ...]

    def __post_init__(self):
        self.type = MOQTMessageType.ANNOUNCE_OK

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)
        payload = Buffer(capacity=32)

        payload.push_uint_var(len(self.namespace))
        for part in self.namespace:
            payload.push_uint_var(len(part))
            payload.push_bytes(part)

        buf.push_uint_var(self.type)
        buf.push_uint_var(len(payload.data))
        buf.push_bytes(payload.data)
        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'AnnounceOk':
        tuple_len = buffer.pull_uint_var()
        namespace = []
        for _ in range(tuple_len):
            part_len = buffer.pull_uint_var()
            namespace.append(buffer.pull_bytes(part_len))
        return cls(namespace=tuple(namespace))

@dataclass
class AnnounceError(MOQTMessage):
    """ANNOUNCE_ERROR response message."""
    namespace: Tuple[bytes, ...]
    error_code: int
    reason: str

    def __post_init__(self):
        self.type = MOQTMessageType.ANNOUNCE_ERROR

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)
        payload = Buffer(capacity=32)

        payload.push_uint_var(len(self.namespace))
        for part in self.namespace:
            payload.push_uint_var(len(part))
            payload.push_bytes(part)
            
        payload.push_uint_var(self.error_code)
        
        reason_bytes = self.reason.encode()
        payload.push_uint_var(len(reason_bytes))
        payload.push_bytes(reason_bytes)

        buf.push_uint_var(self.type)
        buf.push_uint_var(len(payload.data))
        buf.push_bytes(payload.data)
        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'AnnounceError':
        tuple_len = buffer.pull_uint_var()
        namespace = []
        for _ in range(tuple_len):
            part_len = buffer.pull_uint_var()
            namespace.append(buffer.pull_bytes(part_len))
        
        error_code = buffer.pull_uint_var()
        reason_len = buffer.pull_uint_var()
        reason = buffer.pull_bytes(reason_len).decode()
        return cls(namespace=tuple(namespace), error_code=error_code, reason=reason)

@dataclass
class Unannounce(MOQTMessage):
    """UNANNOUNCE message to withdraw track namespace."""
    namespace: Tuple[bytes, ...]

    def __post_init__(self):
        self.type = MOQTMessageType.UNANNOUNCE

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)
        payload = Buffer(capacity=32)

        payload.push_uint_var(len(self.namespace))
        for part in self.namespace:
            payload.push_uint_var(len(part))
            payload.push_bytes(part)

        buf.push_uint_var(self.type)
        buf.push_uint_var(len(payload.data))
        buf.push_bytes(payload.data)
        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'Unannounce':
        tuple_len = buffer.pull_uint_var()
        namespace = []
        for _ in range(tuple_len):
            part_len = buffer.pull_uint_var()
            namespace.append(buffer.pull_bytes(part_len))
        return cls(namespace=tuple(namespace))

@dataclass
class AnnounceCancel(MOQTMessage):
    """ANNOUNCE_CANCEL message to withdraw announcement acceptance."""
    namespace: Tuple[bytes, ...]
    error_code: int
    reason: str

    def __post_init__(self):
        self.type = MOQTMessageType.ANNOUNCE_CANCEL

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)
        payload = Buffer(capacity=32)

        payload.push_uint_var(len(self.namespace))
        for part in self.namespace:
            payload.push_uint_var(len(part))
            payload.push_bytes(part)
            
        payload.push_uint_var(self.error_code)
        
        reason_bytes = self.reason.encode()
        payload.push_uint_var(len(reason_bytes))
        payload.push_bytes(reason_bytes)

        buf.push_uint_var(self.type)
        buf.push_uint_var(len(payload.data))
        buf.push_bytes(payload.data)
        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'AnnounceCancel':
        tuple_len = buffer.pull_uint_var()
        namespace = []
        for _ in range(tuple_len):
            part_len = buffer.pull_uint_var()
            namespace.append(buffer.pull_bytes(part_len))
        
        error_code = buffer.pull_uint_var()
        reason_len = buffer.pull_uint_var()
        reason = buffer.pull_bytes(reason_len).decode()
        return cls(namespace=tuple(namespace), error_code=error_code, reason=reason)

@dataclass
class SubscribeAnnounces(MOQTMessage):
    """SUBSCRIBE_ANNOUNCES message to subscribe to announcements."""
    namespace_prefix: Tuple[bytes, ...]  # Track namespace prefix as tuple
    parameters: Dict[int, bytes]

    def __post_init__(self):
        self.type = MOQTMessageType.SUBSCRIBE_ANNOUNCES

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)
        payload = Buffer(capacity=32)

        payload.push_uint_var(len(self.namespace_prefix))
        for part in self.namespace_prefix:
            payload.push_uint_var(len(part))
            payload.push_bytes(part)

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
    def deserialize(cls, buffer: Buffer) -> 'SubscribeAnnounces':
        tuple_len = buffer.pull_uint_var()
        namespace_prefix = []
        for _ in range(tuple_len):
            part_len = buffer.pull_uint_var()
            namespace_prefix.append(buffer.pull_bytes(part_len))

        params = {}
        param_count = buffer.pull_uint_var()
        for _ in range(param_count):
            param_id = buffer.pull_uint_var()
            param_len = buffer.pull_uint_var()
            param_value = buffer.pull_bytes(param_len)
            params[param_id] = param_value

        return cls(namespace_prefix=tuple(namespace_prefix), parameters=params)

@dataclass
class SubscribeAnnouncesOk(MOQTMessage):
    """SUBSCRIBE_ANNOUNCES_OK response message."""
    namespace_prefix: Tuple[bytes, ...]

    def __post_init__(self):
        self.type = MOQTMessageType.SUBSCRIBE_ANNOUNCES_OK

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)
        payload = Buffer(capacity=32)

        payload.push_uint_var(len(self.namespace_prefix))
        for part in self.namespace_prefix:
            payload.push_uint_var(len(part))
            payload.push_bytes(part)

        buf.push_uint_var(self.type)
        buf.push_uint_var(len(payload.data))
        buf.push_bytes(payload.data)
        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'SubscribeAnnouncesOk':
        tuple_len = buffer.pull_uint_var()
        namespace_prefix = []
        for _ in range(tuple_len):
            part_len = buffer.pull_uint_var()
            namespace_prefix.append(buffer.pull_bytes(part_len))
        return cls(namespace_prefix=tuple(namespace_prefix))

@dataclass
class SubscribeAnnouncesError(MOQTMessage):
    """SUBSCRIBE_ANNOUNCES_ERROR response message."""
    namespace_prefix: Tuple[bytes, ...]
    error_code: int
    reason: str

    def __post_init__(self):
        self.type = MOQTMessageType.SUBSCRIBE_ANNOUNCES_ERROR

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)
        payload = Buffer(capacity=32)

        payload.push_uint_var(len(self.namespace_prefix))
        for part in self.namespace_prefix:
            payload.push_uint_var(len(part))
            payload.push_bytes(part)
            
        payload.push_uint_var(self.error_code)
        
        reason_bytes = self.reason.encode()
        payload.push_uint_var(len(reason_bytes))
        payload.push_bytes(reason_bytes)

        buf.push_uint_var(self.type)
        buf.push_uint_var(len(payload.data))
        buf.push_bytes(payload.data)
        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'SubscribeAnnouncesError':
        tuple_len = buffer.pull_uint_var()
        namespace_prefix = []
        for _ in range(tuple_len):
            part_len = buffer.pull_uint_var()
            namespace_prefix.append(buffer.pull_bytes(part_len))
        
        error_code = buffer.pull_uint_var()
        reason_len = buffer.pull_uint_var()
        reason = buffer.pull_bytes(reason_len).decode()
        return cls(namespace_prefix=tuple(namespace_prefix), error_code=error_code, reason=reason)

@dataclass 
class UnsubscribeAnnounces(MOQTMessage):
    """UNSUBSCRIBE_ANNOUNCES message."""
    namespace_prefix: Tuple[bytes, ...]

    def __post_init__(self):
        self.type = MOQTMessageType.UNSUBSCRIBE_ANNOUNCES

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)
        payload = Buffer(capacity=32)

        payload.push_uint_var(len(self.namespace_prefix))
        for part in self.namespace_prefix:
            payload.push_uint_var(len(part))
            payload.push_bytes(part)

        buf.push_uint_var(self.type)
        buf.push_uint_var(len(payload.data))
        buf.push_bytes(payload.data)
        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'UnsubscribeAnnounces':
        tuple_len = buffer.pull_uint_var()
        namespace_prefix = []
        for _ in range(tuple_len):
            part_len = buffer.pull_uint_var()
            namespace_prefix.append(buffer.pull_bytes(part_len))
        return cls(namespace_prefix=tuple(namespace_prefix))