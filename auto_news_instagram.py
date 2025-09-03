#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Hybrid News → 9:16 image → GitHub Pages
Order: Moneycontrol (Top+Markets) -> Google News RSS -> Fallback
- Always prints verbose counts
- FORCE_GENERATE=1 => duplicate safeguard OFF (always make image)
- Saves full URL to meta.json + out/url.txt
"""

import os, sys, json, time, hashlib, datetime as dt
import feedparser
from urllib.parse import urlparse, urlencode
from PIL import Image, ImageDraw, ImageFont

# ---------- Settings ----------
MC_FEEDS = [
    "https://www.moneycontrol.com/rss/MCtopnews.xml",
    "https://www.moneycontrol.com/rss/marketreports.xml",
]
GOOGLE_QUERY = os.getenv("GOOGLE_QUERY", "Indian share market OR Sensex OR Nifty")
NEWS_WINDOW_HOURS = float(os.getenv("NEWS_WINDOW_HOURS", "6"))
OUTPUT_DIR   = os.getenv("OUTPUT_DIR", "out")
BRAND_NAME   = os.getenv("BRAND_NAME", "instanews")
BASE_URL_ENV = os.getenv("BASE_URL", "")
FORCE_GENERATE = os.getenv("FORCE_GENERATE", "1") == "1"  # default ON to ensure image

# ---------- Helpers ----------
def log(*a):
    print("[INFO]", *a)

def shorten(s, max_chars):
    return s if len(s) <= max_chars else s[:max_chars-1].rstrip() + "…"

def wrap(draw, text, font, max_width):
    words = text.split()
    lines, cur = [], []
    for w in words:
        test = " ".join(cur+[w])
        if draw.textlength(test, font=font) <= max_width:
            cur.append(w)
        else:
            if cur: lines.append(" ".join(cur))
            cur=[w]
    if cur: lines.append(" ".join(cur))
    return lines

def domain_from_url(url):
    try:
        return urlparse(url).netloc.replace("www.","")
    except:
        return ""

def cutoff_dt(hours):
    return dt.datetime.utcnow() - dt.timedelta(hours=hours)

# ---------- Fetchers ----------
def fetch_moneycontrol(feeds, hours):
    items = []
    cut = cutoff_dt(hours)
    for url in feeds:
        d = feedparser.parse(url)
        if getattr(d, "bozo", 0):
            log(f"Moneycontrol feed parse warning for {url}: bozo=1")
        got = 0
        for e in d.entries:
            title, link = e.get("title",""), e.get("link","")
            pp = e.get("published_parsed")
            pub = dt.datetime.fromtimestamp(time.mktime(pp)) if pp else dt.datetime.utcnow()
            if pub < cut: 
                continue
            items.append({"title": title, "link": link, "published": pub})
            got += 1
        log(f"MC fetch {url}: kept={got}")
    return items

def fetch_google(query, hours, lang="en", country="IN"):
    q = urlencode({"q": query})
    url = f"https://news.google.com/rss/search?{q}&hl={lang}-{country}&gl={country}&ceid={country}:{lang}"
    d = feedparser.parse(url)
    if getattr(d, "bozo", 0):
        log("Google feed parse warning: bozo=1")
    items, cut = [], cutoff_dt(hours)
    got = 0
    for e in d.entries:
        title, link = e.get("title",""), e.get("link","")
        pp = e.get("published_parsed")
        pub = dt.datetime.fromtimestamp(time.mktime(pp)) if pp else dt.datetime.utcnow()
        if pub < cut: 
            continue
        items.append({"title": title, "link": link, "published": pub})
        got += 1
    log(f"Google fetch kept={got}")
    return items

# ---------- Image ----------
def draw_card(headline, source, out_path, subtitle=None):
    W,H = 1080,1920
    img = Image.new("RGB",(W,H),(10,35,70))
    d = ImageDraw.Draw(img)

    for y in range(H):
        d.line([(0,y),(W,y)], fill=(10,int(70+80*(y/H)),140))

    font_bold="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font_reg ="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    f_brand=ImageFont.truetype(font_bold,64)
    f_date =ImageFont.truetype(font_reg,40)
    f_head =ImageFont.truetype(font_bold,80)
    f_sub  =ImageFont.truetype(font_reg,48)
    f_src  =ImageFont.truetype(font_reg,38)

    d.text((60,60), f"@{BRAND_NAME}", font=f_brand, fill=(255,255,255))
    date_str=dt.datetime.now().strftime("%d %b %Y, %I:%M %p")
    w_date=d.textlength(date_str,font=f_date)
    d.text((W-60-w_date,70), date_str,font=f_date,fill=(220,230,255))

    y=260; max_width=W-120
    head_lines = wrap(d, headline, f_head, max_width)
    if head_lines:
        box_h = (f_head.size+10)*len(head_lines) + 40
        d.rectangle([(50,y-30),(W-50,y-30+box_h)], fill=(0,0,0,120))
    for line in head_lines:
        d.text((80,y), line, font=f_head, fill=(255,255,255)); y += f_head.size+10

    if subtitle:
        y += 30
        for line in wrap(d, subtitle, f_sub, max_width):
            d.text((80,y), line, font=f_sub, fill=(220,230,255)); y += f_sub.size+10

    d.text((80,H-150), f"Source: {source}", font=f_src, fill=(200,210,235))
    d.text((W-280,H-150), f"@{BRAND_NAME}", font=f_src, fill=(200,210,235))

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path,"PNG")

def compute_base_url():
    if BASE_URL_ENV:
        return BASE_URL_ENV if BASE_URL_ENV.endswith("/") else BASE_URL_ENV+"/"
    repo = os.getenv("GITHUB_REPOSITORY","")
    if "/" in repo:
        owner, name = repo.split("/",1)
        return f"https://{owner}.github.io/{name}/"
    return ""

# ---------- Main ----------
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1) Try Moneycontrol
    items = fetch_moneycontrol(MC_FEEDS, hours=NEWS_WINDOW_HOURS)
    log("MC total kept:", len(items))

    # 2) If nothing, try Google
    if not items:
        log("MC empty, trying Google News…")
        items = fetch_google(GOOGLE_QUERY, hours=NEWS_WINDOW_HOURS)

    # 3) If still nothing and FORCE_GENERATE, create fallback
    if not items:
        if FORCE_GENERATE:
            log("No items from both sources. Creating fallback card.")
            now = dt.datetime.utcnow().strftime("%d %b %Y, %H:%M UTC")
            uid = hashlib.sha1(("fallback"+now).encode()).hexdigest()
            out_file = os.path.join(OUTPUT_DIR, f"{uid}.png")
            draw_card("No fresh news found", "—", out_file, subtitle=f"Auto update at {now}")
            base = compute_base_url()
            image_url = f"{base}{uid}.png" if base else ""
            with open(os.path.join(OUTPUT_DIR,"meta.json"),"w",encoding="utf-8") as f:
                json.dump({"uid":uid,"caption":"No fresh news","image_url":image_url}, f)
            if image_url:
                with open(os.path.join(OUTPUT_DIR,"url.txt"),"w") as f:
                    f.write(image_url)
            print("Generated (fallback):", out_file)
            if image_url: print("Final URL:", image_url)
            return
        else:
            log("No items; exiting.")
            return

    # pick the latest across all sources
    it = max(items, key=lambda x: x["published"])
    uid = hashlib.sha1((it["title"]+it["link"]).encode()).hexdigest()
    out_file = os.path.join(OUTPUT_DIR, f"{uid}.png")

    # duplicate safeguard (skip only when FORCE_GENERATE==0)
    if (not FORCE_GENERATE) and os.path.exists(out_file):
        log("Duplicate detected and FORCE_GENERATE=0 → skipping.")
        return

    headline = shorten(it["title"], 80)
    source = domain_from_url(it["link"]) or "news"
    draw_card(headline, source, out_file)

    base = compute_base_url()
    image_url = f"{base}{uid}.png" if base else ""
    caption = f"{headline}\n\nSource: {it['link']}\n\n#StockMarket #Sensex #Nifty"

    with open(os.path.join(OUTPUT_DIR,"meta.json"),"w",encoding="utf-8") as f:
        json.dump({"uid":uid,"caption":caption,"image_url":image_url}, f, ensure_ascii=False)
    if image_url:
        with open(os.path.join(OUTPUT_DIR,"url.txt"),"w") as f:
            f.write(image_url)

    print("Generated:", out_file)
    if image_url:
        print("Final URL:", image_url)
    print("Caption:\n", caption)

if __name__=="__main__":
    main()