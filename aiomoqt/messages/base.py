import inspect
import asyncio
from dataclasses import dataclass, fields
from aioquic.buffer import Buffer
from ..types import SetupParamType
from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MOQTMessage:
    """Base class for all MOQT messages."""
    # type: Optional[int] = None - let subclass set it - annoying warnings

    def serialize(self) -> bytes:
        """Convert message to complete wire format."""
        raise NotImplementedError()

    @classmethod
    def deserialize(cls, buffer: Buffer) -> 'MOQTMessage':
        """Create message from buffer containing payload."""
        raise NotImplementedError()

    @staticmethod
    def _varint_encode(value: int) -> bytes:
        buf = Buffer(capacity=8)
        buf.push_uint_var(value)
        return buf.data
    
    @staticmethod
    def _varint_decode(data: bytes) -> int:
        buf = Buffer(data=data)
        return buf.pull_uint_var()

    def __str__(self) -> str:
        """Generic string representation showing all fields."""
        parts = []
        class_fields = fields(self.__class__)

        for field in class_fields:
            value = getattr(self, field.name)
            if "version" in field.name.lower():
                if isinstance(value, (list, tuple)):
                    str_val = "[" + ", ".join(f"0x{x:x}" for x in value) + "]"
                else:
                    str_val = f"0x{value:x}"  # Single version number
            elif field.name == "parameters":
                # Decode parameter types and values
                items = []
                for k, v in value.items():
                    param_name = SetupParamType(k).name  # Convert enum value to name
                    try:
                        # Try to decode value as varint
                        param_value = v if isinstance(v, int) else self._varint_decode(v)
                        items.append(f"{param_name}={param_value}")
                    except:
                        # Fall back to hex for non-varint values
                        items.append(f"{param_name}=0x{v.hex()}")
                str_val = "{" + ", ".join(items) + "}"
            elif isinstance(value, bytes):
                try:
                    str_val = value.decode('utf-8')
                except UnicodeDecodeError:
                    str_val = f"0x{value.hex()}"
            elif isinstance(value, dict):
                str_val = "{" + ", ".join(f"{k}: {v}" for k, v in value.items()) + "}"
            else:
                str_val = str(value)
            parts.append(f"{field.name}={str_val}")

        return f"{self.__class__.__name__}({', '.join(parts)})"