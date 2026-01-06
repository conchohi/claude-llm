"""
Logging utilities using Python standard logging.
"""

import logging
import logging.handlers
import sys
from pathlib import Path


def setup_logging(level: str = "INFO",
                  log_file: str = "logs/app.log",
                  enable_file_logging: bool = False) -> None:
    """
    Configure logging with Python standard logging module.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file: Path to log file (default: logs/app.log).
        enable_file_logging: Enable file logging with rotation.
    """
    # 로그 파일 디렉토리 생성
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, level.upper(), logging.INFO)

    # Clear existing handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level)

    # Log format: timestamp - logger name - level - message
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(log_format, datefmt=date_format)

    # 1. Console Handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    if enable_file_logging:
        # 2. TimedRotatingFileHandler: 시간 기반 로테이션
        file_handler = logging.handlers.TimedRotatingFileHandler(
            log_file,
            when='midnight',  # 매일 자정에 로테이션
            interval=1,       # 1일마다
            backupCount=30,   # 최대 30일치 보관
            encoding='utf-8',
            utc=False
        )
        # 로그 파일명에 날짜 추가 (예: app.log.2025-12-31)
        file_handler.suffix = "%Y-%m-%d"
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance.

    Args:
        name: Logger name (typically __name__).

    Returns:
        Logger instance.
    """
    return logging.getLogger(name)
