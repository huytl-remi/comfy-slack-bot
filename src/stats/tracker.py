from .database import get_db_connection

async def record_generation_event(user_id, model_style, aspect_ratio):
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO generation_events (user_id, model_style, aspect_ratio)
        VALUES (?, ?, ?)
    ''', (user_id, model_style, aspect_ratio))
    conn.commit()
    conn.close()
