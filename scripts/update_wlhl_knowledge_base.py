#!/usr/bin/env python3
from core import process

if __name__ == "__main__":
    result = process(force=False)
    print(f"Found {result['files_found']}; updated {result['processed']}; unchanged {result['skipped']}.")
    for error in result["errors"]:
        print("ERROR:", error)
