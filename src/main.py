from src.stats.database import init_db
from src.scheduler import start_scheduler
from src.bot.slack_interface import start_bot
from src.utils.logging_config import logger
from src.utils.exceptions import SDSlackBotError

import asyncio
from src.utils.temp_dir_manager import temp_dir_manager

async def cleanup_temp_files():
    while True:
        temp_dir_manager.cleanup_old_files()
        await asyncio.sleep(3600)  # Run every hour

async def main():
    try:
        logger.info("Initializing database")
        try:
            init_db()
        except Exception as e:
            logger.error(f"Failed to initialize database: {str(e)}")
            raise

        logger.info("Starting scheduler")
        start_scheduler()

        logger.info("Starting SD Slack Bot")
        await start_bot()
    except SDSlackBotError as e:
        logger.error(f"An error occurred: {str(e)}")
    except Exception as e:
        logger.critical(f"An unexpected error occurred: {str(e)}", exc_info=True)

    # Start the cleanup task
    asyncio.create_task(cleanup_temp_files())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
