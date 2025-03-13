from dataclasses import dataclass
from typing import Dict, List, Any
from aioquic.buffer import Buffer
from .base import MOQTMessage, BUF_SIZE
from ..types import *
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
        buf = Buffer(capacity=BUF_SIZE)
        payload = Buffer(capacity=BUF_SIZE)

        # Add selected version
        payload.push_uint_var(self.selected_version)

        # Add parameters
        payload.push_uint_var(len(self.parameters))
        for param_id, param_value in self.parameters.items():
            payload.push_uint_var(param_id)
            if isinstance(param_value, int):
                param_value = MOQTMessage._varint_encode(param_value)
            payload.push_uint_var(len(param_value))
            payload.push_bytes(param_value)

        # Build final message
        buf.push_uint_var(self.type)  # SERVER_SETUP type
        buf.push_uint_var(payload.tell())
        buf.push_bytes(payload.data)
        return buf

    @classmethod
    def deserialize(cls, buf: Buffer) -> 'ServerSetup':
        """Handle SERVER_SETUP message."""

        version = buf.pull_uint_var()

        params = {}
        param_count = buf.pull_uint_var()
        for _ in range(param_count):
            param_id = buf.pull_uint_var()
            param_len = buf.pull_uint_var()
            param_value = buf.pull_bytes(param_len)
            if (param_id == SetupParamType.MAX_SUBSCRIBER_ID):
                param_value = Buffer(data=param_value).pull_uint_var()
            params[param_id] = param_value


        return cls(selected_version=version, parameters=params)


@dataclass
class ClientSetup(MOQTMessage):
    """CLIENT_SETUP message for initializing MOQT session."""
    versions: List[int] = None
    parameters: Dict[int, Any] = None

    def __post_init__(self):
        self.type = MOQTMessageType.CLIENT_SETUP

    def serialize(self) -> Buffer:
        buf = Buffer(capacity=BUF_SIZE)
        payload = Buffer(capacity=BUF_SIZE)

        # Add versions
        payload.push_uint_var(len(self.versions))
        for version in self.versions:
            payload.push_uint_var(version)

        # Add parameters
        payload.push_uint_var(len(self.parameters))
        for param_id, param_value in self.parameters.items():
            payload.push_uint_var(param_id)
            if isinstance(param_value, int):
                param_value = MOQTMessage._varint_encode(param_value)
            payload.push_uint_var(len(param_value))
            payload.push_bytes(param_value)

        # Build final message
        buf.push_uint_var(self.type)  # CLIENT_SETUP type
        buf.push_uint_var(len(payload.data))
        buf.push_bytes(payload.data)
        return buf

    @classmethod
    def deserialize(cls, buf: Buffer) -> 'ClientSetup':
        """Handle CLIENT_SETUP message."""
        logger.info(f"CLIENT_SETUP: {buf.data.hex()} ")
                
        versions = []
        version_count = buf.pull_uint_var()
        for _ in range(version_count):
            versions.append(buf.pull_uint_var())

        param_count = buf.pull_uint_var()
        logger.info(f"CLIENT_SETUP: version: {versions} params: {param_count} ")
        params = {}
        for _ in range(param_count):
            param_id = buf.pull_uint_var()
            param_len = buf.pull_uint_var()
            param_value = buf.pull_bytes(param_len)
            if (param_id == SetupParamType.MAX_SUBSCRIBER_ID):
                param_value = Buffer(data=param_value).pull_uint_var()
            if param_id in [SetupParamType.MAX_SUBSCRIBER_ID, SetupParamType.ENDPOINT_PATH]:
                id = SetupParamType(param_id).name
            else:
                id = f"0x{param_value.hex()}"

            logger.info(f"  {id}: {param_value}")
            params[param_id] = param_value
            
        return cls(versions=versions, parameters=params)
        

@dataclass
class GoAway(MOQTMessage):
    new_session_uri: str = None

    def __post_init__(self):
        self.type = MOQTMessageType.GOAWAY

    def serialize(self) -> Buffer:
        buf = Buffer(capacity=BUF_SIZE)
        payload = Buffer(capacity=BUF_SIZE)
        
        uri_bytes = self.new_session_uri.encode()
        payload.push_uint_var(len(uri_bytes))  # uri bytes
        payload.push_bytes(uri_bytes)
        
        # Write message
        buf.push_uint_var(self.type)
        buf.push_uint_var(payload.tell())
        buf.push_bytes(payload.data)

        return buf

    @classmethod
    def deserialize(cls, buf: Buffer) -> 'GoAway':

        uri_len = buf.pull_uint_var()
        uri = buf.pull_bytes(uri_len).decode()

        return cls(new_session_uri=uri)
