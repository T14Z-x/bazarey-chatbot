"""Manual smoke script for category browsing and ordering scenarios.

Run this script directly while the API is running:
    python tests/test_category_order.py
"""

import json
import time
import urllib.request

URL = "http://127.0.0.1:8000/simulate/chat"
USER = "test_cat_order_2"


def chat(msg: str) -> str:
    data = json.dumps({"channel_user_id": USER, "text": msg}).encode()
    req = urllib.request.Request(URL, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read()).get("reply", "")


def run_smoke() -> None:
    cases = [
        # Category browsing
        ("shobji ki ache?", "category browse vegetables"),
        ("show me vegetables", "english category browse"),
        ("ki ki category ache?", "list all categories"),
        ("\u09ae\u09b6\u09b2\u09be \u09a6\u09c7\u0996\u09be\u0993", "bangla spice category"),
        ("fol dekhao", "banglish fruit category"),
        # Order intent
        ("2 kg peyaj nibo", "banglish structured order"),
        ("dim 5ta dao", "banglish qty-last order"),
        ("I want 3 chicken", "english order"),
        # Price queries (regression)
        ("peyaj er dam koto?", "banglish price query"),
        ("dudh", "product inquiry"),
        ("hello", "greeting"),
        # Bangla category
        ("\u09b8\u09ac\u099c\u09bf \u09a6\u09c7\u0996\u09be\u0993", "bangla vegetable category"),
        ("dal ki ache?", "lentil category"),
        ("rice dekhao", "rice category"),
    ]

    passed = 0
    failed = 0
    t0 = time.time()

    for msg, label in cases:
        try:
            reply = chat(msg)
            ok = len(reply) > 5
            status = "PASS" if ok else "FAIL"
            if ok:
                passed += 1
            else:
                failed += 1
            print(f"{status} [{label}] \"{msg}\" => {reply[:140]}")
        except Exception as err:
            failed += 1
            print(f"FAIL [{label}] \"{msg}\" => ERROR: {err}")

    elapsed = time.time() - t0
    print(f"\n{passed}/{passed + failed} passed in {elapsed:.1f}s")


if __name__ == "__main__":
    run_smoke()
