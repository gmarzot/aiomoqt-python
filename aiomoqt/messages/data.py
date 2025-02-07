from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, Dict, ClassVar, Type, Union
from aioquic.buffer import Buffer
from .base import MOQTMessage
from ..types import StreamType, DatagramType, ObjectStatus, ForwardingPreference

@dataclass
class StreamHeaderSubgroup(MOQTMessage):
    """Stream header for subgroup data."""
    track_alias: int
    group_id: int
    subgroup_id: int
    publisher_priority: int

    def __post_init__(self):
        self.type = StreamType.STREAM_HEADER_SUBGROUP

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)
        payload = Buffer(capacity=32)

        payload.push_uint_var(self.track_alias)
        payload.push_uint_var(self.group_id)
        payload.push_uint_var(self.subgroup_id)
        payload.push_uint8(self.publisher_priority)

        buf.push_uint_var(self.type)
        buf.push_uint_var(len(payload.data))
        buf.push_bytes(payload.data)
        return buf.data

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'StreamHeaderSubgroup':
        track_alias = buffer.pull_uint_var()
        group_id = buffer.pull_uint_var()
        subgroup_id = buffer.pull_uint_var()
        publisher_priority = buffer.pull_uint8()
        
        return cls(
            track_alias=track_alias,
            group_id=group_id,
            subgroup_id=subgroup_id,
            publisher_priority=publisher_priority
        )

@dataclass
class FetchHeader(MOQTMessage):
    """Stream header for fetch data."""
    subscribe_id: int

    def __post_init__(self):
        self.type = StreamType.FETCH_HEADER

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)
        payload = Buffer(capacity=32)

        payload.push_uint_var(self.subscribe_id)

        buf.push_uint_var(self.type)
        buf.push_uint_var(len(payload.data))
        buf.push_bytes(payload.data)
        return buf.data

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'FetchHeader':
        subscribe_id = buffer.pull_uint_var()
        return cls(subscribe_id=subscribe_id)

@dataclass
class ObjectDatagram(MOQTMessage):
    """Object datagram message."""
    track_alias: int
    group_id: int
    object_id: int
    publisher_priority: int
    payload: bytes = b''

    def __post_init__(self):
        self.type = DatagramType.OBJECT_DATAGRAM

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32 + len(self.payload))

        buf.push_uint_var(self.track_alias)
        buf.push_uint_var(self.group_id)
        buf.push_uint_var(self.object_id)
        buf.push_uint8(self.publisher_priority)
        buf.push_bytes(self.payload)

        return buf.data

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'ObjectDatagram':
        track_alias = buffer.pull_uint_var()
        group_id = buffer.pull_uint_var()
        object_id = buffer.pull_uint_var()
        publisher_priority = buffer.pull_uint8()
        payload = buffer.pull_bytes(buffer.capacity - buffer.tell())

        return cls(
            track_alias=track_alias,
            group_id=group_id,
            object_id=object_id,
            publisher_priority=publisher_priority,
            payload=payload
        )

@dataclass
class ObjectDatagramStatus(MOQTMessage):
    """Object datagram status message."""
    track_alias: int
    group_id: int
    object_id: int
    publisher_priority: int
    status: ObjectStatus

    def __post_init__(self):
        self.type = DatagramType.OBJECT_DATAGRAM_STATUS

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)

        buf.push_uint_var(self.track_alias)
        buf.push_uint_var(self.group_id)
        buf.push_uint_var(self.object_id)
        buf.push_uint8(self.publisher_priority)
        buf.push_uint_var(self.status)

        return buf.data

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'ObjectDatagramStatus':
        track_alias = buffer.pull_uint_var()
        group_id = buffer.pull_uint_var()
        object_id = buffer.pull_uint_var()
        publisher_priority = buffer.pull_uint8()
        status = ObjectStatus(buffer.pull_uint_var())

        return cls(
            track_alias=track_alias,
            group_id=group_id,
            object_id=object_id,
            publisher_priority=publisher_priority,
            status=status
        )

@dataclass
class StreamObject(MOQTMessage):
    """Object within a subgroup stream."""
    object_id: int
    payload_length: int
    status: Optional[ObjectStatus] = None
    payload: bytes = b''

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32 + len(self.payload))

        buf.push_uint_var(self.object_id)
        buf.push_uint_var(self.payload_length)

        if self.payload_length == 0 and self.status is not None:
            buf.push_uint_var(self.status)
        elif self.payload:
            buf.push_bytes(self.payload)

        return buf.data

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'StreamObject':
        object_id = buffer.pull_uint_var()
        payload_length = buffer.pull_uint_var()
        
        status = None
        payload = b''
        
        if payload_length == 0:
            status = ObjectStatus(buffer.pull_uint_var())
        else:
            payload = buffer.pull_bytes(payload_length)

        return cls(
            object_id=object_id,
            payload_length=payload_length,
            status=status,
            payload=payload
        )

@dataclass
class FetchObject(MOQTMessage):
    """Object within a fetch stream."""
    group_id: int
    subgroup_id: int
    object_id: int
    publisher_priority: int
    payload_length: int
    status: Optional[ObjectStatus] = None
    payload: bytes = b''

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32 + len(self.payload))

        buf.push_uint_var(self.group_id)
        buf.push_uint_var(self.subgroup_id)
        buf.push_uint_var(self.object_id)
        buf.push_uint8(self.publisher_priority)
        buf.push_uint_var(self.payload_length)

        if self.payload_length == 0 and self.status is not None:
            buf.push_uint_var(self.status)
        elif self.payload:
            buf.push_bytes(self.payload)

        return buf.data

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'FetchObject':
        group_id = buffer.pull_uint_var()
        subgroup_id = buffer.pull_uint_var()
        object_id = buffer.pull_uint_var()
        publisher_priority = buffer.pull_uint8()
        payload_length = buffer.pull_uint_var()

        status = None
        payload = b''

        if payload_length == 0:
            status = ObjectStatus(buffer.pull_uint_var())
        else:
            payload = buffer.pull_bytes(payload_length)

        return cls(
            group_id=group_id,
            subgroup_id=subgroup_id,
            object_id=object_id,
            publisher_priority=publisher_priority,
            payload_length=payload_length,
            status=status,
            payload=payload
        )

