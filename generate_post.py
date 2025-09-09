#!/usr/bin/env python3
"""
Free image-only generator:
- Fetches latest headline from Moneycontrol RSS (or use --headline)
- Renders an Instagram portrait poster (1080x1350) with clean styling
- Saves PNG to ./out/ and prints the file path

Usage:
  python generate_post.py
  python generate_post.py --headline "Your custom headline"
  python generate_post.py --rss "https://www.moneycontrol.com/rss/MCtopnews.xml" --output out/
"""

import os, io, argparse, datetime as dt, hashlib
import feedparser
from slugify import slugify
from PIL import Image, ImageDraw, ImageFont

DEFAULT_RSS = "https://www.moneycontrol.com/rss/MCtopnews.xml"
IMG_W, IMG_H = 1080, 1350  # Instagram portrait
OUT_DIR = "out"
MAX_LEN = 160  # poster text wrap (not IG caption)

def fetch_latest_headline(rss_url: str) -> str:
    d = feedparser.parse(rss_url)
    if not d.entries:
        raise RuntimeError("No entries found in RSS.")
    return d.entries[0].title.strip()

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
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines

def draw_poster(headline: str) -> bytes:
    img = Image.new("RGB", (IMG_W, IMG_H), (18, 22, 33))
    draw = ImageDraw.Draw(img)

    # header bar
    draw.rectangle((0, 0, IMG_W, 260), fill=(34, 40, 60))

    # try fonts
    try:
        h1 = ImageFont.truetype("DejaVuSans-Bold.ttf", 64)
        body = ImageFont.truetype("DejaVuSans.ttf", 42)
        tag  = ImageFont.truetype("DejaVuSans.ttf", 28)
    except:
        h1 = ImageFont.load_default()
        body = ImageFont.load_default()
        tag = ImageFont.load_default()

    # heading text
    heading = "MARKET UPDATE"
    w = draw.textlength(heading, font=h1)
    draw.text(((IMG_W - w) / 2, 110), heading, fill=(240, 245, 255), font=h1)

    # decorative rounded box
    draw.rounded_rectangle((40, 270, IMG_W - 40, IMG_H - 180),
                           radius=36, outline=(80, 90, 120), width=3)

    # headline text (wrapped)
    margin = 90
    text = shorten(headline, MAX_LEN)
    lines = wrap_lines(draw, text, body, IMG_W - 2 * margin)
    y = 360
    for ln in lines:
        wln = draw.textlength(ln, font=body)
        draw.text(((IMG_W - wln) / 2, y), ln, fill=(235, 238, 245), font=body)
        y += 64

    # footer
    footer = f"Auto-generated • {dt.datetime.now().strftime('%d %b %Y, %I:%M %p')}"
    w2 = draw.textlength(footer, font=tag)
    draw.text(((IMG_W - w2) / 2, IMG_H - 120), footer, fill=(210, 215, 230), font=tag)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--headline", type=str, help="Use your own headline instead of RSS")
    ap.add_argument("--rss", type=str, default=DEFAULT_RSS, help="RSS feed URL")
    ap.add_argument("--output", type=str, default=OUT_DIR, help="Output directory")
    args = ap.parse_args()

    os.makedirs(args.output, exist_ok=True)

    headline = args.headline or fetch_latest_headline(args.rss)

    key = hashlib.sha256(headline.encode()).hexdigest()[:10]
    fname = f"{dt.datetime.now().strftime('%Y%m%d_%H%M')}_{slugify(headline)[:48]}_{key}.png"
    fpath = os.path.join(args.output, fname)

    png = draw_poster(headline)
    with open(fpath, "wb") as f:
        f.write(png)

    print(f"[OK] Image saved: {fpath}")

if __name__ == "__main__":
    main()