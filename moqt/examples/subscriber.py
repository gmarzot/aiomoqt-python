#!/usr/bin/env python3

import argparse
import logging
import ssl

import asyncio
import moqt.client


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
    parser.add_argument('--timeout', type=int, default=30,
                        help='How long to run before unsubscribing (seconds)')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug output')
    return parser.parse_args()


async def main(host: str, port: int, namespace: str, trackname: str, timeout: int,
               debug: bool):
    client = await create_client("localhost", 4433)
    await client.subscribe_to_track(
        namespace="example",
        track_name="video"
    )

    except asyncio.TimeoutError:
        logger.error("Operation timed out")
        raise

if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(
        host=args.host,
        port=args.port,
        namespace=args.namespace,
        trackname=args.trackname,
        timeout=args.timeout,
        debug=args.debug
    ))
