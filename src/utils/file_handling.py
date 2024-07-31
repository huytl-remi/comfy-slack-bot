import os
import tempfile
import shutil
from pathlib import Path
from typing import Optional
import aiohttp
import asyncio
from .config import load_config
from .logging_config import logger
from .exceptions import SDSlackBotError

config = load_config()

def is_allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in config['image_generation']['allowed_extensions']

def get_latest_file(directory: str, prefix: str) -> str:
    """
    Get the latest file in the directory that starts with the given prefix.

    :param directory: The directory to search in
    :param prefix: The prefix of the filename to look for
    :return: The full path of the latest matching file
    """
    files = list(Path(directory).glob(f"{prefix}*"))
    if not files:
        raise FileNotFoundError(f"No files found with prefix '{prefix}' in directory '{directory}'")
    return str(max(files, key=os.path.getctime))

def create_temp_dir() -> str:
    try:
        return tempfile.mkdtemp()
    except Exception as e:
        logger.error(f"Failed to create temporary directory: {str(e)}")
        raise SDSlackBotError(f"Failed to create temporary directory: {str(e)}")

async def save_file_to_temp(file_content: bytes, filename: str, temp_dir: str) -> str:
    try:
        file_path = os.path.join(temp_dir, filename)
        with open(file_path, 'wb') as f:
            f.write(file_content)
        return file_path
    except Exception as e:
        logger.error(f"Failed to save file to temporary directory: {str(e)}")
        raise SDSlackBotError(f"Failed to save file to temporary directory: {str(e)}")

async def cleanup_temp_dir(temp_dir: str) -> None:
    try:
        shutil.rmtree(temp_dir)
        logger.info(f"Temporary directory {temp_dir} cleaned up successfully")
    except Exception as e:
        logger.error(f"Failed to clean up temporary directory {temp_dir}: {str(e)}")

async def download_file(url: str, local_filename: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                with open(local_filename, 'wb') as f:
                    while True:
                        chunk = await response.content.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
        return local_filename
    except Exception as e:
        logger.error(f"Failed to download file from {url}: {str(e)}")
        raise SDSlackBotError(f"Failed to download file: {str(e)}")

async def handle_reference_image(file_info: dict, client) -> str:
    temp_dir = create_temp_dir()
    try:
        if not is_allowed_file(file_info["name"]):
            raise SDSlackBotError("Invalid file type. Please upload a JPG, PNG, or WebP file.")

        file_obj = await client.files_info(file=file_info["id"])
        url = file_obj["file"]["url_private"]
        local_filename = os.path.join(temp_dir, file_info["name"])
        return await download_file(url, local_filename)
    except Exception as e:
        await cleanup_temp_dir(temp_dir)
        raise SDSlackBotError(f"Failed to process reference image: {str(e)}")
