#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google News → Latest only → Poster with article image background.
- Source: Google News Top Stories (India) OR search via NEWS_QUERY
- Freshness gate via MAX_AGE_MINUTES (default 60)
- Duplicate prevention via out/last_id.json
- Manual override via headline.txt (skips freshness/dup check)
- Pulls article image from RSS media tags or falls back to page og:image
- Renders full-bleed image with dark overlay + readable text

ENV (optional):
  NEWS_QUERY        e.g., "technology" or "nepal protests"  (empty => Top Stories)
  MAX_AGE_MINUTES   default "60"
"""

import os, io, sys, json, hashlib, datetime as dt
from urllib.parse import quote_plus, urlparse
from email.utils import parsedate_to_datetime

import feedparser, requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageOps
from slugify import slugify

# ---------- Config ----------
OUT_DIR = "out"
STATE_PATH = os.path.join(OUT_DIR, "last_id.json")
OVERRIDE_PATH = "headline.txt"

IMG_W, IMG_H = 1080, 1350
HEADLINE_WRAP_LEN = 160
DEFAULT_MAX_AGE_MIN = 60

NEWS_QUERY = os.getenv("NEWS_QUERY", "").strip()
MAX_AGE_MINUTES = int(os.getenv("MAX_AGE_MINUTES", str(DEFAULT_MAX_AGE_MIN)))

GN_TOP = "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"
GN_SEARCH = lambda q: f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-IN&gl=IN&ceid=IN:en"

# ---------- Helpers ----------
def ensure_dirs():
    os.makedirs(OUT_DIR, exist_ok=True)

def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_state(s):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)

def parse_dt(s):
    if not s: return None
    try:
        d = parsedate_to_datetime(s)
        if d.tzinfo is None: d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc)
    except Exception:
        return None

def publisher_from_link(link: str) -> str:
    try:
        host = urlparse(link).netloc
        if host.startswith("www."): host = host[4:]
        # prettify e.g. indiatoday.in -> IndiaToday
        base = host.split(".")[0]
        return base.replace("-", " ").title()
    except Exception:
        return ""

def fetch_gn_entries(max_items=12):
    url = GN_SEARCH(NEWS_QUERY) if NEWS_QUERY else GN_TOP
    d = feedparser.parse(url)
    entries = []
    for e in d.entries[:max_items]:
        title = (e.get("title") or "").strip()
        link  = (e.get("link")  or "").strip()
        pub   = parse_dt(e.get("published") or e.get("updated") or e.get("pubDate"))
        # Try to grab image from RSS media tags
        media_url = None
        if "media_content" in e and e.media_content:
            # feedparser gives list[{'url':...}]
            media_url = e.media_content[0].get("url")
        if not media_url and "media_thumbnail" in e and e.media_thumbnail:
            media_url = e.media_thumbnail[0].get("url")
        entries.append({
            "title": title, "link": link, "published_at": pub,
            "media_url": media_url,
            "source_title": (getattr(e, "source", {}) or {}).get("title", "")
        })
    return entries

def pick_newest(entries):
    valid = [x for x in entries if x["published_at"]]
    if not valid: return None
    valid.sort(key=lambda x: x["published_at"], reverse=True)
    return valid[0]

def short(t, n): return t if len(t) <= n else t[:n-1] + "…"

def wrap_lines(draw, text, font, max_width):
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

# ---------- Image fetching ----------
def get_og_image(url: str, timeout=10) -> str | None:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code != 200: return None
        soup = BeautifulSoup(r.text, "html.parser")
        for prop in ("og:image","twitter:image","og:image:url"):
            tag = soup.find("meta", property=prop)
            if tag and tag.get("content"): return tag["content"]
        return None
    except Exception:
        return None

def download_image(url: str, timeout=12) -> Image.Image | None:
    try:
        r = requests.get(url, timeout=timeout, stream=True, headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code != 200: return None
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        return img
    except Exception:
        return None

def compose_with_bg(bg: Image.Image) -> Image.Image:
    # Aspect-fill to 1080x1350, then add dark overlay
    bg = ImageOps.exif_transpose(bg)
    bg = ImageOps.fit(bg, (IMG_W, IMG_H), method=Image.LANCZOS, bleed=0.0, centering=(0.5,0.5))
    overlay = Image.new("RGBA", (IMG_W, IMG_H), (0,0,0,120))  # ~47% dark
    bg = bg.convert("RGBA")
    bg.alpha_composite(overlay)
    return bg.convert("RGB")

def render_poster(headline: str, subline: str, bg_img: Image.Image | None) -> bytes:
    if bg_img is not None:
        img = compose_with_bg(bg_img)
        draw = ImageDraw.Draw(img)
    else:
        img = Image.new("RGB", (IMG_W, IMG_H), (18, 22, 33))
        draw = ImageDraw.Draw(img)
        draw.rectangle((0,0,IMG_W,260), fill=(34,40,60))

    # Fonts
    try:
        h1   = ImageFont.truetype("DejaVuSans-Bold.ttf", 64)
        body = ImageFont.truetype("DejaVuSans.ttf", 42)
        meta = ImageFont.truetype("DejaVuSans.ttf", 28)
    except:
        h1 = body = meta = ImageFont.load_default()

    # Heading
    heading = "TOP STORY"
    tw = draw.textlength(heading, font=h1)
    draw.text(((IMG_W - tw)/2, 90), heading, fill=(240,245,255), font=h1)

    # Card outline (for non-image bg it looks like a card; on photo it's subtle)
    draw.rounded_rectangle((36, 240, IMG_W-36, IMG_H-160), radius=36, outline=(220,225,235), width=2)

    # Headline (wrapped)
    margin = 90
    text = short(headline, HEADLINE_WRAP_LEN)
    lines = wrap_lines(draw, text, body, IMG_W - 2*margin)
    y = 320
    for ln in lines:
        lw = draw.textlength(ln, font=body)
        draw.text(((IMG_W - lw)/2, y), ln, fill=(245,248,250), font=body)
        y += 64

    # Subline
    if subline:
        sw = draw.textlength(subline, font=meta)
        draw.text(((IMG_W - sw)/2, y+10), subline, fill=(230,233,240), font=meta)

    # Footer (IST)
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    footer = f"Auto-generated • {dt.datetime.now(ist).strftime('%d %b %Y, %I:%M %p IST')}"
    fw = draw.textlength(footer, font=meta)
    draw.text(((IMG_W - fw)/2, IMG_H-110), footer, fill=(220,225,235), font=meta)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

# ---------- Main ----------
def main():
    ensure_dirs()
    state = load_state()

    # Manual override (always allowed)
    if os.path.exists(OVERRIDE_PATH):
        txt = open(OVERRIDE_PATH, "r", encoding="utf-8").read().strip()
        if txt:
            png = render_poster(txt, "Manual override", None)
            fname = f"{dt.datetime.now().strftime('%Y%m%d_%H%M')}_{slugify(txt)[:48]}_manual.png"
            path = os.path.join(OUT_DIR, fname)
            open(path, "wb").write(png)
            state["last_id"] = "manual_" + hashlib.sha256(txt.encode()).hexdigest()[:16]
            save_state(state)
            print("[OK] Manual override image:", path)
            return

    # Fetch newest Google News item
    entries = fetch_gn_entries()
    newest = pick_newest(entries)
    if not newest:
        print("NO_NEWS_FOUND"); return

    pub = newest["published_at"]
    now = dt.datetime.now(dt.timezone.utc)
    age_min = (now - pub).total_seconds()/60.0 if pub else 9999

    if age_min > MAX_AGE_MINUTES:
        print(f"STALE_NEWS_SKIP age={age_min:.1f} min (> {MAX_AGE_MINUTES})"); return

    title, link = newest["title"], newest["link"]
    nid = hashlib.sha256(f"{title}|{link}".encode()).hexdigest()[:16]
    if state.get("last_id") == nid:
        print("DUPLICATE_SKIP"); return

    # Publisher + local time for subline
    publisher = newest.get("source_title") or publisher_from_link(link)
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    subline = f"{publisher} • {pub.astimezone(ist).strftime('%I:%M %p')}"

    # Try to fetch an image
    bg_img = None
    img_url = newest.get("media_url")
    if not img_url:
        img_url = get_og_image(link)
    if img_url:
        bg_img = download_image(img_url)

    # Render
    png = render_poster(title, subline, bg_img)

    fname = f"{dt.datetime.now().strftime('%Y%m%d_%H%M')}_{slugify(title)[:48]}_{nid[:8]}.png"
    fpath = os.path.join(OUT_DIR, fname)
    with open(fpath, "wb") as f: f.write(png)

    # Save state
    state.update({
        "last_id": nid,
        "last_title": title,
        "last_link": link,
        "last_published_utc": pub.isoformat() if pub else "",
        "query": NEWS_QUERY or "top_stories",
        "max_age_minutes": MAX_AGE_MINUTES
    })
    save_state(state)

    print(f"[OK] Fresh image saved: {fpath}")
    print(f"[INFO] Title: {title}")
    print(f"[INFO] Publisher: {publisher}")
    print(f"[INFO] Link: {link}")
    print(f"[INFO] Age: {age_min:.1f} minutes")

if __name__ == "__main__":
    main()