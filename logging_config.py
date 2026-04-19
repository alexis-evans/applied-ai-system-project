import logging
import os
from pathlib import Path


def configure_logging() -> logging.Logger:
    """Configure console and file logging for the PawPal planning flow."""
    log_level = os.getenv("PAWPAL_LOG_LEVEL", "INFO").upper()
    log_file = os.getenv("PAWPAL_LOG_FILE", "logs/pawpal.log")
    logger = logging.getLogger("pawpal")

    if logger.handlers:
        logger.setLevel(log_level)
        return logger

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger.setLevel(log_level)
    logger.propagate = False
    return logger
