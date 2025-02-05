import asyncio
import ssl
import os
from typing import Optional, Dict, Any
from dataclasses import dataclass
from pathlib import Path

from aioquic.asyncio.server import serve
from aioquic.h3.connection import H3_ALPN
from aioquic.quic.configuration import QuicConfiguration
from aioquic.tls import load_private_key, load_certificate_chain

from .protocol import MOQTProtocol
from .types import SessionCloseCode
from .utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ServerConfig:
    """MOQT Server configuration."""
    host: str = "localhost"
    port: int = 4433
    cert_path: str = "cert.pem"
    key_path: str = "key.pem"
    verify_mode: int = ssl.CERT_NONE
    max_datagram_size: Optional[int] = None


class MOQTServer(MOQTProtocol):
    """MOQT server implementation."""

    async def initialize(self, **kwargs) -> None:
        """Initialize server-side of MOQT session."""
        # WebTransport/H3 is already initialized by this point
        # Wait for CLIENT_SETUP
        try:
            await asyncio.wait_for(self._wt_session.wait(), timeout=30.0)
            logger.info("WebTransport session established")
        except asyncio.TimeoutError:
            logger.error("WebTransport session establishment timeout")
            raise

        # Send SERVER_SETUP
        logger.info("Sending SERVER_SETUP")
        await self.send_message(
            self.message_builder.server_setup(version=0xff000007)
        )

        self._moqt_session.set()
        logger.info("MOQT session setup complete")


def load_server_config(config: ServerConfig) -> QuicConfiguration:
    """Load QUIC server configuration with certificates."""
    if not os.path.exists(config.cert_path) or not os.path.exists(config.key_path):
        logger.error(f"Certificate ({config.cert_path}) or key ({
                     config.key_path}) not found")
        raise FileNotFoundError("Certificate or key file not found")

    quic_config = QuicConfiguration(
        alpn_protocols=H3_ALPN,
        is_client=False,
        max_datagram_size=config.max_datagram_size,
    )

    try:
        quic_config.load_cert_chain(config.cert_path, config.key_path)
    except Exception as e:
        logger.error(f"Failed to load certificates: {e}")
        raise

    return quic_config


async def create_server(config: ServerConfig) -> asyncio.AbstractServer:
    """Create and start a MOQT server."""
    quic_config = load_server_config(config)

    return await serve(
        host=config.host,
        port=config.port,
        configuration=quic_config,
        create_protocol=MOQTServer,
    )

# Example usage:
"""
# Generate test certificates (for development only):
from .utils.certs import generate_test_certs

# Server setup and run:
async def run_server():
    config = ServerConfig(
        host="localhost",
        port=4433,
        cert_path="cert.pem",
        key_path="key.pem"
    )
    
    # Generate test certs if needed
    if not os.path.exists(config.cert_path):
        generate_test_certs(config.cert_path, config.key_path)
    
    server = await create_server(config)
    
    try:
        await asyncio.Future()  # run forever
    finally:
        server.close()
        await server.wait_closed()

if __name__ == "__main__":
    asyncio.run(run_server())
"""
