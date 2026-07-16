#!/usr/bin/env python3
import argparse
from core import search

parser = argparse.ArgumentParser(description="Search every WLHL transcript and index field.")
parser.add_argument("query")
parser.add_argument("--limit", type=int, default=20)
args = parser.parse_args()
for row in search(args.query, args.limit):
    print(f"{row['episode_id']} | {row['episode_title']} | {row['publish_date']}")
    print(" ", row["snippet"].replace("\n", " "))
