from typing import Any, Union, Dict
from dataclasses import dataclass, fields

from aioquic.buffer import Buffer

from ..types import *
from ..utils.logger import *
from ..context import get_moqt_ctx_version, get_major_version

logger = get_logger(__name__)

BUF_SIZE = 64


class MOQTUnderflow(Exception):
    def __init__(self, pos: int, needed: int):
        self.pos = pos
        self.needed = needed


@dataclass
class MOQTMessage:
    """Base class for all MOQT messages."""
    # type: Optional[int] = None - let subclass set it - annoying warnings

    @staticmethod
    def _extensions_encode(buf: Buffer, exts: Dict) -> None:
        vers = get_moqt_ctx_version()
        major_version = get_major_version(vers)
        logger.debug(f"MOQTMessage._extensions_encode(): {vers} maj: {major_version}")
        if exts is None or len(exts) == 0:
            buf.push_uint_var(0)
            return
        
        if major_version > 8:
            pos = buf.tell()
            payload = Buffer(capacity=BUF_SIZE)
            for ext_id, ext_value in exts.items():
                payload.push_uint_var(ext_id)
                if ext_id % 2 == 0:  # even extension types are simple var int
                    payload.push_uint_var(ext_value)
                else:
                    if isinstance(ext_value, str):
                        ext_value = ext_value.encode()
                    assert isinstance(ext_value, bytes)
                    payload.push_uint_var(len(ext_value))
                    payload.push_bytes(ext_value)

            exts_len = payload.tell()
            buf.push_uint_var(exts_len)
            buf.push_bytes(payload.data)
        else:
            buf.push_uint_var(len(exts))
            for ext_id, ext_value in exts.items():
                buf.push_uint_var(ext_id)
                if ext_id % 2 == 0:
                    buf.push_uint_var(ext_value)
                else:
                    if isinstance(ext_value, str):
                        ext_value = ext_value.encode()
                    assert isinstance(ext_value, bytes)
                    buf.push_uint_var(len(ext_value))
                    buf.push_bytes(ext_value)


    @staticmethod
    def _extensions_decode(buf: Buffer) -> Dict[int, Union[int, bytes]]:
        exts = {}
        vers = get_moqt_ctx_version()
        major_version = get_major_version(vers)
        logger.debug(f"MOQTMessage._extensions_decode(): {vers} maj: {major_version}")
        if major_version > 8:
            exts_len = buf.pull_uint_var()
            if exts_len > 0:
                pos = buf.tell()
                exts_end = pos + exts_len
                while buf.tell() < exts_end:
                    ext_id = buf.pull_uint_var()
                    if ext_id % 2 == 0:  # even extension types are simple var int
                        ext_value = buf.pull_uint_var()
                    else:
                        value_len = buf.pull_uint_var()
                        ext_value = buf.pull_bytes(value_len)
                    exts[ext_id] = ext_value
                logger.info(f"MOQT messages: decoding extensions: version: {major_version} {exts}")
                assert buf.tell() == exts_end, f"Payload length mismatch: {exts_len} {buf.tell()-pos}"
        else:
            exts_len = buf.pull_uint_var()
            if exts_len > 0:
                for _ in range(exts_len):
                    ext_id = buf.pull_uint_var()
                    if ext_id % 2 == 0:  # even extension types are simple var int
                        ext_value = buf.pull_uint_var()
                    else:
                        value_len = buf.pull_uint_var()
                        ext_value = buf.pull_bytes(value_len)
                    exts[ext_id] = ext_value

        return exts
          
    @staticmethod
    def _bytes_encode(value: Any) -> bytes:
        if isinstance(value, int):
            return MOQTMessage._varint_encode(value)
        if isinstance(value, str):
            return value.encode()
        return value

    @staticmethod
    def _varint_encode(value: int) -> bytes:
        buf = Buffer(capacity=8)
        buf.push_uint_var(value)
        return buf.data
    
    @staticmethod
    def _varint_decode(data: bytes) -> int:
        buf = Buffer(data=data)
        return buf.pull_uint_var()

    @classmethod
    def deserialize(cls, buf: Buffer) -> 'MOQTMessage':
        """Create message from buf containing payload."""
        raise NotImplementedError()

    def serialize(self) -> bytes:
        """Convert message to complete wire format."""
        raise NotImplementedError()

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
                enum = SetupParamType if class_name(self).endswith('Setup') else ParamType
                for k, v in value.items():
                    param_name = enum(k).name  # Convert enum value to name
                    if isinstance(v, int):
                        items.append(f"{param_name}={v}")
                    else:
                        items.append(f"{param_name}=0x{v.hex()}")

                str_val = "{" + ", ".join(items) + "}"
            elif isinstance(value, bytes):
                try:
                    str_val = value.decode('utf-8')
                except UnicodeDecodeError:
                    str_val = f"0x{value.hex()}"
            elif isinstance(value, dict):
                str_val = "{" + ", ".join(f"{k}: {v}" for k, v in value.items()) + "}"
            elif field.name == 'payload':
                str_val = f"0x{value.hex()}"
            else:
                str_val = str(value)
            parts.append(f"{field.name}={str_val}")

        return f"{class_name(self)}({', '.join(parts)})"