import json
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from contextlib import contextmanager


def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def uid():
    return uuid.uuid4().hex


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,title TEXT,created_at TEXT);
            CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,session_id TEXT,role TEXT,content TEXT,created_at TEXT,execution_id TEXT);
            CREATE INDEX IF NOT EXISTS message_session ON messages(session_id,created_at);
            CREATE TABLE IF NOT EXISTS executions(id TEXT PRIMARY KEY,session_id TEXT,message_id TEXT,user_input TEXT,intent TEXT,status TEXT,created_at TEXT,duration_ms REAL,has_sources INTEGER,is_eval INTEGER DEFAULT 0,payload TEXT);
            CREATE TABLE IF NOT EXISTS feedback(id TEXT PRIMARY KEY,message_id TEXT,rating TEXT,category TEXT,note TEXT,status TEXT,analysis TEXT,fix_note TEXT,retest TEXT,created_at TEXT,updated_at TEXT);
            CREATE TABLE IF NOT EXISTS evaluations(id TEXT PRIMARY KEY,kind TEXT,status TEXT,created_at TEXT,payload TEXT);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def query(self, sql, args=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql, args)]

    def execute(self, sql, args=()):
        with self.connect() as db:
            db.execute(sql, args)

    def one(self, sql, args=()):
        rows = self.query(sql, args)
        return rows[0] if rows else None

    def create_session(self, title="新对话"):
        obj = {"id": uid(), "title": title[:50], "created_at": now()}
        self.execute("INSERT INTO sessions VALUES(?,?,?)", tuple(obj.values()))
        return obj

    def add_message(self, session_id, role, content, execution_id=None):
        obj = {"id": uid(), "session_id": session_id, "role": role, "content": content,
               "created_at": now(), "execution_id": execution_id}
        self.execute("INSERT INTO messages VALUES(?,?,?,?,?,?)", tuple(obj.values()))
        return obj

    def messages(self, session_id):
        rows = self.query("SELECT * FROM messages WHERE session_id=? ORDER BY rowid", (session_id,))
        for r in rows:
            if r["execution_id"]:
                ex = self.one("SELECT payload FROM executions WHERE id=?", (r["execution_id"],))
                r["execution"] = json.loads(ex["payload"]) if ex else None
        return rows

    def save_execution(self, obj):
        self.execute("INSERT OR REPLACE INTO executions VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            obj["id"], obj["session_id"], obj.get("message_id"), obj["user_input"], obj.get("intent", "unknown"),
            obj["status"], obj["created_at"], obj.get("duration_ms", 0), int(bool(obj.get("cited_sources"))),
            int(obj.get("is_eval", False)), json.dumps(obj, ensure_ascii=False),
        ))

    def save_json(self, table, record_id, payload, status=None):
        if table == "evaluations":
            self.execute("INSERT OR REPLACE INTO evaluations VALUES(?,?,?,?,?)", (record_id, payload["kind"], status or payload["status"], payload["created_at"], json.dumps(payload, ensure_ascii=False)))
        else:
            raise ValueError("Unsupported table")

    def load_json(self, table, record_id):
        if table != "evaluations":
            raise ValueError("Unsupported table")
        row = self.one(f"SELECT payload FROM {table} WHERE id=?", (record_id,))
        return json.loads(row["payload"]) if row else None
