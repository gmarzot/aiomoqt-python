
import pytest
from dataclasses import fields

from aioquic.buffer import Buffer
from aiomoqt.protocol import MOQTSessionProtocol
from aiomoqt.client import MOQTClientSession
from aiomoqt.types import *
from aiomoqt.messages import *


def test_message_serialization(cls, params, type_tag = None, needs_len = False):
    """
    test MOQT message class serialization/deserialization
    
    Args:
        cls: MOQT message class
        params: params dict
    """
    obj = cls(**params)
    buf = obj.serialize()

    buf_len = buf.tell()
    buf.seek(0)
    # check/strip type for typed messages
    if type_tag is not None:
        tag = buf.pull_uint_var()
        assert tag == type_tag  

    if needs_len:
        new_obj = cls.deserialize(buf, buf_len)
    else:
        new_obj = cls.deserialize(buf)
    
    # Compare all fields from the dataclass
    for field in fields(cls):            
        original_value = getattr(obj, field.name)
        new_value = getattr(new_obj, field.name)
        
        if isinstance(original_value, dict):
            assert original_value.keys() == new_value.keys(), f"keys don't match"
            for key in original_value:
                assert original_value[key] == new_value[key], f"values don't match for key {key}"
        else:
            assert original_value == new_value, f"'{field.name}' doesn't match after deserialization"
    
    return True


# Example usage for each message class
def test_subgroup_header():
    params = {
        'track_alias': 123,
        'group_id': 456,
        'subgroup_id': 789,
        'publisher_priority': 10
    }
    assert test_message_serialization(SubgroupHeader, params, DataStreamType.SUBGROUP_HEADER)

def test_object_header():
    params = {
        'object_id': 1,
        'extensions': {0: 8, 1: b'\xfa\xce\xb0\x0c'},
        'status': ObjectStatus.NORMAL,
        'payload': b'Hello World'
    }
    assert test_message_serialization(ObjectHeader, params, needs_len=True)

def test_fetch_header():
    params = {
        'subscribe_id': 42
    }
    assert test_message_serialization(FetchHeader, params)

def test_fetch_object():
    params = {
        'group_id': 1,
        'subgroup_id': 2,
        'object_id': 3,
        'publisher_priority': 5,
        'payload': b'Sample payload'
    }
    assert test_message_serialization(FetchObject, params, DataStreamType.FETCH_HEADER)

def test_object_datagram():
    params = {
        'track_alias': 123,
        'group_id': 456,
        'object_id': 789,
        'publisher_priority': 10,
        'extensions': {0: 8, 1: b'\xfa\xce\xb0\x0c'},
        'payload': b'Hello World'
    }
    assert test_message_serialization(ObjectDatagram, params, DatagramType.OBJECT_DATAGRAM)

def test_object_datagram_status():
    params = {
        'track_alias': 123,
        'group_id': 456,
        'object_id': 789,
        'publisher_priority': 10,
        'status': ObjectStatus.DOES_NOT_EXIST
    }
    assert test_message_serialization(ObjectDatagramStatus, params, DatagramType.OBJECT_DATAGRAM)

def test_ObjectHeader():
    data_bytes = b'\xfa\xce\xb0\x0c'
    obj = ObjectHeader(
        object_id = 1,
        status = ObjectStatus.NORMAL,
        extensions = {
            0: 8,
            1: data_bytes,
        },
        payload = b'Hello World'
    )

    obj_buf  = obj.serialize()
    obj_len = obj_buf.tell()
    obj_buf.seek(0)
    new_obj = ObjectHeader.deserialize(obj_buf, obj_len)
    
    assert obj.object_id == new_obj.object_id
    assert obj.status == new_obj.status
    assert len(obj.extensions) == len(new_obj.extensions)
    assert len(obj.payload) == len(new_obj.payload)
