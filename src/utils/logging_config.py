import logging
from .config import load_config

def setup_logging():
    config = load_config()
    logging.basicConfig(
        level=config['logging']['level'],
        format=config['logging']['format']
    )
    return logging.getLogger(__name__)

logger = setup_logging()
