from .database import get_db_connection
from ..utils.config import load_config

config = load_config()

async def get_usage_stats(period):
    conn = get_db_connection()
    if period == 'daily':
        timeframe = "DATE(timestamp) = DATE('now')"
    elif period == 'weekly':
        timeframe = "DATE(timestamp) BETWEEN DATE('now', '-7 days') AND DATE('now')"
    elif period == 'monthly':
        timeframe = "DATE(timestamp) BETWEEN DATE('now', '-1 month') AND DATE('now')"
    elif period == 'yearly':
        timeframe = "DATE(timestamp) BETWEEN DATE('now', '-1 year') AND DATE('now')"
    else:
        raise ValueError("Invalid period")

    cursor = conn.cursor()
    cursor.execute(f'''
        SELECT COUNT(*) as total_images,
               COUNT(DISTINCT user_id) as unique_users,
               MAX(model_style) as most_used_model
        FROM generation_events
        WHERE {timeframe}
    ''')
    stats = cursor.fetchone()
    conn.close()
    return stats

async def generate_report_message(period):
    stats = await get_usage_stats(period)
    return (f"📊 {period.capitalize()} Stats Report 📊\n"
            f"Total images generated: {stats['total_images']}\n"
            f"Unique users: {stats['unique_users']}\n"
            f"Most used model: {stats['most_used_model']}\n"
            f"Keep those creative juices flowing! 🎨✨")
