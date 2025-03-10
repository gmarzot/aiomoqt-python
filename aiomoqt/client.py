import os
import sys
import ssl
from typing import Optional, AsyncContextManager

from aioquic.quic.configuration import QuicConfiguration
from aioquic.asyncio.client import connect
from aioquic.h3.connection import H3_ALPN

from .protocol import *
from .utils.logger import *

logger = get_logger(__name__)

class MOQTClientSession(MOQTSession):  # New connection manager class
    def __init__(
        self,
        host: str,
        port: int,
        endpoint: Optional[str] = None,
        configuration: Optional[QuicConfiguration] = None,
        keylog_filename: Optional[str] = None,
        debug: Optional[bool] = False,
    ):
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
                max_datagram_frame_size=65536,
                max_datagram_size=QuicConfiguration.max_datagram_size,
                quic_logger=QuicDebugLogger() if debug else None,
                secrets_log_file=keylog_file
            )
        self.configuration = configuration
        logger.debug(f"quic_logger: {class_name(configuration.quic_logger)}")

    def connect(self) -> AsyncContextManager[MOQTSessionProtocol]:
        """Return a context manager that creates MOQTSessionProtocol instance."""
        logger.debug(f"MOQT: session connect: {self}")
        protocol = lambda *args, **kwargs: MOQTSessionProtocol(*args, **kwargs, session=self)
        return connect(
            self.host,
            self.port,
            configuration=self.configuration,
            create_protocol=protocol
        )
