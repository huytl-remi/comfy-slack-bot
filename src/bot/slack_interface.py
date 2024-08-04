import asyncio
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from src.utils.config import load_config
from src.utils.logging_config import logger
from .handlers import register_handlers
from .views import register_views
from .queue_processor import start_queue_processing

config = load_config()
app = AsyncApp(token=config['slack']['bot_token'])

# Register handlers and views
register_handlers(app)
register_views(app)

async def start_bot():
    handler = AsyncSocketModeHandler(app, config['slack']['app_token'])

    # Start queue processing
    await start_queue_processing(app.client)

    await handler.start_async()

if __name__ == "__main__":
    import asyncio
    asyncio.run(start_bot())
