import ssl
from typing import Any, Optional, Tuple, Coroutine

import asyncio
from asyncio.futures import Future
from aioquic.quic.configuration import QuicConfiguration
from aioquic.asyncio.server import QuicServer, serve
from aioquic.h3.connection import H3_ALPN

from .protocol import MOQTSession, MOQTSessionProtocol
from .utils.logger import *

logger = get_logger(__name__)


class MOQTServerSession(MOQTSession):
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
                congestion_control_algorithm=congestion_control_algorithm,
                max_datagram_frame_size=65536,
                max_datagram_size=QuicConfiguration.max_datagram_size,
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
        
        protocol = lambda *args, **kwargs: MOQTSessionProtocol(*args, **kwargs, session=self)

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