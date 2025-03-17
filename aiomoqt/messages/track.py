from dataclasses import dataclass
from typing import Optional, Dict, Tuple, Union

from aioquic.buffer import Buffer, BufferReadError

from .base import MOQTUnderflow, MOQTMessage, BUF_SIZE
from ..types import ObjectStatus, DataStreamType, DatagramType, MOQT_DEFAULT_PRIORITY
from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Track:
    """Represents a MOQT track."""
    namespace: Tuple[bytes, ...]
    name: bytes
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
    publisher_priority: int = MOQT_DEFAULT_PRIORITY
    
    def __post_init__(self):
        self.type = DataStreamType.SUBGROUP_HEADER

    def serialize(self) -> Buffer:
        buf = Buffer(capacity=BUF_SIZE)
        buf.push_uint_var(DataStreamType.SUBGROUP_HEADER)   
        buf.push_uint_var(self.track_alias)
        buf.push_uint_var(self.group_id)
        buf.push_uint_var(self.subgroup_id)
        buf.push_uint8(self.publisher_priority)

        return buf

    @classmethod
    def deserialize(cls, buf: Buffer) -> 'SubgroupHeader':
        """MOQT subgroup stream header."""
        track_alias = buf.pull_uint_var()
        group_id = buf.pull_uint_var()
        subgroup_id = buf.pull_uint_var()
        publisher_priority = buf.pull_uint8()

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
    extensions: Optional[Dict[int, Union[bytes, int]]] = None
    status: Optional[ObjectStatus] = ObjectStatus.NORMAL
    payload: bytes = b''

    def serialize(self) -> Buffer:
        """Serialize for stream transmission."""
        payload_len = len(self.payload)
        buf = Buffer(capacity=(BUF_SIZE + payload_len))

        buf.push_uint_var(self.object_id)

        MOQTMessage._extensions_encode(buf, self.extensions)

        if self.status == ObjectStatus.NORMAL and self.payload:
            buf.push_uint_var(payload_len)
            buf.push_bytes(self.payload)
        else:
            buf.push_uint_var(0)  # Zero length
            buf.push_uint_var(self.status)  # Status code

        return buf
    
    @classmethod
    def deserialize(cls, buf: Buffer, buf_len: int) -> 'ObjectHeader':
        """Deserialize from stream transmission."""
        object_id = buf.pull_uint_var()

        # Parse extensions
        extensions = MOQTMessage._extensions_decode(buf)

        # Get payload or status
        payload_len = buf.pull_uint_var()
        pos = buf.tell()
        if payload_len == 0:  # Zero length means status code follows
            status = ObjectStatus(buf.pull_uint_var())
            payload = b''
        elif payload_len > (buf_len - pos):
            raise MOQTUnderflow(pos, pos + payload_len)
        else:
            status = ObjectStatus.NORMAL
            try:
                payload = buf.pull_bytes(payload_len)
            except BufferReadError:
                raise MOQTUnderflow(pos, pos + payload_len)
        
        return cls(
            object_id=object_id,
            extensions=extensions,
            status=status,
            payload=payload
        )

    @classmethod
    def deserialize_track(cls, buf: Buffer, subgroup_id: Optional[int] = None) -> 'ObjectHeader':
        """Deserialize an object with track forwarding."""
        track_alias = buf.pull_uint_var()
        group_id = buf.pull_uint_var()
        object_id = buf.pull_uint_var()
        publisher_priority = buf.pull_uint8()
        payload_len = buf.pull_uint_var()

        if payload_len == 0:
            try:
                status = ObjectStatus(buf.pull_uint_var())
                payload = b''
            except ValueError as e:
                logger.error(f"Invalid object status: {e}")
                raise
        else:
            status = ObjectStatus.NORMAL
            payload = buf.pull_bytes(payload_len)

        return cls(
            track_alias=track_alias,
            group_id=group_id,
            object_id=object_id,
            publisher_priority=publisher_priority,
            subgroup_id=subgroup_id,
            status=status,
            payload=payload
        )

@dataclass
class FetchHeader:
    """MOQT fetch stream header."""
    subscribe_id: int

    def serialize(self) -> bytes:
        buf = Buffer(capacity=BUF_SIZE)
        buf.push_uint_var(DataStreamType.FETCH_HEADER)
        
        buf.push_uint_var(self.subscribe_id)

        return buf

    @classmethod
    def deserialize(cls, buf: Buffer) -> 'FetchHeader':
        subscribe_id = buf.pull_uint_var()
        return cls(subscribe_id=subscribe_id)

@dataclass
class FetchObject:
    """Object within a fetch stream."""
    group_id: int
    subgroup_id: int 
    object_id: int
    publisher_priority: int = MOQT_DEFAULT_PRIORITY
    extensions: Dict[int, bytes] = None
    status: ObjectStatus = ObjectStatus.NORMAL
    payload: bytes = b''

    def serialize(self) -> bytes:
        buf = Buffer(capacity=BUF_SIZE + len(self.payload))
        
        buf.push_uint_var(self.group_id)
        buf.push_uint_var(self.subgroup_id)
        buf.push_uint_var(self.object_id)
        buf.push_uint8(self.publisher_priority)

        MOQTMessage._extensions_encode(buf, self.extensions)

        if self.status == ObjectStatus.NORMAL and len(self.payload) > 0:
            buf.push_uint_var(len(self.payload))
            buf.push_bytes(self.payload)
        else:
            buf.push_uint_var(0)  # Zero length
            buf.push_uint_var(self.status)  # Status code

        return buf

    @classmethod
    def deserialize(cls, buf: Buffer) -> 'FetchObject':
        group_id = buf.pull_uint_var()
        subgroup_id = buf.pull_uint_var()
        object_id = buf.pull_uint_var()
        publisher_priority = buf.pull_uint8()
        
        # Parse extensions
        extensions = MOQTMessage._extensions_decode(buf)
        payload_len = buf.pull_uint_var()

        if payload_len == 0:
            try:
                status = ObjectStatus(buf.pull_uint_var())
                payload = b''
            except ValueError as e:
                logger.error(f"Invalid object status: {e}")
                raise
        else:
            status = ObjectStatus.NORMAL
            payload = buf.pull_bytes(payload_len)

        return cls(
            group_id=group_id,
            subgroup_id=subgroup_id,
            object_id=object_id,
            publisher_priority=publisher_priority,
            extensions=extensions,
            status=status,
            payload=payload
        )
        

@dataclass
class ObjectDatagram(MOQTMessage):
    """Object datagram message."""
    track_alias: int
    group_id: int
    object_id: int
    publisher_priority: int = MOQT_DEFAULT_PRIORITY
    extensions: Optional[Dict[int, bytes]] = None
    payload: bytes = b''

    def __post_init__(self):
        self.type = DatagramType.OBJECT_DATAGRAM

    def serialize(self) -> Buffer:
        payload_len = 0 if self.payload is None else len(self.payload)
        buf = Buffer(capacity=BUF_SIZE + payload_len)
        # MOQT ObjectDatagram
        buf.push_uint_var(DatagramType.OBJECT_DATAGRAM)
        buf.push_uint_var(self.track_alias)
        buf.push_uint_var(self.group_id)
        buf.push_uint_var(self.object_id)
        buf.push_uint8(self.publisher_priority)
        MOQTMessage._extensions_encode(buf, self.extensions)
        if payload_len > 0:
            buf.push_bytes(self.payload)
        return buf

    @classmethod
    def deserialize(cls, buf: Buffer, buf_len: int) -> 'ObjectDatagram':
        track_alias = buf.pull_uint_var()
        group_id = buf.pull_uint_var()
        object_id = buf.pull_uint_var()
        publisher_priority = buf.pull_uint8()
        
        # Parse extensions
        extensions = MOQTMessage._extensions_decode(buf)
                          
        # Get payload - the rest of the datagram - no length needed
        payload = buf.pull_bytes(buf_len - buf.tell())

        return cls(
            track_alias=track_alias,
            group_id=group_id,
            object_id=object_id,
            publisher_priority=publisher_priority,
            extensions=extensions,
            payload=payload
        )

@dataclass
class ObjectDatagramStatus(MOQTMessage):
    """Object datagram status message."""
    track_alias: int
    group_id: int
    object_id: int
    publisher_priority: int = MOQT_DEFAULT_PRIORITY
    extensions: Optional[Dict[int, bytes]] = None
    status: ObjectStatus = ObjectStatus.NORMAL

    def __post_init__(self):
        self.type = DatagramType.OBJECT_DATAGRAM_STATUS

    def serialize(self) -> Buffer:
        buf = Buffer(capacity=BUF_SIZE)

        buf.push_uint_var(DatagramType.OBJECT_DATAGRAM_STATUS)   
        buf.push_uint_var(self.track_alias)
        buf.push_uint_var(self.group_id)
        buf.push_uint_var(self.object_id)
        buf.push_uint8(self.publisher_priority)
        
        MOQTMessage._extensions_encode(buf, self.extensions)
        
        buf.push_uint_var(self.status)  # Status code

        return buf

    @classmethod
    def deserialize(cls, buf: Buffer) -> 'ObjectDatagramStatus':
        track_alias = buf.pull_uint_var()
        group_id = buf.pull_uint_var()
        object_id = buf.pull_uint_var()
        publisher_priority = buf.pull_uint8()

        # Parse extensions
        extensions = MOQTMessage._extensions_decode(buf)

        status = ObjectStatus(buf.pull_uint_var())
        return cls(
            track_alias=track_alias,
            group_id=group_id,
            object_id=object_id,
            publisher_priority=publisher_priority,
            extensions=extensions,
            status=status
        )

