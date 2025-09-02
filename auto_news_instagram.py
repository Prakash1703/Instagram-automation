#!/usr/bin/env python3
"""
Auto Share-Market News → Image → Instagram
- Fetches latest stock market news (Google News RSS)
- Creates a 9:16 image card
- Caption + source credit
- For free setup: image is hosted via GitHub Pages, then posted to Instagram
"""

import os, json, time, hashlib, datetime as dt
from urllib.parse import urlencode, urlparse
import feedparser
from PIL import Image, ImageDraw, ImageFont
import requests

# ---------- Settings ----------
NEWS_QUERY = os.getenv("NEWS_QUERY", "Indian share market OR Sensex OR Nifty")
NEWS_WINDOW_HOURS = int(os.getenv("NEWS_WINDOW_HOURS", "12"))
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "out")
BRAND_NAME = os.getenv("BRAND_NAME", "instanews")

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
            lines.append(" ".join(cur)); cur=[w]
    if cur: lines.append(" ".join(cur))
    return lines

def domain_from_url(url):
    try: return urlparse(url).netloc.replace("www.","")
    except: return ""

# ---------- News fetch ----------
def fetch_google_news(query, hours=12, lang="en", country="IN"):
    q = urlencode({"q": query})
    feed_url = f"https://news.google.com/rss/search?{q}&hl={lang}-{country}&gl={country}&ceid={country}:{lang}"
    d = feedparser.parse(feed_url)
    items, cutoff = [], dt.datetime.utcnow() - dt.timedelta(hours=hours)
    for e in d.entries:
        title, link = e.get("title",""), e.get("link","")
        published_parsed = e.get("published_parsed")
        pub = dt.datetime.fromtimestamp(time.mktime(published_parsed)) if published_parsed else dt.datetime.utcnow()
        if pub < cutoff: continue
        items.append({"title": title, "link": link, "published": pub.isoformat()})
    return items

# ---------- Image card ----------
def draw_card(headline, highlight, source, out_path="card.png"):
    W,H=1080,1920
    img=Image.new("RGB",(W,H),(10,35,70))
    d=ImageDraw.Draw(img)
    for y in range(H): d.line([(0,y),(W,y)], fill=(10,int(70+80*(y/H)),140))

    # fonts
    font_bold="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font_reg="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    f_brand=ImageFont.truetype(font_bold,64)
    f_date=ImageFont.truetype(font_reg,40)
    f_head=ImageFont.truetype(font_bold,80)
    f_sub=ImageFont.truetype(font_reg,48)
    f_src=ImageFont.truetype(font_reg,38)

    # top bar
    d.text((60,60), f"@{BRAND_NAME}", font=f_brand, fill=(255,255,255))
    date_str=dt.datetime.now().strftime("%d %b %Y, %I:%M %p")
    w_date=d.textlength(date_str,font=f_date)
    d.text((W-60-w_date,70), date_str,font=f_date,fill=(220,230,255))

    # headline
    y=260; max_width=W-120
    for line in wrap(d,headline,f_head,max_width):
        d.text((80,y),line,font=f_head,fill=(255,255,255)); y+=f_head.size+10
    y+=30
    for line in wrap(d,highlight,f_sub,max_width):
        d.text((80,y),line,font=f_sub,fill=(220,230,255)); y+=f_sub.size+10

    # source
    d.text((80,H-150),f"Source: {source}",font=f_src,fill=(200,210,235))
    d.text((W-280,H-150),f"@{BRAND_NAME}",font=f_src,fill=(200,210,235))

    os.makedirs(os.path.dirname(out_path),exist_ok=True)
    img.save(out_path,"PNG")
    return out_path

# ---------- Main ----------
def main():
    os.makedirs(OUTPUT_DIR,exist_ok=True)
    items=fetch_google_news(NEWS_QUERY,hours=NEWS_WINDOW_HOURS)
    if not items: 
        print("No news found."); return

    # pick first item
    it=items[0]
    uid=hashlib.sha1((it["title"]+it["link"]).encode()).hexdigest()
    headline=shorten(it["title"],80)
    highlight="Market update in brief."
    source=domain_from_url(it["link"])
    out_file=os.path.join(OUTPUT_DIR,f"{uid}.png")

    draw_card(headline,highlight,source,out_file)
    caption=f"{headline}\n\n{highlight}\n\nSource: {it['link']}\n\n#StockMarket #Sensex #Nifty"

    # save meta.json (for GitHub Actions to pick caption + URL)
    with open(os.path.join(OUTPUT_DIR,"meta.json"),"w",encoding="utf-8") as f:
        json.dump({"uid":uid,"caption":caption},f,ensure_ascii=False)

    print("Generated:",out_file)
    print("Caption:\n",caption)

if __name__=="__main__":
    main()
