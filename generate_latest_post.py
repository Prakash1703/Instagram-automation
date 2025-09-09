#!/usr/bin/env python3
"""
Generate Instagram-ready image ONLY IF the news is really fresh.
- Aggregates from multiple RSS feeds (moneycontrol + livemint + google news markets)
- Picks the newest by published time
- Skips if older than MAX_AGE_MINUTES
- Skips if duplicate of last posted
- Optional manual override via headline.txt
Outputs: ./out/<file>.png (1080x1350)
"""

import os, io, json, hashlib, datetime as dt, sys
from typing import List, Dict, Any, Optional
import feedparser
from slugify import slugify
from PIL import Image, ImageDraw, ImageFont
from email.utils import parsedate_to_datetime

# ===== Config =====
OUT_DIR = "out"
STATE_PATH = "out/last_id.json"
OVERRIDE_PATH = "headline.txt"
IMG_W, IMG_H = 1080, 1350
MAX_LEN = 160
MAX_AGE_MINUTES = int(os.getenv("MAX_AGE_MINUTES", "60"))  # 👈 tweak via workflow env

SOURCES = [
    # Moneycontrol Top News
    "https://www.moneycontrol.com/rss/MCtopnews.xml",
    # LiveMint Markets (official RSS list has /rss/markets)
    "https://www.livemint.com/rss/markets",
    # Google News search (markets india)
    "https://news.google.com/rss/search?q=markets+india&hl=en-IN&gl=IN&ceid=IN:en",
]

# ====== Helpers ======
def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_state(state: Dict[str, Any]) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def parse_dt(s: Optional[str]) -> Optional[dt.datetime]:
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)  # returns aware dt (usually UTC)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc)
    except Exception:
        return None

def get_entries(feed_url: str, max_items: int = 5) -> List[Dict[str, Any]]:
    d = feedparser.parse(feed_url)
    entries = []
    for e in d.entries[:max_items]:
        title = e.get("title", "").strip()
        link  = e.get("link", "").strip()
        # Try best-effort timestamps
        p = e.get("published") or e.get("updated") or e.get("pubDate")
        ts = parse_dt(p)
        # If still None, try feedparser's struct_times
        if ts is None:
            for key in ("published_parsed", "updated_parsed"):
                st = e.get(key)
                if st:
                    ts = dt.datetime(*st[:6], tzinfo=dt.timezone.utc)
                    break
        entries.append({
            "title": title,
            "link": link,
            "published_at": ts,   # UTC aware or None
            "source": feed_url,
            "raw_published": p or "",
        })
    return entries

def pick_newest(entries: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    valid = [x for x in entries if x.get("published_at") is not None]
    if not valid:
        return None
    valid.sort(key=lambda x: x["published_at"], reverse=True)
    return valid[0]

def hash_id(title: str, link: str) -> str:
    return hashlib.sha256(f"{title}|{link}".encode("utf-8")).hexdigest()[:16]

def shorten(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n-1] + "…"

def wrap_lines(draw: ImageDraw.ImageDraw, text: str, font, max_width: int):
    words = text.split()
    lines, line = [], ""
    for w in words:
        test = (line + " " + w).strip()
        if draw.textlength(test, font=font) <= max_width:
            line = test
        else:
            if line: lines.append(line)
            line = w
    if line: lines.append(line)
    return lines

def draw_poster(headline: str, subline: str = "") -> bytes:
    img = Image.new("RGB", (IMG_W, IMG_H), (18, 22, 33))
    draw = ImageDraw.Draw(img)
    # header
    draw.rectangle((0, 0, IMG_W, 260), fill=(34, 40, 60))
    # fonts
    try:
        h1 = ImageFont.truetype("DejaVuSans-Bold.ttf", 64)
        body = ImageFont.truetype("DejaVuSans.ttf", 42)
        tag  = ImageFont.truetype("DejaVuSans.ttf", 28)
        subf = ImageFont.truetype("DejaVuSans.ttf", 28)
    except:
        h1 = body = tag = subf = ImageFont.load_default()

    # heading
    heading = "MARKET UPDATE"
    w = draw.textlength(heading, font=h1)
    draw.text(((IMG_W - w) / 2, 110), heading, fill=(240, 245, 255), font=h1)

    # box
    draw.rounded_rectangle((40, 270, IMG_W - 40, IMG_H - 180),
                           radius=36, outline=(80, 90, 120), width=3)

    # headline
    margin = 90
    text = shorten(headline, MAX_LEN)
    lines = wrap_lines(draw, text, body, IMG_W - 2 * margin)
    y = 360
    for ln in lines:
        wln = draw.textlength(ln, font=body)
        draw.text(((IMG_W - wln) / 2, y), ln, fill=(235, 238, 245), font=body)
        y += 64

    # subline (optional)
    if subline:
        w3 = draw.textlength(subline, font=subf)
        draw.text(((IMG_W - w3) / 2, y + 8), subline, fill=(210, 215, 230), font=subf)

    # footer
    now_ist = dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30)))
    footer = f"Auto-generated • {now_ist.strftime('%d %b %Y, %I:%M %p IST')}"
    w2 = draw.textlength(footer, font=tag)
    draw.text(((IMG_W - w2) / 2, IMG_H - 120), footer, fill=(210, 215, 230), font=tag)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    state = load_state()

    # 1) Manual override
    if os.path.exists(OVERRIDE_PATH):
        with open(OVERRIDE_PATH, "r", encoding="utf-8") as f:
            headline = f.read().strip()
        if headline:
            img = draw_poster(headline, "Manual override")
            fname = f"{dt.datetime.now().strftime('%Y%m%d_%H%M')}_{slugify(headline)[:48]}_manual.png"
            fpath = os.path.join(OUT_DIR, fname)
            with open(fpath, "wb") as out:
                out.write(img)
            print("[OK] Manual override image saved:", fpath)
            # manual overrides are allowed even if duplicate
            state["last_id"] = "manual_" + hash_id(headline, "manual")
            save_state(state)
            return

    # 2) Aggregate all sources, pick newest
    all_entries = []
    for url in SOURCES:
        try:
            all_entries.extend(get_entries(url, max_items=5))
        except Exception as e:
            print(f"[WARN] Failed to fetch {url}: {e}")

    newest = pick_newest(all_entries)
    if not newest:
        print("NO_NEWS_FOUND")
        sys.exit(0)

    # 3) Freshness check
    now = dt.datetime.now(dt.timezone.utc)
    pub = newest.get("published_at")
    if not pub:
        print("NO_PUBLISH_TIME_SKIP")
        sys.exit(0)
    age_min = (now - pub).total_seconds() / 60.0
    if age_min > MAX_AGE_MINUTES:
        print(f"STALE_NEWS_SKIP age={age_min:.1f} min (> {MAX_AGE_MINUTES})")
        sys.exit(0)

    title = newest["title"]
    link  = newest["link"]
    raw_p = newest.get("raw_published", "")
    nid = hash_id(title, link)

    # 4) Duplicate check
    if state.get("last_id") == nid:
        print("DUPLICATE_SKIP")
        sys.exit(0)

    # 5) Render poster
    subline = f"{link} • {pub.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).strftime('%I:%M %p')}"
    png = draw_poster(title, subline=subline)

    fname = f"{dt.datetime.now().strftime('%Y%m%d_%H%M')}_{slugify(title)[:48]}_{nid[:8]}.png"
    fpath = os.path.join(OUT_DIR, fname)
    with open(fpath, "wb") as f:
        f.write(png)

    # 6) Save state
    state["last_id"] = nid
    state["last_title"] = title
    state["last_link"] = link
    state["last_published_utc"] = pub.isoformat()
    state["source"] = newest["source"]
    save_state(state)

    print(f"[OK] Fresh image saved: {fpath}")
    print(f"[INFO] Title: {title}")
    print(f"[INFO] Link:  {link}")
    print(f"[INFO] Pub:   {pub.isoformat()} (UTC)")
    print(f"[INFO] Age:   {age_min:.1f} minutes")

if __name__ == "__main__":
    main()