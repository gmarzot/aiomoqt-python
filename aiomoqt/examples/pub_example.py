#!/usr/bin/env python3

import time
import logging
import argparse

import asyncio
from aioquic.h3.connection import H3_ALPN

from aiomoqt.types import MOQTMessageType, ParamType, ObjectStatus, MOQTException
from aiomoqt.messages import (
    Subscribe, 
    SubgroupHeader, 
    ObjectHeader, 
    ObjectDatagram, 
    ObjectDatagramStatus,
)
from aiomoqt.client import *
from aiomoqt.utils import *


# Create fixed padding buffers once
I_FRAME_PAD = b'I' * 1024 * 1
P_FRAME_PAD = b'P' * 512 * 1

FRAME_INTERVAL = 1/30  # 33ms
GROUP_SIZE = 30


async def dgram_subscribe_data_generator(session: MOQTSessionProtocol, msg: Subscribe) -> None:
    """Wrapper for subscribe handler - spawns stream generators after standard handler"""
    session.default_message_handler(msg.type, msg)  
    logger.debug(f"dgram_subscribe_data_generator: track_alias: {msg.track_alias}")
    # Base layer 
    task = asyncio.create_task(
        generate_group_dgram(
            session=session,
            track_alias=msg.track_alias,
            priority=255  # High priority
        )
    )
    task.add_done_callback(lambda t: session._tasks.discard(t))
    session._tasks.add(task)

    await asyncio.sleep(150)
    session._close_session()
    
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

    await session.async_closed()
    session._close_session()

async def generate_group_dgram(session: MOQTSessionProtocol, track_alias: int, priority: int):
    """Generate a stream of objects simulating video frames"""
    logger = get_logger(__name__)

    next_frame_time = time.monotonic()
    object_id = 0
    group_id = -1
    logger.debug(f"MOQT app: generating dgram group data: {track_alias}")
    try:
        while True:
            if (object_id % GROUP_SIZE) == 0:
                group_id += 1
                if group_id > 0:
                    status = ObjectStatus.END_OF_GROUP
                    obj = ObjectDatagramStatus(
                        track_alias=track_alias,
                        group_id=group_id,
                        object_id=object_id,
                        publisher_priority=priority,
                        status=status,
                        extensions = {
                            0: 4207849484,
                            37: f"MOQT-TS: {int(time.time()*1000)}"
                        }
                    )

                    msg = obj.serialize()
                    if session._close_err is not None:
                        logger.error(f"MOQT app: session closed with error: {session._close_err}")
                        raise MOQTException(*session._close_err)
                    logger.debug(f"MOQT app: sending: ObjectDatagramStatus: id:{group_id-1}.{object_id} alias: {obj.track_alias} status: END_OF_GROUP")
                    if session._close_err is not None:
                        raise asyncio.CancelledError
                    session._quic.send_datagram_frame(b'\0' + msg.data)
                    session.transmit()
                    
                object_id = 0
                ts = int(time.time()*1000)                    
                # prepare I frame
                info = f"| {ts} |I| {group_id}.{object_id} |".encode()
                payload = info + I_FRAME_PAD            
            else:
                ts = int(time.time()*1000)                    
                # prepare P frame            
                info = f"| {ts} |P| {group_id}.{object_id} |".encode()
                payload = info + P_FRAME_PAD 

            logger.debug(f"MOQT app: sending: ObjectDatagram: id: {group_id}.{object_id} payload size: {len(payload)} bytes")
            if object_id == 0:
                extensions = {
                    0: 4207849484,
                    37: f"MOQT-TS: {ts}".encode()
                }
            else:
                extensions = {} 
                
            payload = payload[:1100]    
            obj = ObjectDatagram(
                track_alias=track_alias,
                group_id=group_id,
                object_id=object_id,
                publisher_priority=priority,
                extensions=extensions,
                payload=payload,
            )
            if obj is None:
                logger.error(f"MOQT app: error: ObjectDatagram: constructor failed")
                raise RuntimeError()
            msg = obj.serialize()
            msg_len = len(msg.data)
            logger.debug(f"MOQT app: sending: ObjectDatagram: id: {group_id}.{object_id} alias: {obj.track_alias} size: {msg_len} {msg.tell()} bytes")
            if session._close_err is not None:
                raise asyncio.CancelledError

            session._quic.send_datagram_frame(b'\0' + msg.data)
            session.transmit()
            
            object_id += 1
            next_frame_time += FRAME_INTERVAL
            sleep_time = next_frame_time - time.monotonic()
            sleep_time = 0 if sleep_time < 0 else sleep_time
            logger.debug(f"MOQT app: sleeping: {sleep_time} sec")
            await asyncio.sleep(sleep_time)
                             
    except asyncio.CancelledError:
        logger.warning(f"MOQT app: stream generation cancelled")
        pass
    
async def generate_subgroup_stream(session: MOQTSessionProtocol, subgroup_id: int, track_alias: int, priority: int):
    """Generate a stream of objects simulating video frames"""
    logger = get_logger(__name__)
    if session._h3 is None:
        return
    stream_id = session._h3.create_webtransport_stream(
        session_id=session._session_id, 
        is_unidirectional=True
    )
    logger.info(f"MOQT app: created data stream: group: 0 sub: {subgroup_id} stream: {stream_id}")

    next_frame_time = time.monotonic()
    object_id = 0
    group_id = -1

    try:
        while True:
            if (object_id % GROUP_SIZE) == 0:
                group_id += 1
                if group_id > 0:
                    status = ObjectStatus.END_OF_GROUP
                    header = ObjectHeader(
                        object_id=object_id,
                        status=status,
                        extensions={
                            0: 4207849484,
                            37: f"MOQT-TS: {int(time.time()*1000)}"
                        }
                    )
                    msg = header.serialize()
                    logger.debug(f"MOQT app: sending object status: Ox{msg.data.hex()}")
                    if session._close_err is not None:
                        raise asyncio.CancelledError
                    logger.debug(f"MOQT app: sending: ObjectHeader END_OF_GROUP: id:{group_id-1}.{subgroup_id}.{object_id}")
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
                
                ts = int(time.time()*1000)                    
                # prepare I frame
                info = f"| {ts} |I| {group_id}.{subgroup_id}.{object_id} |".encode()
                payload = info + I_FRAME_PAD
            else:
                ts = int(time.time()*1000)                    
                # prepare P frame            
                info = f"| {ts} |P| {group_id}.{subgroup_id}.{object_id} |".encode()
                payload = info + P_FRAME_PAD    
                
            if object_id == 0:
                extensions = {
                    0: 4207849484,
                    37: f"MOQT-TS: {ts}".encode()
                }
            else:
                extensions = {}
                
            obj = ObjectHeader(
                object_id=object_id,
                    payload=payload,
                    extensions=extensions
            )                
            msg = obj.serialize()
            logger.debug(f"MOQT app: sending ObjectHeader: id: {group_id}.{subgroup_id}.{object_id} size: {msg.tell()} bytes")
            logger.debug(f"MOQT app: sending ObjectHeader: data: 0x{msg.data_slice(0,16).hex()}...")
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
    parser.add_argument('--datagram', action='store_true', help='Emit ObjectDatagrams')
    parser.add_argument('--keylogfile', type=str, default=None, help='TLS secrets file')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug output')
    return parser.parse_args()


async def main(host: str, port: int, endpoint: str, namespace: str, trackname: str, debug: bool, datagram: bool):
    log_level = logging.DEBUG if debug else logging.INFO
    set_log_level(log_level)
    logger = get_logger(__name__)

    client = MOQTClientSession(
        host,
        port,
        endpoint=endpoint,
        keylog_filename=args.keylogfile,
        debug=debug
    )
    logger.info(f"MOQT app: publish session connecting: {client}")
    async with client.connect() as session:
        try:
            # Register our data gen version of the subscribe handler
            if datagram:
                session.register_handler(MOQTMessageType.SUBSCRIBE, dgram_subscribe_data_generator)
            else:
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
    
    logger.info(f"MOQT app: publish session closed: {class_name(client)}")


if __name__ == "__main__":

    try:
        args = parse_args()
        asyncio.run(main(
            host=args.host,
            port=args.port,
            endpoint=args.endpoint,
            namespace=args.namespace,
            trackname=args.trackname,
            datagram=args.datagram,
            debug=args.debug
        ))
      
    except KeyboardInterrupt:
        pass