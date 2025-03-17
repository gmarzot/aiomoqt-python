from aiomoqt.types import MOQT_CUR_VERSION

# Define the context variable - XXX too much trouble propagating
# moqt_version_context = contextvars.ContextVar('moqt_version')

moqt_version = MOQT_CUR_VERSION

def get_moqt_ctx_version() -> int:
    return moqt_version

def set_moqt_ctx_version(version: int = MOQT_CUR_VERSION) -> int:
    global moqt_version
    moqt_version = version
    return moqt_version

def get_major_version(version: int) -> bool:
    if (version & 0x00ff0000):
        return (version & 0x00ff0000) >> 16
    else:
        return (version & 0x0000ffff)
        