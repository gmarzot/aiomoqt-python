from enum import IntEnum


MOQT_VERSIONS = [0xff000008, 0xff080000, 0xff000009, 0xff090000, 0xff00000a, 0xff0a0000]
MOQT_CUR_VERSION = 0xff00000a

MOQT_DEFAULT_PRIORITY = 128

class MOQTMessageType(IntEnum):
    """MOQT message type constants."""
    CLIENT_SETUP = 0x40
    SERVER_SETUP = 0x41
    SUBSCRIBE_UPDATE = 0x02
    SUBSCRIBE = 0x03
    SUBSCRIBE_OK = 0x04
    SUBSCRIBE_ERROR = 0x05
    ANNOUNCE = 0x06
    ANNOUNCE_OK = 0x07
    ANNOUNCE_ERROR = 0x08
    UNANNOUNCE = 0x09
    UNSUBSCRIBE = 0x0A
    SUBSCRIBE_DONE = 0x0B
    ANNOUNCE_CANCEL = 0x0C
    TRACK_STATUS_REQUEST = 0x0D
    TRACK_STATUS = 0x0E
    GOAWAY = 0x10
    SUBSCRIBE_ANNOUNCES = 0x11
    SUBSCRIBE_ANNOUNCES_OK = 0x12
    SUBSCRIBE_ANNOUNCES_ERROR = 0x13
    UNSUBSCRIBE_ANNOUNCES = 0x14
    MAX_SUBSCRIBE_ID = 0x15
    FETCH = 0x16
    FETCH_CANCEL = 0x17
    FETCH_OK = 0x18
    FETCH_ERROR = 0x19
    SUBSCRIBES_BLOCKED = 0x1A


class ParamType(IntEnum):
    """Parameter types for MOQT messages."""
    AUTHORIZATION_INFO = 0x02
    DELIVERY_TIMEOUT = 0x03
    MAX_CACHE_DURATION = 0x04
    GREASE_1_PARAM = 0x25
    GREASE_2_PARAM = 0x3D


class SetupParamType(IntEnum):
    """Setup Parameter type constants"""
    CLIENT_ROLE = 0x0  # deprecated - removed in draft-8
    ENDPOINT_PATH = 0x01  # only relevant to raw QUIC connection
    MAX_SUBSCRIBER_ID = 0x02  # currently encoded as varint in draft0-10 - this will change


class SessionCloseCode(IntEnum):
    """Session close error codes."""
    NO_ERROR = 0x0
    INTERNAL_ERROR = 0x01
    UNAUTHORIZED = 0x02
    PROTOCOL_VIOLATION = 0x03
    DUPLICATE_TRACK_ALIAS = 0x04
    PARAMETER_LENGTH_MISMATCH = 0x05
    TOO_MANY_SUBSCRIBES = 0x06
    GOAWAY_TIMEOUT = 0x10
    CONTROL_MESSAGE_TIMEOUT = 0x11
    DATA_STREAM_TIMEOUT = 0x12

class ContentExistsCode(IntEnum):
    """Content Exists Code"""
    NO_CONTENT = 0x0
    EXISTS = 0x01
    
class SubscribeErrorCode(IntEnum):
    """SUBSCRIBE_ERROR error codes."""
    INTERNAL_ERROR = 0x0
    INVALID_RANGE = 0x01
    RETRY_TRACK_ALIAS = 0x02
    TRACK_DOES_NOT_EXIST = 0x03
    UNAUTHORIZED = 0x04
    TIMEOUT = 0x05


class SubscribeDoneCode(IntEnum):
    """SUBSCRIBE_DONE status codes."""
    UNSUBSCRIBED = 0x0
    INTERNAL_ERROR = 0x01
    UNAUTHORIZED = 0x02
    TRACK_ENDED = 0x03
    SUBSCRIPTION_ENDED = 0x04
    GOING_AWAY = 0x05
    EXPIRED = 0x06
    TOO_FAR_BEHIND = 0x07


class TrackStatusCode(IntEnum):
    """TRACK_STATUS status codes."""
    IN_PROGRESS = 0x00
    DOES_NOT_EXIST = 0x01
    NOT_STARTED = 0x02
    FINISHED = 0x03
    RELAY_NO_INFO = 0x04


class FilterType(IntEnum):
    """Subscription filter types."""
    LATEST_OBJECT = 0x02
    ABSOLUTE_START = 0x03
    ABSOLUTE_RANGE = 0x04


class GroupOrder(IntEnum):
    """Group ordering preferences."""
    PUBLISHER_DEFAULT = 0x0
    ASCENDING = 0x01
    DESCENDING = 0x02


class ObjectStatus(IntEnum):
    """Object status codes."""
    NORMAL = 0x0
    DOES_NOT_EXIST = 0x01
    END_OF_GROUP = 0x03
    END_OF_TRACK_AND_GROUP = 0x04
    END_OF_TRACK = 0x05


class ForwardingPreference(IntEnum):
    """Object forwarding preferences."""
    TRACK = 0x0
    SUBGROUP = 0x01
    DATAGRAM = 0x02


class FetchType(IntEnum):
    FETCH = 0x01
    JOINING_FETCH = 0x02


class DataStreamType(IntEnum):
    """Stream type identifiers."""
    SUBGROUP_HEADER = 0x04
    FETCH_HEADER = 0x05


class DatagramType(IntEnum):
    """Datagram type identifiers."""
    OBJECT_DATAGRAM = 0x01
    OBJECT_DATAGRAM_STATUS = 0x02


class MOQTException(Exception):
    def __init__(self, error_code: SessionCloseCode, reason_phrase: str):
        self.error_code = error_code
        self.reason_phrase = reason_phrase
        super().__init__(f"{reason_phrase} ({error_code})")
        
