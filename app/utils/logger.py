"""
Python 표준 로깅을 사용하는 로깅 유틸리티.
"""

import logging
import logging.handlers
import sys
from pathlib import Path


def setup_logging(level: str = "INFO",
                  log_file: str = "logs/app.log",
                  enable_file_logging: bool = False) -> None:
    """
    Python 표준 로깅 모듈로 로깅을 설정합니다.

    Args:
        level: 로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file: 로그 파일 경로 (기본값: logs/app.log).
        enable_file_logging: 로테이션과 함께 파일 로깅 활성화.
    """
    # 로그 파일 디렉토리 생성
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, level.upper(), logging.INFO)

    # 기존 핸들러 제거
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level)

    # 로그 형식: 타임스탬프 - 로거 이름 - 레벨 - 메시지
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(log_format, datefmt=date_format)

    # 1. 콘솔 핸들러 (stdout)
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
    로거 인스턴스를 가져옵니다.

    Args:
        name: 로거 이름 (일반적으로 __name__).

    Returns:
        로거 인스턴스.
    """
    return logging.getLogger(name)
