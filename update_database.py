#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from core import process

if __name__ == "__main__":
    result = process(force=False)
    print(f"Updated {result['processed']} episode(s); {result['skipped']} unchanged.")
