from dataclasses import dataclass
from typing import List, Dict, Optional
from .utils.buffer import Buffer
from .moqtypes import MessageTypes


@dataclass
class MOQTMessage:
    """Base class for all MOQT messages."""
    type: int

    def serialize(self) -> bytes:
        """Convert message to wire format."""
        raise NotImplementedError()

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'MOQTMessage':
        """Create message from wire format."""
        raise NotImplementedError()


@dataclass
class ClientSetup(MOQTMessage):
    """CLIENT_SETUP message for initializing MOQT session."""
    versions: List[int]
    parameters: Dict[int, bytes]

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)
        payload = Buffer(capacity=32)

        # Add versions
        payload.push_uint_var(len(self.versions))
        for version in self.versions:
            payload.push_uint_var(version)

        # Add parameters
        payload.push_uint_var(len(self.parameters))
        for param_id, param_value in self.parameters.items():
            payload.push_uint_var(param_id)
            payload.push_uint_var(len(param_value))
            payload.push_bytes(param_value)

        # Build final message
        buf.push_uint_var(self.type)  # CLIENT_SETUP type
        buf.push_uint_var(len(payload.data))
        buf.push_bytes(payload.data)
        return buf.data


@dataclass
class ServerSetup(MOQTMessage):
    """SERVER_SETUP message for accepting MOQT session."""
    selected_version: int
    parameters: Dict[int, bytes]

    def serialize(self) -> bytes:
        buf = Buffer(capacity=32)
        payload = Buffer(capacity=32)

        # Add selected version
        payload.push_uint_var(self.selected_version)

        # Add parameters
        payload.push_uint_var(len(self.parameters))
        for param_id, param_value in self.parameters.items():
            payload.push_uint_var(param_id)
            payload.push_uint_var(len(param_value))
            payload.push_bytes(param_value)

        # Build final message
        buf.push_uint_var(self.type)  # SERVER_SETUP type
        buf.push_uint_var(len(payload.data))
        buf.push_bytes(payload.data)
        return buf.data


@dataclass
class Subscribe(MOQTMessage):
    """SUBSCRIBE message for requesting track data."""
    subscribe_id: int
    track_alias: int
    namespace: bytes
    track_name: bytes
    priority: int
    direction: int  # Ascending/Descending
    filter_type: int
    start_group: Optional[int] = None
    start_object: Optional[int] = None
    end_group: Optional[int] = None
    parameters: Optional[Dict[int, bytes]] = None

    def serialize(self) -> bytes:
        buf = Buffer(capacity=64)
        payload = Buffer(capacity=64)

        payload.push_uint_var(self.subscribe_id)
        payload.push_uint_var(self.track_alias)

        # Add namespace as tuple
        namespace_parts = self.namespace.split(b'.')
        payload.push_uint_var(len(namespace_parts))
        for part in namespace_parts:
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
        return buf.data


@dataclass
class Unsubscribe(MOQTMessage):
    """UNSUBSCRIBE message for ending track subscription."""
    subscribe_id: int

    def serialize(self) -> bytes:
        buf = Buffer(capacity=8)
        payload = Buffer(capacity=8)

        payload.push_uint_var(self.subscribe_id)

        buf.push_uint_var(self.type)
        buf.push_uint_var(len(payload.data))
        buf.push_bytes(payload.data)
        return buf.data


class MessageBuilder:
    """Helper class to construct MOQT messages."""

    def client_setup(self, version: int = 0xff000007) -> bytes:
        """Create a CLIENT_SETUP message."""
        msg = ClientSetup(
            type=MessageTypes.CLIENT_SETUP,
            versions=[version],
            parameters={}
        )
        return msg.serialize()

    def subscribe(self, subscribe_id: int, track_alias: int, namespace: bytes,
                  track_name: bytes, priority: int = 128,
                  direction: int = 0x1, filter_type: int = 0x1,
                  start_group: Optional[int] = None,
                  start_object: Optional[int] = None,
                  end_group: Optional[int] = None,
                  parameters: Optional[Dict[int, bytes]] = None) -> bytes:
        """Create a SUBSCRIBE message."""
        msg = Subscribe(
            type=MessageTypes.SUBSCRIBE,
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
            parameters=parameters
        )
        return msg.serialize()

    def unsubscribe(self, subscribe_id: int) -> bytes:
        """Create an UNSUBSCRIBE message."""
        msg = Unsubscribe(
            type=MessageTypes.UNSUBSCRIBE,
            subscribe_id=subscribe_id
        )
        return msg.serialize()
