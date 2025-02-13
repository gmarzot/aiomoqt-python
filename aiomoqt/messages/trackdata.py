from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, Dict, ClassVar, Tuple, Type
from aioquic.buffer import Buffer
from .base import MOQTMessage
from ..utils.logger import get_logger
from ..types import ObjectStatus, StreamType, ForwardingPreference, DatagramType

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
class ObjectHeader:
    """MOQT object header."""
    track_alias: int
    group_id: int
    object_id: int
    publisher_priority: int
    forwarding_preference: ForwardingPreference
    subgroup_id: Optional[int] = None  # Only used when forwarding_preference is SUBGROUP
    status: ObjectStatus = ObjectStatus.NORMAL
    payload: bytes = b''

    def serialize(self) -> bytes:
        if self.forwarding_preference == ForwardingPreference.DATAGRAM:
            return self.serialize_datagram()
        return self.serialize_stream()

    def serialize_datagram(self) -> bytes:
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

    def serialize_stream(self) -> bytes:
        """Serialize for stream transmission."""
        buf = Buffer(capacity=32 + len(self.payload))

        if self.forwarding_preference == ForwardingPreference.SUBGROUP:
            buf.push_uint_var(self.object_id)
        else:
            # Track forwarding includes all fields
            buf.push_uint_var(self.track_alias)
            buf.push_uint_var(self.group_id)
            buf.push_uint_var(self.object_id)
            buf.push_uint8(self.publisher_priority)

        # Handle payload/status
        if self.status == ObjectStatus.NORMAL:
            if self.payload:
                buf.push_uint_var(len(self.payload))
                buf.push_bytes(self.payload)
            else:
                buf.push_uint_var(0)
        else:
            buf.push_uint_var(0)  # Zero length
            buf.push_uint_var(self.status)  # Status code

        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer, forwarding_preference: ForwardingPreference, 
                   subgroup_id: Optional[int] = None, stream_header: Optional['StreamHeaderSubgroup'] = None) -> 'ObjectHeader':
        """Deserialize an object based on its forwarding preference."""
        if forwarding_preference == ForwardingPreference.DATAGRAM:
            return cls.deserialize_datagram(buffer)
        elif forwarding_preference == ForwardingPreference.SUBGROUP and stream_header:
            return cls.deserialize_subgroup(buffer, stream_header)
        return cls.deserialize_track(buffer, forwarding_preference, subgroup_id)

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
    def deserialize_subgroup(cls, buffer: Buffer, header: 'StreamHeaderSubgroup') -> 'ObjectHeader':
        """Deserialize an object within a subgroup stream."""
        object_id = buffer.pull_uint_var()
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
            track_alias=header.track_alias,
            group_id=header.group_id,
            object_id=object_id,
            publisher_priority=header.publisher_priority,
            forwarding_preference=ForwardingPreference.SUBGROUP,
            subgroup_id=header.subgroup_id,
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
class StreamHeaderSubgroup:
    """MOQT subgroup stream header."""
    track_alias: int
    group_id: int
    subgroup_id: int
    publisher_priority: int

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)
        buf.push_uint_var(StreamType.STREAM_HEADER_SUBGROUP)
        
        payload = Buffer(capacity=32)
        payload.push_uint_var(self.track_alias)
        payload.push_uint_var(self.group_id)
        payload.push_uint_var(self.subgroup_id)
        payload.push_uint8(self.publisher_priority)

        buf.push_bytes(payload.data)
        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'StreamHeaderSubgroup':
        stream_type = buffer.pull_uint_var()
        if stream_type != StreamType.STREAM_HEADER_SUBGROUP:
            raise ValueError(f"Invalid stream type: {stream_type}")

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
class FetchHeader:
    """MOQT fetch stream header."""
    subscribe_id: int

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)
        buf.push_uint_var(StreamType.FETCH_HEADER)
        
        payload = Buffer(capacity=32)
        payload.push_uint_var(self.subscribe_id)

        buf.push_bytes(payload.data)
        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'FetchHeader':
        stream_type = buffer.pull_uint_var()
        if stream_type != StreamType.FETCH_HEADER:
            raise ValueError(f"Invalid stream type: {stream_type}")

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