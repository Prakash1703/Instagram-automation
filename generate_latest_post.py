#!/usr/bin/env python3
"""
Generate Instagram-ready PNG from the *latest* Google News item (any topic).
- Source: Google News Top Stories (India) + optional query
- Picks newest by publish time
- Skips if older than MAX_AGE_MINUTES
- Skips if duplicate (title+link hash)
- Optional manual override via headline.txt

ENV (optional):
  NEWS_QUERY        -> if set, uses GN search RSS instead of Top Stories (e.g., "technology" or "nepal protests")
  MAX_AGE_MINUTES   -> freshness window in minutes (default: 60)

Outputs:
  out/<timestamp>_<slug>_<hash>.png  (1080x1350, portrait)
  out/last_id.json                    (state to prevent duplicates)
"""

import os, io, json, sys, hashlib, datetime as dt
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import feedparser
from slugify import slugify
from PIL import Image, ImageDraw, ImageFont

# ---------------- Config ----------------
OUT_DIR = "out"
STATE_PATH = os.path.join(OUT_DIR, "last_id.json")
OVERRIDE_PATH = "headline.txt"

IMG_W, IMG_H = 1080, 1350      # Instagram portrait
HEADLINE_WRAP_LEN = 160
DEFAULT_MAX_AGE_MIN = 60

NEWS_QUERY = os.getenv("NEWS_QUERY", "").strip()
MAX_AGE_MINUTES = int(os.getenv("MAX_AGE_MINUTES", str(DEFAULT_MAX_AGE_MIN)))

GN_TOP_STORIES = "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"
GN_SEARCH = lambda q: f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-IN&gl=IN&ceid=IN:en"

# --------------- Utilities ---------------
def ensure_dirs():
    os.makedirs(OUT_DIR, exist_ok=True)

def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def parse_dt(s):
    """Parse RFC822-style pubDate to aware UTC datetime."""
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc)
    except Exception:
        return None

def fetch_gn_entries(max_items=8):
    """Fetch Google News feed (Top Stories or Search) and return entries with timestamps."""
    url = GN_SEARCH(NEWS_QUERY) if NEWS_QUERY else GN_TOP_STORIES
    d = feedparser.parse(url)
    entries = []
    for e in d.entries[:max_items]:
        title = e.get("title", "").strip()
        link  = e.get("link", "").strip()
        # GN provides 'published' (e.g., "Mon, 09 Sep 2025 16:10:00 GMT")
        pub = parse_dt(e.get("published") or e.get("updated") or e.get("pubDate"))
        entries.append({"title": title, "link": link, "published_at": pub})
    return entries

def pick_newest(entries):
    entries = [x for x in entries if x["published_at"] is not None]
    if not entries:
        return None
    entries.sort(key=lambda x: x["published_at"], reverse=True)
    return entries[0]

def short(text, n):
    return text if len(text) <= n else text[: n - 1] + "…"

def wrap_lines(draw, text, font, max_width):
    words = text.split()
    lines, line = [], ""
    for w in words:
        test = (line + " " + w).strip()
        if draw.textlength(test, font=font) <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines

def draw_poster(headline, subline=""):
    img = Image.new("RGB", (IMG_W, IMG_H), (18, 22, 33))
    draw = ImageDraw.Draw(img)

    # Header band
    draw.rectangle((0, 0, IMG_W, 260), fill=(34, 40, 60))

    # Fonts
    try:
        h1   = ImageFont.truetype("DejaVuSans-Bold.ttf", 64)
        body = ImageFont.truetype("DejaVuSans.ttf", 42)
        meta = ImageFont.truetype("DejaVuSans.ttf", 28)
    except:
        h1 = body = meta = ImageFont.load_default()

    # Title
    heading = "TOP STORY"
    tw = draw.textlength(heading, font=h1)
    draw.text(((IMG_W - tw) / 2, 110), heading, fill=(240, 245, 255), font=h1)

    # Card
    draw.rounded_rectangle((40, 270, IMG_W - 40, IMG_H - 180),
                           radius=36, outline=(80, 90, 120), width=3)

    # Headline
    margin = 90
    text = short(headline, HEADLINE_WRAP_LEN)
    lines = wrap_lines(draw, text, body, IMG_W - 2 * margin)
    y = 360
    for ln in lines:
        lw = draw.textlength(ln, font=body)
        draw.text(((IMG_W - lw) / 2, y), ln, fill=(235, 238, 245), font=body)
        y += 64

    # Subline (optional)
    if subline:
        sw = draw.textlength(subline, font=meta)
        draw.text(((IMG_W - sw) / 2, y + 8), subline, fill=(210, 215, 230), font=meta)

    # Footer (IST)
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    footer = f"Auto-generated • {dt.datetime.now(ist).strftime('%d %b %Y, %I:%M %p IST')}"
    fw = draw.textlength(footer, font=meta)
    draw.text(((IMG_W - fw) / 2, IMG_H - 120), footer, fill=(210, 215, 230), font=meta)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

# --------------- Main --------------------
def main():
    ensure_dirs()
    state = load_state()

    # 1) Manual override via headline.txt
    if os.path.exists(OVERRIDE_PATH):
        with open(OVERRIDE_PATH, "r", encoding="utf-8") as f:
            override = f.read().strip()
        if override:
            png = draw_poster(override, "Manual override")
            fname = f"{dt.datetime.now().strftime('%Y%m%d_%H%M')}_{slugify(override)[:48]}_manual.png"
            path = os.path.join(OUT_DIR, fname)
            with open(path, "wb") as out:
                out.write(png)
            state["last_id"] = "manual_" + hashlib.sha256(override.encode()).hexdigest()[:16]
            save_state(state)
            print("[OK] Manual override image:", path)
            return

    # 2) Fetch latest from Google News
    entries = fetch_gn_entries(max_items=12)
    newest = pick_newest(entries)
    if not newest:
        print("NO_NEWS_FOUND")
        return

    pub = newest["published_at"]          # aware UTC
    now = dt.datetime.now(dt.timezone.utc)
    age_min = (now - pub).total_seconds() / 60.0

    # 3) Freshness filter
    if age_min > MAX_AGE_MINUTES:
        print(f"STALE_NEWS_SKIP age={age_min:.1f} min (> {MAX_AGE_MINUTES})")
        return

    title, link = newest["title"], newest["link"]

    # 4) Duplicate check
    nid = hashlib.sha256(f"{title}|{link}".encode()).hexdigest()[:16]
    if state.get("last_id") == nid:
        print("DUPLICATE_SKIP")
        return

    # 5) Render poster
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    sub = f"{link} • {pub.astimezone(ist).strftime('%I:%M %p')}"
    png = draw_poster(title, subline=sub)

    fname = f"{dt.datetime.now().strftime('%Y%m%d_%H%M')}_{slugify(title)[:48]}_{nid[:8]}.png"
    fpath = os.path.join(OUT_DIR, fname)
    with open(fpath, "wb") as f:
        f.write(png)

    # 6) Save state
    state.update({
        "last_id": nid,
        "last_title": title,
        "last_link": link,
        "last_published_utc": pub.isoformat(),
        "query": NEWS_QUERY or "top_stories",
        "max_age_minutes": MAX_AGE_MINUTES
    })
    save_state(state)

    print(f"[OK] Fresh image saved: {fpath}")
    print(f"[INFO] Title: {title}")
    print(f"[INFO] Link:  {link}")
    print(f"[INFO] Pub:   {pub.isoformat()} UTC")
    print(f"[INFO] Age:   {age_min:.1f} minutes")

if __name__ == "__main__":
    main()