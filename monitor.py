#!/usr/bin/env python3
"""Flat alert: watches three Tirol rental sites and sends a Telegram message
for every new listing that matches the criteria in config.json.

Runs on plain Python 3 (stdlib only). State lives in state/seen.json.
Without TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID env vars it prints alerts
to stdout instead of sending them (dry run).
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(ROOT, "state", "seen.json")
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
SEEN_CAP = 3000  # ids remembered per source


def fetch(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Language": "de-AT,de;q=0.9"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def parse_price(text):
    """'€ 1.300,50' / '798 €' / 1300 -> 1300 (euros, int). None if no number."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    m = re.search(r"(\d[\d.]*)(?:,\d+)?", text.replace(" ", " "))
    if not m:
        return None
    digits = m.group(1).replace(".", "")
    return int(digits) if digits.isdigit() else None


# --------------------------------------------------------------- sources

def source_oeh(cfg):
    """WordPress RSS feed of the newest properties. Price is only on the
    detail page, so leave it None here; fetch_oeh_price fills it for new ids."""
    xml = fetch(cfg["feed"])
    listings = []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
        link = re.search(r"<link>(.*?)</link>", item)
        title = re.search(r"<title>(.*?)</title>", item)
        guid = re.search(r"p=(\d+)</guid>", item)
        if not link:
            continue
        url = unescape(link.group(1).strip())
        listings.append({
            "id": "oeh-" + (guid.group(1) if guid else url.rstrip("/").rsplit("/", 1)[-1]),
            "title": unescape(title.group(1).strip()) if title else url,
            "price": None,
            "url": url,
            "extra": "",
        })
    return listings


def fetch_oeh_price(url):
    try:
        html = fetch(url)
    except Exception:
        return None
    m = re.search(r'"price_area">\s*€?\s*([\d.,]+)', html)
    return parse_price(m.group(1)) if m else None


def source_tt(cfg):
    """Server-rendered cards: <a href="/immobilien/..." data-dlteaser="{...}">
    where the escaped JSON attribute carries price and title."""
    listings = []
    for page in cfg["pages"]:
        html = fetch(page)
        for href, teaser in re.findall(
            r'href="(/immobilien/[^"]+)"[^>]*data-dlteaser="([^"]+)"', html, re.S
        ):
            try:
                data = json.loads(unescape(teaser))
            except ValueError:
                data = {}
            lid = href.rstrip("/").rsplit("/", 1)[-1]
            listings.append({
                "id": "tt-" + lid,
                "title": data.get("title") or href,
                "price": parse_price(data.get("price")),
                "url": "https://immo.tt.com" + href,
                "extra": page.split("/tirol/")[-1].split("?")[0].replace("-", " ").title(),
            })
    return listings


def _is24_state(html):
    marker = "window.__INITIAL_STATE__="
    i = html.find(marker)
    if i < 0:
        raise ValueError("IS24: __INITIAL_STATE__ not found (layout change or bot block)")
    raw = html[i + len(marker):]
    raw = re.sub(r"([:\[,])undefined", r"\1null", raw)
    obj, _ = json.JSONDecoder().raw_decode(raw)
    return obj


def source_is24(cfg):
    """SEO result pages embed a JSON state with all hits; follow pagination."""
    listings = []
    for base in cfg["pages"]:
        origin = "https://" + urllib.parse.urlparse(base).netloc
        state = _is24_state(fetch(base))
        results = state["reduxAsyncConnect"]["pageData"]["results"]
        pages = results.get("pagination", {}).get("all") or []
        hit_batches = [results["hits"]]
        for path in pages[1:]:
            more = _is24_state(fetch(origin + path))
            hit_batches.append(
                more["reduxAsyncConnect"]["pageData"]["results"]["hits"]
            )
        for hits in hit_batches:
            for h in hits:
                facts = " · ".join(
                    ((f.get("value") or "") + " " + (f.get("label") or "")).strip()
                    for f in h.get("mainKeyFacts", [])
                )
                listings.append({
                    "id": "is24-" + h["exposeId"],
                    "title": unescape(h.get("headline") or facts or h["exposeId"]),
                    "price": parse_price(h.get("primaryPrice")),
                    "url": h.get("links", {}).get("absoluteURL")
                    or origin + "/expose/" + h["exposeId"],
                    "extra": unescape(" · ".join(
                        x for x in [h.get("addressString"), facts] if x
                    )),
                })
    return listings


SOURCES = {"oeh": source_oeh, "tt": source_tt, "is24": source_is24}


# --------------------------------------------------------------- alerting

def telegram_send(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[dry-run] " + text.replace("\n", " | "))
        return
    body = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "false",
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=body
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_alert(label, item):
    price = f"€ {item['price']}" if item["price"] is not None else "Preis siehe Inserat"
    lines = [
        f"🏠 <b>{esc(item['title'])}</b>",
        f"💶 {price}",
    ]
    if item.get("extra"):
        lines.append(f"📍 {esc(item['extra'])}")
    lines.append(f"🔗 {item['url']}")
    lines.append(f"<i>{esc(label)}</i>")
    return "\n".join(lines)


# --------------------------------------------------------------- main

def main():
    config = json.load(open(os.path.join(ROOT, "config.json")))
    try:
        state = json.load(open(STATE_PATH))
    except (OSError, ValueError):
        state = {}
    seen = state.setdefault("seen", {})

    max_price = config.get("max_price")
    excludes = [k.lower() for k in config.get("exclude_keywords", [])]
    max_alerts = config.get("max_alerts_per_run", 20)
    alerts_sent = 0
    failures = []

    for name, source_fn in SOURCES.items():
        cfg = config["sources"].get(name)
        if not cfg:
            continue
        try:
            listings = source_fn(cfg)
            listings = list({l["id"]: l for l in listings}.values())
        except Exception as e:  # one broken site must not kill the others
            failures.append(f"{name}: {e}")
            continue
        if not listings:
            failures.append(f"{name}: 0 listings parsed (layout change?)")
            continue

        first_run = name not in seen
        known = set(seen.get(name, []))
        new_items = [l for l in listings if l["id"] not in known]

        for item in new_items:
            known.add(item["id"])
            if first_run:
                continue  # seed silently, no alert flood on first run
            title_l = item["title"].lower()
            if any(k in title_l for k in excludes):
                continue
            if name == "oeh" and item["price"] is None:
                item["price"] = fetch_oeh_price(item["url"])
            if (
                max_price is not None
                and item["price"] is not None
                and item["price"] > max_price
            ):
                continue
            if alerts_sent < max_alerts:
                telegram_send(format_alert(cfg.get("label", name), item))
                alerts_sent += 1

        seen[name] = list(known)[-SEEN_CAP:]
        print(f"{name}: {len(listings)} listings, {len(new_items)} new"
              + (" (first run, seeded)" if first_run else ""))

    state["last_run"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=0, sort_keys=True)

    print(f"alerts sent: {alerts_sent}")
    if failures:
        print("WARNING: " + "; ".join(failures), file=sys.stderr)


if __name__ == "__main__":
    main()
