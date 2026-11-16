"""Tokopedia price watcher -> WhatsApp (Fonnte). Runs once per call (GitHub Actions)."""
import json
import os
import re
import sys

import requests

URL = "https://vt.tokopedia.com/t/ZS9fv8Qh4J9eD-PHGmv/"
PRODUCT = "Cimol Mozzarella AA (paket 5)"
PREFERRED = "balado"
KNOWN_FLAVORS = ["Ayam Bawang", "Balado", "Pedas Asin", "Jagung Bakar", "Barbeque", "BBQ"]
STATE_FILE = "state.json"
FAIL_NOTIFY_AT = 8  # consecutive failed runs before a WhatsApp warning
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "id-ID,id;q=0.9",
}
PRICE_KEY = '"sale_price_decimal"'


def rp(n):
    return "Rp" + f"{n:,}".replace(",", ".")


def to_int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    d = re.sub(r"\D", "", str(v))
    return int(d) if d else None


# ---------- state ----------
def load_state():
    try:
        with open(STATE_FILE) as f:
            s = json.load(f)
    except Exception:
        s = {}
    s.setdefault("alerted", False)
    s.setdefault("threshold", None)
    s.setdefault("fails", 0)
    return s


def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=1, sort_keys=True)


# ---------- WhatsApp ----------
def send_wa(message):
    r = requests.post(
        "https://api.fonnte.com/send",
        headers={"Authorization": os.environ["FONNTE_TOKEN"]},
        data={"target": os.environ["WA_TARGET"], "message": message, "countryCode": "62"},
        timeout=30,
    )
    try:
        res = r.json()
    except ValueError:
        raise RuntimeError(f"Fonnte HTTP {r.status_code}, non-JSON reply")
    if not res.get("status"):
        # print only the reason: logs of a public repo are public
        raise RuntimeError(f"Fonnte rejected the message: {res.get('reason', 'unknown reason')}")


# ---------- page parsing ----------
def fetch():
    r = requests.get(URL, headers=HEADERS, timeout=30, allow_redirects=True)
    r.raise_for_status()
    html = r.text
    if PRICE_KEY not in html and "min_sku_price" not in html and "Rp" not in html:
        raise RuntimeError(f"page has no price data (len={len(html)}), probably blocked")
    return html


def flatten(o, key=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from flatten(v, str(k).lower())
    elif isinstance(o, list):
        for v in o:
            yield from flatten(v, key)
    else:
        yield key, o


def find_sku_objects(html):
    """For every sale_price_decimal, return the largest JSON object that holds
    exactly that one price (so it includes the flavor name and stock fields)."""
    dec = json.JSONDecoder()
    out = []
    pos = 0
    while True:
        i = html.find(PRICE_KEY, pos)
        if i < 0:
            break
        pos = i + len(PRICE_KEY)
        best = None
        j = i
        tries = 0
        while tries < 300:
            j = html.rfind("{", 0, j)
            if j < 0 or i - j > 8000:
                break
            tries += 1
            try:
                obj, end = dec.raw_decode(html, j)
            except ValueError:
                continue
            if end <= i or not isinstance(obj, dict):
                continue
            if html.count(PRICE_KEY, j, end) > 1:
                break
            best = obj
        if best is not None:
            out.append(best)
    return out


def pick_flavor(flat):
    for k, v in flat:
        if (
            isinstance(v, str)
            and any(t in k for t in ("prop_value", "sale_prop", "sku_name", "variant", "value_name", "spec"))
            and 0 < len(v.strip()) < 40
            and not re.search(r"\d{4,}", v)
        ):
            return v.strip()
    blob = " | ".join(v for _, v in flat if isinstance(v, str))
    for f in KNOWN_FLAVORS:
        if re.search(re.escape(f), blob, re.I):
            return f
    return None


STOCK_NUM = ("stock", "stock_num", "stock_count", "available_stock", "stock_qty")
SOLD_FLAGS = ("sold_out", "is_sold_out", "out_of_stock", "is_out_of_stock")
INSTOCK_FLAGS = ("in_stock", "is_in_stock", "has_stock")


def stock_state(flat):
    """True = sold out, False = available, None = no stock info found."""
    seen = None
    for k, v in flat:
        if k in STOCK_NUM and str(v).strip().isdigit():
            if int(v) == 0:
                return True
            seen = False
        elif k in SOLD_FLAGS:
            if v in (True, 1, "true", "1"):
                return True
            seen = False
        elif k in INSTOCK_FLAGS:
            if v in (False, 0, "false", "0"):
                return True
            seen = False
    return seen


def parse_skus(objs):
    merged = {}
    for o in objs:
        flat = list(flatten(o))
        price = next((to_int(v) for k, v in flat if k == "sale_price_decimal"), None)
        if not price:
            continue
        flavor = pick_flavor(flat)
        sold = stock_state(flat)
        key = (flavor, price)
        if key not in merged:
            merged[key] = sold
        elif sold is True or merged[key] is None:
            merged[key] = sold if sold is not None else merged[key]
    return [{"flavor": f, "price": p, "sold": s} for (f, p), s in merged.items()]


def fallback_price(html):
    m = re.search(r'"min_sku_price"\s*:\s*"?([\d.,]+)"?', html)
    if m and to_int(m.group(1)):
        return to_int(m.group(1))
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    m = re.search(r"Rp\s?(\d{1,3}(?:\.\d{3})+)", text)
    return to_int(m.group(1)) if m else None


def decide(skus, html, thr):
    """Return (price, flavor, sold_out_flavors)."""
    if not skus:
        return fallback_price(html), None, []
    sold_names = sorted({s["flavor"] or "?" for s in skus if s["sold"] is True})
    avail = [s for s in skus if s["sold"] is not True]
    if not avail:
        return None, None, sold_names
    cheap = [s for s in avail if s["price"] <= thr]
    pool = cheap or avail
    pick = None
    if cheap:
        pick = next((s for s in cheap if PREFERRED in (s["flavor"] or "").lower()), None)
    pick = pick or min(pool, key=lambda s: s["price"])
    return pick["price"], pick["flavor"], sold_names


# ---------- main ----------
def main():
    thr = to_int(os.environ.get("ALERT_PRICE") or "") or 100_000
    debug = os.environ.get("DEBUG", "").lower() == "true"

    if os.environ.get("SEND_TEST", "").lower() == "true":
        send_wa(f"Tes bot harga: aktif. Batas alert saat ini {rp(thr)}.")
        print("Test message sent.")
        return

    state = load_state()
    try:
        html = fetch()
        objs = find_sku_objects(html)
        skus = parse_skus(objs)
        price, flavor, sold_names = decide(skus, html, thr)
    except Exception as e:  # noqa: BLE001
        state["fails"] += 1
        print("ERROR:", e)
        if state["fails"] == FAIL_NOTIFY_AT:
            try:
                send_wa(f"Bot harga gagal baca halaman {FAIL_NOTIFY_AT}x berturut-turut: {e}")
            except Exception as e2:  # noqa: BLE001
                print("warning send failed:", e2)
        save_state(state)
        return
    state["fails"] = 0

    print(f"threshold={rp(thr)} skus={len(skus)} price={rp(price) if price else None} flavor={flavor} sold_out={sold_names}")
    if debug:
        print(f"html length: {len(html)} | sku objects found: {len(objs)}")
        for o in objs[:8]:
            print("RAW:", json.dumps(o, ensure_ascii=False)[:1500])
        for s in skus:
            print("PARSED:", s)

    if state["threshold"] != thr:
        state["threshold"] = thr
        state["alerted"] = False  # new limit: allow a fresh alert

    if price is not None:
        if price <= thr:
            if not state["alerted"]:
                lines = [f"HARGA TURUN! {rp(price)} (batas {rp(thr)})", PRODUCT]
                if flavor:
                    lines.append(f"Rasa: {flavor}")
                if sold_names:
                    lines.append("Habis: " + ", ".join(sold_names))
                lines.append(URL)
                send_wa("\n".join(lines))  # raises on failure -> state not marked
                state["alerted"] = True
        else:
            state["alerted"] = False  # re-arm
    save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("FATAL:", e)
        sys.exit(1)
