#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Auto Share-Market News → Image → GitHub Pages
- Fetch latest stock-market news from Moneycontrol (Top + Market Reports feeds)
- Pick the latest (most recent) headline among both feeds
- Create 9:16 image card + caption
- Duplicate safeguard: skip if same UID exists
- meta.json + url.txt में पूरा image URL सेव करता है
"""

import os, json, time, hashlib, datetime as dt
import feedparser
from urllib.parse import urlparse
from PIL import Image, ImageDraw, ImageFont

# ---------- Settings ----------
FEEDS = [
    "https://www.moneycontrol.com/rss/MCtopnews.xml",       # Top News
    "https://www.moneycontrol.com/rss/marketreports.xml"    # Market Reports
]

NEWS_WINDOW_HOURS = float(os.getenv("NEWS_WINDOW_HOURS", "1"))
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "out")
BRAND_NAME = os.getenv("BRAND_NAME", "instanews")
BASE_URL_ENV = os.getenv("BASE_URL", "")

# ---------- Helpers ----------
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

# ---------- News fetch ----------
def fetch_from_feeds(feeds, hours=2):
    cutoff = dt.datetime.utcnow() - dt.timedelta(hours=hours)
    all_items = []
    for feed_url in feeds:
        d = feedparser.parse(feed_url)
        for e in d.entries:
            title, link = e.get("title",""), e.get("link","")
            published_parsed = e.get("published_parsed")
            pub = dt.datetime.fromtimestamp(time.mktime(published_parsed)) if published_parsed else dt.datetime.utcnow()
            if pub < cutoff:
                continue
            all_items.append({"title": title, "link": link, "published": pub})
    return all_items

# ---------- Image card ----------
def draw_card(headline, source, out_path):
    W,H = 1080,1920
    img = Image.new("RGB",(W,H),(10,35,70))
    d = ImageDraw.Draw(img)

    # gradient bg
    for y in range(H):
        d.line([(0,y),(W,y)], fill=(10,int(70+80*(y/H)),140))

    # fonts
    font_bold="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font_reg ="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    f_brand=ImageFont.truetype(font_bold,64)
    f_date =ImageFont.truetype(font_reg,40)
    f_head =ImageFont.truetype(font_bold,80)
    f_src  =ImageFont.truetype(font_reg,38)

    # top bar
    d.text((60,60), f"@{BRAND_NAME}", font=f_brand, fill=(255,255,255))
    date_str=dt.datetime.now().strftime("%d %b %Y, %I:%M %p")
    w_date=d.textlength(date_str,font=f_date)
    d.text((W-60-w_date,70), date_str,font=f_date,fill=(220,230,255))

    # headline
    y=260; max_width=W-120
    head_lines = wrap(d, headline, f_head, max_width)
    if head_lines:
        box_h = (f_head.size+10)*len(head_lines) + 40
        d.rectangle([(50,y-30),(W-50,y-30+box_h)], fill=(0,0,0,120))
    for line in head_lines:
        d.text((80,y), line, font=f_head, fill=(255,255,255))
        y += f_head.size+10

    # footer
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
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    items = fetch_from_feeds(FEEDS, hours=NEWS_WINDOW_HOURS)
    if not items:
        print("No news found in window; exiting.")
        return

    # ✅ सबसे latest चुनो (Top + Market दोनों से)
    it = max(items, key=lambda x: x["published"])

    uid = hashlib.sha1((it["title"]+it["link"]).encode()).hexdigest()
    out_file = os.path.join(OUTPUT_DIR,f"{uid}.png")

    # ✅ Duplicate safeguard
    if os.path.exists(out_file):
        print("No new news found in this window, skipping.")
        return

    headline = shorten(it["title"],80)
    source = domain_from_url(it["link"])
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