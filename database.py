# database.py
import sqlite3
import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DB_PATH = "bot_data.db"

def init_db():
    """Создаёт все необходимые таблицы"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Таблица пользователей: баланс и текущая модель (оставляем для совместимости)
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0,
            current_model TEXT,
            last_activity TIMESTAMP
        )
    ''')

    # Таблица истории диалогов
    c.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,  -- 'user' или 'assistant'
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Таблица для учёта использования изображений (бесплатный лимит 5 в неделю)
    c.execute('''
        CREATE TABLE IF NOT EXISTS weekly_image_usage (
            user_id INTEGER,
            week_start TEXT,  -- дата понедельника в формате YYYY-MM-DD
            count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, week_start)
        )
    ''')

    # Таблица для хранения OAuth-токенов DonationAlerts (для будущих донатов)
    c.execute('''
        CREATE TABLE IF NOT EXISTS donation_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            access_token TEXT,
            refresh_token TEXT,
            expires_at INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")

# ----- Работа с балансом и активностью -----
def get_user_balance(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def add_balance(user_id, amount):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    if c.rowcount == 0:
        c.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (user_id, amount))
    conn.commit()
    conn.close()

def deduct_balance(user_id, amount):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if row and row[0] >= amount:
        c.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def update_user_activity(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO users (user_id, last_activity)
        VALUES (?, CURRENT_TIMESTAMP)
    ''', (user_id,))
    conn.commit()
    conn.close()

# ----- Работа с историей диалога -----
def save_message(user_id, role, content):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO chat_history (user_id, role, content)
        VALUES (?, ?, ?)
    ''', (user_id, role, content))
    conn.commit()
    conn.close()

def get_history(user_id, limit=10):
    """Возвращает последние limit сообщений для пользователя"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT role, content FROM chat_history
        WHERE user_id = ?
        ORDER BY created_at DESC LIMIT ?
    ''', (user_id, limit))
    rows = c.fetchall()
    conn.close()
    # Возвращаем в хронологическом порядке (от старых к новым)
    return list(reversed(rows))

def clear_history(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# ----- Работа с лимитом изображений -----
def get_week_start():
    """Возвращает дату понедельника текущей недели в формате YYYY-MM-DD"""
    today = datetime.now().date()
    start = today - timedelta(days=today.weekday())
    return start.isoformat()

def get_weekly_image_count(user_id):
    """Возвращает количество использований изображений за текущую неделю"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    week_start = get_week_start()
    c.execute("SELECT count FROM weekly_image_usage WHERE user_id = ? AND week_start = ?",
              (user_id, week_start))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def increment_weekly_image_count(user_id):
    """Увеличивает счётчик использований изображений на 1"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    week_start = get_week_start()
    c.execute('''
        INSERT INTO weekly_image_usage (user_id, week_start, count)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id, week_start) DO UPDATE SET count = count + 1
    ''', (user_id, week_start))
    conn.commit()
    conn.close()

# ----- Работа с токенами DonationAlerts (опционально) -----
def save_donation_token(access_token, refresh_token, expires_in):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM donation_tokens")
    expires_at = int(time.time()) + expires_in
    c.execute("INSERT INTO donation_tokens (access_token, refresh_token, expires_at) VALUES (?, ?, ?)",
              (access_token, refresh_token, expires_at))
    conn.commit()
    conn.close()

def get_donation_token():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT access_token, refresh_token, expires_at FROM donation_tokens ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    if row:
        access_token, refresh_token, expires_at = row
        if expires_at > int(time.time()):
            return access_token
    return None

def update_donation_token(access_token, refresh_token, expires_in):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    expires_at = int(time.time()) + expires_in
    c.execute("UPDATE donation_tokens SET access_token=?, refresh_token=?, expires_at=? WHERE id=1",
              (access_token, refresh_token, expires_at))
    conn.commit()
    conn.close()
