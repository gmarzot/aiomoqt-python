from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, List, Dict, ClassVar, Tuple, Type
from aioquic.buffer import Buffer
from .base import MOQTMessage, BUF_SIZE
from ..utils.logger import get_logger
from ..types import ObjectStatus, DataStreamType, ForwardingPreference, DatagramType

logger = get_logger(__name__)


@dataclass
class Track:
    """Represents a MOQT track."""
    namespace: Tuple[bytes, ...]
    name: bytes
    forwarding_preference: ForwardingPreference
    groups: Dict[int, 'Group'] = None

    def __post_init__(self):
        if self.groups is None:
            self.groups = {}

    def add_object(self, obj: 'ObjectHeader') -> None:
        """Add an object to the track's structure."""
        if obj.group_id not in self.groups:
            self.groups[obj.group_id] = Group(group_id=obj.group_id)
        
        self.groups[obj.group_id].add_object(obj)

@dataclass
class Group:
    """Represents a group within a track."""
    group_id: int
    subgroups: Dict[int, 'Subgroup'] = None

    def __post_init__(self):
        if self.subgroups is None:
            self.subgroups = {}

    def add_object(self, obj: 'ObjectHeader') -> None:
        """Add an object to appropriate subgroup."""
        subgroup_id = obj.subgroup_id or 0  # Default to 0 for non-subgroup forwarding
        if subgroup_id not in self.subgroups:
            self.subgroups[subgroup_id] = Subgroup(subgroup_id=subgroup_id)
        
        self.subgroups[subgroup_id].add_object(obj)

@dataclass
class Subgroup:
    """Represents a subgroup within a group."""
    subgroup_id: int
    objects: Dict[int, 'ObjectHeader'] = None

    def __post_init__(self):
        if self.objects is None:
            self.objects = {}

    def add_object(self, obj: 'ObjectHeader') -> None:
        """Add an object to the subgroup."""
        self.objects[obj.object_id] = obj


@dataclass
class SubgroupHeader:
    """MOQT subgroup stream header."""
    track_alias: int
    group_id: int
    subgroup_id: int
    publisher_priority: int

    def serialize(self) -> Buffer:
        buf = Buffer(capacity=BUF_SIZE)
        buf.push_uint_var(DataStreamType.SUBGROUP_HEADER)   
        buf.push_uint_var(self.track_alias)
        buf.push_uint_var(self.group_id)
        buf.push_uint_var(self.subgroup_id)
        buf.push_uint8(self.publisher_priority)

        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'SubgroupHeader':
        """MOQT subgroup stream header."""
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
class ObjectHeader:
    """MOQT object header."""
    object_id: int
    extensions: Optional[Dict[int, bytes]] = None
    status: Optional[ObjectStatus] = ObjectStatus.NORMAL
    payload: bytes = b''

    def serialize(self) -> Buffer:
        """Serialize for stream transmission."""
        payload_len = len(self.payload)
        buf = Buffer(capacity=(32 + payload_len))

        buf.push_uint_var(self.object_id)
        extensions = self.extensions or {}
        ext_len = len(extensions)
        buf.push_uint_var(ext_len)
        for ext_id, ext_value in extensions.items():
            if ext_id % 2 == 0:  # even extension types are simple var int
                buf.push_uint_var(ext_value)
            else:
                buf.push_uint_var(len(ext_value))
                buf.push_bytes(ext_value)

        if self.status == ObjectStatus.NORMAL and self.payload:
            buf.push_uint_var(payload_len)
            buf.push_bytes(self.payload)
        else:
            buf.push_uint_var(0)  # Zero length
            buf.push_uint_var(self.status)  # Status code

        return buf
    
    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'ObjectHeader':
        """Deserialize from stream transmission."""
        object_id = buffer.pull_uint_var()
        # Parse extensions
        extensions = {}
        ext_count = buffer.pull_uint_var()
        for _ in range(ext_count):
            ext_id = buffer.pull_uint_var()
            if ext_id % 2 == 0:  # even extension types are simple var int
                ext_value = buffer.pull_uint_var()
                extensions[ext_id] = ext_value
            else:
                ext_value_len = buffer.pull_uint_var()
                ext_value = buffer.pull_bytes(ext_value_len)
                extensions[ext_id] = ext_value
        # Get payload or status
        payload_len = buffer.pull_uint_var()
        if payload_len == 0:
            # Zero length means status code follows
            status = ObjectStatus(buffer.pull_uint_var())
            payload = b''
        else:
            status = ObjectStatus.NORMAL
            assert payload_len <= (buffer.capacity - buffer.tell())
            payload = buffer.pull_bytes(payload_len)
        
        return cls(
            object_id=object_id,
            extensions=extensions,
            status=status,
            payload=payload
        )

    def serialize_datagram(self) -> bytes:  # XXX seperate class - remove
        """Serialize for datagram transmission."""
        buf = Buffer(capacity=32 + len(self.payload))

        buf.push_uint_var(self.track_alias)
        buf.push_uint_var(self.group_id)
        buf.push_uint_var(self.object_id)
        buf.push_uint8(self.publisher_priority)
        
        if self.payload:
            buf.push_bytes(self.payload)
        elif self.status != ObjectStatus.NORMAL:
            buf.push_uint_var(self.status)

        return buf

    @classmethod
    def deserialize_datagram(cls, buffer: Buffer) -> 'ObjectHeader':
        """Deserialize a datagram object."""
        track_alias = buffer.pull_uint_var()
        group_id = buffer.pull_uint_var()
        object_id = buffer.pull_uint_var()
        publisher_priority = buffer.pull_uint8()
        
        remaining = buffer.pull_bytes(buffer.capacity - buffer.tell())
        if not remaining:
            status = ObjectStatus.NORMAL
            payload = b''
        else:
            try:
                status = ObjectStatus(remaining[0])
                payload = b''
            except ValueError:
                status = ObjectStatus.NORMAL
                payload = remaining

        return cls(
            track_alias=track_alias,
            group_id=group_id,
            object_id=object_id,
            publisher_priority=publisher_priority,
            forwarding_preference=ForwardingPreference.DATAGRAM,
            status=status,
            payload=payload
        )

    @classmethod
    def deserialize_track(cls, buffer: Buffer, forwarding_preference: ForwardingPreference, 
                         subgroup_id: Optional[int] = None) -> 'ObjectHeader':
        """Deserialize an object with track forwarding."""
        track_alias = buffer.pull_uint_var()
        group_id = buffer.pull_uint_var()
        object_id = buffer.pull_uint_var()
        publisher_priority = buffer.pull_uint8()
        payload_len = buffer.pull_uint_var()

        if payload_len == 0:
            try:
                status = ObjectStatus(buffer.pull_uint_var())
                payload = b''
            except ValueError as e:
                logger.error(f"Invalid object status: {e}")
                raise
        else:
            status = ObjectStatus.NORMAL
            payload = buffer.pull_bytes(payload_len)

        return cls(
            track_alias=track_alias,
            group_id=group_id,
            object_id=object_id,
            publisher_priority=publisher_priority,
            forwarding_preference=forwarding_preference,
            subgroup_id=subgroup_id,
            status=status,
            payload=payload
        )

@dataclass
class FetchHeader:
    """MOQT fetch stream header."""
    subscribe_id: int

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)
        buf.push_uint_var(DataStreamType.FETCH_HEADER)
        
        payload = Buffer(capacity=32)
        payload.push_uint_var(self.subscribe_id)

        buf.push_bytes(payload.data)
        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'FetchHeader':
        # stream_type = buffer.pull_uint_var()
        # if stream_type != DataStreamType.FETCH_HEADER:
        #     raise ValueError(f"Invalid stream type: {stream_type}")

        subscribe_id = buffer.pull_uint_var()
        return cls(subscribe_id=subscribe_id)

@dataclass
class FetchObject:
    """Object within a fetch stream."""
    group_id: int
    subgroup_id: int 
    object_id: int
    publisher_priority: int
    status: ObjectStatus = ObjectStatus.NORMAL
    payload: bytes = b''

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32 + len(self.payload))
        
        buf.push_uint_var(self.group_id)
        buf.push_uint_var(self.subgroup_id)
        buf.push_uint_var(self.object_id)
        buf.push_uint8(self.publisher_priority)

        if self.status == ObjectStatus.NORMAL:
            buf.push_uint_var(len(self.payload))
            if self.payload:
                buf.push_bytes(self.payload)
        else:
            buf.push_uint_var(0)  # Zero length
            buf.push_uint_var(self.status)  # Status code

        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'FetchObject':
        group_id = buffer.pull_uint_var()
        subgroup_id = buffer.pull_uint_var()
        object_id = buffer.pull_uint_var()
        publisher_priority = buffer.pull_uint8()
        payload_len = buffer.pull_uint_var()

        if payload_len == 0:
            try:
                status = ObjectStatus(buffer.pull_uint_var())
                payload = b''
            except ValueError as e:
                logger.error(f"Invalid object status: {e}")
                raise
        else:
            status = ObjectStatus.NORMAL
            payload = buffer.pull_bytes(payload_len)

        return cls(
            group_id=group_id,
            subgroup_id=subgroup_id,
            object_id=object_id,
            publisher_priority=publisher_priority,
            status=status,
            payload=payload
        )
        

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

        return buf

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

        return buf

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


class TrackDataParser:

    def _handle_stream_object_data(self, hdr: MOQTMessage, buf: Buffer) -> None:
        """Process object data messages."""
        logger.debug(f"async handler called for osyr")