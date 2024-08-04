import os
import tempfile
import shutil
from pathlib import Path
from typing import Optional
from PIL import Image
import aiohttp
import asyncio
from .config import load_config
from .logging_config import logger
from .exceptions import SDSlackBotError
from src.utils.temp_dir_manager import temp_dir_manager

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
        # Create a subdirectory within our custom temp directory
        base_temp_dir = config['temp_dir']
        temp_subdir = tempfile.mkdtemp(dir=base_temp_dir)
        logger.info(f"Created temporary directory: {temp_subdir}")

        # Verify the directory was created
        if not os.path.exists(temp_subdir):
            raise OSError(f"Failed to create temporary directory: {temp_subdir}")

        return temp_subdir
    except Exception as e:
        logger.error(f"Error creating temporary directory: {str(e)}", exc_info=True)
        raise

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

async def download_and_verify_image(url: str, local_filename: str, headers: dict, max_retries: int = 3) -> bool:
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    logger.info(f"Download attempt {attempt + 1}: Status code: {response.status}")
                    logger.info(f"Response headers: {response.headers}")

                    if response.status != 200:
                        logger.error(f"Failed to download image, status code: {response.status}")
                        continue

                    if 'image' not in response.headers.get('Content-Type', ''):
                        logger.error(f"Unexpected content type: {response.headers.get('Content-Type')}")
                        continue

                    content = await response.read()

                    with open(local_filename, 'wb') as f:
                        f.write(content)

            # Verify the image
            try:
                with Image.open(local_filename) as img:
                    img.verify()
                logger.info(f"Image downloaded and verified successfully: {local_filename}")
                return True
            except Exception as e:
                logger.error(f"Failed to verify image: {str(e)}")
                # Save the raw content for debugging
                debug_filename = f"{local_filename}.debug"
                with open(debug_filename, 'wb') as f:
                    f.write(content)
                logger.info(f"Saved raw content to {debug_filename} for debugging")
                os.remove(local_filename)  # Remove the corrupted file

        except Exception as e:
            logger.error(f"Error downloading image (attempt {attempt + 1}/{max_retries}): {str(e)}")

    logger.error(f"Failed to download and verify image after {max_retries} attempts")
    return False

async def handle_reference_image(file_info: dict, client) -> str:
    try:
        if not is_allowed_file(file_info["name"]):
            raise SDSlackBotError("Invalid file type. Please upload a JPG, PNG, or WebP file.")

        file_obj = await client.files_info(file=file_info["id"])
        url = file_obj["file"]["url_private"]
        local_filename = temp_dir_manager.get_temp_file_path(file_info["name"])

        headers = {
            "Authorization": f"Bearer {config['slack']['bot_token']}",
            "User-Agent": "SlackBot/1.0"
        }
        success = await download_and_verify_image(url, local_filename, headers)

        if not success:
            raise SDSlackBotError("Failed to download and verify the image file.")

        return local_filename
    except Exception as e:
        logger.error(f"Error in handle_reference_image: {str(e)}", exc_info=True)
        raise SDSlackBotError(f"Failed to process reference image: {str(e)}")
