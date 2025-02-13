from dataclasses import dataclass
from typing import Dict, List, Any
from aioquic.buffer import Buffer
from .base import MOQTMessage
from ..types import MOQTMessageType, SetupParamType
from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ServerSetup(MOQTMessage):
    """SERVER_SETUP message for accepting MOQT session."""
    selected_version: int = None
    parameters: Dict[int, bytes] = None

    def __post_init__(self):
        self.type = MOQTMessageType.SERVER_SETUP

    def serialize(self) -> Buffer:
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
        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'ServerSetup':
        """Handle SERVER_SETUP message."""
        version = buffer.pull_uint_var()
        param_count = buffer.pull_uint_var()

        params = {}
        for _ in range(param_count):
            param_id = buffer.pull_uint_var()
            param_len = buffer.pull_uint_var()
            param_value = buffer.pull_bytes(param_len)
            params[param_id] = param_value
        return cls(selected_version=version, parameters=params)
        # self.protocol._moqt_session.set()


@dataclass
class ClientSetup(MOQTMessage):
    """CLIENT_SETUP message for initializing MOQT session."""
    versions: List[int] = None
    parameters: Dict[int, Any] = None

    def __post_init__(self):
        self.type = MOQTMessageType.CLIENT_SETUP

    def serialize(self) -> Buffer:
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
        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> None:
        """Handle CLIENT_SETUP message."""

        versions = []
        version_count = buffer.pull_uint_var()
        for _ in range(version_count):
            versions.append(buffer.pull_uint_var())

        param_count = buffer.pull_uint_var()

        logger.info(
            f"CLIENT_SETUP: version: {versions} params: {param_count} ")
        params = {}
        for _ in range(param_count):
            param_id = buffer.pull_uint_var()
            param_len = buffer.pull_uint_var()
            param_value = buffer.pull_bytes(param_len)
            if (param_id == SetupParamType.MAX_SUBSCRIBER_ID):
                id = "MAX_SUBSCRIBER_ID"
                param_value = Buffer(data=param_value).pull_uint_var()
            elif (param_id == SetupParamType.CLIENT_ROLE):
                id = "CLIENT_ROLE"
            elif (param_id == SetupParamType.ENDPOINT_PATH):
                id = "ENDPOINT_PATH"
            else:
                id = "UNKNOWN"
                logger.error(
                    f"_handle_server_setup: received unknown setup param type: {hex(param_id)}")
            params[param_id] = param_value
            logger.debug(
                f"  param: id: {id} ({hex(param_id)}) len: {param_len} val: {param_value}")

            return cls(versions=versions, parameters=params)
        

@dataclass
class GoAway(MOQTMessage):
    new_session_uri: str = None

    def __post_init__(self):
        self.type = MOQTMessageType.GOAWAY

    def serialize(self) -> Buffer:
        buf = Buffer(capacity=32 + len(self.new_session_uri))

        # Calculate payload size
        payload_size = 1  # uri length varint
        payload_size += len(self.new_session_uri.encode())  # uri bytes

        # Write message
        buf.push_uint_var(self.type)
        buf.push_uint_var(payload_size)

        # Write URI length and data
        uri_bytes = self.new_session_uri.encode()
        buf.push_uint_var(len(uri_bytes))
        buf.push_bytes(uri_bytes)

        return buf

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'GoAway':
        uri_len = buffer.pull_uint_var()
        uri = buffer.pull_bytes(uri_len).decode()
        return cls(new_session_uri=uri)
