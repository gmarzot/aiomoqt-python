import logging
import sys
from typing import Optional


def get_logger(name: str, level: Optional[int] = None) -> logging.Logger:
    """Get a logger with consistent formatting."""
    logger = logging.getLogger(name)

    if not logger.handlers:  # Only add handler if none exists
        handler = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter(
            fmt='%(asctime)s.%(msecs)03d %(levelname)-5s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    if level is not None:
        logger.setLevel(level)
    elif not logger.level:  # Only set default if no level set
        logger.setLevel(logging.INFO)

    return logger


class QuicLoggerCustom:
    """Custom QUIC event logger."""

    def __init__(self, level: int = logging.DEBUG):
        self.logger = get_logger('quic_logger', level)

    def log_event(self, event_type: str, data: dict) -> None:
        """Log a QUIC event."""
        import json
        self.logger.debug(f"QUIC Event: {event_type}")
        self.logger.debug(json.dumps(data, indent=2))
