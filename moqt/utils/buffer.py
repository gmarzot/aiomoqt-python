from aioquic.buffer import Buffer as QuicBuffer, UINT_VAR_MAX # type: ignore

class Buffer(QuicBuffer):
    """Extended buffer implementation with MOQT-specific methods."""
    
    def __init__(self, data: bytes = b"", capacity: int = 0):
        super().__init__(data=data, capacity=capacity)

    def push_moqt_header(self, msg_type: int, payload: bytes) -> None:
        """Push a MOQT message header (type + length + payload)."""
        self.push_uint_var(msg_type)
        self.push_uint_var(len(payload))
        self.push_bytes(payload)

    def push_moqt_string(self, value: bytes) -> None:
        """Push a length-prefixed string."""
        self.push_uint_var(len(value))
        self.push_bytes(value)

    def pull_moqt_string(self) -> bytes:
        """Pull a length-prefixed string."""
        length = self.pull_uint_var()
        return self.pull_bytes(length)

    def peek_uint_var(self) -> int:
        """Look at next varint without consuming it."""
        pos = self._pos
        value = self.pull_uint_var()
        self._pos = pos
        return value
