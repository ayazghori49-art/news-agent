#!/usr/bin/env python3
"""Demo video renderer for AI News Digest v2.0 (SerpApi India Hackathon 2026).
Draws the Flask app's UI frame-by-frame with Pillow (matching templates/index.html)
and pipes raw frames to ffmpeg -> 720x1280 H.264 mp4, <3 min.
"""
import math, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 720, 1280, 30

# --- palette from index.html :root ---
BG      = (13, 17, 23)      # --bg
CARD    = (22, 27, 34)      # --card
BORDER  = (48, 54, 61)      # --border
TEXT    = (230, 237, 243)   # --text
MUTED   = (139, 148, 158)   # --muted
ACCENT  = (88, 166, 255)    # --accent
LIVE    = (63, 185, 80)     # --live
SAMPLE  = (210, 153, 34)    # --sample
DARK    = (13, 17, 23)

DEJAVU      = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
DEJAVU_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
EMOJI_FONT  = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"

_font_cache = {}
def font(bold, size):
    key = (bold, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(DEJAVU_BOLD if bold else DEJAVU, size)
    return _font_cache[key]

_emoji_cache = {}
_EMOJI_FIXED = 109  # NotoColorEmoji is a fixed-strike CBDT font: render at 109px, then scale

def emoji_image(chunk, size):
    """Render an emoji chunk at `size` px height -> RGBA image."""
    key = (chunk, size)
    if key not in _emoji_cache:
        f = ImageFont.truetype(EMOJI_FONT, _EMOJI_FIXED)
        tmp = Image.new("RGBA", (_EMOJI_FIXED * 3, _EMOJI_FIXED * 3), (0, 0, 0, 0))
        d = ImageDraw.Draw(tmp)
        d.text((20, 20), chunk, font=f, embedded_color=True)
        bbox = tmp.getbbox()
        glyph = tmp.crop(bbox) if bbox else tmp.crop((0, 0, 1, 1))
        ratio = size / glyph.height
        glyph = glyph.resize((max(1, int(glyph.width * ratio)), max(1, size)), Image.LANCZOS)
        _emoji_cache[key] = glyph
    return _emoji_cache[key]

def is_emoji(ch):
    o = ord(ch)
    return o >= 0x1F000 or 0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF or o in (0xFE0F,)

def runs(s):
    """Split into (is_emoji, chunk) runs."""
    out, cur, cur_e = [], "", None
    for ch in s:
        e = is_emoji(ch)
        if cur_e is None or e == cur_e:
            cur += ch; cur_e = e
        else:
            out.append((cur_e, cur)); cur, cur_e = ch, e
    if cur: out.append((cur_e, cur))
    return out

def emoji_run_width(chunk, size):
    return emoji_image(chunk, size).width

def mixed_width(draw, s, size, bold=False):
    w = 0
    for e, chunk in runs(s):
        if e:
            w += emoji_run_width(chunk, size)
        else:
            w += draw.textlength(chunk, font=font(bold, size))
    return w

def draw_mixed(draw, xy, s, size, color, bold=False, anchor_left=True):
    """Draw text mixing DejaVu + color emoji (pasted). anchor via cx when not left."""
    x, y = xy
    if not anchor_left:
        x = x - mixed_width(draw, s, size, bold) / 2
    for e, chunk in runs(s):
        if e:
            g = emoji_image(chunk, size)
            # anchor emoji vertically to text baseline-ish: align glyph box to font ascent
            asc, _ = font(bold, size).getmetrics()
            draw._image.paste(g, (int(x), int(y + asc - g.height)), g)
            x += g.width
        else:
            f = font(bold, size)
            draw.text((x, y), chunk, font=f, fill=color)
            x += draw.textlength(chunk, font=f)

def centered(draw, cx, y, s, size, color, bold=False):
    draw_mixed(draw, (cx, y), s, size, color, bold, anchor_left=False)

def wrap(draw, text, size, max_w, bold=False):
    f = font(bold, size)
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if draw.textlength(t, font=f) <= max_w:
            cur = t
        else:
            if cur: lines.append(cur)
            cur = wd
    if cur: lines.append(cur)
    return lines

def line_h(size, factor=1.32):
    return int(size * factor)

# ---------------- UI primitives ----------------
def header(draw, subtitle=True):
    centered(draw, W/2, 34, "📰 AI News Digest", 54, TEXT, bold=True)
    # accent underline on "Digest" is hard with mixed runs; add accent bar
    draw.rectangle([W/2-120, 108, W/2+120, 112], fill=ACCENT)
    if subtitle:
        centered(draw, W/2, 122, "Live AI news, 1-2 line Hinglish summary ke saath", 24, MUTED)
    draw.line([0, 164, W, 164], fill=BORDER, width=2)

def searchbar(draw, query="", placeholder=True, active=False):
    x0, y0, x1, y1 = 24, 182, 592, 246
    draw.rounded_rectangle([x0, y0, x1, y1], radius=14, fill=CARD, outline=ACCENT if active else BORDER, width=2)
    if query:
        draw_mixed(draw, (x0+18, y0+16), query, 28, TEXT)
        tw = mixed_width(draw, query, 28)
        if active and (int(__import__('time').perf_counter()*2.5) % 2 == 0):
            draw.rectangle([x0+18+tw+4, y0+18, x0+18+tw+8, y0+46], fill=ACCENT)
    elif placeholder:
        draw_mixed(draw, (x0+18, y0+16), "Search news… e.g. AI robots", 28, MUTED)
    bx0, bx1 = 604, 696
    draw.rounded_rectangle([bx0, y0, bx1, y1], radius=14, fill=ACCENT)
    g = emoji_image("🔍", 34)
    draw._image.paste(g, (int((bx0+bx1-g.width)/2), int((y0+y1-g.height)/2)), g)

def topics(draw, active="ai"):
    labels = ["AI", "STARTUPS", "TECH"]
    widths = []
    tmp = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    for l in labels:
        widths.append(tmp.textlength(l, font=font(True, 26)) + 52)
    total = sum(widths) + 16*2
    x = (W - total) / 2
    y = 262
    for l, w in zip(labels, widths):
        is_a = l.lower() == active
        fill = ACCENT if is_a else CARD
        draw.rounded_rectangle([x, y, x+w, y+52], radius=26, fill=fill,
                               outline=ACCENT if is_a else BORDER, width=2)
        draw.text((x + (w - tmp.textlength(l, font=font(True, 26)))/2, y+11),
                  l, font=font(True, 26), fill=DARK if is_a else TEXT)
        x += w + 16

def status_badge(draw, live, label_text):
    # e.g. ● SAMPLE demo mode · Topic: AI
    y = 332
    badge = "● LIVE" if live else "● SAMPLE"
    bc = LIVE if live else SAMPLE
    tmp = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    bw = tmp.textlength(badge, font=font(True, 22)) + 24
    bx0 = (W - (bw + 12 + tmp.textlength(label_text, font=font(False, 22)))) / 2
    draw.rounded_rectangle([bx0, y, bx0+bw, y+36], radius=8, outline=bc, width=2)
    draw.text((bx0+12, y+5), badge, font=font(True, 22), fill=bc)
    draw.text((bx0+bw+12, y+5), label_text, font=font(False, 22), fill=MUTED)

def news_card(draw, y, title, source, date, summary, max_h=None):
    x0, x1 = 24, 696
    inner = x1 - x0 - 40
    ycur = y + 20
    for ln in wrap(draw, title, 28, inner, bold=True):
        draw.text((x0+20, ycur), ln, font=font(True, 28), fill=TEXT)
        ycur += line_h(28)
    ycur += 10
    draw.text((x0+20, ycur), f"{source} · {date}", font=font(False, 20), fill=MUTED)
    ycur += line_h(20) + 14
    slines = wrap(draw, summary, 24, inner - 28)
    sh = len(slines) * line_h(24) + 28
    draw.rounded_rectangle([x0+20, ycur, x1-20, ycur+sh], radius=8, fill=BG)
    draw.rectangle([x0+20, ycur, x0+24, ycur+sh], fill=ACCENT)
    sy = ycur + 14
    for ln in slines:
        draw.text((x0+20+28, sy), ln, font=font(False, 24), fill=TEXT)
        sy += line_h(24)
    ycur += sh + 14
    draw.text((x0+20, ycur), "Read more →", font=font(True, 22), fill=ACCENT)
    ycur += line_h(22) + 20
    draw.rounded_rectangle([x0, y, x1, ycur], radius=14, outline=BORDER, width=2)
    # card bg under border
    return ycur

def card_frame(draw, y, title, source, date, summary):
    x0, x1 = 24, 696
    inner = x1 - x0 - 40
    tl = wrap(draw, title, 28, inner, bold=True)
    sl = wrap(draw, summary, 24, inner - 28)
    h = 20 + len(tl)*line_h(28) + 10 + line_h(20) + 14 + (len(sl)*line_h(24)+28) + 14 + line_h(22) + 20
    draw.rounded_rectangle([x0, y, x1, y+h], radius=14, fill=CARD)
    news_card(draw, y, title, source, date, summary)
    return y + h

def spinner(draw, cx, cy, angle_deg, r=30, w=7):
    draw.arc([cx-r, cy-r, cx+r, cy+r], 0, 360, fill=BORDER, width=w)
    draw.arc([cx-r, cy-r, cx+r, cy+r], angle_deg, angle_deg+110, fill=ACCENT, width=w)

def footer(draw):
    draw.rectangle([0, H-128, W, H], fill=BG)
    draw.line([0, H-120, W, H-120], fill=BORDER, width=2)
    centered(draw, W/2, H-104, "Built for SerpApi India Hackathon 2026 — Research & AI track", 21, MUTED)
    centered(draw, W/2, H-72, "News: SerpApi Google News API · Summaries: Google Gemini", 21, MUTED)

# ---------------- scene frames ----------------
def blank():
    return Image.new("RGB", (W, H), BG)

def fade_from_black(img, i, n):
    if i < n:
        a = i / n
        black = Image.new("RGB", img.size, (0, 0, 0))
        return Image.blend(black, img, a)
    return img

def fade_to_black(img, i, total, n):
    if i >= total - n:
        a = (total - 1 - i) / n
        black = Image.new("RGB", img.size, (0, 0, 0))
        return Image.blend(black, img, max(a, 0))
    return img

# ---- SEG 1: title card (3s) ----
def seg_title(i, n):
    im = blank(); d = ImageDraw.Draw(im)
    centered(d, W/2, 430, "📰", 110, TEXT)
    centered(d, W/2, 560, "AI News Digest", 76, TEXT, bold=True)
    d.rectangle([W/2-140, 668, W/2+140, 672], fill=ACCENT)
    centered(d, W/2, 700, "SerpApi India Hackathon 2026", 36, ACCENT, bold=True)
    centered(d, W/2, 762, "Research & AI track", 30, MUTED)
    im = fade_from_black(im, i, 10)
    im = fade_to_black(im, i, n, 10)
    return im

# sample headlines + Hinglish summaries (app-style, from sample_news.json)
HOME_CARDS = [
    ("Google rolls out Gemini 3 across Workspace apps in India with Hindi support",
     "Google Blog", "10/05/2026",
     "Google ne Gemini 3 ko India me Workspace apps me launch kar diya — poora Hindi support ke saath."),
    ("OpenAI launches affordable AI coding assistant tier aimed at Indian startups",
     "TechCrunch", "10/04/2026",
     "OpenAI ne Indian startups ke liye sasta AI coding plan nikala — early-stage teams ka budget dhyaan me rakhkar."),
    ("Bengaluru AI startup Krutrim raises $200M to build Indic language models",
     "YourStory", "10/04/2026",
     "Krutrim ne $200M raise kiye Indic language models banane ke liye — Bengaluru se badi khabar."),
]
SEARCH_CARDS = [
    ("Humanoid robots enter Indian factories — pilots start in Pune and Chennai",
     "Mint", "10/04/2026",
     "Pune aur Chennai ki factories me humanoid robots ke pilot shuru — assembly line pe AI helpers kaam karenge."),
    ("IIT Bombay builds low-cost AI robot for rural classrooms",
     "Indian Express", "10/03/2026",
     "IIT Bombay ne gaon ke schools ke liye sasta AI robot banaya — bachchon ki padhai me madad karega."),
]

# ---- SEG 2: app home (8s) ----
def seg_home(i, n, scroll=0):
    im = blank(); d = ImageDraw.Draw(im)
    header(d)
    searchbar(d)
    topics(d, active="ai")
    status_badge(d, False, "demo mode · Topic: AI")
    y = 386 - scroll
    for c in HOME_CARDS:
        y = card_frame(d, y, *c) + 18
    d.rectangle([0, 366, W, 390], fill=BG)  # clip: cards slide under header
    footer(d)
    return im

# ---- SEG 3: custom search (12s) ----
QUERY = "ai robots"
def seg_search(i, n):
    # phase A: typing (0-2.6s), phase B: loading (2.6-4.6s), phase C: results (4.6-12s)
    im = blank(); d = ImageDraw.Draw(im)
    header(d)
    if i < 78:  # typing
        k = min(len(QUERY), int(i / 78 * len(QUERY) * 1.15))
        searchbar(d, query=QUERY[:k], active=True)
        topics(d, active="ai")
        status_badge(d, False, "demo mode · Topic: AI")
        y = 386
        for c in HOME_CARDS[:2]:
            y = card_frame(d, y, *c) + 18
    elif i < 138:  # loading
        searchbar(d, query=QUERY, active=False)
        topics(d, active="")
        spinner(d, W/2, 560, (i-78)*15)
        centered(d, W/2, 620, f'"{QUERY}" search ho raha hai…', 28, MUTED)
    else:  # results
        searchbar(d, query=QUERY, active=False)
        topics(d, active="")
        status_badge(d, False, f'demo mode · Search: "{QUERY}"')
        y = 386
        for c in SEARCH_CARDS:
            y = card_frame(d, y, *c) + 18
    footer(d)
    return im

# ---- SEG 4: states montage (8s) -> LIVE / error / empty ----
def seg_states(i, n):
    im = blank(); d = ImageDraw.Draw(im)
    third = n // 3
    if i < third:  # LIVE badge        header(d)
        searchbar(d)
        topics(d, active="ai")
        status_badge(d, True, "via SerpApi · Topic: AI")
        card_frame(d, 386, *HOME_CARDS[0])
        centered(d, W/2, 1180, "LIVE mode — SerpApi se taaza news", 24, MUTED)
    elif i < 2*third:  # error state
        g = emoji_image("⚠️", 96)
        d._image.paste(g, (int(W/2 - g.width/2), 380), g)
        for j, ln in enumerate(wrap(d, "Live news unavailable — is mahine ka SerpApi quota khatm ho gaya. Sample headlines dikha rahe hain.", 27, 600)):
            centered(d, W/2, 520 + j*line_h(27), ln, 27, MUTED)
        d.rounded_rectangle([W/2-110, 700, W/2+110, 700+64], radius=12, fill=ACCENT)
        centered(d, W/2, 716, "Retry", 28, DARK, bold=True)
        centered(d, W/2, 1180, "Error state — friendly Hinglish message", 24, MUTED)
    else:  # empty state
        g = emoji_image("🔎", 96)
        d._image.paste(g, (int(W/2 - g.width/2), 400), g)
        centered(d, W/2, 540, "Koi news nahi mili —", 28, MUTED)
        draw_mixed(d, (W/2, 584), "kuch aur search karke dekho 🔎", 28, MUTED, anchor_left=False)
        centered(d, W/2, 1180, "Empty state — search me kuch na mile to", 24, MUTED)
    return im

# ---- SEG 5: end card (4s) ----
def seg_end(i, n):
    im = blank(); d = ImageDraw.Draw(im)
    centered(d, W/2, 470, "AI News Digest", 54, TEXT, bold=True)
    d.rectangle([W/2-120, 560, W/2+120, 564], fill=ACCENT)
    centered(d, W/2, 600, "Built with SerpApi Google News API + Gemini", 31, TEXT)
    centered(d, W/2, 664, "Built with AI assistance — Muse Spark agent", 29, MUTED)
    centered(d, W/2, 760, "SerpApi India Hackathon 2026 · Research & AI track", 25, MUTED)
    im = fade_from_black(im, i, 10)
    im = fade_to_black(im, i, n, 12)
    return im

def main():
    segs = [
        (seg_title, 90),    # 3s
        (lambda i, n: seg_home(i, n, scroll=int(i/n*24)), 240),  # 8s, gentle scroll
        (seg_search, 360),  # 12s
        (seg_states, 240),  # 8s
        (seg_end, 120),     # 4s
    ]
    total = sum(n for _, n in segs)
    print(f"rendering {total} frames = {total/FPS:.1f}s", flush=True)
    cmd = ["ffmpeg", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "23",
           "-movflags", "+faststart",
           "/home/hatch/workspace/serpapi-hackathon/demo-video.mp4"]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    done = 0
    for fn, n in segs:
        for i in range(n):
            im = fn(i, n)
            p.stdin.write(im.tobytes())
            done += 1
        print(f"  seg done ({done}/{total})", flush=True)
    p.stdin.close(); p.wait()
    print("ffmpeg exit:", p.returncode, flush=True)

if __name__ == "__main__":
    main()
