"""
Logger configuration for OrdeloAgent.
    . Sets up loguru logger with console and file handlers
    . Configures extra log context (user)
    . Depends on: loguru, sys
"""

# Import the logger and sys modules
import sys
from loguru import logger

# Configuration for the logger
config = {
    "handlers": [
        {
            "sink": sys.stdout,
            "format": "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            "level": "INFO",
        },
        {
            "sink": "file.log",
            "serialize": True,
            "rotation": "10 MB",
            "retention": "10 days",
            "level": "DEBUG",
        },
        {"sink": "error.log", "level": "ERROR", "backtrace": True, "diagnose": True},
    ],
    "extra": {"user": "someone"},
}

logger.configure(**config)
