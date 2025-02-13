#!/usr/bin/env python3

import argparse
import logging
import ssl

import asyncio
from aioquic.h3.connection import H3_ALPN
from aioquic.quic.configuration import QuicConfiguration
from aiomoqt.types import ParamType
from aiomoqt.client import MOQTClientSession
from aiomoqt.utils.logger import get_logger, set_log_level, QuicDebugLogger


def parse_args():
    parser = argparse.ArgumentParser(description='MOQT WebTransport Client')
    parser.add_argument('--host', type=str, default='localhost',
                        help='Host to connect to')
    parser.add_argument('--port', type=int, default=4433,
                        help='Port to connect to')
    parser.add_argument('--namespace', type=str, required=True,
                        help='Track namespace')
    parser.add_argument('--trackname', type=str, required=True,
                        help='Track name')
    parser.add_argument('--endpoint', type=str, required=True,
                        help='MOQT WT endpoint')
    parser.add_argument('--timeout', type=int, default=30,
                        help='How long to run before unsubscribing (seconds)')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug output')
    return parser.parse_args()


async def main(host: str, port: int, endpoint: str, namespace: str, trackname: str, timeout: int,  debug: bool):
    log_level = logging.DEBUG if debug else logging.INFO
    set_log_level(log_level)
    logger = get_logger(__name__)

    client = MOQTClientSession(host, port, endpoint=endpoint, debug=debug)
    logger.info(f"Opening MOQT client session: {client}")
    async with client.connect() as session:
        try: 
            await session.initialize()
            logger.info(f"Publish namespace via ANNOUNCE: {namespace}")
            response = await session.announce(
                namespace=namespace,
                parameters={ParamType.AUTHORIZATION_INFO: b"auth-token-123"},
                wait_response=True,
            )
            logger.info(f"Announce reponse: {response}")
            # process subscription - publisher will open stream and send data
            close = await session._moqt_session_close
            logger.info(f"exiting client session: {close}")
        except Exception as e:
            logger.error(f"MOQT session error: {e}")
            code, reason = session._close if session._close is not None else (0,"Session Closed")
            session.close(error_code=code, reason_phrase=reason)
            pass
    
    logger.info(f"MOQT client session closed: {client}")


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(
        host=args.host,
        port=args.port,
        endpoint=args.endpoint,
        namespace=args.namespace,
        trackname=args.trackname,
        timeout=args.timeout,
        debug=args.debug
    ))
