import os
import time
import shutil
from src.utils.logging_config import logger
from src.utils.config import load_config

config = load_config()

class TempDirManager:
    def __init__(self):
        self.base_temp_dir = os.path.join(config['temp_dir'], 'sd_bot_temp')
        os.makedirs(self.base_temp_dir, exist_ok=True)
        logger.info(f"Created base temporary directory: {self.base_temp_dir}")

    def get_temp_file_path(self, filename):
        return os.path.join(self.base_temp_dir, f"{time.time()}_{filename}")

    def cleanup_old_files(self, max_age_hours=1):
        current_time = time.time()
        for filename in os.listdir(self.base_temp_dir):
            file_path = os.path.join(self.base_temp_dir, filename)
            if os.path.isfile(file_path):
                file_age = current_time - os.path.getctime(file_path)
                if file_age > (max_age_hours * 3600):
                    os.remove(file_path)
                    logger.info(f"Removed old temporary file: {file_path}")

temp_dir_manager = TempDirManager()
