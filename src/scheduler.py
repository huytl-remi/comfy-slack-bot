import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.stats.reporter import generate_report_message
from src.utils.config import load_config
from src.bot.slack_interface import app

config = load_config()

async def send_report(period):
    message = await generate_report_message(period)
    await app.client.chat_postMessage(
        channel=config['slack']['report_channel'],
        text=message
    )

def start_scheduler():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_report, 'cron', args=['daily'], hour=0, minute=0)
    scheduler.add_job(send_report, 'cron', args=['weekly'], day_of_week='mon', hour=0, minute=5)
    scheduler.add_job(send_report, 'cron', args=['monthly'], day=1, hour=0, minute=10)
    scheduler.add_job(send_report, 'cron', args=['yearly'], month=1, day=1, hour=0, minute=15)
    scheduler.start()
