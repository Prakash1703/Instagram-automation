#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google News → Latest only → Poster (Top text + bottom news photo)

Features:
- Fresh-only (MAX_AGE_MINUTES), duplicate-safe (out/last_id.json robust)
- Google News link → publisher URL (canonical)
- Image candidates with strong priority:
    1) Publisher page: og/twitter/twitter:src/JSON-LD/<img>
    1b) AMP page: largest <amp-img>/<img>
    2) RSS media thumbnail
    2b) GDELT Doc API image (free, no key)
    3) Google News page og/twitter/JSON-LD
  -> Prefer Publisher/AMP > RSS/GDELT > GNews
  -> Skip branding/logo/placeholder; tiny images ignored
- No URL printed on poster (only “Publisher • Local Time”)
"""

import os, io, json, hashlib, datetime as dt
from urllib.parse import quote_plus, urlparse, urljoin
from email.utils import parsedate_to_datetime

import feedparser, requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageOps
from slugify import slugify

# ---------------- Config ----------------
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

UA = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9"
}

BAD_IMG_HINTS = ("logo", "icon", "placeholder", "default", "sprite", "branding")

# ---------------- Utils ----------------
def ensure_dirs():
    os.makedirs(OUT_DIR, exist_ok=True)

def load_state():
    """Return {} if state file missing/empty/corrupt."""
    try:
        if not os.path.exists(STATE_PATH):
            return {}
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = f.read().strip()
            if not data:
                return {}
            return json.loads(data)
    except Exception:
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

def looks_generic_url(u: str) -> bool:
    u = (u or "").lower()
    return any(h in u for h in BAD_IMG_HINTS)

def host_of(u: str) -> str:
    try:
        return urlparse(u).netloc.lower()
    except Exception:
        return ""

def is_gnews_logo(u: str) -> bool:
    """Skip Google News branding/logo images on news.google.com pages."""
    u = (u or "").lower()
    h = host_of(u)
    if "news.google.com" in h:
        if "/images/branding/" in u or "news_icon" in u or "logo" in u:
            return True
    return False

# ---------------- Google News fetch ----------------
def fetch_gn_entries(max_items=12):
    url = GN_SEARCH(NEWS_QUERY) if NEWS_QUERY else GN_TOP
    d = feedparser.parse(url)
    entries = []
    for e in d.entries[:max_items]:
        title = (e.get("title") or "").strip()
        link  = (e.get("link")  or "").strip()
        pub   = parse_dt(e.get("published") or e.get("updated") or e.get("pubDate"))
        media_url = None
        if "media_content" in e and e.media_content:
            media_url = e.media_content[0].get("url")
        if not media_url and "media_thumbnail" in e and e.media_thumbnail:
            media_url = e.media_thumbnail[0].get("url")
        entries.append({
            "title": title, "link": link, "published_at": pub,
            "rss_media_url": media_url
        })
    return entries

def pick_newest(entries):
    valid = [x for x in entries if x["published_at"]]
    if not valid: return None
    valid.sort(key=lambda x: x["published_at"], reverse=True)
    return valid[0]

# ---------------- Resolve & extract images ----------------
def resolve_canonical(url: str, timeout=12):
    """Follow Google News redirect → publisher article URL; return (final_url, soup)."""
    try:
        r = requests.get(url, headers=UA, timeout=timeout, allow_redirects=True)
        final_url = r.url
        soup = BeautifulSoup(r.text, "html.parser")
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

def _jsonld_pick_image(obj, base_url):
    """Walk JSON-LD to find image/thumbnailUrl urls."""
    def norm(u):
        return urljoin(base_url, u) if u else None
    if isinstance(obj, list):
        for it in obj:
            u = _jsonld_pick_image(it, base_url)
            if u: return u
        return None
    if isinstance(obj, dict):
        for key in ("image", "thumbnailUrl", "thumbnailURL"):
            if key in obj:
                v = obj[key]
                if isinstance(v, str):
                    return norm(v)
                if isinstance(v, dict) and v.get("url"):
                    return norm(v["url"])
                if isinstance(v, list):
                    for it in v:
                        if isinstance(it, str):
                            return norm(it)
                        if isinstance(it, dict) and it.get("url"):
                            return norm(it["url"])
        for key in ("mainEntityOfPage", "primaryImageOfPage"):
            if key in obj:
                u = _jsonld_pick_image(obj[key], base_url)
                if u: return u
        if "@graph" in obj:
            return _jsonld_pick_image(obj["@graph"], base_url)
    return None

def extract_og_like(page_url: str, soup: BeautifulSoup | None, timeout=12):
    """Try og/twitter/twitter:src/link rel=image_src/JSON-LD/first <img> on a page."""
    def from_soup(sp: BeautifulSoup):
        if not sp: return None
        for attr, val in (
            ("property","og:image"),
            ("property","og:image:secure_url"),
            ("name","twitter:image"),
            ("property","twitter:image"),
            ("name","twitter:image:src"),
        ):
            tag = sp.find("meta", {attr: val})
            if tag and tag.get("content"):
                return urljoin(page_url, tag["content"])
        tag = sp.find("link", rel="image_src")
        if tag and tag.get("href"):
            return urljoin(page_url, tag["href"])
        for node in sp.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(node.string or node.text or "")
            except Exception:
                continue
            u = _jsonld_pick_image(data, page_url)
            if u: return u
        img = sp.find("img")
        if img and img.get("src"):
            return urljoin(page_url, img["src"])
        return None

    img_url = from_soup(soup)
    if img_url:
        return img_url
    try:
        r = requests.get(page_url, headers=UA, timeout=timeout)
        if r.status_code == 200:
            sp = BeautifulSoup(r.text, "html.parser")
            return from_soup(sp)
    except Exception:
        pass
    return None

def extract_from_amp(page_url: str, timeout=10):
    """Find AMP page then pull largest <amp-img>/<img>."""
    try:
        r = requests.get(page_url, headers=UA, timeout=timeout)
        if r.status_code != 200: 
            return None
        sp = BeautifulSoup(r.text, "html.parser")
        amp = sp.find("link", rel=lambda v: v and "amphtml" in v)
        if not amp or not amp.get("href"):
            return None
        amp_url = urljoin(page_url, amp["href"])

        ra = requests.get(amp_url, headers=UA, timeout=timeout)
        if ra.status_code != 200:
            return None
        sa = BeautifulSoup(ra.text, "html.parser")

        cand = []
        for tag in sa.find_all(["amp-img", "img"]):
            src = None
            if tag.get("srcset"):
                parts = [p.strip().split(" ")[0] for p in tag["srcset"].split(",") if p.strip()]
                if parts:
                    src = parts[-1]
            if not src:
                src = tag.get("src")
            if src:
                cand.append(urljoin(amp_url, src))

        for u in reversed(cand):
            if looks_generic_url(u) or is_gnews_logo(u):
                continue
            img = download_image(u)
            if img and img.size[0] >= 300 and img.size[1] >= 200:
                return u
    except Exception:
        return None
    return None

def extract_gnews_thumbnail(gnews_url: str, timeout=10):
    """Fallback: use og/twitter/JSON-LD from the Google News article page itself."""
    try:
        r = requests.get(gnews_url, headers=UA, timeout=timeout)
        if r.status_code != 200: return None
        sp = BeautifulSoup(r.text, "html.parser")
        return extract_og_like(gnews_url, sp, timeout=0)
    except Exception:
        return None

def fetch_gdelt_image(query_title: str, timeout=10):
    """Free fallback: GDELT Doc API image for matching headline."""
    try:
        q = quote_plus(query_title)
        url = f"https://api.gdeltproject.org/api/v2/doc/doc?query={q}&mode=ArtList&maxrecords=10&format=json"
        r = requests.get(url, headers=UA, timeout=timeout)
        if r.status_code != 200:
            return None
        data = r.json()
        arts = data.get("articles") or []
        for a in arts:
            u = a.get("image")
            if not u or looks_generic_url(u) or is_gnews_logo(u):
                continue
            img = download_image(u)
            if img and img.size[0] >= 300 and img.size[1] >= 200:
                return u
    except Exception:
        return None
    return None

def download_image(url: str, timeout=12):
    try:
        if not url or looks_generic_url(url) or is_gnews_logo(url):
            return None
        r = requests.get(url, timeout=timeout, stream=True, headers=UA)
        if r.status_code != 200:
            return None
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception:
        return None

def aspect_fit_fill(img: Image.Image, size):
    return ImageOps.fit(ImageOps.exif_transpose(img), size, method=Image.LANCZOS, centering=(0.5,0.5))

def pick_best_image(candidates):
    """
    candidates: list of tuples [(url, 'publisher'|'rss'|'gnews'), ...]
    Prefer publisher > rss > gnews, pick largest per source.
    Penalize google-hosted images so publisher wins when comparable.
    """
    best = {"publisher": (0, None), "rss": (0, None), "gnews": (0, None)}

    for url, src in candidates:
        if not url:
            continue
        if looks_generic_url(url) or is_gnews_logo(url):
            continue

        img = download_image(url)
        if img is None:
            continue

        w, h = img.size
        if w < 300 or h < 200:
            continue

        area = w * h
        hst = host_of(url)
        penalty = 0.6 if ("googleusercontent" in hst or "gstatic" in hst or "news.google.com" in hst) else 1.0
        score = area * penalty

        best_area, _ = best.get(src, (0, None))
        if score > best_area:
            best[src] = (score, img)

    for src in ("publisher", "rss", "gnews"):
        if best[src][1] is not None:
            return best[src][1]
    return None

# ---------------- Typography & layout ----------------
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

    # TOP band
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

    # BOTTOM image
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

    buf = io.BytesIO(); canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

# ---------------- Main ----------------
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

    # 1) Publisher page + rich extraction
    page_url, soup = resolve_canonical(gnews_link)
    publisher      = publisher_from_link(page_url)
    pub_img_url    = extract_og_like(page_url, soup)

    # 1b) AMP page (treat as publisher-quality)
    amp_img_url    = extract_from_amp(page_url)

    # 2) RSS media thumbnail
    rss_img_url    = newest.get("rss_media_url")

    # 2b) GDELT fallback by title
    gdelt_img_url  = fetch_gdelt_image(title)

    # 3) Google News page fallback
    gnews_img_url  = extract_gnews_thumbnail(gnews_link)

    # Priority-based pick: Publisher/AMP > RSS/GDELT > GNews
    candidates = [
        (pub_img_url,   "publisher"),
        (amp_img_url,   "publisher"),
        (rss_img_url,   "rss"),
        (gdelt_img_url, "rss"),
        (gnews_img_url, "gnews"),
    ]
    bg_img = pick_best_image(candidates)

    # Render poster
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    pub_local = pub.astimezone(ist).strftime("%I:%M %p")
    png = render_layout(title, publisher, pub_local, bg_img)

    nid = hashlib.sha256((title + page_url).encode()).hexdigest()[:16]
    fname = f"{dt.datetime.now().strftime('%Y%m%d_%H%M')}_{slugify(title)[:48]}_{nid[:8]}.png"
    fpath = os.path.join(OUT_DIR, fname)
    open(fpath, "wb").write(png)

    # Save state
    state.update({
        "last_id": nid,
        "last_title": title,
        "last_link": page_url,
        "last_published_utc": pub.isoformat() if pub else "",
        "query": NEWS_QUERY or "top_stories",
        "max_age_minutes": MAX_AGE_MINUTES
    })
    save_state(state)

    print(f"[OK] Fresh image saved: {fpath}")
    print(f"[INFO] Title: {title}")
    print(f"[INFO] Publisher URL: {page_url}")
    print(f"[INFO] Img candidates:")
    print(f"  publisher: {pub_img_url}")
    print(f"  amp:       {amp_img_url}")
    print(f"  rss:       {rss_img_url}")
    print(f"  gdelt:     {gdelt_img_url}")
    print(f"  gnews:     {gnews_img_url}")
    print(f"[INFO] Age: {age_min:.1f} minutes")

if __name__ == "__main__":
    main()