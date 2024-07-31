import asyncio
from .bot.slack_interface import start_bot
from .utils.logging_config import logger
from .utils.exceptions import SDSlackBotError
from .stats.database import init_db
from scheduler import start_scheduler

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

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
