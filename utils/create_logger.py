import os
import logging
from dotenv import load_dotenv


def create_logger():
    load_dotenv()
    log_file_path = os.getenv("LOG_PATH", ".")
    os.makedirs(log_file_path, exist_ok=True)

    logger = logging.getLogger("personal_notion_integration")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    file_handler = logging.FileHandler(os.path.join(log_file_path, "log_file.txt"))
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger
