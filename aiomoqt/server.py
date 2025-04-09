import ssl
from typing import Any, Optional, Tuple, Coroutine

import asyncio
from asyncio.futures import Future
from qh3.quic.configuration import QuicConfiguration
from qh3.asyncio.server import QuicServer, serve
from qh3.h3.connection import H3_ALPN

from .protocol import MOQTPeer, MOQTSession
from .utils.logger import *

logger = get_logger(__name__)


class MOQTServer(MOQTPeer):
    """Server-side session manager."""
    def __init__(
        self,
        host: str,
        port: int,
        certificate: str,
        private_key: str,
        endpoint: Optional[str] = "moq",
        congestion_control_algorithm: Optional[str] = 'reno',
        configuration: Optional[QuicConfiguration] = None,
        debug: bool = False
    ):
        super().__init__()
        self.host = host
        self.port = port
        self.endpoint = endpoint
        self.debug = debug
        self._loop = asyncio.get_running_loop()
        self._server_closed:Future[Tuple[int,str]] = self._loop.create_future()
        self._next_subscribe_id = 1  # prime subscribe id generator

        if configuration is None:
            configuration = QuicConfiguration(
                is_client=False,
                alpn_protocols=H3_ALPN,
                verify_mode=ssl.CERT_NONE,
                certificate=certificate,
                private_key=private_key,
                max_datagram_frame_size=65536,
                max_data=1024*1024*8,
                max_stream_data=1024*1024*4,
                quic_logger=QuicDebugLogger() if debug else None,
                secrets_log_file=open("/tmp/keylog.server.txt", "a") if debug else None
            )        
        # load SSL certificate and key
        configuration.load_cert_chain(certificate, private_key)
        
        self.configuration = configuration
        logger.debug(f"quic_logger: {class_name(configuration.quic_logger)}")

    def serve(self) -> Coroutine[Any, Any, QuicServer]:
        """Start the MOQT server."""
        logger.info(f"Starting MOQT server on {self.host}:{self.port}")
        protocol = lambda *args, **kwargs: MOQTSession(*args, **kwargs, session=self)
        return serve(
            self.host,
            self.port,
            configuration=self.configuration,
            create_protocol=protocol,
        )
        
    async def closed(self) -> bool:
        if not self._server_closed.done():
            self._server_closed = await self._server_closed
        return True