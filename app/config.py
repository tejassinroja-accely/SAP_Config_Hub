from langchain_openai import AzureChatOpenAI
from pydantic import BaseModel
import os
from dotenv import load_dotenv
import logging
import sys
from logging.handlers import RotatingFileHandler

load_dotenv()

llm = AzureChatOpenAI(model="gpt-4.1")

class Settings(BaseModel):
    company_id: str = None
    username: str= None
    password: str= None

settings = Settings(
    company_id=os.getenv("company_id"),
    username=os.getenv("username"),
    password=os.getenv("password")
)


def setup_logger(
    name: str = "app_logger",
    log_file: str = "app.log",
    level: int = logging.INFO,
    max_bytes: int = 5_000_000,  # 5 MB per log file
    backup_count: int = 5,       # Keep last 5 logs
):
    # Create custom logger
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False  # Prevent duplicate logs if root logger also logs

    # Format logs
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Stream handler (console)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    # File handler (rotating)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    # Add handlers (if not already)
    if not logger.handlers:
        logger.addHandler(stream_handler)
        logger.addHandler(file_handler)

    return logger
