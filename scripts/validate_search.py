#!/usr/bin/env python3
"""Run the required WLHL search smoke tests through the Streamlit app."""
from __future__ import annotations

import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
QUERIES = [
    "plateau", "emotional eating", "grief eating", "food controls me", "keep the weight off",
    "I keep starting over", "menopause", "bariatric surgery", "motivation", "The Biggest Loser",
    "eat pizza in moderation", "fear of gaining the weight back",
]

def main():
    results = {}
    for query in QUERIES:
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
        app.text_input[0].set_value(query).run()
        if app.exception: raise RuntimeError(f"{query}: {app.exception[0].message}")
        results[query] = [item.value for item in app.subheader if "EP-" in str(item.value)][:10]
    target = ROOT / "database" / "search_validation.json"
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))

if __name__ == "__main__": main()
