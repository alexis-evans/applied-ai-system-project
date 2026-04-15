import logging
import os


def configure_logging() -> logging.Logger:
    """Configure a simple console logger for the PawPal planning flow."""
    log_level = os.getenv("PAWPAL_LOG_LEVEL", "INFO").upper()
    logger = logging.getLogger("pawpal")

    if logger.handlers:
        logger.setLevel(log_level)
        return logger

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.setLevel(log_level)
    logger.propagate = False
    return logger
