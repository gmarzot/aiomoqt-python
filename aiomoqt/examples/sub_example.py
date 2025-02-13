#!/usr/bin/env python3
import uvloop
import asyncio
import argparse
import logging

from aioquic.h3.connection import H3_ALPN
from aiomoqt.types import ParamType
from aiomoqt.client import MOQTClientSession
from aiomoqt.messages.announce import SubscribeAnnouncesOk
from aiomoqt.messages.subscribe import SubscribeOk
from aiomoqt.utils.logger import get_logger, set_log_level


def parse_args():
    parser = argparse.ArgumentParser(description='MOQT WebTransport Client')
    parser.add_argument('--host', type=str, default='localhost', help='Host to connect to')
    parser.add_argument('--port', type=int, default=4433, help='Port to connect to')
    parser.add_argument('--namespace', type=str, default="live/test", help='Track Namespace')
    parser.add_argument('--trackname', type=str, default="track", help='Track Name')
    parser.add_argument('--endpoint', type=str, default="moq", help='MOQT WT endpoint')
    parser.add_argument('--timeout', type=int, default=10, help='connection/response tomeout')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    return parser.parse_args()


async def main(host: str, port: int, endpoint: str, namespace: str, trackname: str, timeout: int,  debug: bool):
    log_level = logging.DEBUG if debug else logging.INFO
    set_log_level(log_level)
    logger = get_logger(__name__)

    client = MOQTClientSession(
        host, port, endpoint=endpoint,
        debug=debug
    )
    logger.info(f"MOQT publish session connecting: {client}")
    async with client.connect() as session:
        try: 
            response = await session.initialize()
            response = await session.subscribe_announces(
                namespace_prefix=namespace,
                parameters={ParamType.AUTHORIZATION_INFO: b"auth-token-123"},
                wait_response=True
            )
            if not isinstance(response, SubscribeAnnouncesOk):
                logger.error(f"SubscribeAnnounces error: {response}")
                raise RuntimeError(response)
            logger.info(f"SubscribeAnnounces response: {response}")
            response = await session.subscribe(
                namespace=namespace, track_name=trackname, wait_response=True
            )
            if not isinstance(response, SubscribeOk):
                # logger.error(f"Subscribe error: {response}")
                raise RuntimeError(response)
            # process subscription - publisher will open stream and send data
            close = await session._moqt_session_close
            logger.info(f"exiting client session: {close}")
        except Exception as e:
            logger.error(f"MOQT session error: {e}")
            code, reason = session._close if session._close is not None else (0,"Session Closed")
            session.close(error_code=code, reason_phrase=reason)
            pass
        
    logger.info(f"MOQT publish session closed: {client}")


if __name__ == "__main__":
    args = parse_args()
    uvloop.run(main(
        host=args.host,
        port=args.port,
        endpoint=args.endpoint,
        namespace=args.namespace,
        trackname=args.trackname,
        timeout=args.timeout,
        debug=args.debug
    ), debug=args.debug)
