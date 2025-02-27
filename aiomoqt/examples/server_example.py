import time
import logging
import argparse
import datetime

import asyncio
from aioquic.h3.connection import H3_ALPN

from aiomoqt.types import MOQTMessageType, ParamType
from aioquic.quic.configuration import QuicConfiguration
from aiomoqt.server import MOQTServerSession, MOQTSessionProtocol
from aiomoqt.utils.logger import get_logger, set_log_level

def parse_args():
    defaults = QuicConfiguration(is_client=False)
    
    parser = argparse.ArgumentParser(description='MOQT WebTransport Server')
    parser.add_argument('--host', type=str, default='localhost',
                      help='Host to bind to')
    parser.add_argument('--port', type=int, default=4433,
                      help='Port to bind to')
    parser.add_argument('--certificate', type=str, required=True,
                      help='load the TLS certificate from the specified file')
    parser.add_argument('--private-key', type=str, required=True,
                      help='load the TLS private key from the specified file')
    parser.add_argument('--endpoint', type=str, default="moq",
                      help='MOQT WebTransport endpoint')
    parser.add_argument('--congestion-control-algorithm', type=str, default="reno",
                      help='use the specified congestion control algorithm')
    parser.add_argument('--max-datagram-size', type=int, default=defaults.max_datagram_size,
                      help='maximum datagram size to send, excluding UDP or IP overhead')
    parser.add_argument('--retry', action='store_true',
                      help='send a retry for new connections')
    parser.add_argument('--debug', action='store_true',
                      help='debug logging verbosity')
    return parser.parse_args()

async def main(args):
    log_level = logging.DEBUG if args.debug else logging.INFO
    set_log_level(log_level)
    logger = get_logger(__name__)

    server = MOQTServerSession(
        host=args.host,
        port=args.port,
        certificate=args.certificate,
        private_key=args.private_key,
        endpoint=args.endpoint,
        debug=args.debug
    )

    logger.info(f"MOQT server: starting session: {server}")
    try:
        # run until closed
        await server.serve()
        await server.closed()
    except Exception as e:
        logger.error(f"MOQT server: session exception: {e}")
    finally:
        logger.info("MOQT server: shutting down")

if __name__ == "__main__":
    try:
        args = parse_args()
        asyncio.run(main(args), debug=args.debug)
    
    except KeyboardInterrupt:
        pass