import logging
import os
from datetime import datetime

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


class TestLogger:
    __test__ = False  # not a pytest class

    def __init__(self, test_name: str, log_dir: str = "results/logs"):
        self._test_name = test_name
        self._log_dir = log_dir
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        """Logger writing to a timestamped file (DEBUG+) and to the console (WARNING+)."""
        os.makedirs(self._log_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(self._log_dir, f"{timestamp}_{self._test_name}.log")
        self.log_file = log_file

        logger = logging.getLogger(f"test_{self._test_name}")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        # Drop handlers from earlier instances with the same name (avoids duplicate lines)
        for h in list(logger.handlers):
            logger.removeHandler(h)
            h.close()

        formatter = logging.Formatter(LOG_FORMAT)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        console = logging.StreamHandler()
        console.setLevel(logging.WARNING)
        console.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(console)

        return logger

    def info(self, message: str):
        self.logger.info(message)

    def error(self, message: str):
        self.logger.error(message)

    def debug(self, message: str):
        self.logger.debug(message)

    def warning(self, message: str):
        self.logger.warning(message)
