
import ssl
from typing import Optional, AsyncContextManager

from qh3.quic.configuration import QuicConfiguration
from qh3.asyncio.client import connect
from qh3.h3.connection import H3_ALPN

from .protocol import *
from .utils.logger import *

logger = get_logger(__name__)

class MOQTClient(MOQTPeer):  # New connection manager class
    def __init__(
        self,
        host: str,
        port: int,
        endpoint: Optional[str] = None,
        configuration: Optional[QuicConfiguration] = None,
        keylog_filename: Optional[str] = None,
        debug: Optional[bool] = False,
        quic_debug: Optional[bool] = False,
    ):
        super().__init__()
        self.host = host
        self.port = port
        self.debug = debug
        self.endpoint = endpoint
        if configuration is None:
            keylog_file = open(keylog_filename, 'a') if keylog_filename else None
            configuration = QuicConfiguration(
                alpn_protocols=H3_ALPN,
                is_client=True,
                verify_mode=ssl.CERT_NONE,
                max_data=2**24,
                max_stream_data=2**24,
                max_datagram_frame_size=64*1024,
                quic_logger=QuicDebugLogger() if quic_debug else None,
                secrets_log_file=keylog_file
            )
        self.configuration = configuration

    def connect(self) -> AsyncContextManager[MOQTSession]:
        """Return a context manager that creates MOQTSessionProtocol instance."""
        logger.debug(f"MOQT: session connect: {self}")
        protocol = lambda *args, **kwargs: MOQTSession(*args, **kwargs, session=self)
        return connect(
            self.host,
            self.port,
            configuration=self.configuration,
            create_protocol=protocol
        )
