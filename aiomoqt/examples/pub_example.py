#!/usr/bin/env python3

import time
import logging
import argparse
import datetime

import asyncio
from aioquic.h3.connection import H3_ALPN

from aiomoqt.types import MOQTMessageType, ParamType, ObjectStatus
from aiomoqt.messages import Subscribe, SubgroupHeader, ObjectHeader
from aiomoqt.client import MOQTClientSession, MOQTSessionProtocol
from aiomoqt.utils.logger import get_logger, set_log_level

async def subscribe_data_generator(session: MOQTSessionProtocol, msg: Subscribe) -> None:
    """Wrapper for subscribe handler - spawns stream generators after standard handler"""
    
    session.default_message_handler(msg.type, msg)  
    tasks = []
    # Base layer 
    task = asyncio.create_task(
        generate_subgroup_stream(
            session=session,
            subgroup_id=0,
            track_alias=msg.track_alias,
            priority=255  # High priority
        )
    )
    task.add_done_callback(lambda t: session._tasks.discard(t))
    session._tasks.add(task)
    tasks.append(task)
    # Enhancement layer
    task = asyncio.create_task(
        generate_subgroup_stream(
            session=session,
            subgroup_id=1,
            track_alias=msg.track_alias,
            priority=0  # Lower priority
        )
    )
    task.add_done_callback(lambda t: session._tasks.discard(t))
    session._tasks.add(task)
    tasks.append(task)

    await asyncio.sleep(150)
    session._close_session()

# Create fixed padding buffers once
I_FRAME_PAD = b'I' * 100
P_FRAME_PAD = b'P' * 10

async def generate_subgroup_stream(session: MOQTSessionProtocol, subgroup_id: int, track_alias: int, priority: int):
    """Generate a stream of objects simulating video frames"""
    logger = get_logger(__name__)
    
    stream_id = session._h3.create_webtransport_stream(
        session_id=session._session_id, 
        is_unidirectional=True
    )
    logger.info(f"MOQT app: created data stream: group: 0 sub: {subgroup_id} stream: {stream_id}")

    FRAME_INTERVAL = 1/5  # 200ms
    GROUP_SIZE = 20
    next_frame_time = time.monotonic()
    object_id = 0
    group_id = -1

    try:
        while True:
            now = datetime.datetime.now()
            ts = now.second
            tu = now.microsecond
            if (object_id % GROUP_SIZE) == 0:
                group_id += 1
                if group_id > 0:
                    object_id += 1
                    status = ObjectStatus.END_OF_GROUP
                    header = ObjectHeader(
                        object_id=object_id,
                        status=status
                    )
                    msg = header.serialize()
                    if session._close_err is not None:
                        raise asyncio.CancelledError
                    logger.debug(f"MOQT app: sending: ObjectHeader: id:{group_id-1}.{subgroup_id}.{object_id} status: END_OF_GROUP")
                    session._quic.send_stream_data(stream_id, msg.data, end_stream=True)
                    session.transmit()
                    # create next group data stream
                    stream_id = session._h3.create_webtransport_stream(
                        session_id=session._session_id, 
                        is_unidirectional=True
                    )

                object_id = 0                    
                logger.debug(f"MOQT app: starting new group: id: {group_id}.{subgroup_id}.{object_id} stream: {stream_id}")
                header = SubgroupHeader(
                    track_alias=track_alias,
                    group_id=group_id,
                    subgroup_id=subgroup_id,
                    publisher_priority=priority
                )
                msg = header.serialize()
                
                if session._close_err is not None:
                    raise asyncio.CancelledError
                logger.debug(f"MOQT app: sending: {header}")
                session._quic.send_stream_data(stream_id, msg.data, end_stream=False)
                session.transmit()
                
                # prepare I frame
                info = f"{ts}.{tu} |I| {group_id}.{subgroup_id}.{object_id} |".encode()
                payload = info + I_FRAME_PAD
            else:
                # prepare P frame            
                info = f"{ts}.{tu} |P| {group_id}.{subgroup_id}.{object_id} |".encode()
                payload = info + P_FRAME_PAD    
   
            obj = ObjectHeader(object_id=object_id, payload=payload)
            msg = obj.serialize()
            logger.debug(f"MOQT app: sending: ObjectHeader: id:{group_id-1}.{subgroup_id}.{object_id} size: {msg.capacity} bytes")
            if session._close_err is not None:
                raise asyncio.CancelledError
            session._quic.send_stream_data(stream_id, msg.data, end_stream=False)
            session.transmit()
            
            object_id += 1
            next_frame_time += FRAME_INTERVAL
            sleep_time = next_frame_time - time.monotonic()
            sleep_time = 0 if sleep_time < 0 else sleep_time
            await asyncio.sleep(sleep_time)

    except asyncio.CancelledError:
        logger.warning(f"MOQT app: stream generation cancelled")
        pass

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
            # Register our data gen version of the subscribe handler
            session.register_handler(MOQTMessageType.SUBSCRIBE, subscribe_data_generator)
            
            # Complete the MoQT session setup
            await session.client_session_init()
            
            logger.info(f"MOQT app: announce namespace: {namespace}")
            response = await session.announce(
                namespace=namespace,
                parameters={ParamType.AUTHORIZATION_INFO: b"auth-token-123"},
                wait_response=True,
            )
            logger.info(f"MOQT app: announce reponse: {response}")
            
            # Process subscriptions until closed
            await session.async_closed()
        except Exception as e:
            logger.error(f"MOQT session exception: {e}")
            pass
    
    logger.info(f"MOQT app: publish session closed: {client.__class__.__name__}")


if __name__ == "__main__":
    try:
        args = parse_args()
        asyncio.run(main(
            host=args.host,
            port=args.port,
            endpoint=args.endpoint,
            namespace=args.namespace,
            trackname=args.trackname,
            debug=args.debug
        ))
      
    except KeyboardInterrupt:
        pass