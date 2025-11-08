# =============================== #
#  MeadowLite — Self-Updating EXE #
# =============================== #
# How it works (single file):
# 1) On start, it checks MANIFEST_URL (JSON) for a newer version.
# 2) If remote version > APP_VERSION and we are a frozen EXE, it downloads the
#    new EXE, replaces this file safely, relaunches, and exits.
# 3) Otherwise it just runs the game (pygame) immediately.
#
# Manifest example (host this JSON at MANIFEST_URL):
# {
#   "version": "0.9.3",
#   "win": {
#     "exe_url": "https://your.host/path/MeadowLite-0.9.2.exe",
#     "sha256": ""
#   },
#   "notes": "optional release notes"
# }
#
# Build into one EXE:
#   pyinstaller -y --noconfirm --onefile --windowed --name "MeadowLite" meadowlite_selfupdating.py
#
# IMPORTANT: Set MANIFEST_URL to your hosted version.json before building.

from __future__ import annotations
import os, sys, json, hashlib, tempfile, shutil, subprocess, time
import urllib.request

# -------- UPDATE CONFIG --------
APP_NAME      = "MeadowLite"
APP_VERSION   = "0.9.3 - automatic update update patch"   # keep this equal to the version in version.json
MANIFEST_URL  = "https://raw.githubusercontent.com/itay10001/meadow.lite/main/version.json"
REQUEST_TIMEOUT = 20
# -------------------------------

def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)

def _this_exe() -> str:
    return sys.executable if _is_frozen() else os.path.abspath(__file__)

def _fetch_manifest() -> dict:
    req = urllib.request.Request(MANIFEST_URL, headers={"User-Agent": f"{APP_NAME}-Updater/1"})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))

def _parse_ver(v: str):
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0,0,0)

def _need_update(local: str, remote: str) -> bool:
    return _parse_ver(remote) > _parse_ver(local)

def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()

def _download_file(url: str, dest: str):
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}-Updater/1"})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r, open(dest, "wb") as f:
        while True:
            b = r.read(1024*256)
            if not b: break
            f.write(b)

def _self_update_stage2(dest_final: str):
    """We are the NEW exe (in a temp path), launched with --self-update <dest>.
    Copy ourselves over <dest>, then launch <dest> and exit."""
    src = _this_exe()
    # Wait until old exe is unlocked
    for _ in range(60):
        try:
            bak = dest_final + ".bak"
            if os.path.exists(bak):
                try: os.remove(bak)
                except Exception: pass
            if os.path.exists(dest_final):
                try:
                    os.replace(dest_final, bak)
                except PermissionError:
                    time.sleep(0.25); continue
            break
        except Exception:
            time.sleep(0.25)
    shutil.copy2(src, dest_final)
    subprocess.Popen([dest_final], cwd=os.path.dirname(dest_final))
    sys.exit(0)

def ensure_self_updated_then_continue():
    # Handle stage2
    if len(sys.argv) == 3 and sys.argv[1] == "--self-update":
        _self_update_stage2(sys.argv[2])
        return

    # If not frozen (running as .py), skip updating
    if not _is_frozen():
        return

    # Soft-fail updater (never block playing)
    try:
        man = _fetch_manifest()
        remote_ver = man["version"]
        if not _need_update(APP_VERSION, remote_ver):
            return
        exe_url = man["win"]["exe_url"]
        sha_exp = man["win"].get("sha256", "").strip().lower()

        tmp = tempfile.mkdtemp(prefix="ml_up_")
        new_exe = os.path.join(tmp, f"{APP_NAME}-{remote_ver}.exe")
        _download_file(exe_url, new_exe)
        if sha_exp:
            if _sha256(new_exe) != sha_exp:
                raise RuntimeError("Checksum mismatch")

        dest = _this_exe()
        subprocess.Popen([new_exe, "--self-update", dest], cwd=os.path.dirname(new_exe))
        sys.exit(0)
    except Exception:
        return


# =================================================================
# =======================  GAME (pygame)  ==========================
# Menu & Minimap Edition (Planting Fix + JSON save fix)
# =================================================================
import json as _json, math, random, time as _time
from dataclasses import dataclass, asdict, field
from typing import Dict, Tuple, Optional, List, Any

import pygame as pg

# ------------------------------- Constants ---------------------------------
WIDTH, HEIGHT = 1280, 720
TILE = 32
COLS, ROWS = WIDTH // TILE, HEIGHT // TILE
FPS = 60

SAVE_FILE = "meadow_save.json"
SAVE_VERSION = 7   # JSON tuple-key fix

REACH_TILES = 2
MAX_ENERGY = 300
MAX_HP = 100

# Colors
WHITE=(240,240,240); BLACK=(16,16,20); UI_BG=(26,26,30); UI_ACC=(196,196,210)
GRASS1=(58,114,58); GRASS2=(68,132,68); DIRT=(120,86,60); WET=(76,112,150)
WATER=(60,120,180)
YELLOW=(240,210,90); RED=(220,80,80); BLUE=(90,150,240)
ORANGE=(220,160,80); SNOW=(220,230,240); GRAY=(150,150,150)
GOLD=(230,200,60); SAND=(206,186,120); FOREST=(44,96,52); MOUNTAIN=(115,110,120)
VIOLET=(140,100,200)

FERT_COLORS=[(120,80,60),(140,100,70),(160,120,80),(180,140,90),(200,160,100),(220,180,110)]
HILITE_OK=(80,220,120); HILITE_BAD=(235,90,90)

SEASONS = ("spring","summer","fall","winter")
WEEKDAYS = ("Mon","Tue","Wed","Thu","Fri","Sat","Sun")
SCENES = ("farm","town","forest","mountain","beach","mine","house")

DEFAULT_KEYS = {
    "up": pg.K_w, "down": pg.K_s, "left": pg.K_a, "right": pg.K_d,
    "interact": pg.K_e, "use": pg.K_SPACE, "craft": pg.K_c, "pause": pg.K_ESCAPE,
    "fullscreen": pg.K_f, "save": pg.K_F5, "load": pg.K_F9, "aim_toggle": pg.K_r,
    "debug": pg.K_F3, "inv": pg.K_i, "quests": pg.K_q, "minimap_quick_edit": pg.K_m
}

# ------------------------------- Data Tables -------------------------------
DATA_ITEMS = {
    "parsnip_seeds": {"name":"Parsnip Seeds","kind":"seed","crop":"parsnip","price":20},
    "turnip_seeds":  {"name":"Turnip Seeds","kind":"seed","crop":"turnip","price":30},
    "potato_seeds":  {"name":"Potato Seeds","kind":"seed","crop":"potato","price":50},
    "parsnip": {"name":"Parsnip","kind":"crop","sell":35},
    "parsnip_silver": {"name":"Parsnip (Silver)","kind":"crop","sell":44},
    "parsnip_gold": {"name":"Parsnip (Gold)","kind":"crop","sell":52},
    "turnip":  {"name":"Turnip","kind":"crop","sell":50},
    "turnip_silver":  {"name":"Turnip (Silver)","kind":"crop","sell":62},
    "turnip_gold":  {"name":"Turnip (Gold)","kind":"crop","sell":75},
    "potato":  {"name":"Potato","kind":"crop","sell":80},
    "potato_silver": {"name":"Potato (Silver)","kind":"crop","sell":96},
    "potato_gold": {"name":"Potato (Gold)","kind":"crop","sell":120},
    "fiber":   {"name":"Fiber","kind":"res","sell":2},
    "wood":    {"name":"Wood","kind":"res","sell":3},
    "stone":   {"name":"Stone","kind":"res","sell":2},
    "copper_ore": {"name":"Copper Ore","kind":"res","sell":8},
    "iron_ore": {"name":"Iron Ore","kind":"res","sell":12},
    "gold_ore": {"name":"Gold Ore","kind":"res","sell":25},
    "path_tile": {"name":"Path Tile","kind":"placeable","price":0},
    "chest": {"name":"Chest","kind":"placeable","price":0},
    "furnace": {"name":"Furnace","kind":"placeable","price":0},
    "sprinkler_copper": {"name":"Sprinkler (Cu)","kind":"placeable","price":0},
    "sprinkler_iron":   {"name":"Sprinkler (Fe)","kind":"placeable","price":0},
    "sprinkler_gold":   {"name":"Sprinkler (Au)","kind":"placeable","price":0},
    "fertilizer": {"name":"Basic Fertilizer","kind":"fertilizer","price":80},
    "quality_fertilizer": {"name":"Quality Fertilizer","kind":"fertilizer","price":160},
    "egg": {"name":"Egg","kind":"animal","sell":30},
    "egg_silver": {"name":"Egg (Silver)","kind":"animal","sell":38},
    "egg_gold": {"name":"Egg (Gold)","kind":"animal","sell":48},
}

DATA_CROPS = {
    "parsnip": {"stages": (1,2,2), "seasons": ("spring",)},
    "turnip":  {"stages": (2,2,2), "seasons": ("spring","fall")},
    "potato":  {"stages": (2,3,3), "seasons": ("spring",)},
}

DATA_RECIPES = {
    "path_tile": {"req": {"stone": 2}},
    "chest":     {"req": {"wood": 20}},
    "furnace":   {"req": {"stone": 20, "copper_ore": 5}},
    "sprinkler_copper": {"req": {"copper_ore": 5, "stone": 5}},
    "sprinkler_iron":   {"req": {"iron_ore": 6, "stone": 10}},
    "sprinkler_gold":   {"req": {"gold_ore": 6, "stone": 12}},
    "fertilizer": {"req": {"fiber": 5, "stone": 1}},
    "quality_fertilizer": {"req": {"fiber": 10, "copper_ore": 1}},
}

DATA_NPCS = {
    "Ava": {
        "likes": ["parsnip","egg"],
        "dislikes": ["stone"],
        "dialogue": {
            "greet": ["Lovely day!", "Plant anything new?", "What's new?", "How are you?"],
            "rain":["Rain’s good for the soil."],
            "quest":["Could you ship 3 parsnips? I’ll pay you back."],
            "thanks":["Thanks for helping the town!"]
        }
    }
}

CATEGORY_OF = {
    "parsnip":"crops","turnip":"crops","potato":"crops",
    "parsnip_silver":"crops","parsnip_gold":"crops",
    "turnip_silver":"crops","turnip_gold":"crops",
    "potato_silver":"crops","potato_gold":"crops",
    "wood":"res","stone":"res","fiber":"res","copper_ore":"res","iron_ore":"res","gold_ore":"res",
    "egg":"animal","egg_silver":"animal","egg_gold":"animal",
}

WATER_TILES = {"farm_pond": []}

# -------------------- pygame init --------------------
pg.init()
screen = pg.display.set_mode((WIDTH, HEIGHT))
pg.display.set_caption(f"{APP_NAME} {APP_VERSION}")
clock = pg.time.Clock()
FONT = pg.font.SysFont("consolas", 18)
BIG = pg.font.SysFont("consolas", 24, bold=True)

WATER_TILES["farm_pond"] = [(COLS//2-10 + i, ROWS//2+6) for i in range(10)]

# ------------------------------- Helpers -----------------------------------
def draw_text(surf, text, pos, color=WHITE, font=FONT):
    img = font.render(text, True, color); surf.blit(img, pos)

def lerp(a: float, b: float, t: float) -> float: return a + (b-a)*t
def clamp(x: float, lo: float, hi: float) -> float: return lo if x<lo else hi if x>hi else x
def rect_from_tile(tx:int, ty:int) -> pg.Rect: return pg.Rect(tx*TILE, ty*TILE, TILE, TILE)

# ------------------------------- Dataclasses --------------------------------
@dataclass
class Crop:
    kind: str
    stage: int = 0
    in_stage_days: float = 0.0
    watered: bool = False
    diseased: bool = False
    def mature(self) -> bool: return self.stage >= len(DATA_CROPS[self.kind]["stages"])
    def next_day(self, raining: bool, fert_bonus: float = 0.0, disease_chance: float = 0.0):
        if not self.mature() and not self.diseased and random.random() < disease_chance: self.diseased = True
        if self.mature(): self.watered = False; return
        if self.watered or raining:
            stall = self.diseased and random.random() < 0.66
            if not stall:
                speed = 1.0 + min(0.35, max(0.0, fert_bonus))
                self.in_stage_days += speed
                need = DATA_CROPS[self.kind]["stages"][self.stage]
                if self.in_stage_days + 1e-6 >= need:
                    self.stage += 1; self.in_stage_days = 0.0
                    if self.diseased and random.random() < 0.35: self.diseased = False
        self.watered = False

@dataclass
class Animal:
    kind: str = "chicken"
    name: str = "Hen"
    x: float = 0; y: float = 0
    fed: bool = False; produced: bool = False; happy: float = 0.5

@dataclass
class Player:
    x: float; y: float
    fx: int = 0; fy: int = 1
    gold: int = 250; energy: int = 270; hp: int = MAX_HP
    hotbar_index: int = 0
    inv: Dict[str, int] = field(default_factory=dict)
    tools: Dict[str, int] = field(default_factory=lambda: {"hoe":1, "can":1, "rod":1, "pick":1, "axe":1})
    def rect(self) -> pg.Rect: return pg.Rect(int(self.x)-12, int(self.y)-12, 24, 24)

@dataclass
class Skills:
    farming:int=0; mining:int=0; fishing:int=0
    fxp:int=0; mxp:int=0; hxp:int=0
    def add(self, which:str, amt:int=1):
        if which=="farming": self.fxp+=amt; self.farming = min(10, self.farming + self.fxp//100); self.fxp%=100
        if which=="mining": self.mxp+=amt; self.mining  = min(10, self.mining  + self.mxp//100); self.mxp%=100
        if which=="fishing": self.hxp+=amt; self.fishing = min(10, self.fishing + self.hxp//100); self.hxp%=100

@dataclass
class Economy:
    day:int=1
    drift:Dict[str,float]=field(default_factory=lambda:{"crops":1.0,"res":1.0,"animal":1.0})
    def roll(self):
        for k,v in list(self.drift.items()): self.drift[k] = max(0.85, min(1.25, v + random.uniform(-0.05,0.05)))

@dataclass
class Farm:
    soil: List[List[int]]
    fertility: List[List[int]]
    crops: Dict[Tuple[int,int], Crop]
    placed: Dict[Tuple[int,int], str]
    animals: List[Animal]
    bed: Tuple[int,int]
    bin: Tuple[int,int]
    tv: Tuple[int,int]
    coop: Tuple[int,int]
    house_pos: Tuple[int,int] = (COLS//2-14, ROWS//2-4)
    house_size: Tuple[int,int] = (6,4)
    house_door: Tuple[int,int] = (COLS//2-11, ROWS//2)

@dataclass
class TimeState:
    day: int = 1; season_idx: int = 0; minutes: int = 6*60
    weather: str = "clear"; weekday: int = 0; tomorrow: str = "clear"
    def season(self) -> str: return SEASONS[self.season_idx]
    def advance(self, dt: float):
        self.minutes += int(dt * 8)
        if self.minutes >= (24+2)*60: self.minutes = 2*60
    def clock_str(self) -> str:
        h=(self.minutes//60)%24; m=self.minutes%60
        suff = "AM" if 0<=h<12 else "PM"
        h12 = h if 1<=h<=12 else (12 if h%12==0 else h%12)
        return f"{h12:02d}:{m:02d} {suff}"

# ------------------------------- UI Systems ---------------------------------
class DialogueBox:
    def __init__(self): self.lines=[]; self.visible=False
    def say(self, text:str): self.lines=[text] if isinstance(text,str) else text[:]; self.visible=True
    def hide(self): self.visible=False
    def draw(self, surf: pg.Surface):
        if not self.visible: return
        panel = pg.Rect(16, 60, WIDTH-32, 120)
        pg.draw.rect(surf, UI_BG, panel, border_radius=12); pg.draw.rect(surf, UI_ACC, panel, 2, border_radius=12)
        y = panel.y+12
        for ln in self.lines[:3]: draw_text(surf, ln, (panel.x+16, y)); y += 26
        draw_text(surf, "Press E to continue", (panel.right-220, panel.bottom-26), UI_ACC)

class Minimap:
    def __init__(self):
        self.dragging=False; self.drag_off=(0,0)
    def rect(self, pos:Tuple[int,int], size:Tuple[int,int]) -> pg.Rect:
        x,y = pos; w,h = size; return pg.Rect(x,y,w,h)
    def draw(self, surf: pg.Surface, scene: str, player_px: Tuple[int,int], pos:Tuple[int,int], size:Tuple[int,int]):
        x,y = pos; w,h = size
        x = clamp(x, 8, WIDTH - w - 8); y = clamp(y, 8, HEIGHT - h - 8)
        area = pg.Rect(x,y,w,h)
        pg.draw.rect(surf, UI_BG, area, border_radius=12); pg.draw.rect(surf, UI_ACC, area, 2, border_radius=12)
        color = {
            "farm": (70,110,70), "town": (90,110,160), "forest": (44,96,52),
            "mountain": (115,110,120), "beach": (206,186,120), "mine": (80,80,90),
            "house": (80,70,60)
        }.get(scene, (80,80,80))
        inner = area.inflate(-16,-16)
        pg.draw.rect(surf, color, inner, border_radius=8)
        px,py = player_px
        relx = inner.x + int((px/WIDTH) * inner.w)
        rely = inner.y + int((py/HEIGHT) * inner.h)
        pg.draw.circle(surf, YELLOW, (relx, rely), max(3, int(inner.w/60)))
        draw_text(surf, scene.upper(), (inner.x+8,inner.y+6), WHITE, BIG)
        return (x,y)

class Fade:
    def __init__(self): self.alpha=0.0; self.target=0.0; self.speed=3.5
    def to(self, a:float): self.target=clamp(a,0.0,1.0)
    def update(self, dt:float): self.alpha = lerp(self.alpha, self.target, clamp(dt*self.speed,0,1))
    def draw(self, surf: pg.Surface):
        if self.alpha <= 0.01: return
        shade = pg.Surface((WIDTH, HEIGHT), pg.SRCALPHA); shade.fill((0,0,0, int(255*self.alpha)))
        surf.blit(shade, (0,0))

class WeatherFX:
    def __init__(self): self.particles=[]
    def spawn(self, kind:str):
        need = 140 if kind=="rain" else 110 if kind=="snow" else 0
        while len(self.particles) < need:
            x = random.randint(0, WIDTH); y = random.randint(-HEIGHT, 0)
            vel = (random.uniform(-40,20), random.uniform(220,360)) if kind=="rain" else (random.uniform(-30,30), random.uniform(60,120))
            self.particles.append({"x":x,"y":y,"vx":vel[0],"vy":vel[1],"k":kind})
    def update(self, dt:float, kind:str):
        if kind not in ("rain","snow"): self.particles.clear(); return
        self.spawn(kind)
        for p in self.particles:
            p["x"] += p["vx"]*dt; p["y"] += p["vy"]*dt
            if p["y"]>HEIGHT or p["x"]< -20 or p["x"]>WIDTH+20:
                p["x"] = random.randint(0, WIDTH); p["y"] = random.randint(-80, -10)
    def draw(self, surf: pg.Surface):
        for p in self.particles:
            if p["k"]=="rain":
                pg.draw.line(surf, (180,200,255), (int(p["x"]), int(p["y"])), (int(p["x"]-3), int(p["y"]+8)), 1)
            else:
                pg.draw.circle(surf, WHITE, (int(p["x"]), int(p["y"])), 2)

class QuestLog:
    def __init__(self): self.active={}; self.completed=[]
    def add(self, qid:str, text:str, goal:Dict[str,int]):
        if qid in self.active or qid in self.completed: return
        self.active[qid] = {"text": text, "goal": goal.copy(), "progress": {k:0 for k in goal}}
    def bump_ship(self, shipped: Dict[str,int]):
        for q in list(self.active.keys()):
            for item,qty in shipped.items():
                if item in self.active[q]["goal"]: self.active[q]["progress"][item] += qty
            done = all(self.active[q]["progress"][k] >= self.active[q]["goal"][k] for k in self.active[q]["goal"])
            if done: self.completed.append(q); del self.active[q]
    def draw_panel(self, surf: pg.Surface):
        panel = pg.Rect(16, HEIGHT-240, 360, 224)
        pg.draw.rect(surf, UI_BG, panel, border_radius=12); pg.draw.rect(surf, UI_ACC, panel, 2, border_radius=12)
        draw_text(surf, "Quests", (panel.x+12,panel.y+8), WHITE, BIG)
        y = panel.y+40
        if not self.active: draw_text(surf, "(No active quests)", (panel.x+12,y)); return
        for qid,info in list(self.active.items())[:5]:
            draw_text(surf, info["text"], (panel.x+12,y), YELLOW); y+=22
            for k,need in info["goal"].items():
                have = info["progress"][k]
                draw_text(surf, f"  {DATA_ITEMS.get(k,{'name':k})['name']}: {have}/{need}", (panel.x+12,y)); y+=20

# ------------------------------- Game ---------------------------------------
class Game:
    def __init__(self):
        self.keys = DEFAULT_KEYS.copy()
        self.time = TimeState()
        self.player = Player(WIDTH//2, HEIGHT//2)
        self.scene = "farm"
        self.fullscreen=False; self.paused=False
        self.aim_mode = "front"
        self.skills = Skills(); self.eco = Economy()
        self.fade = Fade(); self.fx = WeatherFX()
        self.dialogue = DialogueBox(); self.quests = QuestLog()
        self.debug = False; self.show_quests = False

        # Minimap
        self.show_minimap = True
        self.minimap = Minimap()
        self.minimap_pos = (WIDTH-220, 16)
        self.minimap_size = (200, 150)
        self.minimap_quick_edit = False

        # farm init
        soil = [[0 for _ in range(ROWS)] for _ in range(COLS)]
        fertility = [[60 for _ in range(ROWS)] for _ in range(COLS)]
        self.farm = Farm(soil=soil, fertility=fertility, crops={}, placed={}, animals=[],
                         bed=(COLS//2-9, ROWS//2-1), bin=(COLS//2-2, ROWS//2-1), tv=(COLS//2-8, ROWS//2-1),
                         coop=(COLS//2+6, ROWS//2+2))
        self.farm_colliders: List[pg.Rect] = self.make_farm_colliders()

        # shipping
        self.shipping: Dict[str,int] = {}

        # npcs
        self.npcs = {"Ava":{"x": COLS//2*TILE, "y": (ROWS//2-8)*TILE, "scene":"farm", "hearts": 0, "wander": 0.0}}

        # ui/effects
        self.toast_msg=""; self.toast_timer=0.0
        self.inventory_open=False; self.fishing_state=None
        self.action_cd = 0.0; self.effects: List[Dict] = []
        self.autosave_timer = 45.0

        # starter items
        self.give("parsnip_seeds", 6); self.give("turnip_seeds", 5); self.give("potato_seeds", 3)
        self.give("fertilizer", 4); self.give("sprinkler_copper", 1)

        self.quests.add("ship_parsnips", "Ship 3 Parsnips", {"parsnip": 3})
        self.time.weather, self.time.tomorrow = self.roll_weather(self.time.season())

        # Menu/Settings state
        self.menu_open = False
        self.settings_open = False
        self._dragging_minimap = False
        self._drag_offset = (0,0)

    # ---------------- Inventory helpers (HOTBAR ITEMS FIX) -------------------
    def inventory_items_sorted(self) -> List[Tuple[str,int]]:
        return sorted([(k,v) for k,v in self.player.inv.items() if v>0], key=lambda kv: DATA_ITEMS.get(kv[0],{"name":kv[0]})["name"].lower())

    def hotbar_item_at_slot(self, slot_index: int) -> Optional[str]:
        if slot_index < 5: return None
        items = self.inventory_items_sorted()
        idx = slot_index - 5
        if 0 <= idx < len(items): return items[idx][0]
        return None

    # ---------------- Utility ----------------
    def make_farm_colliders(self) -> List[pg.Rect]:
        hx,hy = self.farm.house_pos; hw,hh = self.farm.house_size
        door = self.farm.house_door
        rects = []
        for x in range(hx, hx+hw):
            for y in range(hy, hy+hh):
                is_edge = x in (hx, hx+hw-1) or y in (hy, hy+hh-1)
                if not is_edge: continue
                if (x,y)==door: continue
                rects.append(rect_from_tile(x,y))
        return rects

    def collide_player(self):
        pr = self.player.rect()
        for r in self.farm_colliders:
            if r.colliderect(pr) and self.scene=="farm":
                dx = (r.centerx - pr.centerx); dy = (r.centery - pr.centery)
                if abs(dx) > abs(dy):
                    if dy>0: self.player.y = r.top - pr.h/2 - 1
                    else:    self.player.y = r.bottom + pr.h/2 + 1
                else:
                    if dx>0: self.player.x = r.left - pr.w/2 - 1
                    else:    self.player.x = r.right + pr.w/2 + 1

    def give(self, item: str, qty=1): self.player.inv[item]= self.player.inv.get(item,0)+qty
    def take(self, item: str, qty=1) -> bool:
        have=self.player.inv.get(item,0)
        if have>=qty:
            new=have-qty
            if new: self.player.inv[item]=new
            else: self.player.inv.pop(item, None)
            return True
        return False

    def toast(self, msg: str, sec=2.0): self.toast_msg=msg; self.toast_timer=sec
    def tile_under_mouse(self) -> Tuple[int,int]:
        mx,my = pg.mouse.get_pos(); return mx//TILE, my//TILE
    def front_tile(self) -> Tuple[int,int]:
        px, py = int(self.player.x)//TILE, int(self.player.y)//TILE
        tx, ty = px + self.player.fx, py + self.player.fy
        tx = max(0, min(COLS-1, tx)); ty = max(0, min(ROWS-1, ty))
        return tx, ty
    def target_tile(self) -> Tuple[int,int]: return self.front_tile() if self.aim_mode == "front" else self.tile_under_mouse()
    def in_reach(self, tx:int, ty:int) -> bool:
        px, py = int(self.player.x)//TILE, int(self.player.y)//TILE
        return max(abs(px-tx), abs(py-ty)) <= REACH_TILES
    def current_hotbar_tool(self) -> Optional[str]:
        i=self.player.hotbar_index; return ["hoe","can","rod","pick","axe"][i] if 0<=i<5 else None

    def current_hotbar_item(self) -> Optional[str]:
        return self.hotbar_item_at_slot(self.player.hotbar_index)

    def selected_name(self) -> str:
        if self.player.hotbar_index < 5:
            tool_names = ["Hoe","Watering Can","Fishing Rod","Pickaxe","Axe"]; return tool_names[self.player.hotbar_index]
        item = self.current_hotbar_item()
        if item and item in DATA_ITEMS: return DATA_ITEMS[item].get("name", item)
        return "(empty)"

    # --------------- Save/Load ---------------
    def save(self):
        # Build farm payload with stringified (x,y) keys for JSON safety
        fdat = {
            "soil": self.farm.soil,
            "fertility": self.farm.fertility,
            "crops": {f"{x},{y}": asdict(c) for (x,y), c in self.farm.crops.items()},
            "placed": {f"{x},{y}": name for (x,y), name in self.farm.placed.items()},
            "animals": [asdict(a) for a in self.farm.animals],
            "bed": self.farm.bed,
            "bin": self.farm.bin,
            "tv": self.farm.tv,
            "coop": self.farm.coop,
            "house_pos": self.farm.house_pos,
            "house_size": self.farm.house_size,
            "house_door": self.farm.house_door,
        }
        data={
            "save_version": SAVE_VERSION, "keys": self.keys, "time": asdict(self.time),
            "player": {"x":self.player.x, "y":self.player.y, "fx":self.player.fx, "fy":self.player.fy,
                       "gold":self.player.gold, "energy":self.player.energy, "hp":self.player.hp,
                       "tools": self.player.tools, "inv": self.player.inv},
            "farm": fdat, "npcs": self.npcs, "shipping": self.shipping,
            "scene": self.scene, "skills": asdict(self.skills), "eco": {"day": self.eco.day, "drift": self.eco.drift},
            "quests": {"active": self.quests.active, "completed": self.quests.completed},
            "opts": {"show_minimap": self.show_minimap, "minimap_pos": self.minimap_pos, "minimap_size": self.minimap_size}
        }
        try:
            with open(SAVE_FILE,"w") as f: json.dump(data,f)
            self.toast("Saved.")
        except Exception as e:
            self.toast(f"Save failed: {e}")

    def load(self):
        if not os.path.exists(SAVE_FILE): self.toast("No save found."); return
        with open(SAVE_FILE) as f: data=json.load(f)
        self.keys = data.get("keys", DEFAULT_KEYS.copy())
        self.time = TimeState(**data["time"])
        p=data["player"]
        self.player.x,self.player.y=p["x"],p["y"]; self.player.fx,self.player.fy=p.get("fx",0),p.get("fy",1)
        self.player.gold=p["gold"]; self.player.energy=p["energy"]; self.player.hp=p.get("hp",MAX_HP)
        self.player.tools=p.get("tools", self.player.tools); self.player.inv=p.get("inv", {})
        fdat=data["farm"]

        def tupkey(d):
            out={}
            for k,v in d.items():
                if isinstance(k, str):
                    k2 = k.strip("() ")
                    parts = [int(x) for x in k2.split(",")]
                    out[(parts[0], parts[1])] = v
                else:
                    out[k]=v
            return out

        crops = {k: Crop(**v) for k,v in tupkey(fdat.get("crops", {})).items()}
        placed = tupkey(fdat.get("placed", {}))
        self.farm = Farm(
            soil=fdat["soil"], fertility=fdat["fertility"], crops=crops, placed=placed,
            animals=[Animal(**a) for a in fdat.get("animals",[])],
            bed=tuple(fdat.get("bed", (COLS//2-9, ROWS//2-1))),
            bin=tuple(fdat.get("bin", (COLS//2-2, ROWS//2-1))),
            tv =tuple(fdat.get("tv",  (COLS//2-8, ROWS//2-1))),
            coop=tuple(fdat.get("coop",(COLS//2+6, ROWS//2+2))),
            house_pos=tuple(fdat.get("house_pos", (COLS//2-14, ROWS//2-4))),
            house_size=tuple(fdat.get("house_size", (6,4))),
            house_door=tuple(fdat.get("house_door", (COLS//2-11, ROWS//2)))
        )
        self.farm_colliders = self.make_farm_colliders()
        self.npcs=data.get("npcs", self.npcs); self.shipping=data.get("shipping", {})
        self.scene=data.get("scene","farm")
        sk=data.get("skills", {}); self.skills = Skills(**{k:sk.get(k,0) for k in ("farming","mining","fishing","fxp","mxp","hxp")})
        eco=data.get("eco", {}); self.eco.day = eco.get("day", self.eco.day); self.eco.drift = eco.get("drift", self.eco.drift)
        q = data.get("quests", {}); self.quests.active = q.get("active", {}); self.quests.completed = q.get("completed", [])
        opts = data.get("opts",{})
        self.show_minimap = opts.get("show_minimap", True)
        self.minimap_pos = tuple(opts.get("minimap_pos", self.minimap_pos))
        self.minimap_size = tuple(opts.get("minimap_size", self.minimap_size))
        self.toast("Loaded.")

    # --------------- Daily Tick ---------------
    def roll_weather(self, season:str) -> Tuple[str,str]:
        rnd = random.Random(self.time.day*1234 + self.time.season_idx*777)
        rprob = 0.35 if season=="spring" else 0.2 if season=="summer" else 0.25 if season=="fall" else 0.15
        snow = (season=="winter" and rnd.random()<0.30)
        w_tom = "snow" if snow else ("rain" if rnd.random()<rprob else "clear")
        snow2 = (season=="winter" and random.random()<0.30)
        w_today = "snow" if snow2 else ("rain" if random.random()<rprob else "clear")
        return w_today, w_tom

    def sleep(self):
        earnings=0
        for item,qty in list(self.shipping.items()):
            base = DATA_ITEMS.get(item,{}).get("sell",0)
            cat = CATEGORY_OF.get(item, "crops")
            price = int(round(base * self.eco.drift.get(cat,1.0)))
            earnings += price*qty
        self.quests.bump_ship(self.shipping)
        self.player.gold += earnings; self.shipping.clear()

        self.time.day += 1; self.eco.day = self.time.day
        if self.time.day>28: self.time.day=1; self.time.season_idx=(self.time.season_idx+1)%4
        self.time.minutes = 6*60; self.time.weekday = (self.time.weekday+1)%7
        s=self.time.season(); self.time.weather, self.time.tomorrow = self.roll_weather(s)

        for x in range(COLS):
            for y in range(ROWS):
                if self.farm.soil[x][y]==2 and self.time.weather=="clear": self.farm.soil[x][y]=1

        for (x,y),name in list(self.farm.placed.items()):
            if not name.startswith("sprinkler_"): continue
            tiles=[]
            if name=="sprinkler_copper": tiles=[(x, y),(x-1,y),(x+1,y),(x,y-1),(x,y+1)]
            elif name=="sprinkler_iron": tiles=[(x+dx,y+dy) for dx in (-1,0,1) for dy in (-1,0,1)]
            elif name=="sprinkler_gold": tiles=[(x+dx,y+dy) for dx in (-2,-1,0,1,2) for dy in (-2,-1,0,1,2)]
            for tx,ty in tiles:
                if 0<=tx<COLS and 0<=ty<ROWS and self.farm.soil[tx][ty] in (1,2):
                    self.farm.soil[tx][ty]=2; c=self.farm.crops.get((tx,ty))
                    if c: c.watered=True

        self.eco.roll()

        for (x,y),c in list(self.farm.crops.items()):
            if SEASONS[self.time.season_idx] not in DATA_CROPS[c.kind]["seasons"]:
                del self.farm.crops[(x,y)]; continue
            fert = self.farm.fertility[x][y]
            fert_bonus = max(0.0, (fert-50)/180.0)
            base_risk = 0.025; risk = max(0.0, base_risk - (fert-50)/500.0)
            if self.time.weather in ("rain","snow"): risk *= 0.75
            c.next_day(self.time.weather in ("rain","snow"), fert_bonus=fert_bonus, disease_chance=risk)

        for a in self.farm.animals:
            a.produced = False
            if a.fed: a.happy=min(1.0, a.happy+0.05)
            else: a.happy=max(0.0, a.happy-0.08)
            a.fed=False

        base=270 + self.skills.farming*2; self.player.energy=min(MAX_ENERGY, base)
        self.toast(f"Day {self.time.day} {WEEKDAYS[self.time.weekday]} — {self.time.season().title()} — {self.time.weather.title()}  +{earnings}g", 3.0)
        self.save()

    # --------------- Interaction ---------------
    def try_house_enter_exit(self, click=False):
        if self.scene=="farm":
            tx,ty=self.target_tile()
            if (tx,ty)==self.farm.house_door and click:
                self.fade.to(1.0); self.scene="house"
                hx,hy=self.farm.house_pos; hw,hh=self.farm.house_size
                self.player.x=( (hx+hw//2)*TILE + TILE//2 ); self.player.y=( (hy+hh-2)*TILE + TILE//2 )
                self.toast("Entered house"); return True
        elif self.scene=="house":
            if click:
                hx,hy=self.farm.house_pos; hw,hh=self.farm.house_size
                door_px=(hx+hw//2)*TILE + TILE//2
                doorway=pg.Rect(door_px-14, (hy+hh-1)*TILE-6, 28, 18)
                if doorway.colliderect(self.player.rect()):
                    self.fade.to(1.0); self.scene="farm"
                    dx,dy=self.farm.house_door; self.player.x=dx*TILE+TILE//2; self.player.y=(dy+1)*TILE+TILE//2
                    self.toast("Left house"); return True
        return False

    def harvest_tile(self, tx:int, ty:int) -> bool:
        c=self.farm.crops.get((tx,ty))
        if not c or not c.mature(): return False
        fert=self.farm.fertility[tx][ty]
        qroll = random.random() + (fert-50)/150.0 + self.skills.farming*0.02
        if qroll>1.15: suffix="_gold"
        elif qroll>0.95: suffix="_silver"
        else: suffix=""
        out_id = c.kind+suffix if suffix else c.kind
        self.give(out_id,1); self.skills.add("farming", 5)
        self.farm.fertility[tx][ty] = max(10, self.farm.fertility[tx][ty] - (8 if suffix=="" else 10))
        del self.farm.crops[(tx,ty)]; self.toast(f"Harvested {DATA_ITEMS[out_id]['name']}"); return True

    def current_valid_item(self) -> Optional[str]:
        if self.player.hotbar_index<5: return None
        return self.current_hotbar_item()

    def start_fishing(self):
        self.fishing_state = {"t":0.0, "win":False, "cursor":0.0, "fish": random.uniform(0.2,0.8), "dir":1}
        self.toast("Fishing… press SPACE to catch!")

    def update_fishing(self, dt: float):
        if not self.fishing_state: return
        st=self.fishing_state
        st["t"] += dt; st["fish"] += (random.uniform(-0.4,0.4))*dt; st["fish"] = clamp(st["fish"], 0.1, 0.9)
        st["cursor"] += st["dir"]*dt*0.5
        if st["cursor"]>1.0: st["cursor"]=1.0; st["dir"]*=-1
        if st["cursor"]<0.0: st["cursor"]=0.0; st["dir"]*=-1
        if st["t"]>4.0: self.toast("Fish escaped"); self.fishing_state=None

    def resolve_fishing_key(self):
        if not self.fishing_state: return
        st=self.fishing_state
        if abs(st["cursor"]-st["fish"])<0.08: self.skills.add("fishing", 6); self.toast("Caught a fish (stub)"); self.fishing_state=None
        else: self.toast("Too early/late!")

    def use_tool_or_item(self):
        if self.action_cd > 0: return
        tx, ty = self.target_tile()
        if not (0 <= tx < COLS and 0 <= ty < ROWS): return
        if self.scene=="farm" and (tx,ty)==self.farm.house_door:
            self.try_house_enter_exit(click=True); return
        if not self.in_reach(tx, ty): self.toast("Out of reach"); return
        did=False
        tool = self.current_hotbar_tool()
        if tool and self.scene in ("farm","mine","forest","mountain","beach","town","house"):
            crop_here = self.farm.crops.get((tx,ty)) if self.scene=="farm" else None
            if crop_here and crop_here.mature(): did |= self.harvest_tile(tx,ty)
            elif tool=="hoe" and self.scene=="farm":
                if self.farm.soil[tx][ty]==0:
                    self.farm.soil[tx][ty]=1; self.player.energy=max(0,self.player.energy-2); did=True; self.skills.add("farming",1)
            elif tool=="can" and self.scene=="farm":
                if self.farm.soil[tx][ty] in (1,2):
                    self.farm.soil[tx][ty]=2; c=self.farm.crops.get((tx,ty))
                    if c: c.watered=True
                    self.player.energy=max(0,self.player.energy-1); did=True
            elif tool=="pick" and self.scene in ("mine","mountain"):
                got=False
                if random.random()<0.75: self.give("stone",1); got=True
                r=random.random()+self.skills.mining*0.02
                if r<0.20: pass
                elif r<0.45: self.give("copper_ore",1); got=True
                elif r<0.65: self.give("iron_ore",1); got=True
                else: self.give("gold_ore",1); got=True
                if got: self.skills.add("mining", 3); self.toast("+ore"); did=True
            elif tool=="axe" and self.scene in ("forest","farm"):
                self.give("wood",1); self.toast("+wood"); did=True
            elif tool=="rod" and self.scene in ("farm","beach"):
                if (tx,ty) in WATER_TILES.get("farm_pond",[]): self.start_fishing(); did=True
            if did: self.action_cd = max(0.12, 0.18 - self.skills.farming*0.005); self.effects.append({"x": tx*TILE+TILE//2, "y": ty*TILE+TILE//2, "t": 0.15})
            return

        # ----- ITEM USE (Planting) -----
        item = self.current_valid_item()
        if item and item in self.player.inv and self.scene=="farm":
            info=DATA_ITEMS[item]; kind=info.get("kind")
            if kind=="seed":
                crop=info["crop"]
                if SEASONS[self.time.season_idx] not in DATA_CROPS[crop]["seasons"]:
                    self.toast("Out of season")
                elif self.farm.soil[tx][ty] in (1,2) and (tx,ty) not in self.farm.crops:
                    self.farm.crops[(tx,ty)]=Crop(crop); self.take(item,1); did=True; self.toast(f"Planted {DATA_ITEMS[item]['name']}")
            elif kind=="placeable":
                if (tx,ty) not in self.farm.placed: self.farm.placed[(tx,ty)] = item; self.take(item,1); did=True
            elif kind=="fertilizer":
                if self.farm.soil[tx][ty] in (1,2):
                    delta = 14 if item=="fertilizer" else 24
                    self.farm.fertility[tx][ty] = min(100, self.farm.fertility[tx][ty] + delta); self.take(item,1); did=True; self.toast("Fertility +")
            if did: self.action_cd = 0.18; self.effects.append({"x": tx*TILE+TILE//2, "y": ty*TILE+TILE//2, "t": 0.15})

    def interact(self):
        px,py = int(self.player.x)//TILE, int(self.player.y)//TILE
        tx, ty = self.target_tile()
        if self.scene=="farm" and (tx,ty)==self.farm.house_door:
            if self.try_house_enter_exit(click=True): return
        if self.scene=="house":
            if self.try_house_enter_exit(click=True): return
        bx,by = self.farm.bed
        if self.scene=="farm" and abs(px-bx)<=1 and abs(py-by)<=1: self.sleep(); return
        sx,sy = self.farm.bin
        if self.scene=="farm" and abs(px-sx)<=1 and abs(py-sy)<=1: self.open_shipping(); return
        tvx,tvy = self.farm.tv
        if self.scene=="farm" and abs(px-tvx)<=1 and abs(py-tvy)<=1: self.tv_ui(); return
        cx,cy = self.farm.coop
        if self.scene=="farm" and abs(px-cx)<=1 and abs(py-cy)<=1: self.coop_ui(); return
        if self.scene=="town": self.shop_ui(); return
        for name,data in self.npcs.items():
            if data["scene"]!=self.scene: continue
            nr = pg.Rect(int(data["x"])-12,int(data["y"])-12,24,24)
            if nr.colliderect(self.player.rect().inflate(24,24)): self.dialogue.say(random.choice(DATA_NPCS[name]["dialogue"]["greet"])); return

    # ---------------------- UI Panels ---------------------------------------
    def open_shipping(self):
        running=True; items=list(self.player.inv.keys()); idx=0
        while running:
            for ev in pg.event.get():
                if ev.type==pg.QUIT: pg.quit(); sys.exit(0)
                if ev.type==pg.KEYDOWN:
                    if ev.key in (pg.K_ESCAPE, self.keys["interact"]): running=False
                    if ev.key in (pg.K_RIGHT, pg.K_d): idx=(idx+1)%max(1,len(items))
                    if ev.key in (pg.K_LEFT, pg.K_a): idx=(idx-1)%max(1,len(items))
                    if ev.key in (pg.K_RETURN, pg.K_SPACE) and items:
                        item=items[idx]
                        if DATA_ITEMS.get(item,{}).get("sell",0)>0 and self.take(item,1):
                            self.shipping[item]=self.shipping.get(item,0)+1
                            if self.player.inv.get(item,0)==0: items=list(self.player.inv.keys()); idx=min(idx, max(0,len(items)-1))
            self.draw()
            panel=pg.Rect(WIDTH//2-300, HEIGHT//2-140, 600, 260)
            pg.draw.rect(screen, UI_BG, panel, border_radius=12); pg.draw.rect(screen, UI_ACC, panel,2, border_radius=12)
            draw_text(screen, "Shipping Bin — ENTER: deposit, E: close", (panel.x+16,panel.y+12))
            draw_text(screen, f"Queued: {sum(self.shipping.values())} items", (panel.x+16,panel.y+40))
            if items:
                item=items[idx]; info=DATA_ITEMS.get(item,{})
                draw_text(screen, f"Select: {info.get('name',item)}  x{self.player.inv.get(item,0)}  (sells {info.get('sell',0)}g)", (panel.x+16,panel.y+80))
            else: draw_text(screen, "Inventory empty", (panel.x+16,panel.y+80))
            pg.display.flip(); clock.tick(FPS)

    def tv_ui(self):
        running=True
        while running:
            for ev in pg.event.get():
                if ev.type==pg.QUIT: pg.quit(); sys.exit(0)
                if ev.type==pg.KEYDOWN and ev.key in (pg.K_ESCAPE, self.keys["interact"], self.keys["use"]): running=False
            self.draw()
            panel=pg.Rect(WIDTH//2-280, HEIGHT//2-120, 560, 220)
            pg.draw.rect(screen, UI_BG, panel, border_radius=12); pg.draw.rect(screen, UI_ACC, panel,2, border_radius=12)
            draw_text(screen, "TV Weather — press E to close", (panel.x+16,panel.y+12))
            draw_text(screen, f"Today:   {self.time.weather.title()}", (panel.x+16,panel.y+60), YELLOW)
            draw_text(screen, f"Tomorrow:{self.time.tomorrow.title()}", (panel.x+16,panel.y+96), YELLOW)
            pg.display.flip(); clock.tick(FPS)

    def coop_ui(self):
        running=True
        while running:
            for ev in pg.event.get():
                if ev.type==pg.QUIT: pg.quit(); sys.exit(0)
                if ev.type==pg.KEYDOWN:
                    if ev.key in (pg.K_ESCAPE, self.keys["interact"]): running=False
                    if ev.key in (pg.K_f, pg.K_SPACE):
                        if self.take("fiber", 1):
                            for a in self.farm.animals: a.fed=True; self.toast("Fed the chickens.")
                        else: self.toast("Need fiber to feed (placeholder hay)")
            self.draw()
            panel=pg.Rect(WIDTH//2-300, HEIGHT//2-140, 600, 260)
            pg.draw.rect(screen, UI_BG, panel, border_radius=12); pg.draw.rect(screen, UI_ACC, panel,2, border_radius=12)
            draw_text(screen, "Coop — F: feed all (uses 1 fiber)", (panel.x+16,panel.y+12))
            y=60
            if not self.farm.animals: draw_text(screen, "(No animals yet — future feature)", (panel.x+16,y))
            for a in self.farm.animals: draw_text(screen, f"{a.name}  happy:{int(a.happy*100)}%  fed:{a.fed}", (panel.x+16,y)); y+=26
            pg.display.flip(); clock.tick(FPS)

    # --------------- Shop ----------------------------------------
    def shop_ui(self):
        base=["parsnip_seeds","turnip_seeds","potato_seeds","fertilizer","quality_fertilizer"]
        wk=self.time.weekday
        if wk in (1,4): base += ["sprinkler_copper"]
        if wk in (2,5): base += ["sprinkler_iron"]
        if wk==6: base += ["sprinkler_gold"]
        stock=base
        idx=0; running=True
        def cat_price(it):
            info=DATA_ITEMS[it]
            p=info.get("price", info.get("sell",10))
            cat = CATEGORY_OF.get(it, "res")
            return int(round(p * (self.eco.drift.get(cat,1.0))))
        while running:
            for ev in pg.event.get():
                if ev.type==pg.QUIT: pg.quit(); sys.exit(0)
                if ev.type==pg.KEYDOWN:
                    if ev.key in (pg.K_ESCAPE, self.keys["interact"]): running=False
                    if ev.key in (pg.K_LEFT, pg.K_a): idx=(idx-1)%len(stock)
                    if ev.key in (pg.K_RIGHT, pg.K_d): idx=(idx+1)%len(stock)
                    if ev.key in (pg.K_RETURN, pg.K_SPACE):
                        it=stock[idx]; price=cat_price(it)
                        if self.player.gold>=price:
                            self.player.gold-=price; self.give(it,1); self.toast("Purchased")
                        else: self.toast("Not enough gold")
            self.draw()
            panel=pg.Rect(WIDTH//2-320, HEIGHT//2-140, 640, 260)
            pg.draw.rect(screen, UI_BG, panel, border_radius=12); pg.draw.rect(screen, UI_ACC, panel,2, border_radius=12)
            draw_text(screen, "Shop — ←/→ select, ENTER buy, E close", (panel.x+16,panel.y+12))
            it=stock[idx]; info=DATA_ITEMS[it]
            price=cat_price(it)
            draw_text(screen, f"{info['name']} — {price}g", (panel.x+16,panel.y+60))
            draw_text(screen, f"Stock rotates by weekday ({WEEKDAYS[self.time.weekday]})", (panel.x+16,panel.y+96))
            pg.display.flip(); clock.tick(FPS)

    # --------------- Menu & Settings ----------------------------------------
    def draw_menu(self):
        panel = pg.Rect(WIDTH//2-240, HEIGHT//2-220, 480, 440)
        pg.draw.rect(screen, UI_BG, panel, border_radius=16); pg.draw.rect(screen, UI_ACC, panel, 2, border_radius=16)
        draw_text(screen, "Pause Menu", (panel.x+16, panel.y+12), WHITE, BIG)
        btns = [("Resume", self.menu_action_resume), ("Settings", self.menu_action_settings),
                ("Save", self.save), ("Load", self.load), ("Quit", self.menu_action_quit)]
        self._menu_buttons = []
        y = panel.y+64
        for label, _ in btns:
            r = pg.Rect(panel.x+40, y, panel.w-80, 56)
            pg.draw.rect(screen, (48,48,54), r, border_radius=10); pg.draw.rect(screen, UI_ACC, r, 2, border_radius=10)
            draw_text(screen, label, (r.x+18, r.y+16), YELLOW)
            self._menu_buttons.append((r, label))
            y += 72
        draw_text(screen, "Tip: Shift+M to quickly move the minimap", (panel.x+20, panel.bottom-32), UI_ACC)
    def menu_action_resume(self): self.menu_open=False; self.settings_open=False
    def menu_action_settings(self): self.settings_open=True
    def menu_action_quit(self): pg.quit(); sys.exit(0)

    def draw_settings(self):
        panel = pg.Rect(WIDTH//2-320, HEIGHT//2-260, 640, 520)
        pg.draw.rect(screen, UI_BG, panel, border_radius=16); pg.draw.rect(screen, UI_ACC, panel, 2, border_radius=16)
        draw_text(screen, "Settings", (panel.x+16, panel.y+12), WHITE, BIG)
        tog_rect = pg.Rect(panel.x+24, panel.y+64, 28, 28)
        pg.draw.rect(screen, (48,48,54), tog_rect, border_radius=6); 
        if self.show_minimap: pg.draw.rect(screen, YELLOW, tog_rect.inflate(-6,-6), border_radius=4)
        draw_text(screen, "Show Minimap", (tog_rect.right+12, tog_rect.y+4))
        draw_text(screen, "Minimap Size", (panel.x+24, panel.y+116))
        sizes = [("Small", (160,120)), ("Medium",(200,150)), ("Large",(260,190))]
        self._size_buttons=[]
        x = panel.x+24; y=panel.y+142
        for label, sz in sizes:
            r=pg.Rect(x,y,120,36)
            sel = (self.minimap_size==sz)
            pg.draw.rect(screen, (60,60,66) if not sel else (80,80,88), r, border_radius=8)
            pg.draw.rect(screen, UI_ACC, r, 2, border_radius=8)
            draw_text(screen, label, (r.x+10, r.y+8))
            self._size_buttons.append((r, sz))
            x += 140
        draw_text(screen, "Drag the minimap to reposition it. Position is saved.", (panel.x+24, panel.y+200), UI_ACC)
        back = pg.Rect(panel.centerx-80, panel.bottom-64, 160, 44)
        pg.draw.rect(screen, (48,48,54), back, border_radius=10); pg.draw.rect(screen, UI_ACC, back, 2, border_radius=10)
        draw_text(screen, "Back", (back.x+56, back.y+10))
        self._settings_back = back
        self._settings_checkbox = tog_rect

    # --------------- Input ---------------
    def handle_event(self, ev):
        if ev.type==pg.QUIT: pg.quit(); sys.exit(0)

        # Minimap dragging
        if ev.type==pg.MOUSEBUTTONDOWN and ev.button==1:
            if (self.settings_open or self.minimap_quick_edit) and self.show_minimap:
                r = self.minimap.rect(self.minimap_pos, self.minimap_size)
                if r.collidepoint(ev.pos):
                    self._dragging_minimap=True
                    self._drag_offset = (ev.pos[0]-r.x, ev.pos[1]-r.y)
        if ev.type==pg.MOUSEBUTTONUP and ev.button==1:
            if self._dragging_minimap:
                self._dragging_minimap=False
                self.save()
        if ev.type==pg.MOUSEMOTION and self._dragging_minimap:
            mx,my = ev.pos
            nx = mx - self._drag_offset[0]; ny = my - self._drag_offset[1]
            w,h = self.minimap_size
            nx = clamp(nx, 8, WIDTH - w - 8); ny = clamp(ny, 8, HEIGHT - h - 8)
            self.minimap_pos = (nx, ny)

        if ev.type==pg.KEYDOWN:
            if ev.key==DEFAULT_KEYS["fullscreen"]:
                self.fullscreen=not self.fullscreen
                pg.display.set_mode((WIDTH,HEIGHT), pg.FULLSCREEN if self.fullscreen else 0)

            if ev.key==self.keys["minimap_quick_edit"] and (pg.key.get_mods() & pg.KMOD_SHIFT):
                self.minimap_quick_edit = not self.minimap_quick_edit
                self.toast("Minimap edit ON" if self.minimap_quick_edit else "Minimap edit OFF")

            if ev.key==self.keys["pause"]:
                if self.settings_open:
                    self.settings_open=False; self.menu_open=False
                else:
                    self.menu_open = not self.menu_open
                return

            if self.menu_open and not self.settings_open:
                if ev.key==pg.K_RETURN: self.menu_open=False
                return
            if self.settings_open:
                return

            if ev.key==self.keys["inv"]: self.inventory_open=not self.inventory_open
            if ev.key==self.keys["craft"]: self.open_crafting()
            if ev.key==self.keys["interact"]:
                if self.dialogue.visible: self.dialogue.hide()
                else: self.interact()
            if ev.key==self.keys["aim_toggle"]:
                self.aim_mode = "mouse" if self.aim_mode=="front" else "front"; self.toast(f"Aim: {self.aim_mode}")
            if ev.key==self.keys["save"]: self.save()
            if ev.key==self.keys["load"]: self.load()
            if ev.key==self.keys["debug"]: self.debug = not self.debug
            if ev.key==self.keys["quests"]: self.show_quests = not self.show_quests
            if ev.key==self.keys["use"]:
                if self.fishing_state: self.resolve_fishing_key()
                elif self.action_cd<=0: self.use_tool_or_item()
            if ev.key in (pg.K_1,pg.K_2,pg.K_3,pg.K_4,pg.K_5,pg.K_6,pg.K_7,pg.K_8,pg.K_9,pg.K_0):
                self.player.hotbar_index = (ev.key - pg.K_1) % 10

        if ev.type==pg.MOUSEBUTTONDOWN:
            if ev.button==4: self.player.hotbar_index=(self.player.hotbar_index-1)%10
            if ev.button==5: self.player.hotbar_index=(self.player.hotbar_index+1)%10
            if ev.button==1 and not (self.menu_open or self.settings_open):
                if not self.try_house_enter_exit(click=True):
                    if self.action_cd<=0: self.use_tool_or_item()

        # Menu/Settings clicks
        if ev.type==pg.MOUSEBUTTONDOWN and ev.button==1:
            mx,my = ev.pos
            if self.menu_open and not self.settings_open:
                for r,label in getattr(self, "_menu_buttons", []):
                    if r.collidepoint((mx,my)):
                        {"Resume":self.menu_action_resume,"Settings":self.menu_action_settings,"Save":self.save,"Load":self.load,"Quit":self.menu_action_quit}[label]()
                        return
            if self.settings_open:
                if getattr(self, "_settings_checkbox", pg.Rect(0,0,0,0)).collidepoint((mx,my)):
                    self.show_minimap = not self.show_minimap; self.save()
                for r,sz in getattr(self, "_size_buttons", []):
                    if r.collidepoint((mx,my)):
                        self.minimap_size = sz; self.save()
                if getattr(self, "_settings_back", pg.Rect(0,0,0,0)).collidepoint((mx,my)):
                    self.settings_open=False; self.menu_open=True

    # --------------- Crafting ---------------
    def open_crafting(self):
        running=True; outs=list(DATA_RECIPES.keys()); idx=0
        while running:
            for ev in pg.event.get():
                if ev.type==pg.QUIT: pg.quit(); sys.exit(0)
                if ev.type==pg.KEYDOWN:
                    if ev.key in (pg.K_ESCAPE, self.keys["craft"]): running=False
                    if ev.key in (pg.K_LEFT, pg.K_a): idx=(idx-1)%len(outs)
                    if ev.key in (pg.K_RIGHT, pg.K_d): idx=(idx+1)%len(outs)
                    if ev.key in (pg.K_RETURN, pg.K_SPACE):
                        out=outs[idx]; req=DATA_RECIPES[out]["req"]
                        ok=True
                        for it,q in req.items():
                            if self.player.inv.get(it,0)<q: ok=False; break
                        if ok:
                            for it,q in req.items(): self.take(it,q)
                            self.give(out,1); self.toast("Crafted!")
                        else: self.toast("Missing items")
            self.draw()
            panel=pg.Rect(WIDTH//2-300, HEIGHT//2-160, 600, 300)
            pg.draw.rect(screen, UI_BG, panel, border_radius=12); pg.draw.rect(screen, UI_ACC, panel,2, border_radius=12)
            draw_text(screen, "Crafting — ←/→ select, ENTER craft, C close", (panel.x+16,panel.y+12))
            out=outs[idx]; req=DATA_RECIPES[out]["req"]
            draw_text(screen, f"{out}", (panel.x+16,panel.y+52), YELLOW)
            y=82
            for it,q in req.items(): draw_text(screen, f"{it} x{q}  (have {self.player.inv.get(it,0)})", (panel.x+26,y)); y+=24
            pg.display.flip(); clock.tick(FPS)

    # --------------- Update ---------------------------------------------------
    def update(self, dt: float):
        if not self.paused and not self.menu_open and not self.settings_open:
            self.time.advance(dt)
            self.fade.update(dt)
            if self.fade.target > 0.5 and self.fade.alpha > 0.98: self.fade.to(0.0)
            if self.action_cd>0: self.action_cd=max(0.0, self.action_cd-dt)
            self.effects=[{**e, "t":e["t"]-dt} for e in self.effects if e["t"]-dt>0]
            self.update_fishing(dt); self.fx.update(dt, self.time.weather)
            # autosave disabled by default; uncomment if desired
            # self.autosave_timer -= dt
            # if self.autosave_timer<=0: self.autosave_timer=45.0; self.save()
            self.update_npcs(dt)
        if self.toast_timer>0: self.toast_timer-=dt

    def update_npcs(self, dt: float):
        for name,dat in self.npcs.items():
            if dat["scene"]!=self.scene: continue
            dat["wander"] -= dt
            if dat["wander"]<=0: dat["wander"] = random.uniform(1.0, 3.0); dat["dx"] = random.uniform(-1,1); dat["dy"] = random.uniform(-1,1)
            sp = 60.0; dat["x"] += dat.get("dx",0)*sp*dt; dat["y"] += dat.get("dy",0)*sp*dt
            dat["x"] = clamp(dat["x"], 16, WIDTH-16); dat["y"] = clamp(dat["y"], 48, HEIGHT-16)

    def move_player(self, dt: float):
        if self.paused or self.menu_open or self.settings_open: return
        keys=pg.key.get_pressed()
        dx=(keys[self.keys["right"]] or keys[pg.K_RIGHT])-(keys[self.keys["left"]] or keys[pg.K_LEFT])
        dy=(keys[self.keys["down"]]  or keys[pg.K_DOWN]) -(keys[self.keys["up"]]   or keys[pg.K_UP])
        mag=math.hypot(dx,dy) or 1
        sp = (220 * (0.8 if self.player.energy<40 else 1.0))
        self.player.x += (dx/mag)*sp*dt; self.player.y += (dy/mag)*sp*dt
        if dx or dy: self.player.fx = 1 if dx>0 else (-1 if dx<0 else 0); self.player.fy = 1 if dy>0 else (-1 if dy<0 else 0)
        self.player.x = clamp(self.player.x, 16, WIDTH-16); self.player.y = clamp(self.player.y, 48, HEIGHT-16)

        if self.scene=="farm":
            if self.player.x>WIDTH-8:  self.scene_swap("town");     self.player.x=20
            if self.player.x<8:        self.scene_swap("forest");   self.player.x=WIDTH-20
            if self.player.y<48:       self.scene_swap("mountain"); self.player.y=HEIGHT-20
            if self.player.y>HEIGHT-8: self.scene_swap("beach");    self.player.y=60
            self.collide_player()
        elif self.scene=="town" and self.player.x<8: self.scene_swap("farm"); self.player.x=WIDTH-20
        elif self.scene=="forest" and self.player.x>WIDTH-8: self.scene_swap("farm"); self.player.x=20
        elif self.scene=="mountain" and self.player.y>HEIGHT-8: self.scene_swap("farm"); self.player.y=60
        elif self.scene=="beach" and self.player.y<48: self.scene_swap("farm"); self.player.y=HEIGHT-20

    def scene_swap(self, to_scene:str): self.fade.to(1.0); self.scene = to_scene; self.toast(f"{to_scene.title()}")

    # ------------------------------- Draw ------------------------------------
    def draw_world(self):
        if self.scene=="farm":
            season=self.time.season(); bg1=SNOW if season=="winter" else GRASS1; bg2=SNOW if season=="winter" else GRASS2
        elif self.scene=="town": bg1=bg2=(90,110,160)
        elif self.scene=="forest": bg1=bg2=FOREST
        elif self.scene=="mountain": bg1=bg2=MOUNTAIN
        elif self.scene=="beach": bg1=bg2=SAND
        elif self.scene=="house": bg1=bg2=(80,70,60)
        else: bg1=bg2=GRASS1

        for x in range(COLS):
            for y in range(ROWS):
                color = bg1 if (x+y)%2==0 else bg2
                pg.draw.rect(screen, color, (x*TILE, y*TILE, TILE, TILE))

        if self.scene=="farm":
            for (x,y) in WATER_TILES["farm_pond"]: pg.draw.rect(screen, WATER, (x*TILE, y*TILE, TILE, TILE))
            hx,hy=self.farm.house_pos; hw,hh=self.farm.house_size
            house_rect=pg.Rect(hx*TILE, hy*TILE, hw*TILE, hh*TILE)
            pg.draw.rect(screen, (140,110,80), house_rect, border_radius=6)
            pg.draw.rect(screen, (120,60,40), (house_rect.x, house_rect.y-8, house_rect.w, 12))
            dx,dy=self.farm.house_door; pg.draw.rect(screen, (70,40,20), (dx*TILE+8, dy*TILE, TILE-16, TILE))
            for x in range(COLS):
                for y in range(ROWS):
                    st=self.farm.soil[x][y]
                    if st in (1,2):
                        pg.draw.rect(screen, (DIRT if st==1 else WET), (x*TILE+2,y*TILE+2,TILE-4,TILE-4), border_radius=4)
                        f=self.farm.fertility[x][y]; idx=min(len(FERT_COLORS)-1, max(0, f//20))
                        tint=pg.Surface((TILE-6, TILE-6), pg.SRCALPHA); tr,tg,tb=FERT_COLORS[idx]; tint.fill((tr,tg,tb,40))
                        screen.blit(tint,(x*TILE+3,y*TILE+3))
            for (x,y),c in self.farm.crops.items():
                r=pg.Rect(x*TILE+6,y*TILE+6,TILE-12,TILE-12)
                if c.diseased and not c.mature(): pg.draw.rect(screen, RED, r, 2, border_radius=6)
                if c.mature(): pg.draw.rect(screen, YELLOW, r, border_radius=6)
                else:
                    need=DATA_CROPS[c.kind]['stages'][c.stage]
                    h=int(((c.stage + c.in_stage_days/max(1,need)) / len(DATA_CROPS[c.kind]['stages'])) * (TILE-12))
                    rr=pg.Rect(r.x, r.bottom-h, r.w, h); pg.draw.rect(screen, (120,200,120), rr, border_radius=4)
            for (x,y),name in self.farm.placed.items():
                color = (ORANGE if name=="chest" else GRAY if name=="furnace" else (90,130,190) if name.startswith("sprinkler_") else (120,110,90))
                pg.draw.rect(screen, color, (x*TILE+2,y*TILE+2,TILE-4,TILE-4), border_radius=6)
                if name.startswith("sprinkler_"): pg.draw.circle(screen, (200,220,255), (x*TILE+TILE//2, y*TILE+TILE//2), 3)

        elif self.scene=="house":
            for x in range(COLS):
                for y in range(ROWS):
                    pg.draw.rect(screen, (96,84,70) if (x+y)%2==0 else (104,92,78), (x*TILE, y*TILE, TILE, TILE))
            pg.draw.rect(screen, (180,140,120), (4*TILE, 3*TILE, TILE*2, TILE))
            pg.draw.rect(screen, (220,200,200), (4*TILE+6, 3*TILE+6, TILE-12, TILE-12))
            hx,hy=self.farm.house_pos; hw,hh=self.farm.house_size
            door_px=(hx+hw//2)*TILE + TILE//2
            pg.draw.rect(screen, (60,50,40), (door_px-14, (hy+hh-1)*TILE-6, 28, 18))

        for name,data in self.npcs.items():
            if data["scene"]!=self.scene: continue
            pg.draw.rect(screen, VIOLET, (int(data["x"])-12,int(data["y"])-12,24,24), border_radius=6)

        if self.scene!="house":
            tx,ty = self.target_tile()
            if 0<=tx<COLS and 0<=ty<ROWS:
                color = HILITE_OK if self.in_reach(tx,ty) else HILITE_BAD
                pg.draw.rect(screen, color, (tx*TILE+2, ty*TILE+2, TILE-4, TILE-4), 2, border_radius=6)

        pg.draw.rect(screen, BLUE, self.player.rect(), border_radius=6)

        h = (self.time.minutes//60)%24; night = 0.0
        if 0<=h<5: night = 0.6
        elif 5<=h<7: night = 0.4
        elif 18<=h<21: night = 0.35
        elif 21<=h<=24: night = 0.6
        if night>0:
            shade = pg.Surface((WIDTH, HEIGHT), pg.SRCALPHA); shade.fill((0,0,0, int(255*night)))
            screen.blit(shade,(0,0))

        self.fx.draw(screen)

    def draw_inventory_grid(self):
        panel = pg.Rect(WIDTH//2-360, HEIGHT//2-240, 720, 480)
        pg.draw.rect(screen, UI_BG, panel, border_radius=12); pg.draw.rect(screen, UI_ACC, panel, 2, border_radius=12)
        draw_text(screen, "Inventory — I to close", (panel.x+16, panel.y+12), WHITE, BIG)
        cols, rows = 6, 5; cell = 96; x0, y0 = panel.x+24, panel.y+56
        items = self.inventory_items_sorted(); idx = 0
        for r in range(rows):
            for c in range(cols):
                rect = pg.Rect(x0+c*cell, y0+r*cell, cell-12, cell-12)
                pg.draw.rect(screen, (42,42,44), rect, border_radius=8)
                if idx < len(items):
                    it,qt = items[idx]; nm = DATA_ITEMS.get(it, {"name":it})["name"]
                    draw_text(screen, nm[:14], (rect.x+8, rect.y+8)); draw_text(screen, f"x{qt}", (rect.right-46, rect.bottom-28), YELLOW)
                idx += 1

    def draw_fishing_ui(self):
        if not self.fishing_state: return
        st = self.fishing_state
        panel = pg.Rect(WIDTH//2-260, HEIGHT-160, 520, 120)
        pg.draw.rect(screen, UI_BG, panel, border_radius=12); pg.draw.rect(screen, UI_ACC, panel,2, border_radius=12)
        draw_text(screen, "Fishing — Press SPACE when the cursors overlap!", (panel.x+16,panel.y+12), YELLOW)
        bar = pg.Rect(panel.x+40, panel.y+60, panel.w-80, 12)
        pg.draw.rect(screen, (58,58,62), bar, border_radius=6)
        cursor_x = bar.x + int(bar.w * st["cursor"]); fish_x   = bar.x + int(bar.w * st["fish"])
        pg.draw.rect(screen, (80,200,100), (fish_x-10, bar.y-8, 20, bar.h+16), border_radius=6)
        pg.draw.rect(screen, (220,220,255), (cursor_x-2, bar.y-6, 4, bar.h+12), border_radius=2)

    def draw_ui(self):
        bar=pg.Rect(0,0, WIDTH, 36); pg.draw.rect(screen, UI_BG, bar)
        draw_text(screen, f"{self.scene.upper()} | {self.time.season().title()} Day {self.time.day} {WEEKDAYS[self.time.weekday]}  {self.time.clock_str()}  {self.time.weather.title()}",
                  (12,8))
        draw_text(screen, f"Gold:{self.player.gold}", (WIDTH-240,8)); draw_text(screen, f"E:{self.player.energy}", (WIDTH-140,8))
        draw_text(screen, f"Aim:{self.aim_mode}", (WIDTH-340,8))

        # Hotbar
        hb=pg.Rect(0, HEIGHT-52, WIDTH, 52); pg.draw.rect(screen, UI_BG, hb)
        tool_abbrev=["Hoe","Can","Rod","Pick","Axe"]
        items_sorted = self.inventory_items_sorted()
        for i in range(10):
            r=pg.Rect(16+i*64, HEIGHT-46, 56, 40); sel=(i==self.player.hotbar_index)
            pg.draw.rect(screen, UI_ACC, r, 0 if sel else 2, border_radius=8)
            draw_text(screen, str((i+1)%10), (r.x+2, r.y+2))
            if i<5:
                draw_text(screen, tool_abbrev[i], (r.x+8, r.y+16))
            else:
                item_id = self.hotbar_item_at_slot(i)
                if item_id:
                    name=DATA_ITEMS.get(item_id,{}).get("name", item_id)
                    qty = dict(items_sorted).get(item_id, self.player.inv.get(item_id,0))
                    draw_text(screen, (name[:6] + (f" x{qty}" if qty>1 else "")), (r.x+6, r.y+16))
                else:
                    draw_text(screen, "-", (r.x+24, r.y+16))

        draw_text(screen, f"Selected: {self.selected_name()}", (16, HEIGHT-80), YELLOW)
        if self.toast_timer>0 and self.toast_msg: draw_text(screen, self.toast_msg, (WIDTH//2-200, HEIGHT-84))
        if self.inventory_open: self.draw_inventory_grid()
        if self.show_quests: self.quests.draw_panel(screen)
        self.dialogue.draw(screen)
        self.draw_fishing_ui()

        if self.show_minimap:
            self.minimap_pos = self.minimap.draw(screen, self.scene, (int(self.player.x), int(self.player.y)), self.minimap_pos, self.minimap_size)
            if self.settings_open or self.minimap_quick_edit:
                r = self.minimap.rect(self.minimap_pos, self.minimap_size)
                for i in range(r.x, r.right, 10):
                    pg.draw.line(screen, UI_ACC, (i, r.y), (i+5, r.y), 1)
                    pg.draw.line(screen, UI_ACC, (i, r.bottom), (i+5, r.bottom), 1)
                for j in range(r.y, r.bottom, 10):
                    pg.draw.line(screen, UI_ACC, (r.x, j), (r.x, j+5), 1)
                    pg.draw.line(screen, UI_ACC, (r.right, j), (r.right, j+5), 1)
                draw_text(screen, "Drag to move", (r.x+8, r.y-22), UI_ACC)

        if self.menu_open and not self.settings_open: self.draw_menu()
        if self.settings_open: self.draw_settings()

        self.fade.draw(screen)
        pg.display.flip()

    def draw(self):
        screen.fill(BLACK)
        self.draw_world()
        self.draw_ui()

# ------------------------------- Main ---------------------------------------
def main():
    game=Game(); last=time.time()
    while True:
        now=time.time(); dt=now-last; last=now
        for ev in pg.event.get(): game.handle_event(ev)
        game.move_player(dt)
        game.update(dt)
        game.draw()
        clock.tick(FPS)

if __name__=="__main__":
    ensure_self_updated_then_continue()
    main()
