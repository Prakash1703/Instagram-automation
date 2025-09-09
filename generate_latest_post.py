#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google News → Latest only → TEXT on TOP, ARTICLE IMAGE at BOTTOM.
Fixes: resolve Google News redirect to publisher page and fetch real og:image.
Rejects Google thumbnails (news.google.com/gstatic/googleusercontent).

ENV (optional):
  NEWS_QUERY        e.g., "technology"  (empty => Top Stories)
  MAX_AGE_MINUTES   freshness window in minutes (default 60)
"""

import os, io, sys, json, hashlib, datetime as dt
from urllib.parse import quote_plus, urlparse, urljoin
from email.utils import parsedate_to_datetime

import feedparser, requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageOps
from slugify import slugify

# ---------- Config ----------
OUT_DIR       = "out"
STATE_PATH    = os.path.join(OUT_DIR, "last_id.json")
OVERRIDE_PATH = "headline.txt"

IMG_W, IMG_H         = 1080, 1350
TOP_H                = 520
PADDING              = 56
HEADLINE_WRAP_LEN    = 170
DEFAULT_MAX_AGE_MIN  = 60

NEWS_QUERY       = os.getenv("NEWS_QUERY", "").strip()
MAX_AGE_MINUTES  = int(os.getenv("MAX_AGE_MINUTES", str(DEFAULT_MAX_AGE_MIN)))

GN_TOP    = "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"
GN_SEARCH = lambda q: f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-IN&gl=IN&ceid=IN:en"

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "en-IN,en;q=0.9"}

REJECT_HOSTS = {"news.google.com", "googleusercontent.com", "gstatic.com", "gvt1.com"}

# ---------- Utils ----------
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
        base = host.split(".")[0]
        return base.replace("-", " ").title()
    except Exception:
        return ""

def is_rejected_image(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
        return any(h in host for h in REJECT_HOSTS)
    except Exception:
        return True

# ---------- Fetch from Google News ----------
def fetch_gn_entries(max_items=12):
    url = GN_SEARCH(NEWS_QUERY) if NEWS_QUERY else GN_TOP
    d = feedparser.parse(url)
    entries = []
    for e in d.entries[:max_items]:
        title = (e.get("title") or "").strip()
        link  = (e.get("link")  or "").strip()
        pub   = parse_dt(e.get("published") or e.get("updated") or e.get("pubDate"))
        # Some feeds include generic thumbnails; we won't trust them anymore.
        entries.append({
            "title": title, "link": link, "published_at": pub
        })
    return entries

def pick_newest(entries):
    valid = [x for x in entries if x["published_at"]]
    if not valid: return None
    valid.sort(key=lambda x: x["published_at"], reverse=True)
    return valid[0]

# ---------- Resolve to publisher & scrape og:image ----------
def resolve_canonical(url: str, timeout=12):
    """
    Follow the Google News redirect to the publisher article.
    Returns (final_url, soup) where final_url is publisher domain.
    """
    try:
        r = requests.get(url, headers=UA, timeout=timeout, allow_redirects=True)
        final_url = r.url  # after redirects
        soup = BeautifulSoup(r.text, "html.parser")
        # Prefer <link rel="canonical"> or og:url if present
        can = soup.find("link", rel="canonical")
        if can and can.get("href"):
            final_url = urljoin(final_url, can["href"])
        else:
            ogu = soup.find("meta", property="og:url")
            if ogu and ogu.get("content"):
                final_url = urljoin(final_url, ogu["content"])
        return final_url, soup
    except Exception:
        return url, None

def extract_best_image(page_url: str, soup: BeautifulSoup | None, timeout=12):
    """
    Try multiple selectors to get a good article image from publisher page.
    Rejects Google/GNews thumbnails.
    """
    # 1) from given soup
    def from_soup(sp: BeautifulSoup):
        if not sp: return None
        # try common meta tags
        for attr, val in (("property","og:image"),
                          ("property","og:image:secure_url"),
                          ("name","twitter:image"),
                          ("property","twitter:image"),
                          ("rel","image_src")):
            if attr == "rel":
                tag = sp.find("link", rel="image_src")
                if tag and tag.get("href"):
                    return urljoin(page_url, tag["href"])
            else:
                tag = sp.find("meta", {attr: val})
                if tag and tag.get("content"):
                    return urljoin(page_url, tag["content"])
        # sometimes <figure><img>
        img = sp.find("img")
        if img and img.get("src"):
            return urljoin(page_url, img["src"])
        return None

    img_url = from_soup(soup)
    if img_url and not is_rejected_image(img_url):
        return img_url

    # 2) fetch page again if needed (some sites lazy-load on first request)
    try:
        r = requests.get(page_url, headers=UA, timeout=timeout)
        if r.status_code == 200:
            sp = BeautifulSoup(r.text, "html.parser")
            img_url = from_soup(sp)
            if img_url and not is_rejected_image(img_url):
                return img_url
    except Exception:
        pass

    return None

def download_image(url: str, timeout=12):
    try:
        r = requests.get(url, timeout=timeout, stream=True, headers=UA)
        if r.status_code != 200: return None
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        return img
    except Exception:
        return None

def aspect_fit_fill(img: Image.Image, size):
    return ImageOps.fit(ImageOps.exif_transpose(img), size, method=Image.LANCZOS, centering=(0.5,0.5))

# ---------- Typography & layout ----------
def load_fonts():
    try:
        h1   = ImageFont.truetype("DejaVuSans-Bold.ttf", 62)
        body = ImageFont.truetype("DejaVuSans.ttf", 40)
        meta = ImageFont.truetype("DejaVuSans.ttf", 30)
    except:
        h1 = body = meta = ImageFont.load_default()
    return h1, body, meta

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

def short(t, n): return t if len(t) <= n else t[:n-1] + "…"

def render_layout(headline: str, publisher: str, pub_time_local: str, bg_img: Image.Image | None):
    canvas = Image.new("RGB", (IMG_W, IMG_H), (18,22,33))
    draw   = ImageDraw.Draw(canvas)
    h1, body, meta = load_fonts()

    # TOP area
    draw.rectangle((0,0,IMG_W,TOP_H), fill=(34,40,60))
    title_txt = "TOP STORY"
    tw = draw.textlength(title_txt, font=h1)
    draw.text(((IMG_W - tw)/2, PADDING), title_txt, fill=(240,245,255), font=h1)

    maxw = IMG_W - 2*PADDING
    lines = wrap_lines(draw, short(headline, HEADLINE_WRAP_LEN), body, maxw)
    y = PADDING + 90
    for ln in lines:
        lw = draw.textlength(ln, font=body)
        draw.text(((IMG_W - lw)/2, y), ln, fill=(235,238,245), font=body)
        y += 58

    sub = f"{publisher} • {pub_time_local}" if publisher else pub_time_local
    sw = draw.textlength(sub, font=meta)
    draw.text(((IMG_W - sw)/2, TOP_H - 80), sub, fill=(210,215,230), font=meta)

    draw.line((PADDING, TOP_H, IMG_W - PADDING, TOP_H), fill=(90,100,125), width=2)

    # Bottom image
    bottom_h = IMG_H - TOP_H
    if bg_img is not None:
        photo = aspect_fit_fill(bg_img, (IMG_W, bottom_h))
        canvas.paste(photo, (0, TOP_H))
    else:
        ph = Image.new("RGB", (IMG_W, bottom_h), (28,32,45))
        canvas.paste(ph, (0, TOP_H))

    # Footer
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    footer = f"Auto-generated • {dt.datetime.now(ist).strftime('%d %b %Y, %I:%M %p IST')}"
    fw = draw.textlength(footer, font=meta)
    draw.text(((IMG_W - fw)/2, IMG_H - 48), footer, fill=(210,215,230), font=meta)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

# ---------- Main ----------
def main():
    ensure_dirs()
    state = load_state()

    # Manual override
    if os.path.exists(OVERRIDE_PATH):
        txt = open(OVERRIDE_PATH, "r", encoding="utf-8").read().strip()
        if txt:
            png = render_layout(txt, "Manual", "--:--", None)
            fname = f"{dt.datetime.now().strftime('%Y%m%d_%H%M')}_{slugify(txt)[:48]}_manual.png"
            path  = os.path.join(OUT_DIR, fname)
            open(path, "wb").write(png)
            state["last_id"] = "manual_" + hashlib.sha256(txt.encode()).hexdigest()[:16]
            save_state(state)
            print("[OK] Manual override image:", path)
            return

    entries = fetch_gn_entries()
    newest  = pick_newest(entries)
    if not newest:
        print("NO_NEWS_FOUND"); return

    pub = newest["published_at"]
    now = dt.datetime.now(dt.timezone.utc)
    age_min = (now - pub).total_seconds()/60.0 if pub else 9999
    if age_min > MAX_AGE_MINUTES:
        print(f"STALE_NEWS_SKIP age={age_min:.1f} min (> {MAX_AGE_MINUTES})"); return

    title, gnews_link = newest["title"], newest["link"]
    # Resolve Google News article to publisher page
    page_url, soup = resolve_canonical(gnews_link)
    publisher = publisher_from_link(page_url)

    nid = hashlib.sha256(f"{title}|{page_url}".encode()).hexdigest()[:16]
    if state.get("last_id") == nid:
        print("DUPLICATE_SKIP"); return

    # Find real article image on publisher page
    img_url = extract_best_image(page_url, soup)
    bg_img  = None
    if img_url and not is_rejected_image(img_url):
        bg_img = download_image(img_url)

    # Render
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    pub_local = pub.astimezone(ist).strftime("%I:%M %p")
    png = render_layout(title, publisher, pub_local, bg_img)

    fname = f"{dt.datetime.now().strftime('%Y%m%d_%H%M')}_{slugify(title)[:48]}_{nid[:8]}.png"
    fpath = os.path.join(OUT_DIR, fname)
    open(fpath, "wb").write(png)

    state.update({
        "last_id": nid,
        "last_title": title,
        "last_link": page_url,                 # store publisher URL
        "last_published_utc": pub.isoformat() if pub else "",
        "query": NEWS_QUERY or "top_stories",
        "max_age_minutes": MAX_AGE_MINUTES
    })
    save_state(state)

    print(f"[OK] Fresh image saved: {fpath}")
    print(f"[INFO] Title: {title}")
    print(f"[INFO] Publisher URL: {page_url}")
    print(f"[INFO] Image URL: {img_url if img_url else 'None'}")
    print(f"[INFO] Age: {age_min:.1f} minutes")

if __name__ == "__main__":
    main()