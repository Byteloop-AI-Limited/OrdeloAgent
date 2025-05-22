"""
Logger configuration for OrdeloAgent.
    . Sets up loguru logger with console and file handlers
    . Configures extra log context (user)
    . Depends on: loguru, sys
"""
# Import the logger and sys modules
import sys

# Configuration for the logger
config = {
    # Define the handlers for the logger
    "handlers": [
        # Handler to output log messages to the console
        {"sink": sys.stdout, "format": "{time} - {message}"},
        # Handler to output log messages to a file
        {"sink": "file.log", "serialize": True},
    ],
    # Extra information to include in the log messages
    "extra": {"user": "someone"},
}
