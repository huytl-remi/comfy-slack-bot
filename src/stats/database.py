import os
import sqlite3
from src.utils.config import load_config
from src.utils.logging_config import logger

config = load_config()

def get_db_connection():
    db_path = config['stats']['database_path']
    if not db_path:
        raise ValueError("Database path is not set in the configuration")

    db_dir = os.path.dirname(db_path)
    os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = None
    try:
        conn = get_db_connection()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS generation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                user_id TEXT,
                model_style TEXT,
                aspect_ratio TEXT
            )
        ''')
        conn.commit()
        logger.info(f"Database initialized at {config['stats']['database_path']}")
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}")
        raise
    finally:
        if conn is not None:
            conn.close()
