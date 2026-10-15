"""原始帖子持久化 — SQLite

分析结果只保留聚合指数，原始帖子如果不落盘，将来调整信号词库就
无法重算历史。这里把每次采集的原始帖子追加到 SQLite，供重算/回测使用。

数据库位置:
    src/data/raw_posts.db（可用环境变量 MOM_INDEX_DB_PATH 覆盖）
"""
import json
import os
import sqlite3
from datetime import datetime
from mom_index.provenance import is_mock, post_key

DATA_DIR = os.environ.get(
    "MOM_INDEX_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"),
)
DB_PATH = os.environ.get("MOM_INDEX_DB_PATH", os.path.join(DATA_DIR, "raw_posts.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collected_at TEXT NOT NULL,
    sector TEXT NOT NULL,
    platform TEXT,
    title TEXT,
    url TEXT,
    author TEXT,
    raw TEXT
);
CREATE INDEX IF NOT EXISTS idx_raw_posts_sector_time
    ON raw_posts(sector, collected_at);
"""


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(_SCHEMA)
    if "run_id" not in {row[1] for row in conn.execute("PRAGMA table_info(raw_posts)")}:
        conn.execute("ALTER TABLE raw_posts ADD COLUMN run_id TEXT")
    return conn


def save_posts(sector: str, posts: list, platform: str = "unknown", run_id=None) -> int:
    """把一批原始帖子追加存档，返回实际写入条数"""
    if not posts:
        return 0
    conn = _connect()
    now = datetime.now().isoformat()
    rows = []
    demo_rows = []
    for p in posts:
        if not p or not p.get("title"):
            continue
        target = demo_rows if is_mock(p) else rows
        target.append((
            now,
            sector,
            p.get("platform") or platform,
            p.get("title"),
            p.get("url", ""),
            p.get("author", ""),
            json.dumps(p, ensure_ascii=False),
            run_id,
        ))
    conn.execute("CREATE TABLE IF NOT EXISTS demo_posts AS SELECT * FROM raw_posts WHERE 0")
    if demo_rows:
        conn.executemany(
            "INSERT INTO demo_posts (collected_at, sector, platform, title, url, author, raw, run_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", demo_rows)
    if rows:
        conn.executemany(
            "INSERT INTO raw_posts (collected_at, sector, platform, title, url, author, raw, run_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    conn.commit()
    conn.close()
    return len(rows)


def seen_post_ids(sector):
    """已有存档中的帖子身份，仅用于首次见到统计，不推断发布时间。"""
    conn = _connect()
    try:
        result = set()
        for (raw,) in conn.execute('SELECT raw FROM raw_posts WHERE sector = ?', (sector,)):
            try:
                post = json.loads(raw)
                if not is_mock(post):
                    result.add(post_key(post))
            except (ValueError, TypeError):
                continue
        return result
    finally:
        conn.close()


def count_posts() -> int:
    """当前存档帖子总数（用于状态展示）"""
    conn = _connect()
    total = conn.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0]
    conn.close()
    return total


def export_posts(sector: str = None, limit: int = 100) -> list:
    """按板块导出原始帖子（调试/重算用）"""
    conn = _connect()
    if sector:
        rows = conn.execute(
            "SELECT sector, collected_at, title, url, author FROM raw_posts "
            "WHERE sector = ? ORDER BY id DESC LIMIT ?",
            (sector, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT sector, collected_at, title, url, author FROM raw_posts "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [
        {"sector": r[0], "collected_at": r[1], "title": r[2], "url": r[3], "author": r[4]}
        for r in rows
    ]


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "count":
        print(f"raw_posts.db 当前存档: {count_posts()} 条")
    else:
        for p in export_posts(limit=10):
            print(f"  [{p['sector']}] {p['title'][:40]} — {p['collected_at'][:19]}")
