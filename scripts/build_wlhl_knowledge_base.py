#!/usr/bin/env python3
from core import process

if __name__ == "__main__":
    result = process(force=True)
    print(f"Found {result['files_found']} transcript files; processed {result['processed']}.")
    for error in result["errors"]:
        print("ERROR:", error)
