import contextvars
from aiomoqt.types import MOQT_CUR_VERSION

# Define the context variable
moqt_version_context = contextvars.ContextVar('moqt_version', default=MOQT_CUR_VERSION)

def get_moqt_ctx_version() -> int:
    return moqt_version_context.get()

def set_moqt_ctx_version(version: int = MOQT_CUR_VERSION) -> contextvars.Token:
    return moqt_version_context.set(version)

def reset_moqt_ctx_version(token: contextvars.Token) -> None:
    moqt_version_context.reset(token)

def get_major_version(version: int) -> bool:
    if (version & 0x00ff0000):
        return (version & 0x00ff0000) >> 16
    else:
        return (version & 0x0000ffff)
        