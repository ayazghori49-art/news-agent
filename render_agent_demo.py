#!/usr/bin/env python3
"""Demo video renderer for News Agent (SerpApi India Hackathon 2026, AI Agents track).
Pillow-rendered frames (headless sandbox) -> ffmpeg -> 720x1280 H.264 MP4, <3 min.
Matches templates/chat.html: dark theme, chat bubbles, agent trace, chips, SAMPLE badge.
No emoji (DejaVu renders boxes) -- text + symbols only.
"""
import subprocess, time
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 720, 1280, 30

BG     = (13, 17, 23)
CARD   = (22, 27, 34)
BORDER = (48, 54, 61)
TEXT   = (230, 237, 243)
MUTED  = (139, 148, 158)
ACCENT = (88, 166, 255)
USERB  = (31, 111, 235)
SAMPLE = (210, 153, 34)
DARK   = (13, 17, 23)

DEJAVU      = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
DEJAVU_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

_fc = {}
def font(bold, size):
    k = (bold, size)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(DEJAVU_BOLD if bold else DEJAVU, size)
    return _fc[k]

def lh(size, f=1.5):
    return int(size * f)
LH26, LH22 = lh(26), lh(22)
GAP = 14

_scratch = ImageDraw.Draw(Image.new("RGB", (8, 8)))

def wrap(text, size, max_w, bold=False):
    f = font(bold, size)
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if _scratch.textlength(t, font=f) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines

def tw(s, size, bold=False):
    return _scratch.textlength(s, font=font(bold, size))

def centered(d, cx, y, s, size, color, bold=False):
    f = font(bold, size)
    d.text((cx - _scratch.textlength(s, font=f) / 2, y), s, font=f, fill=color)

def fade(im, i, n, edge):
    black = Image.new("RGB", im.size, (0, 0, 0))
    if i < edge:
        return Image.blend(black, im, i / edge)
    if i >= n - edge:
        return Image.blend(black, im, max((n - 1 - i) / edge, 0))
    return im

# ---------------- content (sample mode) ----------------
Q1 = "AI me nayi jobs ka kya scene hai?"
Q2 = "Aur salary kitni milti hai?"
WELCOME = ("Namaste! Main ek AI research agent hun — koi bhi news/tech sawaal poochho, "
           "main plan karke live search karunga aur Hinglish me jawab dunga.")
A1 = ("AI me jobs ka scene 2026 me kaafi garam hai [1][2]. India me startups aur badi "
      "companies dono AI engineers, data scientists aur ML roles ke liye hire kar rahe hain. "
      "Indic-language aur voice-first AI skills walon ko sabse zyada edge mil raha hai [3].")
S1 = [("[1]", "OpenAI launches affordable AI coding assistant tier aimed at Indian startups", "TechCrunch"),
      ("[2]", "Bengaluru AI startup Krutrim raises $200M to build Indic language models", "YourStory"),
      ("[3]", "Sarvam AI releases open voice model supporting 11 Indian languages", "Inc42")]
T1 = [("Plan", "(sample): 2 queries banayi"),
      ("Search 1", 'google_news "AI jobs India 2026" -> 8 hits (cached)'),
      ("Search 2", 'google "AI hiring trends 2026" -> 8 hits (cached)'),
      ("Compare", "16 sources -> top 7 picked"),
      ("Synthesize", "Hinglish jawab taiyaar - Mode: SAMPLE")]
A2 = ("Entry-level AI roles me Rs 8-15 LPA milta hai [1], 2-4 saal experience par "
      "Rs 18-35 LPA [2]. Senior/lead roles me Rs 40 LPA+ tak ja sakta hai — ML, LLM "
      "fine-tuning aur MLOps sabse zyada paid skills hain [3].")
S2 = [("[1]", "OpenAI launches affordable AI coding assistant tier aimed at Indian startups", "TechCrunch"),
      ("[2]", "Bengaluru AI startup Krutrim raises $200M to build Indic language models", "YourStory"),
      ("[3]", "Sarvam AI releases open voice model supporting 11 Indian languages", "Inc42")]
T2 = [("Plan", "(sample): 1 query banayi"),
      ("Search", 'google "AI engineer salary India 2026" -> 8 hits (cached)'),
      ("Compare", "8 sources -> top 3 picked")]

BODY_W = 640
U1_L  = wrap(Q1, 26, 602)
U2_L  = wrap(Q2, 26, 602)
WEL_L = wrap(WELCOME, 26, BODY_W)
A1_L  = wrap(A1, 26, BODY_W)
A2_L  = wrap(A2, 26, BODY_W)
T1_R  = [(lab, wrap(txt, 22, 616 - tw(lab + " ", 22, True), True)) for lab, txt in T1]
T2_R  = [(lab, wrap(txt, 22, 616 - tw(lab + " ", 22, True), True)) for lab, txt in T2]
S1_L  = [(num, wrap(title + " - " + src, 22, 640 - tw(num + " ", 22, True))) for num, title, src in S1]
S2_L  = [(num, wrap(title + " - " + src, 22, 640 - tw(num + " ", 22, True))) for num, title, src in S2]

# ---------------- chrome ----------------
def header(d):
    t1, t2 = "News ", "Agent"
    f = font(True, 40)
    w = _scratch.textlength(t1 + t2, font=f)
    x = W / 2 - w / 2
    d.text((x, 28), t1, font=f, fill=TEXT)
    d.text((x + _scratch.textlength(t1, font=f), 28), t2, font=f, fill=ACCENT)
    bl, bf = "● SAMPLE", font(True, 22)
    bw = _scratch.textlength(bl, font=bf) + 28
    bx = W / 2 - bw / 2
    d.rounded_rectangle([bx, 86, bx + bw, 120], radius=8, outline=SAMPLE, width=2)
    d.text((bx + 14, 92), bl, font=bf, fill=SAMPLE)
    centered(d, W / 2, 132, "Sawaal poochho — agent plan karke search karega", 22, MUTED)
    d.line([0, 168, W, 168], fill=BORDER, width=2)

def chips(d):
    labels = ["AI agents India", "Startup funding", "Gemini 3"]
    f = font(False, 24)
    ws = [_scratch.textlength(l, font=f) + 40 for l in labels]
    x = (W - (sum(ws) + 24)) / 2
    for l, w in zip(labels, ws):
        d.rounded_rectangle([x, 186, x + w, 232], radius=23, fill=CARD, outline=BORDER, width=2)
        d.text((x + (w - _scratch.textlength(l, font=f)) / 2, 195), l, font=f, fill=TEXT)
        x += w + 12

CHAT_TOP, CHAT_BOT = 252, 1138

def inputbar(d, text="", active=False):
    y0 = 1154
    d.line([0, y0 - 8, W, y0 - 8], fill=BORDER, width=2)
    d.rounded_rectangle([24, y0, 624, y0 + 66], radius=14, fill=CARD,
                        outline=ACCENT if active else BORDER, width=2)
    f = font(False, 26)
    if text:
        d.text((42, y0 + 17), text, font=f, fill=TEXT)
        if active and int(time.perf_counter() * 2.5) % 2 == 0:
            cx = 42 + _scratch.textlength(text, font=f) + 6
            d.rectangle([cx, y0 + 19, cx + 4, y0 + 47], fill=ACCENT)
    else:
        d.text((42, y0 + 17), "Sawaal poochho…", font=f, fill=MUTED)
    d.rounded_rectangle([636, y0, 696, y0 + 66], radius=14, fill=ACCENT)
    centered(d, 666, y0 + 13, ">", 32, DARK, bold=True)

# ---------------- chat items ----------------
def draw_user(d, y, lines):
    h = len(lines) * LH26 + 28
    if d is not None:
        f = font(False, 26)
        bw = max(_scratch.textlength(l, font=f) for l in lines) + 32
        x1, x0 = W - 24, W - 24 - bw
        d.rounded_rectangle([x0, y, x1, y + h], radius=16, fill=USERB)
        yy = y + 14
        for ln in lines:
            d.text((x0 + 16, yy), ln, font=f, fill=(255, 255, 255))
            yy += LH26
    return h

def agent_block_h(body, nb, trace, nt, srcs, ns):
    h = 16 + LH22 + 10
    if nb > 0:
        h += nb * LH26 + 12
    if nt > 0:
        h += 12 + LH22 + 10
        for _, lines in trace[:nt]:
            h += len(lines) * LH22 + 8
        h += 24
    if ns > 0:
        h += LH22 + 10
        for _, lines in srcs[:ns]:
            h += len(lines) * LH22 + 8
        h += 8
    h += 16
    return h

def draw_agent_block(d, y, body, nb, trace, nt, srcs, ns):
    h = agent_block_h(body, nb, trace, nt, srcs, ns)
    if d is not None:
        d.rounded_rectangle([24, y, W - 24, y + h], radius=14, fill=CARD, outline=BORDER, width=2)
        yy = y + 16
        d.text((40, yy), "News Agent", font=font(True, 22), fill=ACCENT)
        yy += LH22 + 10
        for ln in body[:nb]:
            d.text((40, yy), ln, font=font(False, 26), fill=TEXT)
            yy += LH26
        if nb > 0:
            yy += 12
        if nt > 0:
            tx0, tx1 = 40, W - 40
            th = 12 + LH22 + 10 + sum(len(l) * LH22 + 8 for _, l in trace[:nt]) + 12
            d.rounded_rectangle([tx0, yy, tx1, yy + th], radius=10, fill=BG, outline=BORDER, width=2)
            ty = yy + 12
            d.text((tx0 + 12, ty), "> Agent trace — agent ne kya kiya", font=font(True, 22), fill=MUTED)
            ty += LH22 + 10
            for lab, lines in trace[:nt]:
                lw_ = tw(lab + " ", 22, True)
                d.text((tx0 + 12, ty), lab, font=font(True, 22), fill=ACCENT)
                for j, ln in enumerate(lines):
                    d.text((tx0 + 12 + lw_, ty + j * LH22), ln, font=font(False, 22), fill=MUTED)
                ty += len(lines) * LH22 + 8
            yy += th + 12
        if ns > 0:
            d.text((40, yy), "SOURCES", font=font(True, 20), fill=MUTED)
            yy += LH22 + 10
            for num, lines in srcs[:ns]:
                nw_ = tw(num + " ", 22, True)
                d.text((40, yy), num, font=font(True, 22), fill=ACCENT)
                for j, ln in enumerate(lines):
                    d.text((40 + nw_, yy + j * LH22), ln, font=font(False, 22), fill=TEXT)
                yy += len(lines) * LH22 + 8
    return h

def draw_typing(d, y, text, i):
    x0, bw, bh = 24, 430, 58
    if d is not None:
        d.rounded_rectangle([x0, y, x0 + bw, y + bh], radius=14, fill=CARD, outline=BORDER, width=2)
        for j in range(3):
            c = ACCENT if ((i // 10) + j) % 3 == 0 else BORDER
            d.ellipse([x0 + 18 + j * 20, y + 23, x0 + 18 + j * 20 + 12, y + 35], fill=c)
        d.text((x0 + 90, y + 16), text, font=font(False, 22), fill=MUTED)
    return bh

def draw_item(d, y, it):
    k = it[0]
    if k == "user":
        return draw_user(d, y, it[1])
    if k == "agent":
        return draw_agent_block(d, y, it[1], it[2], it[3], it[4], it[5], it[6])
    if k == "typing":
        return draw_typing(d, y, it[1], it[2])
    return 0

def paint_chat(d, items):
    tot = sum(draw_item(None, 0, it) + GAP for it in items)
    scroll = max(0, tot - (CHAT_BOT - CHAT_TOP))
    y = CHAT_TOP - scroll
    for it in items:
        y += draw_item(d, y, it) + GAP

def blank():
    return Image.new("RGB", (W, H), BG)

# ---------------- segments ----------------
def seg_title(i, n):
    im = blank(); d = ImageDraw.Draw(im)
    t1, t2, f = "News ", "Agent", font(True, 72)
    w = _scratch.textlength(t1 + t2, font=f)
    x = W / 2 - w / 2
    d.text((x, 500), t1, font=f, fill=TEXT)
    d.text((x + _scratch.textlength(t1, font=f), 500), t2, font=f, fill=ACCENT)
    d.rectangle([W / 2 - 130, 612, W / 2 + 130, 616], fill=ACCENT)
    centered(d, W / 2, 642, "SerpApi India Hackathon 2026", 34, ACCENT, bold=True)
    centered(d, W / 2, 702, "AI Agents track", 28, MUTED)
    return fade(im, i, n, 10)

def seg_home(i, n):
    im = blank(); d = ImageDraw.Draw(im)
    header(d); chips(d)
    paint_chat(d, [("agent", WEL_L, len(WEL_L), [], 0, [], 0)])
    inputbar(d)
    return im

def seg_type(i, n):
    im = blank(); d = ImageDraw.Draw(im)
    header(d); chips(d)
    items, inp, act = [], "", False
    if i < 125:
        k = min(len(Q1), int(i / 125 * len(Q1) * 1.15))
        inp, act = Q1[:k], True
    else:
        items = [("user", U1_L)]
    paint_chat(d, items)
    inputbar(d, inp, act)
    return im

def seg_trace(i, n):
    im = blank(); d = ImageDraw.Draw(im)
    header(d); chips(d)
    if i < 90:
        nt, tt, show_typ = 0, "Plan bana raha hai…", True
    elif i < 170:
        nt, tt, show_typ = 1, "Search chal raha hai…", True
    elif i < 250:
        nt, tt, show_typ = 2, "Search chal raha hai…", True
    elif i < 330:
        nt, tt, show_typ = 3, "Compare ho raha hai…", True
    else:
        nt, tt, show_typ = 5, "Jawab ban raha hai…", i < 400
    items = [("user", U1_L), ("agent", [], 0, T1_R, nt, [], 0)]
    if show_typ:
        items.append(("typing", tt, i))
    paint_chat(d, items)
    inputbar(d)
    return im

def seg_answer(i, n):
    im = blank(); d = ImageDraw.Draw(im)
    header(d); chips(d)
    nb = 0 if i < 15 else min(len(A1_L), 1 + (i - 15) // 70)
    ns = 0 if i < 300 else min(len(S1_L), 1 + (i - 300) // 45)
    paint_chat(d, [("user", U1_L), ("agent", A1_L, nb, T1_R, 5, S1_L, ns)])
    inputbar(d)
    return im

def seg_follow(i, n):
    im = blank(); d = ImageDraw.Draw(im)
    header(d); chips(d)
    items = [("user", U1_L), ("agent", A1_L, len(A1_L), T1_R, 5, S1_L, len(S1_L))]
    if i < 75:
        k = min(len(Q2), int(i / 60 * len(Q2) * 1.2))
        inp, act = Q2[:k], True
    else:
        inp, act = "", False
        items.append(("user", U2_L))
    if 80 <= i < 150:
        items.append(("typing", "Search chal raha hai…", i))
    if i >= 140:
        nb2 = 0 if i < 210 else min(len(A2_L), 1 + (i - 210) // 45)
        ns2 = 0 if i < 262 else min(len(S2_L), 1 + (i - 262) // 30)
        items.append(("agent", A2_L, nb2, T2_R, 3, S2_L, ns2))
    paint_chat(d, items)
    inputbar(d, inp, act)
    return im

def seg_end(i, n):
    im = blank(); d = ImageDraw.Draw(im)
    centered(d, W / 2, 470, "News Agent", 54, TEXT, bold=True)
    d.rectangle([W / 2 - 120, 552, W / 2 + 120, 556], fill=ACCENT)
    centered(d, W / 2, 600, "Built for SerpApi India Hackathon 2026", 30, TEXT)
    centered(d, W / 2, 656, "AI Agents track", 26, MUTED)
    centered(d, W / 2, 716, "Code: GitHub - Deployed on Render", 24, MUTED)
    return fade(im, i, n, 12)

def main():
    segs = [
        (seg_title, 90),    # 3s
        (seg_home, 150),    # 5s
        (seg_type, 150),    # 5s
        (seg_trace, 450),   # 15s
        (seg_answer, 450),  # 15s
        (seg_follow, 300),  # 10s
        (seg_end, 120),     # 4s
    ]
    total = sum(n for _, n in segs)
    print(f"rendering {total} frames = {total / FPS:.1f}s", flush=True)
    cmd = ["ffmpeg", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "23",
           "-movflags", "+faststart",
           "/home/hatch/workspace/serpapi-hackathon/demo-video.mp4"]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    done = 0
    for fn, n in segs:
        for j in range(n):
            p.stdin.write(fn(j, n).tobytes())
            done += 1
        print(f"  seg done ({done}/{total})", flush=True)
    p.stdin.close()
    p.wait()
    print("ffmpeg exit:", p.returncode, flush=True)

if __name__ == "__main__":
    main()
