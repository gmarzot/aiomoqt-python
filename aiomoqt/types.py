from enum import IntEnum


class MOQTMessageType:
    """MOQT message type constants."""
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
    CLIENT_SETUP = 0x40
    SERVER_SETUP = 0x41


class ParamType(IntEnum):
    """Parameter types for MOQT messages."""
    AUTHORIZATION_INFO = 0x02
    DELIVERY_TIMEOUT = 0x03
    MAX_CACHE_DURATION = 0x04


class SetupParamType(IntEnum):
    """Setup Parameter type constants"""
    CLIENT_ROLE = 0x0  # deprecated - removed in draft-8
    ENDPOINT_PATH = 0x1  # only relevant to raw QUIC connection
    MAX_SUBSCRIBER_ID = 0x2


class SessionCloseCode(IntEnum):
    """Session close error codes."""
    NO_ERROR = 0x0
    INTERNAL_ERROR = 0x1
    UNAUTHORIZED = 0x2
    PROTOCOL_VIOLATION = 0x3
    DUPLICATE_TRACK_ALIAS = 0x4
    PARAMETER_LENGTH_MISMATCH = 0x5
    TOO_MANY_SUBSCRIBES = 0x6
    GOAWAY_TIMEOUT = 0x10
    CONTROL_MESSAGE_TIMEOUT = 0x11
    DATA_STREAM_TIMEOUT = 0x12


class SubscribeErrorCode(IntEnum):
    """SUBSCRIBE_ERROR error codes."""
    INTERNAL_ERROR = 0x0
    INVALID_RANGE = 0x1
    RETRY_TRACK_ALIAS = 0x2
    TRACK_DOES_NOT_EXIST = 0x3
    UNAUTHORIZED = 0x4
    TIMEOUT = 0x5


class SubscribeDoneCode(IntEnum):
    """SUBSCRIBE_DONE status codes."""
    UNSUBSCRIBED = 0x0
    INTERNAL_ERROR = 0x1
    UNAUTHORIZED = 0x2
    TRACK_ENDED = 0x3
    SUBSCRIPTION_ENDED = 0x4
    GOING_AWAY = 0x5
    EXPIRED = 0x6
    TOO_FAR_BEHIND = 0x7


class TrackStatusCode(IntEnum):
    """TRACK_STATUS status codes."""
    IN_PROGRESS = 0x0
    DOES_NOT_EXIST = 0x1
    NOT_STARTED = 0x2
    FINISHED = 0x3
    RELAY_NO_INFO = 0x4


class FilterType(IntEnum):
    """Subscription filter types."""
    LATEST_GROUP = 0x1
    RECENT_GROUP = 0x1
    LATEST_OBJECT = 0x2
    ABSOLUTE_START = 0x3
    ABSOLUTE_RANGE = 0x4


class GroupOrder(IntEnum):
    """Group ordering preferences."""
    PUBLISHER_DEFAULT = 0x0
    ASCENDING = 0x1
    DESCENDING = 0x2


class ObjectStatus(IntEnum):
    """Object status codes."""
    NORMAL = 0x0
    DOES_NOT_EXIST = 0x1
    END_OF_GROUP = 0x3
    END_OF_TRACK_AND_GROUP = 0x4
    END_OF_TRACK = 0x5


class StreamType(IntEnum):
    """Stream type identifiers."""
    STREAM_HEADER_SUBGROUP = 0x4
    FETCH_HEADER = 0x5


class ForwardingPreference(IntEnum):
    """Object forwarding preferences."""
    TRACK = 0x0
    SUBGROUP = 0x1
    DATAGRAM = 0x2


class DatagramType(IntEnum):
    """Datagram type identifiers."""
    OBJECT_DATAGRAM = 0x1
    OBJECT_DATAGRAM_STATUS = 0x2
