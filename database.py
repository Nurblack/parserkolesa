import sqlite3
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

DB_PATH = 'parskolesa.db'
ASTANA_TZ = timezone(timedelta(hours=5))

def now_local():
    return datetime.now(ASTANA_TZ).strftime('%Y-%m-%d %H:%M:%S')


class Database:
    def __init__(self):
        self.init_db()

    def conn(self):
        c = sqlite3.connect(DB_PATH)
        c.row_factory = sqlite3.Row
        return c

    def init_db(self):
        with self.conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY,
                    data TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_url TEXT,
                    title TEXT,
                    price TEXT,
                    city TEXT,
                    car_brand TEXT,
                    car_model TEXT,
                    year INTEGER,
                    phone TEXT,
                    phone_clean TEXT UNIQUE,
                    status TEXT DEFAULT 'NEW',
                    parser_job_id INTEGER,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id INTEGER,
                    phone TEXT,
                    status TEXT DEFAULT 'ACTIVE',
                    current_step INTEGER DEFAULT 0,
                    ai_context TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now')),
                    last_message_at TEXT
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER,
                    content TEXT,
                    direction TEXT,
                    is_ai INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS parser_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    config TEXT DEFAULT '{}',
                    status TEXT DEFAULT 'RUNNING',
                    new_added INTEGER DEFAULT 0,
                    pages_parsed INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    finished_at TEXT
                );
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT DEFAULT 'INFO',
                    source TEXT,
                    message TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                INSERT OR IGNORE INTO settings (id, data) VALUES (1, '{}');
            """)

    # ── Settings ──────────────────────────────────────────────────────────────

    def get_settings(self) -> dict:
        with self.conn() as c:
            row = c.execute('SELECT data FROM settings WHERE id=1').fetchone()
            return json.loads(row['data']) if row else {}

    def save_settings(self, data: dict):
        existing = self.get_settings()
        existing.update(data)
        with self.conn() as c:
            c.execute('UPDATE settings SET data=? WHERE id=1',
                      (json.dumps(existing, ensure_ascii=False),))

    # ── Listings ──────────────────────────────────────────────────────────────

    def save_listing(self, data: dict) -> Optional[int]:
        try:
            with self.conn() as c:
                cur = c.execute("""
                    INSERT OR IGNORE INTO listings
                    (source_url, title, price, city, car_brand, car_model,
                     year, phone, phone_clean, status, parser_job_id, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,'NEW',?,?)
                """, (
                    data.get('source_url', ''), data.get('title', ''),
                    data.get('price', ''), data.get('city', ''),
                    data.get('car_brand', ''), data.get('car_model', ''),
                    data.get('year'), data.get('phone', ''),
                    data.get('phone_clean', ''), data.get('parser_job_id'),
                    now_local()
                ))
                return cur.lastrowid if cur.rowcount > 0 else None
        except Exception as e:
            self.log('ERROR', 'DB', f'save_listing: {e}')
            return None

    def get_listings(self, status='', limit=200) -> list:
        with self.conn() as c:
            if status:
                rows = c.execute(
                    'SELECT * FROM listings WHERE status=? ORDER BY created_at DESC LIMIT ?',
                    (status, limit)).fetchall()
            else:
                rows = c.execute(
                    'SELECT * FROM listings ORDER BY created_at DESC LIMIT ?',
                    (limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_pending_listings(self) -> list:
        with self.conn() as c:
            rows = c.execute(
                "SELECT * FROM listings WHERE status='NEW' ORDER BY created_at ASC LIMIT 5"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_new_listings(self) -> list:
        with self.conn() as c:
            rows = c.execute(
                "SELECT * FROM listings WHERE status='NEW' ORDER BY created_at ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_listing_by_id(self, listing_id: int) -> Optional[dict]:
        with self.conn() as c:
            row = c.execute('SELECT * FROM listings WHERE id=?', (listing_id,)).fetchone()
            return dict(row) if row else None

    def update_listing_status(self, listing_id: int, status: str):
        with self.conn() as c:
            c.execute('UPDATE listings SET status=? WHERE id=?', (status, listing_id))

    def get_listing_stats(self) -> dict:
        with self.conn() as c:
            rows = c.execute(
                'SELECT status, COUNT(*) as cnt FROM listings GROUP BY status'
            ).fetchall()
            stats = {r['status']: r['cnt'] for r in rows}
            stats['total'] = sum(stats.values())
            return stats

    # ── Conversations ─────────────────────────────────────────────────────────

    def get_or_create_conversation(self, listing_id: int, phone: str) -> dict:
        with self.conn() as c:
            row = c.execute(
                'SELECT * FROM conversations WHERE listing_id=?', (listing_id,)
            ).fetchone()
            if row:
                return dict(row)
            cur = c.execute(
                'INSERT INTO conversations (listing_id, phone, created_at) VALUES (?,?,?)',
                (listing_id, phone, now_local())
            )
            return {'id': cur.lastrowid, 'listing_id': listing_id,
                    'phone': phone, 'status': 'ACTIVE', 'current_step': 0, 'ai_context': '{}'}

    def get_conversation_by_phone(self, phone: str) -> Optional[dict]:
        with self.conn() as c:
            row = c.execute(
                'SELECT * FROM conversations WHERE phone=? ORDER BY created_at DESC LIMIT 1',
                (phone,)
            ).fetchone()
            return dict(row) if row else None

    def update_conversation(self, conv_id: int, data: dict):
        if not data:
            return
        fields = ', '.join(f'{k}=?' for k in data)
        vals = list(data.values()) + [conv_id]
        with self.conn() as c:
            c.execute(f'UPDATE conversations SET {fields} WHERE id=?', vals)

    def get_conversations(self, limit=50) -> list:
        with self.conn() as c:
            rows = c.execute("""
                SELECT c.*,
                    l.car_brand, l.car_model, l.year,
                    (SELECT content FROM messages
                     WHERE conversation_id=c.id
                     ORDER BY created_at DESC LIMIT 1) as last_message
                FROM conversations c
                LEFT JOIN listings l ON l.id=c.listing_id
                ORDER BY COALESCE(c.last_message_at, c.created_at) DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]

    # ── Messages ──────────────────────────────────────────────────────────────

    def save_message(self, conv_id: int, content: str, direction: str, is_ai=False):
        t = now_local()
        with self.conn() as c:
            c.execute(
                'INSERT INTO messages (conversation_id, content, direction, is_ai, created_at) VALUES (?,?,?,?,?)',
                (conv_id, content, direction, 1 if is_ai else 0, t)
            )
            c.execute(
                'UPDATE conversations SET last_message_at=? WHERE id=?',
                (t, conv_id)
            )

    def get_messages(self, conv_id: int) -> list:
        with self.conn() as c:
            rows = c.execute(
                'SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at ASC',
                (conv_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_message_history(self, conv_id: int, limit=10) -> list:
        with self.conn() as c:
            rows = c.execute(
                'SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT ?',
                (conv_id, limit)
            ).fetchall()
            return list(reversed([dict(r) for r in rows]))

    # ── Parser Jobs ───────────────────────────────────────────────────────────

    def create_parser_job(self, config: dict) -> int:
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO parser_jobs (config, status, created_at) VALUES (?,'RUNNING',?)",
                (json.dumps(config), now_local())
            )
            return cur.lastrowid

    def update_parser_job(self, job_id: int, data: dict):
        if not data:
            return
        fields = ', '.join(f'{k}=?' for k in data)
        vals = list(data.values()) + [job_id]
        with self.conn() as c:
            c.execute(f'UPDATE parser_jobs SET {fields} WHERE id=?', vals)

    # ── Daily counters ────────────────────────────────────────────────────────

    def get_daily_sent_count(self) -> int:
        today = datetime.now(ASTANA_TZ).strftime('%Y-%m-%d')
        with self.conn() as c:
            row = c.execute(
                "SELECT COUNT(*) as cnt FROM messages WHERE direction='OUTGOING' AND is_ai=1 AND created_at LIKE ?",
                (f'{today}%',)
            ).fetchone()
            return row['cnt'] if row else 0

    # ── Logs ──────────────────────────────────────────────────────────────────

    def log(self, level: str, source: str, message: str):
        print(f'[{source}] {level}: {message}')
        try:
            with self.conn() as c:
                c.execute(
                    'INSERT INTO logs (level, source, message, created_at) VALUES (?,?,?,?)',
                    (level, source, message, now_local())
                )
        except Exception:
            pass

    def get_logs(self, limit=200, source='') -> list:
        with self.conn() as c:
            if source:
                rows = c.execute(
                    'SELECT * FROM logs WHERE source=? ORDER BY created_at DESC LIMIT ?',
                    (source, limit)
                ).fetchall()
            else:
                rows = c.execute(
                    'SELECT * FROM logs ORDER BY created_at DESC LIMIT ?',
                    (limit,)
                ).fetchall()
            return [dict(r) for r in rows]


db = Database()
