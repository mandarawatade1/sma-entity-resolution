import json
import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).parent / "repository.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    columns_json TEXT NOT NULL,
    mapping_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    row_index INTEGER NOT NULL,
    raw_json TEXT NOT NULL,
    normalized_json TEXT NOT NULL,
    cluster_id INTEGER,
    FOREIGN KEY (dataset_id) REFERENCES datasets(id)
);

CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL DEFAULT 'pending',
    max_score REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS master_repository (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_id INTEGER,
    merged_json TEXT NOT NULL,
    source_record_ids TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}
