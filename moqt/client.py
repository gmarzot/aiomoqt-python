import asyncio
import ssl
from typing import Optional, Dict, Any

from aioquic.quic.configuration import QuicConfiguration
from aioquic.asyncio.client import connect
from aioquic.h3.connection import H3_ALPN

from .protocol import MOQTProtocol
from .moqtypes import (
    FilterType, GroupOrder, SessionCloseCode, 
    SubscribeErrorCode, SubscribeDoneCode
)
from .utils.logger import get_logger

logger = get_logger(__name__)

USER_AGENT = "moqt-client/0.1.0"

class MOQTClient(MOQTProtocol):
    """MOQT client implementation."""
    
    async def initialize(self, host: str, port: int) -> None:
        """Initialize WebTransport and MOQT session."""
        # Create WebTransport session
        session_stream_id = self._h3._quic.get_next_available_stream_id(
            is_unidirectional=False
        )
        
        headers = [
            (b":method", b"CONNECT"),
            (b":protocol", b"webtransport"),
            (b":scheme", b"https"),
            (b":authority", f"{host}:{port}".encode()),
            (b":path", b"/moq"),
            (b"sec-webtransport-http3-draft", b"draft02"),
            (b"user-agent", USER_AGENT.encode()),
        ]
        
        logger.info(f"Sending WebTransport session request (stream: {session_stream_id})")
        self._h3.send_headers(stream_id=session_stream_id, headers=headers, end_stream=False)
        
        # Wait for WebTransport session establishment
        try:
            await asyncio.wait_for(self._wt_session.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            logger.error("WebTransport session establishment timeout")
            raise
        
        # Create MOQT control stream
        self._control_stream_id = self._h3.create_webtransport_stream(
            session_id=session_stream_id
        )
        logger.info(f"Created control stream: {self._control_stream_id}")
        
        # Send CLIENT_SETUP
        logger.info("Sending CLIENT_SETUP")
        await self.send_message(
            self.message_builder.client_setup(version=0xff000007)
        )
        
        # Wait for SERVER_SETUP
        try:
            await asyncio.wait_for(self._moqt_session.wait(), timeout=5.0)
            logger.info("MOQT session setup complete")
        except asyncio.TimeoutError:
            logger.error("MOQT session setup timeout")
            raise

    async def subscribe_to_track(
        self,
        namespace: str,
        track_name: str,
        subscribe_id: int = 1,
        track_alias: int = 1,
        priority: int = 128,
        group_order: GroupOrder = GroupOrder.ASCENDING,
        filter_type: FilterType = FilterType.LATEST_GROUP,
        start_group: Optional[int] = None,
        start_object: Optional[int] = None,
        end_group: Optional[int] = None,
        parameters: Optional[Dict[int, bytes]] = None
    ) -> None:
        """Subscribe to a track with configurable options."""
        logger.info(f"Subscribing to {namespace}/{track_name}")
        
        if parameters is None:
            parameters = {}
            
        await self.send_message(
            self.message_builder.subscribe(
                subscribe_id=subscribe_id,
                track_alias=track_alias,
                namespace=namespace.encode(),
                track_name=track_name.encode(),
                priority=priority,
                direction=group_order,
                filter_type=filter_type,
                start_group=start_group,
                start_object=start_object,
                end_group=end_group,
                parameters=parameters
            )
        )

async def create_client(
    host: str, 
    port: int,
    configuration: Optional[QuicConfiguration] = None,
    debug: bool = False
) -> MOQTClient:
    """Create and initialize a MOQT client connection."""
    if configuration is None:
        configuration = QuicConfiguration(
            alpn_protocols=H3_ALPN,
            is_client=True,
            verify_mode=ssl.CERT_NONE,  # For development only
        )
    
    client = await connect(
        host,
        port,
        configuration=configuration,
        create_protocol=MOQTClient
    )
    
    await client.initialize(host, port)
    return client
