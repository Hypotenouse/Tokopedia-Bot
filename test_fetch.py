"""Block test v2: use the short link only, and show every price with context."""
import re
import sys

import requests

URL = "https://vt.tokopedia.com/t/ZS9fv8Qh4J9eD-PHGmv/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "id-ID,id;q=0.9",
}

r = requests.get(URL, headers=HEADERS, timeout=25, allow_redirects=True)
html = r.text
print("status:", r.status_code, "| length:", len(html))
print("final url:", r.url[:120])

# strip tags so we see text the way a person would
text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
text = re.sub(r"<[^>]+>", " ", text)
text = re.sub(r"\s+", " ", text)

print("\n--- first 10 'Rp' prices in visible text (with context) ---")
count = 0
for m in re.finditer(r"Rp\s?\d{1,3}(?:\.\d{3})+", text):
    s = max(0, m.start() - 40)
    e = min(len(text), m.end() + 40)
    print(f"{count + 1}. {m.group(0)}  <- ...{text[s:e]}...")
    count += 1
    if count >= 10:
        break
if count == 0:
    print("none found in visible text")

print("\n--- price-like fields in raw HTML/JSON ---")
seen = 0
for m in re.finditer(r'"([A-Za-z_]*[Pp]rice[A-Za-z_]*)"\s*:\s*"?([\d.,Rp ]{3,20})"?', html):
    print(m.group(1), "=", m.group(2))
    seen += 1
    if seen >= 15:
        break
if seen == 0:
    print("none found")

sys.exit(0)
