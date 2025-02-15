#!/usr/bin/env python3

import argparse
import logging

import uvloop
import asyncio
from aioquic.h3.connection import H3_ALPN
from aiomoqt.types import ParamType
from aiomoqt.client import MOQTClientSession
from aiomoqt.utils.logger import get_logger, set_log_level


def parse_args():
    parser = argparse.ArgumentParser(description='MOQT WebTransport Client')
    parser.add_argument('--host', type=str, default='localhost', help='Host to connect to')
    parser.add_argument('--port', type=int, default=4433, help='Port to connect to')
    parser.add_argument('--namespace', type=str, default='test', help='Namespace')
    parser.add_argument('--trackname', type=str, default='track', help='Track')
    parser.add_argument('--endpoint', type=str, default='moq', help='MOQT WT endpoint')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug output')
    return parser.parse_args()


async def main(host: str, port: int, endpoint: str, namespace: str, trackname: str, debug: bool):
    log_level = logging.DEBUG if debug else logging.INFO
    set_log_level(log_level)
    logger = get_logger(__name__)

    client = MOQTClientSession(host, port, endpoint=endpoint, debug=debug)
    logger.info(f"MOQT app: publish session connecting: {client}")
    async with client.connect() as session:
        try: 
            await session.initialize()
            logger.info(f"Publish namespace via ANNOUNCE: {namespace}")
            response = await session.announce(
                namespace=namespace,
                parameters={ParamType.AUTHORIZATION_INFO: b"auth-token-123"},
                wait_response=True,
            )
            logger.info(f"MOQT app: Announce reponse: {response}")
            # process subscription requests - open data streams
            close = await session._moqt_session_close
            logger.info(f"MOQT app: exiting client session: {close}")
        except Exception as e:
            logger.error(f"MOQT session exception: {e}")
            code, reason = session._close if session._close is not None else (0,"Session Closed")
            session.close(error_code=code, reason_phrase=reason)
            pass
    
    logger.info(f"MOQT subscribe session closed: {client}")


if __name__ == "__main__":
    args = parse_args()
    uvloop.run(main(
        host=args.host,
        port=args.port,
        endpoint=args.endpoint,
        namespace=args.namespace,
        trackname=args.trackname,
        debug=args.debug
    ))
