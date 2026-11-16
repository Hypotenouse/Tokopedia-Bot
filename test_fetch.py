"""Block test: can GitHub's servers read the Tokopedia product page?"""
import re
import sys

import requests

URLS = [
    "https://shop-id.tokopedia.com/pdp/1730698185538963098",
    "https://vt.tokopedia.com/t/ZS9fv8Qh4J9eD-PHGmv/",
]
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "id-ID,id;q=0.9",
}
BLOCK_WORDS = ["captcha", "verify you are", "access denied", "forbidden", "robot"]

ok = False
for url in URLS:
    print("=" * 60)
    print("URL:", url)
    try:
        r = requests.get(url, headers=HEADERS, timeout=25, allow_redirects=True)
    except Exception as e:  # noqa: BLE001
        print("REQUEST FAILED:", e)
        continue
    html = r.text
    print("status:", r.status_code, "| length:", len(html))
    m = re.search(r"Rp\s?(\d{1,3}(?:\.\d{3})+)", html)
    print("price found:", m.group(0) if m else "NO")
    hits = [w for w in BLOCK_WORDS if w in html.lower()]
    print("block keywords:", hits or "none")
    if r.status_code == 200 and m:
        ok = True

print("=" * 60)
print("RESULT:", "NOT BLOCKED (price readable)" if ok else "BLOCKED or price missing")
sys.exit(0 if ok else 1)
