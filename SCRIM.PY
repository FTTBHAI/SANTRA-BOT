import asyncio
import io
import math
import discord, json, os, random, re, time
from typing import Optional
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
from datetime import time as dtime

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except ImportError:
    raise SystemExit("Pillow is missing. Run:  pip install pillow")

# ================= SETTINGS =================
TOKEN = os.getenv("MTU2NzYzOTY0OTQ5NTgxMDA3OA.GZgGLB.n4m2W--X5qndqeH4eLsqHkojsFLb9oUdiE2t1A", "MTU2NzYzOTY0OTQ5NTgxMDA3OA.GZgGLB.n4m2W--X5qndqeH4eLsqHkojsFLb9oUdiE2t1A").strip().strip('"').strip("'")

PREFIX = "!"
BRAND = "SUPREME SCRIMS"
OWNER_ID = 1522148066281521176
THRONE_ROLE = "THRONE CLAIMER"
BANNED_ROLE = "SCRIM BANNED"
GROUP_CAP = 21
MIN_TEAMS = 18
START_GROUP_ID = 1
START_TEAM_ID = 1
SLOT_START = 3
LOCK_MINUTES = 20
IST = timezone(timedelta(hours=5, minutes=30))

# IDP times: 7-9 PM → 07:22 / 08:02 / 08:42 PM
#            9-11 PM → 09:22 / 10:02 / 10:42 PM
WINDOWS = {
    "A": {
        "label": "7-9 PM",
        "role": "7-9 IDP",
        "m1": (19, 22),
        "m2": (20, 2),
        "m3": (20, 42),
        "color": 0xFF6A00,
    },
    "B": {
        "label": "9-11 PM",
        "role": "9-11 IDP",
        "m1": (21, 22),
        "m2": (22, 2),
        "m3": (22, 42),
        "color": 0x9B59B6,
    },
}

DURATIONS = {
    "1d":   ("1 Day", 86400),
    "2d":   ("2 Days", 172800),
    "3d":   ("3 Days (max)", 259200),
    "leak": ("IDP Leak — PERMANENT", None),
}
MAP_ROTATION = ["Erangel", "Rondo"]
MAP_REVEAL_MINUTES_BEFORE = 30
MAPS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "maps")
MAP_STYLE = {
    "Erangel": {"sky": ((12, 22, 38), (128, 158, 156)), "sun": (255, 218, 160),
                "land": [(58, 84, 66), (40, 62, 50), (24, 40, 34), (12, 22, 20)],
                "accent": (120, 220, 160), "tag": "THE CLASSIC BATTLEGROUND"},
    "Miramar": {"sky": ((58, 20, 26), (255, 152, 72)), "sun": (255, 196, 96),
                "land": [(176, 100, 56), (134, 72, 42), (86, 44, 30), (42, 22, 18)],
                "accent": (255, 170, 70), "tag": "DESERT SHOWDOWN"},
    "Rondo":   {"sky": ((22, 18, 54), (240, 124, 156)), "sun": (255, 206, 206),
                "land": [(96, 72, 120), (66, 50, 98), (40, 30, 70), (20, 14, 40)],
                "accent": (255, 130, 190), "tag": "CITY & MOUNTAIN CLASH"},
}
DATA_FILE = "data.json"
IDP_BANNER_URL = "https://cdn.discordapp.com/attachments/1453442713193152684/1497823623099060284/IMG_20260426_100811.jpg"

# ============================================

# ---------- storage ----------
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        DATA = json.load(f)
else:
    DATA = {}
DATA.setdefault("guilds", {})
DATA.setdefault("giveaways", [])

def save():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(DATA, f, indent=2)

def G(guild_id):
    gd = DATA["guilds"].setdefault(str(guild_id), {})
    gd.setdefault("channel", None)          # registration panel channel id
    gd.setdefault("message", None)          # registration panel message id
    gd.setdefault("idp_channels", {})       # window key -> IDP channel id
    gd.setdefault("idp_msgs", {})           # window key -> {group id -> message id}
    gd.setdefault("summary_channel", None)  # channel for overall stats / team data
    gd.setdefault("map_announcements", {})
    gd.setdefault("category", None)
    gd.setdefault("setup_channels", [])
    gd.setdefault("throne_role", None)
    gd.setdefault("banned_role", None)
    gd.setdefault("bans", {})
    gd.setdefault("open", True)
    gd.setdefault("roles", {})
    gd.setdefault("teams", [])
    gd.setdefault("groups", [])
    gd.setdefault("next_gid", START_GROUP_ID)
    gd.setdefault("next_tid", START_TEAM_ID)
    gd.setdefault("date", datetime.now(IST).strftime("%Y-%m-%d"))
    return gd

def default_date():
    now = datetime.now(IST)
    if now.hour >= 23:
        now += timedelta(days=1)
    return now.strftime("%Y-%m-%d")

# ---------- group helpers ----------
def gcount(gd, gid):
    return sum(1 for t in gd["teams"] if t["group"] == gid)

def get_group(gd, gid):
    return next((g for g in gd["groups"] if g["id"] == gid), None)

def new_group(gd, key):
    g = {"id": gd["next_gid"], "window": key, "date": gd["date"]}
    gd["next_gid"] += 1
    gd["groups"].append(g)
    return g

def open_group(gd, key):
    for g in sorted(gd["groups"], key=lambda x: x["id"]):
        if g["window"] == key and gcount(gd, g["id"]) < GROUP_CAP:
            return g
    return new_group(gd, key)

def fresh_groups(gd, date):
    gd["teams"] = []
    gd["groups"] = []
    gd["date"] = date
    gd["next_gid"] = START_GROUP_ID
    gd["next_tid"] = START_TEAM_ID
    for key in WINDOWS:
        new_group(gd, key)

def find_team(gd, user_id, window_key=None):
    """Return the team the user owns in the given window (or any window if key=None)."""
    for t in gd["teams"]:
        if t["owner"] == user_id:
            if window_key is None or t["window"] == window_key:
                return t
    return None

def fmt_time(h, m):
    ap = "AM" if h < 12 else "PM"
    return f"{(h - 1) % 12 + 1:02d}:{m:02d} {ap}"

def idp_text(key):
    w = WINDOWS[key]
    return (
        f"M1: `{fmt_time(*w['m1'])}` | "
        f"M2: `{fmt_time(*w['m2'])}` | "
        f"M3: `{fmt_time(*w['m3'])}`"
    )

def m1_dt(g):
    y, mo, d = map(int, g["date"].split("-"))
    h, m = WINDOWS[g["window"]]["m1"]
    return datetime(y, mo, d, h, m, tzinfo=IST)

# ---------- throne permission ----------
class NotThrone(commands.CheckFailure):
    pass

def is_throne(member):
    if member is None:
        return False
    return int(getattr(member, "id", 0)) == OWNER_ID

def throne_only():
    async def pred(ctx):
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        if is_throne(ctx.author):
            return True
        raise NotThrone()
    return commands.check(pred)

# ---------- scrim ban helpers ----------
def get_active_ban(gd, user_id):
    b = gd["bans"].get(str(user_id))
    if b and b["until"] is not None and b["until"] <= int(time.time()):
        gd["bans"].pop(str(user_id), None)
        save()
        return None
    return b

def ban_text(b):
    if b["until"] is None:
        return f"**PERMANENT** scrim ban • Reason: {b['reason']}"
    return f"Scrim banned until <t:{b['until']}:f> (<t:{b['until']}:R>) • Reason: {b['reason']}"

# ---------- slotlist image ----------
BOLD_FONTS = ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"]
REG_FONTS = ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"]

def load_font(size, bold=True):
    for name in (BOLD_FONTS if bold else REG_FONTS):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()

def _fit(d, text, font, max_w):
    if d.textlength(text, font=font) <= max_w:
        return text
    while text and d.textlength(text + "...", font=font) > max_w:
        text = text[:-1]
    return text + "..."

def _ctext(d, cx, cy, text, font, fill):
    b = d.textbbox((0, 0), text, font=font)
    d.text((cx - (b[2] - b[0]) / 2 - b[0], cy - (b[3] - b[1]) / 2 - b[1]), text, font=font, fill=fill)

def _ltext(d, x, cy, text, font, fill):
    b = d.textbbox((0, 0), text, font=font)
    d.text((x - b[0], cy - (b[3] - b[1]) / 2 - b[1]), text, font=font, fill=fill)

def make_slotlist_png(group, teams, is_open):
    GOLD = (255, 196, 0, 255)
    ORANGE = (255, 106, 0, 255)
    W, COLS, M, GAP, CELL_H = 1280, 3, 48, 18, 72
    ROWS = (GROUP_CAP + COLS - 1) // COLS
    HEADER_H, FOOTER_H = 250, 130
    cell_w = (W - 2 * M - (COLS - 1) * GAP) // COLS
    H = HEADER_H + ROWS * CELL_H + (ROWS - 1) * GAP + FOOTER_H

    base = Image.new("RGB", (W, H))
    bd = ImageDraw.Draw(base)
    top, bot = (10, 11, 24), (34, 14, 6)
    for y in range(H):
        t = y / (H - 1)
        bd.line([(0, y), (W, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    img = base.convert("RGBA")

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gdw = ImageDraw.Draw(glow)
    gdw.ellipse((W - 520, -260, W + 160, 320), fill=(255, 106, 0, 120))
    gdw.ellipse((-220, H - 320, 420, H + 200), fill=(255, 196, 0, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    img = Image.alpha_composite(img, glow)
    d = ImageDraw.Draw(img, "RGBA")

    f_title, f_sub = load_font(64), load_font(30)
    f_chip, f_cell, f_num = load_font(26), load_font(27), load_font(27)
    f_small = load_font(22, bold=False)

    d.rectangle((0, 0, W, 8), fill=GOLD)
    ox, oy = M, 44
    d.polygon([(ox, oy + 42), (ox, oy + 8), (ox + 15, oy + 24), (ox + 30, oy), (ox + 45, oy + 24),
               (ox + 60, oy + 8), (ox + 60, oy + 42)], fill=GOLD)
    d.rectangle((ox, oy + 48, ox + 60, oy + 56), fill=GOLD)
    d.text((M + 84, 34), BRAND, font=f_title, fill=GOLD)
    d.text((M + 86, 112), f"SLOT LIST   |   GROUP {group['id']:02d}", font=f_sub, fill=(225, 225, 238, 255))

    w = WINDOWS[group["window"]]
    chips = [
        f"DATE  {group['date']}",
        f"TIME  {w['label']}",
        f"M1 {fmt_time(*w['m1'])}  M2 {fmt_time(*w['m2'])}  M3 {fmt_time(*w['m3'])}",
    ]
    cx = M
    for text in chips:
        tw = d.textlength(text, font=f_chip)
        d.rounded_rectangle((cx, 168, cx + tw + 40, 224), 28, fill=(255, 106, 0, 55),
                            outline=(255, 150, 40, 220), width=2)
        _ctext(d, cx + (tw + 40) / 2, 196, text, f_chip, (255, 255, 255, 255))
        cx += tw + 40 + 16
    d.line([(M, HEADER_H - 12), (W - M, HEADER_H - 12)], fill=(255, 196, 0, 120), width=2)

    for idx in range(GROUP_CAP):
        col, row = idx // ROWS, idx % ROWS
        x = M + col * (cell_w + GAP)
        y = HEADER_H + row * (CELL_H + GAP)
        filled = idx < len(teams)
        if filled:
            d.rounded_rectangle((x, y, x + cell_w, y + CELL_H), 16, fill=(255, 106, 0, 46),
                                outline=(255, 150, 40, 235), width=2)
            badge_fill, badge_txt = GOLD, (24, 14, 4, 255)
        else:
            d.rounded_rectangle((x, y, x + cell_w, y + CELL_H), 16, fill=(255, 255, 255, 10),
                                outline=(255, 255, 255, 45), width=2)
            badge_fill, badge_txt = (70, 72, 92, 255), (175, 177, 195, 255)
        bs = CELL_H - 24
        bx, by = x + 12, y + 12
        d.rounded_rectangle((bx, by, bx + bs, by + bs), 12, fill=badge_fill)
        _ctext(d, bx + bs / 2, by + bs / 2, f"{idx + SLOT_START:02d}", f_num, badge_txt)
        name = teams[idx].upper() if filled else "EMPTY SLOT"
        color = (255, 255, 255, 255) if filled else (125, 127, 145, 255)
        max_w = cell_w - (bs + 24) - 28
        _ltext(d, bx + bs + 16, y + CELL_H / 2, _fit(d, name, f_cell, max_w), f_cell, color)

    fy = HEADER_H + ROWS * CELL_H + (ROWS - 1) * GAP + 30
    count = len(teams)
    _ltext(d, M, fy + 14, f"{count}/{GROUP_CAP} TEAMS REGISTERED", f_chip, (255, 255, 255, 255))
    track_x0, track_x1 = M, M + 560
    d.rounded_rectangle((track_x0, fy + 38, track_x1, fy + 54), 8, fill=(255, 255, 255, 35))
    if count:
        d.rounded_rectangle((track_x0, fy + 38, track_x0 + int((track_x1 - track_x0) * min(count / GROUP_CAP, 1)),
                             fy + 54), 8, fill=ORANGE)
    if count >= MIN_TEAMS:
        pill, pcol = "READY TO RUN", (46, 204, 113, 255)
    else:
        pill, pcol = f"NEED {MIN_TEAMS - count} MORE TEAMS", (231, 76, 60, 255)
    status = "REGISTRATION OPEN" if is_open else "REGISTRATION CLOSED"
    scol = (255, 196, 0, 255) if is_open else (231, 76, 60, 255)
    x_right = W - M
    for txt, col in [(status, scol), (pill, pcol)]:
        tw = d.textlength(txt, font=f_chip)
        x0 = x_right - tw - 40
        d.rounded_rectangle((x0, fy, x_right, fy + 56), 28, fill=col[:3] + (45,), outline=col, width=2)
        _ctext(d, (x0 + x_right) / 2, fy + 28, txt, f_chip, col)
        x_right = x0 - 16
    _ctext(d, W / 2, H - 26, "Play fair  •  Be on time  •  Submit SS after the last match", f_small, (170, 172, 190, 255))

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf

# ---------- map rotation + cinematic ----------
def map_for(date_str, window_key, match_no):
    return MAP_ROTATION[match_no % len(MAP_ROTATION)]

def match_dt(date_str, window_key, match_no):
    y, mo, d = map(int, date_str.split("-"))
    key = ["m1", "m2", "m3"][match_no % 3]
    h, m = WINDOWS[window_key][key]
    return datetime(y, mo, d, h, m, tzinfo=IST)

def _spaced(d, x, cy, text, font, fill, spacing=6):
    for ch in text:
        b = d.textbbox((0, 0), ch, font=font)
        d.text((x - b[0], cy - (b[3] - b[1]) / 2 - b[1]), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + spacing
    return x

def _spaced_w(d, text, font, spacing=6):
    return sum(d.textlength(ch, font=font) + spacing for ch in text) - spacing

def _find_map_photo(name):
    for ext in ("jpg", "jpeg", "png", "webp"):
        p = os.path.join(MAPS_DIR, f"{name.lower()}.{ext}")
        if os.path.exists(p):
            return p
    return None

def make_map_cinematic_png(map_name, match_no, window_key, date_str):
    W, H, BAR = 1280, 540, 46
    st = MAP_STYLE[map_name]
    w = WINDOWS[window_key]
    acc = st["accent"] + (255,)
    img = None
    photo = _find_map_photo(map_name)
    if photo:
        try:
            im = Image.open(photo).convert("RGB")
            s = max(W / im.width, H / im.height)
            im = im.resize((int(im.width * s) + 1, int(im.height * s) + 1))
            l, t = (im.width - W) // 2, (im.height - H) // 2
            img = im.crop((l, t, l + W, t + H)).convert("RGBA")
        except Exception:
            img = None
    if img is None:
        base = Image.new("RGB", (W, H))
        bd = ImageDraw.Draw(base)
        top_c, bot_c = st["sky"]
        for y in range(H):
            t = min(1, y / (H * 0.78))
            bd.line([(0, y), (W, y)], fill=tuple(int(top_c[i] + (bot_c[i] - top_c[i]) * t) for i in range(3)))
        img = base.convert("RGBA")
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sx, sy = int(W * 0.74), int(H * 0.50)
        ImageDraw.Draw(glow).ellipse((sx - 150, sy - 150, sx + 150, sy + 150), fill=st["sun"] + (230,))
        img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(46)))
        rnd = random.Random(sum(map(ord, map_name)) * 31 + 7)
        d0 = ImageDraw.Draw(img, "RGBA")
        for i, col in enumerate(st["land"]):
            y0 = H * (0.52 + i * 0.12)
            amp = 62 - i * 11
            ph = [rnd.uniform(0, 6.28) for _ in range(3)]
            pts = [(0, H)]
            for x in range(0, W + 8, 8):
                y = y0 + amp * (0.6 * math.sin(x / (190 - i * 30) + ph[0])
                                + 0.3 * math.sin(x / 63 + ph[1]) + 0.1 * math.sin(x / 24 + ph[2]))
                pts.append((x, y))
            pts.append((W, H))
            d0.polygon(pts, fill=col + (255,))
            mist = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(mist).rectangle((0, int(y0 - 10), W, int(y0 + 46)), fill=st["sky"][1] + (34,))
            img = Image.alpha_composite(img, mist.filter(ImageFilter.GaussianBlur(26)))
            d0 = ImageDraw.Draw(img, "RGBA")
        grain = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd_ = ImageDraw.Draw(grain)
        for _ in range(2600):
            gd_.point((rnd.randrange(W), rnd.randrange(H)), fill=(255, 255, 255, rnd.randrange(10, 28)))
        img = Image.alpha_composite(img, grain)

    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for x in range(W):
        sd.line([(x, 0), (x, H)], fill=(0, 0, 0, int(205 * max(0, 1 - x / (W * 0.8)))))
    img = Image.alpha_composite(img, shade)
    vig = Image.new("RGBA", (W, H), (0, 0, 0, 215))
    ImageDraw.Draw(vig).ellipse((-W * 0.15, -H * 0.35, W * 1.15, H * 1.35), fill=(0, 0, 0, 0))
    img = Image.alpha_composite(img, vig.filter(ImageFilter.GaussianBlur(110)))

    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle((0, 0, W, BAR), fill=(0, 0, 0, 255))
    d.rectangle((0, H - BAR, W, H), fill=(0, 0, 0, 255))
    d.line([(0, BAR), (W, BAR)], fill=acc, width=2)
    d.line([(0, H - BAR), (W, H - BAR)], fill=acc, width=2)

    f_big, f_tag, f_chip = load_font(128), load_font(28), load_font(30)
    f_bar = load_font(21)
    match_key = ["m1", "m2", "m3"][match_no % 3]
    t_start = fmt_time(*w[match_key])
    _spaced(d, 48, BAR / 2 + 1, BRAND, f_bar, (255, 196, 0, 255), 4)
    right = f"MAP ROTATION REVEAL  |  {date_str}"
    _spaced(d, W - 48 - _spaced_w(d, right, f_bar, 3), BAR / 2 + 1, right, f_bar, (225, 225, 238, 255), 3)
    _spaced(d, 48, H - BAR / 2, f"{w['label']} SLOT", f_bar, (225, 225, 238, 255), 4)
    mt = f"MATCH {match_no + 1}"
    _spaced(d, W - 48 - _spaced_w(d, mt, f_bar, 4), H - BAR / 2, mt, f_bar, acc, 4)

    _spaced(d, 64, 178, st["tag"], f_tag, acc, 7)
    name = map_name.upper()
    _spaced(d, 66, 276, name, f_big, (0, 0, 0, 150), 10)
    _spaced(d, 62, 272, name, f_big, (255, 255, 255, 255), 10)
    chips = [f"M{match_no + 1}", f"{t_start} IST"]
    chip_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cd = ImageDraw.Draw(chip_layer)
    cx = 64
    for text in chips:
        tw = d.textlength(text, font=f_chip)
        cd.rounded_rectangle((cx, 372, cx + tw + 44, 432), 30, fill=(0, 0, 0, 120), outline=acc, width=2)
        cx += tw + 44 + 16
    img = Image.alpha_composite(img, chip_layer)
    d = ImageDraw.Draw(img, "RGBA")
    cx = 64
    for text in chips:
        tw = d.textlength(text, font=f_chip)
        _ctext(d, cx + (tw + 44) / 2, 402, text, f_chip, (255, 255, 255, 255))
        cx += tw + 44 + 16

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    buf.seek(0)
    return buf

# ---------- bot ----------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None,
    status=discord.Status.invisible,
)

# ---------- panel ----------
def status_icon(c):
    if c >= GROUP_CAP:
        return "🔴"
    if c >= GROUP_CAP - 2:
        return "🟡"
    return "🟢"

def build_embeds(gd):
    lines = []
    for g in sorted(gd["groups"], key=lambda x: (x["window"], x["id"])):
        c = gcount(gd, g["id"])
        filled = round(10 * c / GROUP_CAP)
        bar = "●" * filled + "○" * (10 - filled)
        ready = "  ✅ Ready" if c >= MIN_TEAMS else ""
        lines.append(
            f"{status_icon(c)} **Group {g['id']:02d} — {g['date']}** • {WINDOWS[g['window']]['label']}\n"
            f"🕒 **IDP:** {idp_text(g['window'])}\n"
            f"`{bar}` {c}/{GROUP_CAP} filled{ready}\n"
        )
    slots = discord.Embed(
        title="REGISTRATION — Slot availability",
        description=("\n".join(lines) or "No groups yet.")[:4000],
        color=0xFF6A00,
    )
    slots.set_footer(text=(
        ("Registration OPEN ✅" if gd["open"] else "Registration CLOSED ❌")
        + " • Slots fill on first-come basis • Play fair and check in on time."
    ))
    info = discord.Embed(
        title="📥 Team Registration",
        description=(
            "Click the button below to register your team.\n\n"
            f"➤ Can't play? Use **Clear Registration** at least {LOCK_MINUTES} minutes before M1 IDP.\n"
            "➤ SS submission is mandatory after the last match is completed.\n"
            f"➤ A group needs at least **{MIN_TEAMS}** teams to run.\n"
            "➤ You may register for **both** time windows (7-9 PM and 9-11 PM).\n"
            "➤ After registering you get a **DM** and access to your **IDP channel**."),
        color=0x2B2D31,
    )
    return [slots, info]

async def refresh_panel(guild):
    gd = G(guild.id)
    if not gd["channel"] or not gd["message"]:
        return
    try:
        ch = guild.get_channel(gd["channel"]) or await guild.fetch_channel(gd["channel"])
        msg = await ch.fetch_message(gd["message"])
        await msg.edit(embeds=build_embeds(gd))
    except Exception as e:
        print("panel refresh failed:", e)

_locks = {}

async def _sync_idp_channel(ch, msgs, groups, images):
    live = {str(g["id"]) for g in groups}
    for gid in list(msgs):
        if gid not in live:
            try:
                m = await ch.fetch_message(msgs[gid])
                await m.delete()
            except Exception:
                pass
            msgs.pop(gid, None)
    for g in groups:
        content = f"📊 **Group {g['id']:02d}** • {WINDOWS[g['window']]['label']} • {g['date']}"
        file = discord.File(io.BytesIO(images[g["id"]]), filename=f"slotlist_group_{g['id']:02d}.png")
        msg = None
        mid = msgs.get(str(g["id"]))
        if mid:
            try:
                msg = await ch.fetch_message(mid)
            except discord.NotFound:
                msg = None
        if msg:
            await msg.edit(content=content, attachments=[file])
        else:
            msg = await ch.send(content=content, file=file)
            msgs[str(g["id"])] = msg.id

async def refresh_slotlists(guild):
    gd = G(guild.id)
    idp_chs = {k: guild.get_channel(v) for k, v in gd.get("idp_channels", {}).items() if v}
    if not any(idp_chs.values()):
        return
    async with _locks.setdefault(guild.id, asyncio.Lock()):
        try:
            groups = sorted(gd["groups"], key=lambda x: (x["window"], x["id"]))
            images = {}
            for g in groups:
                names = [t["name"] for t in gd["teams"] if t["group"] == g["id"]]
                buf = await asyncio.to_thread(make_slotlist_png, g, names, gd["open"])
                images[g["id"]] = buf.getvalue()
            for key, ch in idp_chs.items():
                if ch:
                    msgs = gd["idp_msgs"].setdefault(key, {})
                    window_groups = [g for g in groups if g["window"] == key]
                    await _sync_idp_channel(ch, msgs, window_groups, images)
            save()
        except Exception as e:
            print("slotlist refresh failed:", e)

async def refresh_all(guild):
    await refresh_panel(guild)
    await refresh_slotlists(guild)

async def refresh_summary(guild):
    gd = G(guild.id)
    sid = gd.get("summary_channel")
    if not sid:
        return
    ch = guild.get_channel(sid)
    if not ch:
        return
    total = len(gd["teams"])
    lines_a, lines_b = [], []
    for t in gd["teams"]:
        member = guild.get_member(t["owner"])
        tag = str(member) if member else f"<@{t['owner']}>"
        line = f"`{t['id']:02d}` **{t['name']}** — {tag}"
        if t["window"] == "A":
            lines_a.append(line)
        else:
            lines_b.append(line)
    desc = (
        f"**Total teams registered: {total}**\n\n"
        f"**7-9 PM ({len(lines_a)} teams)**\n"
        + ("\n".join(lines_a) if lines_a else "— none —")
        + f"\n\n**9-11 PM ({len(lines_b)} teams)**\n"
        + ("\n".join(lines_b) if lines_b else "— none —")
    )
    e = discord.Embed(title="📋 Overall Participation — Today", description=desc[:4000], color=0xFFC400)
    e.set_footer(text=f"Date: {gd['date']} • Auto-updated on every registration")

    mid = gd.get("summary_msg")
    msg = None
    if mid:
        try:
            msg = await ch.fetch_message(mid)
        except discord.NotFound:
            msg = None
    if msg:
        await msg.edit(embed=e)
    else:
        msg = await ch.send(embed=e)
        gd["summary_msg"] = msg.id
        save()

async def ensure_roles(guild, gd):
    for key, w in WINDOWS.items():
        role = guild.get_role(gd["roles"].get(key, 0)) or discord.utils.get(guild.roles, name=w["role"])
        if not role:
            role = await guild.create_role(name=w["role"], colour=discord.Colour(w["color"]),
                                           mentionable=True, reason="Scrim IDP role")
        gd["roles"][key] = role.id
    save()

async def remove_team(guild, gd, team, dm_text=None):
    if team in gd["teams"]:
        gd["teams"].remove(team)
        save()
    member = guild.get_member(team["owner"])
    if not find_team(gd, team["owner"], team["window"]):
        role = guild.get_role(gd["roles"].get(team["window"], 0))
        if member and role:
            try:
                await member.remove_roles(role)
            except Exception:
                pass
    if dm_text and member:
        try:
            await member.send(dm_text)
        except Exception:
            pass

# ---------- daily automatic registration panel ----------
async def post_daily_panel(guild):
    gd = G(guild.id)
    if not gd.get("channel"):
        return
    ch = guild.get_channel(gd["channel"])
    if ch is None:
        try:
            ch = await guild.fetch_channel(gd["channel"])
        except Exception:
            return
    today = datetime.now(IST).strftime("%Y-%m-%d")
    for t in list(gd["teams"]):
        await remove_team(guild, gd, t)
    fresh_groups(gd, today)
    gd["open"] = True
    gd.setdefault("summary_msg", None)
    gd["summary_msg"] = None

    if gd.get("message"):
        try:
            old = await ch.fetch_message(gd["message"])
            await old.delete()
        except Exception:
            pass
    msg = await ch.send(embeds=build_embeds(gd), view=RegisterView())
    gd["message"] = msg.id
    save()
    await refresh_slotlists(guild)
    await refresh_summary(guild)

# ---------- scrim ban ----------
async def lock_banned(guild, gd, role):
    targets = [guild.get_channel(c) for c in gd.get("setup_channels", [])]
    for ch in targets:
        if ch is None:
            continue
        try:
            await ch.set_permissions(role, send_messages=False, add_reactions=False,
                                     create_public_threads=False, create_private_threads=False,
                                     send_messages_in_threads=False, reason="Scrim banned role")
        except Exception as e:
            print("lock_banned failed:", e)

async def get_banned_role(guild, gd):
    role = guild.get_role(gd.get("banned_role") or 0) or discord.utils.get(guild.roles, name=BANNED_ROLE)
    if not role:
        role = await guild.create_role(name=BANNED_ROLE, colour=discord.Colour.dark_red(),
                                       reason="Scrim banned role")
        await lock_banned(guild, gd, role)
    gd["banned_role"] = role.id
    save()
    return role

async def apply_ban(guild, user, key, by):
    gd = G(guild.id)
    label, secs = DURATIONS[key]
    until = None if secs is None else int(time.time()) + secs
    reason = "IDP Leak" if key == "leak" else "Scrim rule violation"
    ban = {"until": until, "reason": reason, "by": by.id, "at": int(time.time())}
    gd["bans"][str(user.id)] = ban
    for t in list(gd["teams"]):
        if t["owner"] == user.id:
            await remove_team(guild, gd, t)
    member = guild.get_member(user.id)
    if member:
        for rid in gd["roles"].values():
            r = guild.get_role(rid)
            if r and r in member.roles:
                try:
                    await member.remove_roles(r)
                except Exception:
                    pass
        try:
            role = await get_banned_role(guild, gd)
            await member.add_roles(role, reason=f"Scrim ban: {reason}")
        except Exception as e:
            print("ban role failed:", e)
    save()
    await refresh_all(guild)
    await refresh_summary(guild)

    dm_ok = True
    e = discord.Embed(title="🔨 You have been SCRIM BANNED", color=0xE74C3C,
                      description=f"Server: **{guild.name}**")
    e.add_field(name="Reason", value=reason, inline=True)
    e.add_field(name="Duration", value=label, inline=True)
    e.add_field(name="Ends", value="Never (permanent)" if until is None else f"<t:{until}:f> (<t:{until}:R>)",
                inline=False)
    e.set_footer(text="This is a scrim ban only. You are not banned from the server.")
    try:
        await user.send(embed=e)
    except Exception:
        dm_ok = False
    return ban, dm_ok

async def lift_ban(guild, gd, user_id, dm=True, reason_text="Your scrim ban has ended. You can register again."):
    gd["bans"].pop(str(user_id), None)
    save()
    member = guild.get_member(int(user_id))
    role = guild.get_role(gd.get("banned_role") or 0)
    if member and role and role in member.roles:
        try:
            await member.remove_roles(role, reason="Scrim ban lifted")
        except Exception:
            pass
    if dm and member:
        try:
            await member.send(f"✅ **{guild.name}** — {reason_text}")
        except Exception:
            pass

# ---------- registration UI ----------
async def dm_confirmation(guild, user, team, g, slot):
    w = WINDOWS[g["window"]]
    e = discord.Embed(title="✅ Registered!", color=0x2ECC71)
    e.add_field(name="Team", value=f"#{team['id']:02d} · **{team['name']}**", inline=True)
    e.add_field(name="Group / Slot", value=f"Group {g['id']:02d} · Slot {slot:02d}", inline=True)
    e.add_field(name="Window", value=w["label"], inline=True)
    e.add_field(name="IDP Times", value=idp_text(g["window"]), inline=False)
    e.set_footer(text=f"Date: {g['date']} • Clear 20 min before M1 if you can't play. GL! 👑")
    try:
        await user.send(embed=e)
        return True
    except Exception:
        return False

class TeamModal(discord.ui.Modal, title="Register Team"):
    name = discord.ui.TextInput(label="Team Name", max_length=30, placeholder="Enter your team name")

    def __init__(self, key):
        super().__init__()
        self.key = key

    async def on_submit(self, interaction: discord.Interaction):
        gd = G(interaction.guild.id)
        team_name = self.name.value.strip()
        if not gd["open"]:
            return await interaction.response.send_message("❌ Registration is closed.", ephemeral=True)
        b = get_active_ban(gd, interaction.user.id)
        if b:
            return await interaction.response.send_message(f"🔨 {ban_text(b)}", ephemeral=True)

        if find_team(gd, interaction.user.id, self.key):
            return await interaction.response.send_message(
                f"❌ You already have a team in the **{WINDOWS[self.key]['label']}** slot. "
                "You can register for the other time window.", ephemeral=True)

        if any(t["name"].lower() == team_name.lower() for t in gd["teams"]):
            return await interaction.response.send_message("❌ That team name is already taken.", ephemeral=True)

        g = open_group(gd, self.key)
        tid = gd["next_tid"]
        gd["next_tid"] += 1
        team = {"id": tid, "name": team_name, "owner": interaction.user.id,
                "window": self.key, "group": g["id"], "remind": False, "reminded": False}
        gd["teams"].append(team)
        count = gcount(gd, g["id"])
        slot_no = count + SLOT_START - 1
        if count >= GROUP_CAP:
            new_group(gd, self.key)
        save()

        role_note = "—"
        try:
            await ensure_roles(interaction.guild, gd)
            role = interaction.guild.get_role(gd["roles"].get(self.key, 0))
            if role:
                role_note = role.mention
                await interaction.user.add_roles(role, reason="Scrim registration")
        except discord.Forbidden:
            role_note = "⚠️ Missing perms — move bot role above IDP roles."
        except Exception as ex:
            role_note = f"⚠️ Role error: {ex}"

        dm_ok = await dm_confirmation(interaction.guild, interaction.user, team, g, slot_no)

        e = discord.Embed(title="🏆 Team Confirmed", color=0x2ECC71)
        e.description = f"📝 `{tid:02d}` : **{team_name}**\n👑 {interaction.user.mention}"
        e.add_field(name="Group / Slot", value=f"Group {g['id']:02d} — Slot {slot_no:02d} • {WINDOWS[self.key]['label']}", inline=False)
        e.add_field(name="IDP Times", value=idp_text(self.key), inline=False)
        e.add_field(name="IDP Role", value=role_note, inline=True)
        idp_id = gd.get("idp_channels", {}).get(self.key)
        if idp_id:
            e.add_field(name="IDP Channel", value=f"<#{idp_id}>", inline=True)
        e.add_field(name="DM", value="Sent ✅" if dm_ok else "⚠️ Open your DMs.", inline=True)
        await interaction.response.send_message(content=interaction.user.mention, embed=e)
        await refresh_all(interaction.guild)
        await refresh_summary(interaction.guild)

class WindowSelect(discord.ui.Select):
    def __init__(self, gd):
        opts = []
        for key, w in WINDOWS.items():
            g = open_group(gd, key)
            opts.append(discord.SelectOption(
                label=w["label"], value=key,
                description=f"Group {g['id']:02d} • {gcount(gd, g['id'])}/{GROUP_CAP} filled"))
        save()
        super().__init__(placeholder="Choose your time window", options=opts)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TeamModal(self.values[0]))

class WindowView(discord.ui.View):
    def __init__(self, gd):
        super().__init__(timeout=120)
        self.add_item(WindowSelect(gd))

class RemoveModal(discord.ui.Modal, title="Remove Team"):
    name = discord.ui.TextInput(label="Exact team name")

    async def on_submit(self, interaction: discord.Interaction):
        if not is_throne(interaction.user):
            return await interaction.response.send_message("❌ Only THRONE CLAIMER can do this.", ephemeral=True)
        gd = G(interaction.guild.id)
        t = next((x for x in gd["teams"] if x["name"].lower() == self.name.value.strip().lower()), None)
        if not t:
            return await interaction.response.send_message("❌ Team not found.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await remove_team(interaction.guild, gd, t,
                          dm_text=f"🗑️ Your team **{t['name']}** was removed from the scrim by staff.")
        await interaction.followup.send(f"✅ Removed **{t['name']}**.", ephemeral=True)
        await refresh_all(interaction.guild)
        await refresh_summary(interaction.guild)

# ---------- ban panel ----------
class BanView(discord.ui.View):
    def __init__(self, author_id, target=None):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.target = target
        self.key = None
        if target is not None:
            self.remove_item(self.pick_user)

    def summary(self):
        who = self.target.mention if self.target else "*not selected*"
        what = DURATIONS[self.key][0] if self.key else "*not selected*"
        return (f"🔨 **Scrim Punishment Panel**\n👤 Player: {who}\n⏱️ Punishment: {what}\n\n"
                "Pick both, then press **PUNISH**.")

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id or not is_throne(interaction.user):
            await interaction.response.send_message("❌ This panel isn't yours.", ephemeral=True)
            return False
        return True

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="1️⃣ Select the player to punish", row=0)
    async def pick_user(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        self.target = select.values[0]
        await interaction.response.edit_message(content=self.summary())

    @discord.ui.select(placeholder="2️⃣ Select punishment", row=1, options=[
        discord.SelectOption(label="1 Day scrim ban", value="1d", emoji="⏱️"),
        discord.SelectOption(label="2 Days scrim ban", value="2d", emoji="⏱️"),
        discord.SelectOption(label="3 Days scrim ban (max)", value="3d", emoji="⏱️"),
        discord.SelectOption(label="IDP Leak — PERMANENT scrim ban", value="leak", emoji="🚫"),
    ])
    async def pick_time(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.key = select.values[0]
        await interaction.response.edit_message(content=self.summary())

    @discord.ui.button(label="PUNISH", style=discord.ButtonStyle.danger, emoji="🔨", row=2)
    async def punish(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.target or not self.key:
            return await interaction.response.send_message("⚠️ Select the player and the punishment first.", ephemeral=True)
        if self.target.bot or self.target.id == interaction.user.id:
            return await interaction.response.send_message("❌ You can't punish that user.", ephemeral=True)
        member = interaction.guild.get_member(self.target.id)
        if member and is_throne(member):
            return await interaction.response.send_message("❌ You can't punish a THRONE CLAIMER.", ephemeral=True)
        await interaction.response.defer()
        ban, dm_ok = await apply_ban(interaction.guild, self.target, self.key, interaction.user)
        e = discord.Embed(title="🔨 SCRIM BAN APPLIED", color=0xE74C3C)
        e.add_field(name="Player", value=self.target.mention, inline=True)
        e.add_field(name="Punishment", value=DURATIONS[self.key][0], inline=True)
        e.add_field(name="Reason", value=ban["reason"], inline=True)
        e.add_field(name="Ends", value="Never (permanent)" if ban["until"] is None
                    else f"<t:{ban['until']}:f> (<t:{ban['until']}:R>)", inline=False)
        e.add_field(name="By", value=interaction.user.mention, inline=True)
        e.add_field(name="DM", value="Sent ✅" if dm_ok else "⚠️ Closed DMs", inline=True)
        await interaction.edit_original_response(content=None, embed=e, view=None)
        self.stop()

class ManageView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Open / Close Registration", style=discord.ButtonStyle.primary, emoji="🔒")
    async def toggle(self, interaction, button):
        gd = G(interaction.guild.id)
        gd["open"] = not gd["open"]
        save()
        await interaction.response.send_message(
            "Registration is now " + ("**OPEN** ✅" if gd["open"] else "**CLOSED** ❌"), ephemeral=True)
        await refresh_all(interaction.guild)

    @discord.ui.button(label="Team List", style=discord.ButtonStyle.secondary, emoji="📋")
    async def tlist(self, interaction, button):
        gd = G(interaction.guild.id)
        out = []
        for g in sorted(gd["groups"], key=lambda x: (x["window"], x["id"])):
            ts = [t for t in gd["teams"] if t["group"] == g["id"]]
            out.append(f"**Group {g['id']:02d}** • {WINDOWS[g['window']]['label']} • {len(ts)}/{GROUP_CAP}")
            for i, t in enumerate(ts, SLOT_START):
                out.append(f"`{i:02d}` {t['name']} (<@{t['owner']}>)")
            if not ts:
                out.append("— none —")
        await interaction.response.send_message(("\n".join(out))[:1900], ephemeral=True)

    @discord.ui.button(label="Remove Team", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def rem(self, interaction, button):
        await interaction.response.send_modal(RemoveModal())

    @discord.ui.button(label="Punish (Scrim Ban)", style=discord.ButtonStyle.danger, emoji="🔨")
    async def punish_btn(self, interaction, button):
        view = BanView(interaction.user.id)
        await interaction.response.send_message(view.summary(), view=view, ephemeral=True)

    @discord.ui.button(label="Reset All", style=discord.ButtonStyle.danger, emoji="♻️")
    async def reset_all(self, interaction, button):
        gd = G(interaction.guild.id)
        await interaction.response.defer(ephemeral=True)
        for t in list(gd["teams"]):
            await remove_team(interaction.guild, gd, t)
        fresh_groups(gd, gd["date"])
        save()
        await refresh_all(interaction.guild)
        await refresh_summary(interaction.guild)
        await interaction.followup.send("♻️ All registrations cleared.", ephemeral=True)

class RegisterView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Register Team", style=discord.ButtonStyle.success, emoji="📥", custom_id="reg:register")
    async def register(self, interaction, button):
        gd = G(interaction.guild.id)
        if not gd["open"]:
            return await interaction.response.send_message("❌ Registration is closed.", ephemeral=True)
        b = get_active_ban(gd, interaction.user.id)
        if b:
            return await interaction.response.send_message(f"🔨 {ban_text(b)}", ephemeral=True)
        await interaction.response.send_message("Select your time window:", view=WindowView(gd), ephemeral=True)

    @discord.ui.button(label="Set Slot Reminder", style=discord.ButtonStyle.primary, emoji="⏰", custom_id="reg:remind")
    async def remind(self, interaction, button):
        gd = G(interaction.guild.id)
        teams = [t for t in gd["teams"] if t["owner"] == interaction.user.id]
        if not teams:
            return await interaction.response.send_message("❌ Register a team first.", ephemeral=True)
        for t in teams:
            t["remind"] = True
            t["reminded"] = False
        save()
        await interaction.response.send_message("⏰ I'll DM you 15 minutes before M1 IDP for all your slots. Keep your DMs open!", ephemeral=True)

    @discord.ui.button(label="Clear Registration", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="reg:clear")
    async def clear(self, interaction, button):
        gd = G(interaction.guild.id)
        teams = [t for t in gd["teams"] if t["owner"] == interaction.user.id]
        if not teams:
            return await interaction.response.send_message("❌ You have no registration.", ephemeral=True)
        locked = []
        for t in teams:
            g = get_group(gd, t["group"])
            if g and datetime.now(IST) >= m1_dt(g) - timedelta(minutes=LOCK_MINUTES):
                locked.append(WINDOWS[t["window"]]["label"])
        if locked:
            return await interaction.response.send_message(
                f"❌ Too close to M1 for: **{', '.join(locked)}**. Contact a moderator.", ephemeral=True)
        for t in list(teams):
            await remove_team(interaction.guild, gd, t)
        await interaction.response.send_message("✅ All your registrations have been cleared.", ephemeral=True)
        await refresh_all(interaction.guild)
        await refresh_summary(interaction.guild)

    @discord.ui.button(label="Manage", style=discord.ButtonStyle.secondary, emoji="🛠️", custom_id="reg:manage")
    async def manage(self, interaction, button):
        if not is_throne(interaction.user):
            return await interaction.response.send_message("❌ Only the bot owner can open this.", ephemeral=True)
        await interaction.response.send_message("🛠️ **Manage Panel**", view=ManageView(), ephemeral=True)

# ---------- tickets ----------
TICKET_TYPES = {
    "general":  ("🎫", "General Support", "Get help with general queries, registration issues, or technical problems."),
    "staffapp": ("📝", "Staff Application", "Want to join the Staff Team? Open a ticket to apply."),
    "report":   ("🛡️", "Staff Reports", "Report staff misconduct. Please provide valid evidence."),
    "event":    ("🏆", "Event Support", "Help with tournaments, registrations or team participation."),
}

class CloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="ticket:close")
    async def close(self, interaction, button):
        opener = (interaction.channel.topic or "").replace("opener:", "")
        if not (is_throne(interaction.user) or interaction.user.guild_permissions.manage_messages
                or str(interaction.user.id) == opener):
            return await interaction.response.send_message("❌ Not allowed.", ephemeral=True)
        await interaction.response.send_message("Closing in 5 seconds...")
        await asyncio.sleep(5)
        await interaction.channel.delete()

class TicketSelect(discord.ui.Select):
    def __init__(self):
        opts = [discord.SelectOption(label=v[1], value=k, emoji=v[0]) for k, v in TICKET_TYPES.items()]
        super().__init__(placeholder="Ticket Purpose Selection", options=opts, custom_id="ticket:select")

    async def callback(self, interaction: discord.Interaction):
        kind = self.values[0]
        emoji, title, _ = TICKET_TYPES[kind]
        guild = interaction.guild
        ow = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        for r in guild.roles:
            if r.permissions.manage_messages and not r.is_default() and not r.managed:
                ow[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        thr = guild.get_role(G(guild.id).get("throne_role") or 0)
        if thr:
            ow[thr] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        ch = await guild.create_text_channel(f"{kind}-{interaction.user.name}"[:90], overwrites=ow,
                                             topic=f"opener:{interaction.user.id}")
        e = discord.Embed(title=f"{emoji} {title}", description="Describe your issue. Staff will reply soon.",
                          color=0x2ECC71)
        await ch.send(interaction.user.mention, embed=e, view=CloseView())
        await interaction.response.send_message(f"✅ Ticket created: {ch.mention}", ephemeral=True)
        try:
            await interaction.message.edit(view=TicketView())
        except Exception:
            pass

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())

# ---------- setup Modal & View ----------
class SetupModal(discord.ui.Modal, title="Scrim Setup — Channel IDs"):
    idp_a  = discord.ui.TextInput(label="7-9 PM IDP Channel ID",         placeholder="Right-click channel → Copy ID")
    idp_b  = discord.ui.TextInput(label="9-11 PM IDP Channel ID",        placeholder="Right-click channel → Copy ID")
    sum_ch = discord.ui.TextInput(label="Summary / Stats Channel ID",    placeholder="Right-click channel → Copy ID")
    date   = discord.ui.TextInput(label="Scrim Date (YYYY-MM-DD)",       placeholder="e.g. 2026-11-19", required=False)

    def __init__(self, reg_channel):
        super().__init__()
        self.reg_channel = reg_channel

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        gd = G(guild.id)
        await interaction.response.defer(ephemeral=True)

        date_str = self.date.value.strip() or default_date()
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return await interaction.followup.send("❌ Invalid date format. Use YYYY-MM-DD.", ephemeral=True)

        def _ch(raw):
            try:
                return guild.get_channel(int(raw.strip())) or guild.get_channel(int(raw.strip().strip("<#>")))
            except Exception:
                return None

        reg = self.reg_channel
        a_ch = _ch(self.idp_a.value)
        b_ch = _ch(self.idp_b.value)
        s_ch = _ch(self.sum_ch.value)

        missing = []
        if not a_ch: missing.append("7-9 PM IDP Channel")
        if not b_ch: missing.append("9-11 PM IDP Channel")
        if not s_ch: missing.append("Summary Channel")
        if missing:
            return await interaction.followup.send(f"❌ Could not find channels: {', '.join(missing)}. Check the IDs.", ephemeral=True)

        # Persist channel IDs (using current channel for registration panel)
        gd["channel"] = reg.id
        gd["idp_channels"] = {"A": a_ch.id, "B": b_ch.id}
        gd["summary_channel"] = s_ch.id
        gd["idp_msgs"] = {}
        gd["summary_msg"] = None

        # Throne role
        throne = guild.get_role(gd.get("throne_role") or 0) or discord.utils.get(guild.roles, name=THRONE_ROLE)
        if not throne:
            throne = await guild.create_role(name=THRONE_ROLE, colour=discord.Colour.gold(), hoist=True,
                                             mentionable=False, reason="Scrim bot admin role")
        gd["throne_role"] = throne.id
        if throne not in interaction.user.roles:
            try:
                await interaction.user.add_roles(throne)
            except Exception:
                pass

        # IDP roles + banned role
        await ensure_roles(guild, gd)
        banned_role = guild.get_role(gd.get("banned_role") or 0) or discord.utils.get(guild.roles, name=BANNED_ROLE)
        if not banned_role:
            banned_role = await guild.create_role(name=BANNED_ROLE, colour=discord.Colour.dark_red(),
                                                  reason="Scrim banned role")
        gd["banned_role"] = banned_role.id
        save()

        # Fresh groups + post registration panel in THIS channel
        gd["open"] = True
        fresh_groups(gd, date_str)
        if gd.get("message"):
            try:
                old = await reg.fetch_message(gd["message"])
                await old.delete()
            except Exception:
                pass

        msg = await reg.send(embeds=build_embeds(gd), view=RegisterView())
        gd["message"] = msg.id
        save()

        # Post IDP announcements
        for key, ch in [("A", a_ch), ("B", b_ch)]:
            w = WINDOWS[key]
            role = guild.get_role(gd["roles"].get(key, 0))
            intro = discord.Embed(
                title=f"🔑 IDP Room — {w['label']}",
                description=(
                    f"Only registered teams of this window can see this channel.\n"
                    f"{idp_text(key)}\n\n"
                    "Room ID & password will be posted here by staff. "
                    "**Never share IDP details outside this channel** — leaking = permanent scrim ban."
                ),
                color=0xFF6A00 if key == "A" else 0x9B59B6,
            )
            intro.set_image(url=IDP_BANNER_URL)
            allowed = discord.AllowedMentions(roles=bool(role), users=False, everyone=False)
            content = role.mention if role else f"**{w['label']} GROUP**"
            pin_msg = await ch.send(content=content, embed=intro, allowed_mentions=allowed)
            try:
                await pin_msg.pin()
            except Exception:
                pass

        # Push initial slotlists and summary
        await refresh_slotlists(guild)
        await refresh_summary(guild)

        e = discord.Embed(title="✅ Scrim system ready", color=0x2ECC71)
        e.add_field(name="Registration Panel", value=reg.mention, inline=True)
        e.add_field(name="7-9 PM IDP", value=a_ch.mention, inline=True)
        e.add_field(name="9-11 PM IDP", value=b_ch.mention, inline=True)
        e.add_field(name="Summary Channel", value=s_ch.mention, inline=True)
        e.add_field(name="Date", value=date_str, inline=True)
        e.add_field(name="Auto Panel", value="Posts daily at **10:00 AM IST**", inline=False)
        await interaction.followup.send(embed=e, ephemeral=True)

class StartSetupView(discord.ui.View):
    def __init__(self, author_id):
        super().__init__(timeout=180)
        self.author_id = author_id

    @discord.ui.button(label="⚙️ Configure Scrim Setup", style=discord.ButtonStyle.primary, custom_id="setup:start")
    async def start_setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id and not is_throne(interaction.user):
            return await interaction.response.send_message("❌ Only THRONE CLAIMER can configure setup.", ephemeral=True)
        await interaction.response.send_modal(SetupModal(interaction.channel))
        try:
            await interaction.message.delete()
        except Exception:
            pass

@bot.command(name="setup")
@commands.guild_only()
@throne_only()
async def setup_cmd(ctx):
    """!setup — initiate scrim setup for the current channel."""
    try:
        await ctx.message.delete()
    except Exception:
        pass
    e = discord.Embed(
        title="⚙️ Scrim Setup",
        description=(
            f"This channel ({ctx.channel.mention}) will automatically be set as the **Registration Panel Channel**.\n\n"
            "Click the button below to enter the IDP and Summary Channel IDs."
        ),
        color=0xFF6A00
    )
    await ctx.send(embed=e, view=StartSetupView(ctx.author.id))

@bot.command(name="ban")
@commands.guild_only()
@throne_only()
async def ban_cmd(ctx, member: Optional[discord.Member] = None):
    view = BanView(ctx.author.id, member)
    await ctx.send(view.summary(), view=view)

@bot.command()
@commands.guild_only()
@throne_only()
async def unban(ctx, user: discord.User):
    gd = G(ctx.guild.id)
    if str(user.id) not in gd["bans"]:
        return await ctx.send("❌ That user has no scrim ban.", delete_after=8)
    await lift_ban(ctx.guild, gd, user.id, reason_text="Your scrim ban was lifted by staff.")
    await ctx.send(f"✅ Scrim ban lifted for {user.mention}.")

@bot.command()
@commands.guild_only()
@throne_only()
async def banlist(ctx):
    gd = G(ctx.guild.id)
    lines = []
    for uid in list(gd["bans"]):
        b = get_active_ban(gd, uid)
        if b:
            end = "PERMANENT" if b["until"] is None else f"<t:{b['until']}:R>"
            lines.append(f"<@{uid}> • {b['reason']} • ends: {end}")
    await ctx.send(embed=discord.Embed(title="🔨 Active Scrim Bans", color=0xE74C3C,
                                       description="\n".join(lines) or "No active scrim bans."))

@bot.command()
@commands.guild_only()
@throne_only()
async def throne(ctx, member: discord.Member):
    role = ctx.guild.get_role(G(ctx.guild.id).get("throne_role") or 0)
    if not role:
        return await ctx.send("❌ Run `!setup` first.")
    await member.add_roles(role)
    await ctx.send(f"👑 {member.mention} is now a **{THRONE_ROLE}**.")

@bot.command()
@commands.guild_only()
@throne_only()
async def unthrone(ctx, member: discord.Member):
    role = ctx.guild.get_role(G(ctx.guild.id).get("throne_role") or 0)
    if role and role in member.roles:
        await member.remove_roles(role)
    await ctx.send(f"✅ {member.mention} is no longer a **{THRONE_ROLE}**.")

@bot.command()
@commands.guild_only()
@throne_only()
async def ticketpanel(ctx):
    e = discord.Embed(title="TICKET SUPPORT", color=0x2ECC71,
                      description="\n\n".join(f"{v[0]} **{v[1].upper()}**\n{v[2]}" for v in TICKET_TYPES.values()))
    await ctx.send(embed=e, view=TicketView())

def parse_duration(s):
    m = re.fullmatch(r"(\d+)([smhd])", s.lower())
    return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)] if m else None

@bot.command()
@commands.guild_only()
@throne_only()
async def giveaway(ctx, duration: str, winners: int, *, prize: str):
    secs = parse_duration(duration)
    if not secs:
        return await ctx.send("Use a duration like `30m`, `2h`, `2d`.")
    end = int(time.time()) + secs
    e = discord.Embed(title=f"🎁 {prize} 🎁", color=0x1ABC9C,
                      description=f"🔹 Winners: {winners}\n🔹 Ends: <t:{end}:R> (<t:{end}:f>)\n"
                                  f"🔹 Hosted by: {ctx.author.mention}\n\n🔹 React with 🎁 to participate!")
    msg = await ctx.send("🎁 **New Giveaway** 🎁", embed=e)
    await msg.add_reaction("🎁")
    DATA["giveaways"].append({"channel": ctx.channel.id, "message": msg.id, "end": end,
                              "winners": winners, "prize": prize})
    save()

@bot.command()
@commands.guild_only()
@throne_only()
async def reset(ctx, date: Optional[str] = None):
    gd = G(ctx.guild.id)
    if date:
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return await ctx.send("❌ Date format must be `YYYY-MM-DD`.", delete_after=8)
    for t in list(gd["teams"]):
        await remove_team(ctx.guild, gd, t)
    fresh_groups(gd, date or gd["date"])
    gd["summary_msg"] = None
    save()
    await refresh_all(ctx.guild)
    await refresh_summary(ctx.guild)
    await ctx.send("♻️ Registrations cleared.", delete_after=8)

@bot.command()
@commands.guild_only()
@throne_only()
async def fixroles(ctx):
    gd = G(ctx.guild.id)
    await ensure_roles(ctx.guild, gd)
    ok = bad = 0
    for t in gd["teams"]:
        member = ctx.guild.get_member(t["owner"])
        role = ctx.guild.get_role(gd["roles"].get(t["window"], 0))
        if not member or not role:
            bad += 1
            continue
        try:
            await member.add_roles(role)
            ok += 1
        except Exception:
            bad += 1
    await ctx.send(f"✅ Roles given: {ok} | ❌ Failed: {bad}")

@bot.command(name="thanks")
@commands.guild_only()
@throne_only()
async def thanks_cmd(ctx, *, note: Optional[str] = None):
    text = "Thank you to all the teams for playing with us! 🔥\n\nPlay fair, be on time and keep grinding. 💛"
    if note:
        text += f"\n\n💬 {note}"
    e = discord.Embed(title="🙏 THANK YOU TEAMS!", description=text[:4000], color=0xFFC400)
    e.set_footer(text="See you next time")
    try:
        await ctx.message.delete()
    except Exception:
        pass
    await ctx.send(embed=e)

async def send_group_map_announcement(guild, gd, key, date_str, destination=None, manual=False):
    w = WINDOWS[key]
    channel_id = gd.get("idp_channels", {}).get(key)
    channel = destination or (guild.get_channel(channel_id) if channel_id else None)
    if channel is None:
        return False

    groups = [g for g in gd.get("groups", []) if g.get("window") == key and g.get("date") == date_str]
    group_text = ", ".join(f"{g['id']:02d}" for g in groups) if groups else "Not assigned"
    role = guild.get_role(gd.get("roles", {}).get(key, 0))
    role_text = role.mention if role else ""
    reveal_dt = m1_dt({"date": date_str, "window": key}) - timedelta(minutes=MAP_REVEAL_MINUTES_BEFORE)

    header = discord.Embed(
        title=f"🗺️ MAP SCHEDULE • {w['label']} GROUP",
        description=(
            f"**{BRAND} — DAILY MAP ROTATION**\n"
            f"**Date:** {date_str}\n"
            f"**Group(s):** {group_text}\n"
            f"**Map reveal:** {fmt_time(reveal_dt.hour, reveal_dt.minute)} IST\n"
            f"**M1:** {fmt_time(*w['m1'])} IST  •  **M2:** {fmt_time(*w['m2'])} IST  •  **M3:** {fmt_time(*w['m3'])} IST\n\n"
            "Be ready before your IDP time. Follow the announced match order."
        ), color=w["color"])
    header.set_footer(text=f"{BRAND} • Play fair • Be on time")

    embeds, files = [header], []
    for n in (0, 1):
        map_name = map_for(date_str, key, n)
        match_key = ["m1", "m2"][n]
        match_ts = int(match_dt(date_str, key, n).timestamp())
        image_buf = await asyncio.to_thread(make_map_cinematic_png, map_name, n, key, date_str)
        filename = f"{date_str}_{key.lower()}_m{n + 1}_{map_name.lower()}.png"
        files.append(discord.File(image_buf, filename=filename))
        embed = discord.Embed(
            title=f"M{n + 1}  |  {map_name.upper()}",
            description=(
                f"**{date_str} • {w['label']}**\n"
                f"**IDP:** {fmt_time(*w[match_key])} IST\n"
                f"<t:{match_ts}:t> your time  •  <t:{match_ts}:R>"
            ), color=w["color"])
        embed.set_image(url=f"attachment://{filename}")
        embeds.append(embed)

    content = f"🎯 {role_text}" if role_text else f"🎯 **{w['label']} GROUP**"
    allowed = discord.AllowedMentions(roles=bool(role), users=False, everyone=False)
    await channel.send(content=content, embeds=embeds, files=files, allowed_mentions=allowed)
    return True

@bot.command(name="maps")
@commands.guild_only()
@throne_only()
async def maps_cmd(ctx, group: Optional[str] = None, date: Optional[str] = None):
    gd = G(ctx.guild.id)
    if group and re.fullmatch(r"\d{4}-\d{2}-\d{2}", group):
        date, group = group, None
    date = date or gd["date"]
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return await ctx.send("❌ Date format must be `YYYY-MM-DD`.", delete_after=8)
    keys = list(WINDOWS)
    if group:
        group = group.upper()
        if group not in WINDOWS:
            return await ctx.send("❌ Use `!maps A`, `!maps B`, or `!maps`.", delete_after=8)
        keys = [group]
    await ctx.send(f"🗺️ **MAP SCHEDULE REQUESTED** • {date}")
    posted = 0
    for key in keys:
        channel_id = gd.get("idp_channels", {}).get(key)
        destination = ctx.guild.get_channel(channel_id) if channel_id else ctx.channel
        if await send_group_map_announcement(ctx.guild, gd, key, date, destination=destination, manual=True):
            posted += 1
    await ctx.send(f"✅ Posted {posted} group map schedule(s).")

@bot.command(name="help")
async def help_cmd(ctx):
    e = discord.Embed(title="👑 Commands", color=0x5865F2, description=(
        "*All admin commands are locked to the bot owner only.*\n\n"
        "`!setup` — open setup dialog in the current channel\n"
        "`!ban [@user]` — scrim punishment panel\n"
        "`!unban @user` — lift a scrim ban\n"
        "`!banlist` — show active scrim bans\n"
        f"`!throne @user` / `!unthrone @user` — give / remove {THRONE_ROLE}\n"
        "`!giveaway 2d 1 ROYAL PASS` — start a giveaway\n"
        "`!maps` — post both group map schedules\n"
        "`!maps A` / `!maps B` — post one group's schedule\n"
        "`!thanks [message]` — post a thank-you message\n"
        "`!ticketpanel` — post ticket dropdown\n"
        "`!fixroles` — give IDP roles to registered teams\n"
        "`!reset [YYYY-MM-DD]` — clear all registrations\n\n"
        "🕙 Registration panel posts automatically every day at **10:00 AM IST**."))
    await ctx.send(embed=e)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, NotThrone):
        await ctx.send("❌ Only the bot owner can use this command.", delete_after=6)
    elif isinstance(error, commands.NoPrivateMessage):
        pass
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission.", delete_after=6)
    elif isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument)):
        await ctx.send("❌ Wrong usage. Type `!help` to see examples.", delete_after=8)
    elif not isinstance(error, commands.CommandNotFound):
        print(error)

# ---------- background loops ----------
AUTO_PANEL_TIME = dtime(hour=10, minute=0, tzinfo=IST)

@tasks.loop(time=AUTO_PANEL_TIME)
async def daily_panel_loop():
    for gid in list(DATA["guilds"]):
        guild = bot.get_guild(int(gid))
        if not guild:
            continue
        try:
            await post_daily_panel(guild)
        except Exception as e:
            print("daily panel failed:", e)

@tasks.loop(seconds=20)
async def map_announcement_loop():
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    for gid, gd in list(DATA["guilds"].items()):
        guild = bot.get_guild(int(gid))
        if not guild or gd.get("date") != today:
            continue
        for key in WINDOWS:
            announcement_key = f"{today}:{key}"
            if gd.setdefault("map_announcements", {}).get(announcement_key):
                continue
            groups = [g for g in gd.get("groups", []) if g.get("window") == key and g.get("date") == today]
            if not groups:
                continue
            reveal_at = m1_dt({"date": today, "window": key}) - timedelta(minutes=MAP_REVEAL_MINUTES_BEFORE)
            match_start = m1_dt({"date": today, "window": key})
            if not (reveal_at <= now < match_start):
                continue
            try:
                sent = await send_group_map_announcement(guild, gd, key, today)
                if sent:
                    gd["map_announcements"][announcement_key] = int(now.timestamp())
                    save()
            except Exception as e:
                print(f"map announcement failed for guild {gid}, group {key}:", e)

@tasks.loop(seconds=20)
async def giveaway_loop():
    now = int(time.time())
    for gw in list(DATA["giveaways"]):
        if gw["end"] > now:
            continue
        DATA["giveaways"].remove(gw)
        save()
        try:
            ch = bot.get_channel(gw["channel"]) or await bot.fetch_channel(gw["channel"])
            msg = await ch.fetch_message(gw["message"])
            r = discord.utils.get(msg.reactions, emoji="🎁")
            users = [u async for u in r.users() if not u.bot] if r else []
            win = random.sample(users, min(gw["winners"], len(users)))
            text = ", ".join(u.mention for u in win) if win else "No valid participants"
            e = discord.Embed(title=f"🎁 {gw['prize']} 🎁", description=f"🏆 Winner(s): {text}", color=0x95A5A6)
            await msg.edit(content="🎁 **Giveaway Ended** 🎁", embed=e)
            await ch.send(f"🎉 Congratulations {text}! You won **{gw['prize']}**!" if win
                          else "No one entered the giveaway.")
        except Exception as e:
            print("giveaway end failed:", e)

@tasks.loop(seconds=30)
async def reminder_loop():
    now = datetime.now(IST)
    for gid, gd in DATA["guilds"].items():
        for t in gd.get("teams", []):
            if not t.get("remind") or t.get("reminded"):
                continue
            g = get_group(gd, t.get("group"))
            if not g:
                continue
            m1 = m1_dt(g)
            if m1 - timedelta(minutes=15) <= now < m1:
                t["reminded"] = True
                save()
                try:
                    user = await bot.fetch_user(t["owner"])
                    await user.send(
                        f"⏰ **{t['name']}** — M1 IDP of Group {g['id']:02d} ({WINDOWS[g['window']]['label']}) "
                        f"is at {fmt_time(*WINDOWS[g['window']]['m1'])} (in ~15 min). Be ready!")
                except Exception:
                    pass

@tasks.loop(seconds=60)
async def ban_loop():
    now = int(time.time())
    for gid, gd in list(DATA["guilds"].items()):
        expired = [uid for uid, b in gd.get("bans", {}).items()
                   if b["until"] is not None and b["until"] <= now]
        if not expired:
            continue
        guild = bot.get_guild(int(gid))
        for uid in expired:
            if guild:
                await lift_ban(guild, gd, uid)
            else:
                gd["bans"].pop(uid, None)
        save()

@bot.event
async def on_member_join(member):
    gd = G(member.guild.id)
    if get_active_ban(gd, member.id):
        role = member.guild.get_role(gd.get("banned_role") or 0)
        if role:
            try:
                await member.add_roles(role, reason="Active scrim ban")
            except Exception:
                pass

@bot.event
async def setup_hook():
    bot.add_view(RegisterView())
    bot.add_view(TicketView())
    bot.add_view(CloseView())
    giveaway_loop.start()
    map_announcement_loop.start()
    reminder_loop.start()
    ban_loop.start()
    daily_panel_loop.start()

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

# ---------- start ----------
if not TOKEN:
    raise SystemExit(
        "No bot token found.\n"
        "Set the DISCORD_TOKEN environment variable before running.\n"
        'PowerShell:  $env:DISCORD_TOKEN = "YOUR_BOT_TOKEN"'
    )

try:
    bot.run(TOKEN)
except discord.LoginFailure:
    raise SystemExit(
        "Login failed: Discord rejected the token.\n"
        "Go to discord.com/developers/applications → your app → Bot → Reset Token,\n"
        "then set the NEW token in DISCORD_TOKEN."
    )
except discord.PrivilegedIntentsRequired:
    raise SystemExit(
        "Enable 'Message Content Intent' and 'Server Members Intent' in\n"
        "Developer Portal → your app → Bot → Privileged Gateway Intents."
    )
