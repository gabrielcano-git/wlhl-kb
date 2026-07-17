#!/usr/bin/env python3
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from unified_search import ensure_index, search

parser = argparse.ArgumentParser(description="Search every WLHL transcript and index field.")
parser.add_argument("query")
parser.add_argument("--limit", type=int, default=20)
args = parser.parse_args()
connection=sqlite3.connect(ROOT / "database.sqlite")
connection.row_factory=sqlite3.Row
ensure_index(connection)
for match in search(connection,args.query)[:args.limit]:
    row=connection.execute("SELECT episode_id,episode_title,publish_date FROM episodes WHERE id=?",(match["episode_db_id"],)).fetchone()
    print(f"{row['episode_id']} | {row['episode_title']} | {row['publish_date']}")
    print(" ",match["reason"])
    if match["snippet"]: print(" ",match["snippet"].replace("\n"," "))
