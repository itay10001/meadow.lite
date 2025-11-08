"""
MeadowLite++ — progression/stable edition (single file)

What's new & fixed:
- Stable save path (next to EXE) + forced working directory
- Crash logger shows message box + writes crash.log on errors (double-click friendly)
- Quests & progression (ship totals, bridge repair, furnace, sprinklers, bulk shipment,
  farming level), with tangible rewards & gates
- Multi-scene world: farm, house, town, forest, mountain, beach, mine
- House entry/exit + transitions fixed, planting/harvest stable
- Shop+ unlocks, Saturday market discount, fishing bonus, tiny house energy perk

Controls
  Move ............... WASD / Arrows
  Interact ........... E (context: bed, bin, TV, shop, bridge)
  Use tool/item ...... Space / Left Click
  Enter door ......... Left Click (or E) while facing the door tile
  Toggle aim ......... R (front ↔ mouse)
  Open crafting ...... C
  Save/Load .......... F5 / F9
  Hotbar ............. 1-0 or mouse wheel (1..5 tools, 6..10 items)
  Pause/Fullscreen ... P / F   |   Quit ESC
"""
from __future__ import annotations
import json, math, os, random, sys, time, traceback

# ------------------------------- App dir / paths ----------------------------
def app_dir() -> str:
    # Works in PyInstaller onefile and plain script
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

# Force working directory to the app folder so relative files work when double-clicked
os.chdir(app_dir())

SAVE_FILE = os.path.join(app_dir(), "meadow_save.json")
SAVE_VERSION = 5

# ------------------------------- Imports ------------------------------------
import pygame as pg

# ------------------------------- Globals ------------------------------------
WIDTH, HEIGHT = 1024, 640
TILE = 32
REACH_TILES = 2
COLS, ROWS = WIDTH // TILE, HEIGHT // TILE
FPS = 60

# Colors
WHITE=(240,240,240); BLACK=(16,16,20); UI_BG=(26,26,30); UI_ACC=(196,196,210)
GRASS1=(58,114,58); GRASS2=(68,132,68); DIRT=(120,86,60); WET=(76,112,150)
WATER=(60,120,180)
YELLOW=(240,210,90); RED=(220,80,80); BLUE=(90,150,240)
ORANGE=(220,160,80); SNOW=(220,230,240); GRAY=(150,150,150)
GOLD=(230,200,60); SAND=(206,186,120); FOREST=(44,96,52); MOUNTAIN=(115,110,120)

# fertility tint scale (low→high)
FERT_COLORS=[(120,80,60),(140,100,70),(160,120,80),(180,140,90),(200,160,100),(220,180,110)]
# target highlight colors
HILITE_OK=(80,220,120)
HILITE_BAD=(235,90,90)

pg.init()
screen = pg.display.set_mode((WIDTH, HEIGHT))
pg.display.set_caption("MeadowLite++")
clock = pg.time.Clock()
FONT = pg.font.SysFont("consolas", 18)
BIG = pg.font.SysFont("consolas", 24, bold=True)

# ------------------------------- Data --------------------------------------
DATA_ITEMS = {
    # seeds
    "parsnip_seeds": {"name":"Parsnip Seeds","kind":"seed","crop":"parsnip","price":20},
    "turnip_seeds":  {"name":"Turnip Seeds","kind":"seed","crop":"turnip","price":30},
    # crops (quality tiers)
    "parsnip": {"name":"Parsnip","kind":"crop","sell":35},
    "parsnip_silver": {"name":"Parsnip (Silver)","kind":"crop","sell":44},
    "parsnip_gold": {"name":"Parsnip (Gold)","kind":"crop","sell":52},
    "turnip":  {"name":"Turnip","kind":"crop","sell":50},
    "turnip_silver":  {"name":"Turnip (Silver)","kind":"crop","sell":62},
    "turnip_gold":  {"name":"Turnip (Gold)","kind":"crop","sell":75},
    # resources & misc
    "fiber":   {"name":"Fiber","kind":"res","sell":2},
    "wood":    {"name":"Wood","kind":"res","sell":3},
    "stone":   {"name":"Stone","kind":"res","sell":2},
    "copper_ore": {"name":"Copper Ore","kind":"res","sell":8},
    "iron_ore": {"name":"Iron Ore","kind":"res","sell":12},
    "gold_ore": {"name":"Gold Ore","kind":"res","sell":25},
    # placeables / machines
    "path_tile": {"name":"Path Tile","kind":"placeable","price":0},
    "chest": {"name":"Chest","kind":"placeable","price":0},
    "furnace": {"name":"Furnace","kind":"placeable","price":0},
    "sprinkler_copper": {"name":"Sprinkler (Cu)","kind":"placeable","price":0},
    "sprinkler_iron": {"name":"Sprinkler (Fe)","kind":"placeable","price":0},
    "sprinkler_gold": {"name":"Sprinkler (Au)","kind":"placeable","price":0},
    # farming aids
    "fertilizer": {"name":"Basic Fertilizer","kind":"fertilizer","price":80},
    "quality_fertilizer": {"name":"Quality Fertilizer","kind":"fertilizer","price":160},
    # animal products
    "egg": {"name":"Egg","kind":"animal","sell":30},
    "egg_silver": {"name":"Egg (Silver)","kind":"animal","sell":38},
    "egg_gold": {"name":"Egg (Gold)","kind":"animal","sell":48},
}

DATA_CROPS = {
    "parsnip": {"stages": (1,2,2), "seasons": ("spring",)},
    "turnip":  {"stages": (2,2,2), "seasons": ("spring","fall")},
}

DATA_RECIPES = {
    "path_tile": {"req": {"stone": 2}},
    "chest":     {"req": {"wood": 20}},
    "furnace":   {"req": {"stone": 20, "copper_ore": 5}},
    "sprinkler_copper": {"req": {"copper_ore": 5, "stone": 5}},  # cross 5
    "sprinkler_iron":   {"req": {"iron_ore": 6, "stone": 10}},   # 3×3
    "sprinkler_gold":   {"req": {"gold_ore": 6, "stone": 12}},   # 5×5
    "fertilizer": {"req": {"fiber": 5, "stone": 1}},
    "quality_fertilizer": {"req": {"fiber": 10, "copper_ore": 1}},
}

DATA_NPCS = {
    "Ava": {
        "likes": ["parsnip","egg"],
        "dislikes": ["stone"],
        "dialogue": {"greet": ["Lovely day!", "Plant anything new?"], "rain":["Rain’s good for the soil."]},
    }
}

SEASONS = ("spring","summer","fall","winter")

# simple pond tiles (safe bounds)
pond_x0 = max(1, COLS//2-10)
WATER_TILES = {"farm_pond": [(pond_x0 + i, min(ROWS-2, ROWS//2+6)) for i in range(8) if 0 <= pond_x0+i < COLS]}

CATEGORY_OF = {
    "parsnip":"crops","turnip":"crops","parsnip_silver":"crops","parsnip_gold":"crops",
    "turnip_silver":"crops","turnip_gold":"crops",
    "wood":"res","stone":"res","fiber":"res","copper_ore":"res","iron_ore":"res","gold_ore":"res",
    "egg":"animal","egg_silver":"animal","egg_gold":"animal",
}

WEEKDAYS = ("Mon","Tue","Wed","Thu","Fri","Sat","Sun")
SCENES = ("farm","town","forest","mountain","beach","mine","house")

# ------------------------------- Progression --------------------------------
QUESTS = {
    "start": {
        "title": "Ship 300g",
        "desc": "Grow and ship crops until you've shipped 300g lifetime.",
        "check": "total_shipped>=300",
        "reward": "unlock_bridge"
    },
    "bridge": {
        "title": "Repair the North Bridge",
        "desc": "Bring 50 wood + 25 stone to the broken bridge at the north of the farm and press E.",
        "check": "flag:bridge_built",
        "reward": "unlock_mountain"
    },
    "furnace": {
        "title": "First Smelt",
        "desc": "Craft a Furnace in the Crafting menu (C).",
        "check": "flag:furnace_crafted",
        "reward": "shop_plus"
    },
    "sprinkler": {
        "title": "Go Automatic",
        "desc": "Place any sprinkler on the farm.",
        "check": "flag:any_sprinkler_placed",
        "reward": "house_upgrade_1"
    },
    "beach": {
        "title": "Bulk Shipment",
        "desc": "Ship 10 items in one day.",
        "check": "flag:bulk10",
        "reward": "fishing_bonus"
    },
    "market": {
        "title": "Market Day",
        "desc": "Reach Farming level 2.",
        "check": "skill:farming>=2",
        "reward": "market_unlocked"
    }
}
BRIDGE_X = COLS//2   # approx center at the top

# ------------------------------- Helpers ------------------------------------
def draw_text(surf, text, pos, color=WHITE, font=FONT):
    if not text:
        return
    img = font.render(str(text), True, color)
    surf.blit(img, pos)

# ------------------------------- Dataclasses --------------------------------
from dataclasses import dataclass, asdict, field
from typing import Dict, Tuple, Optional, List

@dataclass
class Crop:
    kind: str
    stage: int = 0
    in_stage_days: float = 0.0
    watered: bool = False
    diseased: bool = False
    def mature(self) -> bool:
        return self.stage >= len(DATA_CROPS[self.kind]["stages"])
    def next_day(self, raining: bool, fert_bonus: float = 0.0, disease_chance: float = 0.0):
        if not self.mature() and not self.diseased and random.random()<disease_chance:
            self.diseased = True
        if self.mature():
            self.watered = False
            return
        if self.watered or raining:
            stall = self.diseased and random.random()<0.66
            if not stall:
                speed = 1.0 + min(0.35, max(0.0, fert_bonus))
                self.in_stage_days += speed
                need = DATA_CROPS[self.kind]["stages"][self.stage]
                if self.in_stage_days + 1e-6 >= need:
                    self.stage += 1
                    self.in_stage_days = 0.0
                    if self.diseased and random.random()<0.35:
                        self.diseased = False
        self.watered = False

@dataclass
class Player:
    x: float
    y: float
    fx: int = 0
    fy: int = 1
    gold: int = 200
    energy: int = 270
    hp: int = 100
    hotbar_index: int = 0
    inv: Dict[str, int] = field(default_factory=dict)
    tools: Dict[str, int] = field(default_factory=lambda: {"hoe":1, "can":1, "rod":1, "pick":1, "axe":1})
    def rect(self) -> pg.Rect:
        return pg.Rect(int(self.x)-12, int(self.y)-12, 24, 24)

@dataclass
class Skills:
    farming:int=0; mining:int=0; fishing:int=0
    fxp:int=0; mxp:int=0; hxp:int=0
    def add(self, which:str, amt:int=1):
        if which=="farming":
            self.fxp+=amt; self.farming = min(10, self.farming + self.fxp//100); self.fxp%=100
        if which=="mining":
            self.mxp+=amt; self.mining  = min(10, self.mining  + self.mxp//100); self.mxp%=100
        if which=="fishing":
            self.hxp+=amt; self.fishing = min(10, self.fishing + self.hxp//100); self.hxp%=100

@dataclass
class Economy:
    day:int=1
    drift:Dict[str,float]=field(default_factory=lambda:{"crops":1.0,"res":1.0,"animal":1.0})
    def roll(self):
        for k,v in list(self.drift.items()):
            self.drift[k] = max(0.85, min(1.25, v + random.uniform(-0.05,0.05)))

@dataclass
class Farm:
    soil: List[List[int]]  # 0 grass, 1 tilled, 2 watered
    fertility: List[List[int]]  # 0..100
    crops: Dict[Tuple[int,int], Crop]
    placed: Dict[Tuple[int,int], str]
    bed: Tuple[int,int]
    bin: Tuple[int,int]
    tv: Tuple[int,int]
    # house on farm
    house_pos: Tuple[int,int] = (COLS//2-14, ROWS//2-4)
    house_size: Tuple[int,int] = (6,4)
    house_door: Tuple[int,int] = (COLS//2-11, ROWS//2)

@dataclass
class TimeState:
    day: int = 1
    season_idx: int = 0
    minutes: int = 6*60
    weather: str = "clear"
    weekday: int = 0
    tomorrow: str = "clear"
    def season(self) -> str:
        return SEASONS[self.season_idx]
    def advance(self, dt: float):
        self.minutes += int(dt * 6)  # 1s = 6 minutes
        if self.minutes >= (24+2)*60:
            self.minutes = 2*60
    def clock_str(self) -> str:
        h=(self.minutes//60)%24; m=self.minutes%60
        suff = "AM" if 0<=h<12 else "PM"
        h12 = h if 1<=h<=12 else (12 if h%12==0 else h%12)
        return f"{h12:02d}:{m:02d} {suff}"

# ------------------------------- Game ---------------------------------------
class Game:
    def __init__(self):
        self.time = TimeState()
        self.player = Player(WIDTH//2, HEIGHT//2)
        self.scene = "farm"
        self.fullscreen=False; self.paused=False
        self.aim_mode = "front"  # 'front' or 'mouse'
        self.skills = Skills()
        self.eco = Economy()
        # farm init
        soil = [[0 for _ in range(ROWS)] for _ in range(COLS)]
        fertility = [[60 for _ in range(ROWS)] for _ in range(COLS)]
        self.farm = Farm(soil=soil, fertility=fertility, crops={}, placed={},
                         bed=(COLS//2-9, ROWS//2-1), bin=(COLS//2-2, ROWS//2-1), tv=(COLS//2-8, ROWS//2-1))
        # shipping
        self.shipping: Dict[str,int] = {}
        # ui state
        self.toast_msg=""; self.toast_timer=0
        self.inventory_open=False; self.crafting_open=False
        self.fishing_state=None
        self.action_cd = 0.0
        self.effects: List[Dict] = []
        # starter items
        self.give("parsnip_seeds", 6)
        self.give("turnip_seeds", 4)
        self.give("fertilizer", 4)
        self.give("sprinkler_copper", 1)

        # --- PROGRESSION state ---
        self.flags = set()
        self.total_shipped = 0
        self.day_ship_count = 0
        self.active_quest = "start"

    # ---------------- Utility ----------------
    def give(self, item: str, qty=1):
        self.player.inv[item]= self.player.inv.get(item,0)+qty

    def take(self, item: str, qty=1) -> bool:
        have=self.player.inv.get(item,0)
        if have>=qty:
            new=have-qty
            if new: self.player.inv[item]=new
            else: self.player.inv.pop(item, None)
            return True
        return False

    def toast(self, msg: str, sec=2.0):
        self.toast_msg=msg; self.toast_timer=sec

    def tile_under_mouse(self) -> Tuple[int,int]:
        mx,my = pg.mouse.get_pos(); return mx//TILE, my//TILE

    def front_tile(self) -> Tuple[int,int]:
        px, py = int(self.player.x)//TILE, int(self.player.y)//TILE
        tx, ty = px + self.player.fx, py + self.player.fy
        tx = max(0, min(COLS-1, tx)); ty = max(0, min(ROWS-1, ty))
        return tx, ty

    def target_tile(self) -> Tuple[int,int]:
        return self.front_tile() if self.aim_mode == "front" else self.tile_under_mouse()

    def in_reach(self, tx:int, ty:int) -> bool:
        px, py = int(self.player.x)//TILE, int(self.player.y)//TILE
        return max(abs(px-tx), abs(py-ty)) <= REACH_TILES

    def current_hotbar_tool(self) -> Optional[str]:
        i=self.player.hotbar_index
        return ["hoe","can","rod","pick","axe"][i] if 0<=i<5 else None

    def current_hotbar_item(self) -> Optional[str]:
        return None if self.player.hotbar_index<5 else next(iter(self.player.inv.keys()), None)

    def selected_name(self) -> str:
        if self.player.hotbar_index < 5:
            tool_names = ["Hoe","Watering Can","Fishing Rod","Pickaxe","Axe"]
            return tool_names[self.player.hotbar_index]
        item = self.current_hotbar_item()
        if item and item in DATA_ITEMS:
            return DATA_ITEMS[item].get("name", item)
        return "(empty)"

    # --------------- Save/Load ---------------
    def encode_xy(self, p: Tuple[int,int]) -> str:
        x,y=p; return f"{x},{y}"
    def decode_xy(self, s: str) -> Tuple[int,int]:
        a,b = s.split(","); return int(a),int(b)

    def save(self):
        try:
            data={
                "save_version": SAVE_VERSION,
                "time": asdict(self.time),
                "player": {"x":self.player.x, "y":self.player.y, "fx":self.player.fx, "fy":self.player.fy,
                            "gold":self.player.gold, "energy":self.player.energy, "hp":self.player.hp,
                            "tools": self.player.tools, "inv": self.player.inv},
                "farm": {
                    "soil": self.farm.soil,
                    "fertility": self.farm.fertility,
                    "crops": { self.encode_xy(k): asdict(v) for k,v in self.farm.crops.items() },
                    "placed": { self.encode_xy(k): v for k,v in self.farm.placed.items() },
                    "bed": self.farm.bed, "bin": self.farm.bin, "tv": self.farm.tv,
                    "house_pos": self.farm.house_pos, "house_size": self.farm.house_size, "house_door": self.farm.house_door
                },
                "shipping": self.shipping,
                "scene": self.scene,
                "skills": asdict(self.skills),
                "eco": {"day": self.eco.day, "drift": self.eco.drift},
                "progress": {
                    "flags": list(self.flags),
                    "total_shipped": self.total_shipped,
                    "day_ship_count": self.day_ship_count,
                    "active_quest": self.active_quest
                }
            }
            with open(SAVE_FILE,"w") as f: json.dump(data,f)
            self.toast("Saved.")
        except Exception as e:
            self.toast(f"Save failed: {e}")

    def load(self):
        if not os.path.exists(SAVE_FILE):
            self.toast("No save found.")
            return
        with open(SAVE_FILE) as f: data=json.load(f)
        self.time = TimeState(**data["time"])
        p=data["player"]
        self.player.x,self.player.y=p["x"],p["y"]
        self.player.fx,self.player.fy=p.get("fx",0),p.get("fy",1)
        self.player.gold=p["gold"]; self.player.energy=p["energy"]; self.player.hp=p.get("hp",100)
        self.player.tools=p.get("tools", self.player.tools)
        self.player.inv=p.get("inv", {})
        fdat=data["farm"]
        self.farm = Farm(
            soil=fdat["soil"], fertility=fdat["fertility"],
            crops={ self.decode_xy(k): Crop(**v) for k,v in fdat.get("crops",{}).items() },
            placed={ self.decode_xy(k): v for k,v in fdat.get("placed",{}).items() },
            bed=tuple(fdat.get("bed", (COLS//2-9, ROWS//2-1))),
            bin=tuple(fdat.get("bin", (COLS//2-2, ROWS//2-1))),
            tv =tuple(fdat.get("tv",  (COLS//2-8, ROWS//2-1))),
            house_pos=tuple(fdat.get("house_pos", (COLS//2-14, ROWS//2-4))),
            house_size=tuple(fdat.get("house_size", (6,4))),
            house_door=tuple(fdat.get("house_door", (COLS//2-11, ROWS//2)))
        )
        self.shipping=data.get("shipping", {})
        self.scene=data.get("scene","farm")
        sk=data.get("skills", {})
        self.skills = Skills(**{k:sk.get(k,0) for k in ("farming","mining","fishing","fxp","mxp","hxp")})
        eco=data.get("eco", {})
        self.eco.day = eco.get("day", self.eco.day)
        self.eco.drift = eco.get("drift", self.eco.drift)
        prog = data.get("progress", {})
        self.flags = set(prog.get("flags", []))
        self.total_shipped = prog.get("total_shipped", 0)
        self.day_ship_count = prog.get("day_ship_count", 0)
        self.active_quest = prog.get("active_quest", "start")
        self.toast("Loaded.")

    # ------------- PROGRESSION helpers -------------
    def set_flag(self, name: str):
        if name not in self.flags:
            self.flags.add(name)
            self.toast(f"Unlocked: {name.replace('_',' ').title()}", 3.0)

    def has_flag(self, name: str) -> bool:
        return name in self.flags

    def quest_ok(self, cond: str) -> bool:
        if cond.startswith("flag:"):
            return self.has_flag(cond.split(":",1)[1])
        if cond.startswith("skill:"):
            k, n = cond.split(":",1)[1].split(">=")
            return getattr(self.skills, k.strip(), 0) >= int(n)
        if cond.startswith("total_shipped"):
            return self.total_shipped >= int(cond.split(">=")[1])
        return False

    def grant_reward(self, r: str):
        if r == "unlock_bridge":
            self.set_flag("bridge_worksite")
        elif r == "unlock_mountain":
            self.set_flag("mountain_access")
        elif r == "shop_plus":
            self.set_flag("shop_plus")
        elif r == "house_upgrade_1":
            self.set_flag("house_upgrade_1")
        elif r == "fishing_bonus":
            self.set_flag("fishing_bonus")
        elif r == "market_unlocked":
            self.set_flag("market_unlocked")

    def check_quest_progress(self):
        q = QUESTS.get(self.active_quest)
        if not q: return
        if self.quest_ok(q["check"]):
            keys = list(QUESTS.keys())
            i = keys.index(self.active_quest)
            self.grant_reward(q["reward"])
            if i+1 < len(keys):
                self.active_quest = keys[i+1]
                self.toast("New Quest: " + QUESTS[self.active_quest]["title"], 3.0)
            else:
                self.active_quest = ""

    # --------------- Daily Tick ---------------
    def roll_weather(self, season:str) -> tuple[str,str]:
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
            price = int(round(base * self.eco.drift.get(cat, 1.0)))  # fixed extra paren
            earnings += price*qty
        # totals for quests
        shipped_count_today = sum(self.shipping.values())
        if shipped_count_today >= 10:
            self.set_flag("bulk10")
        self.day_ship_count = shipped_count_today
        self.total_shipped += earnings

        self.player.gold += earnings
        self.shipping.clear()
        self.time.day += 1
        self.eco.day = self.time.day
        if self.time.day>28:
            self.time.day=1; self.time.season_idx=(self.time.season_idx+1)%4
        self.time.minutes = 6*60
        self.time.weekday = (self.time.weekday+1)%7
        s=self.time.season()
        self.time.weather, self.time.tomorrow = self.roll_weather(s)
        for x in range(COLS):
            for y in range(ROWS):
                if self.farm.soil[x][y]==2 and self.time.weather=="clear":
                    self.farm.soil[x][y]=1
        # sprinklers
        for (x,y),name in list(self.farm.placed.items()):
            if name.startswith("sprinkler_"):
                tiles=[]
                if name=="sprinkler_copper":
                    tiles=[(x, y),(x-1,y),(x+1,y),(x,y-1),(x,y+1)]
                elif name=="sprinkler_iron":
                    tiles=[(x+dx,y+dy) for dx in (-1,0,1) for dy in (-1,0,1)]
                elif name=="sprinkler_gold":
                    tiles=[(x+dx,y+dy) for dx in (-2,-1,0,1,2) for dy in (-2,-1,0,1,2)]
                for tx,ty in tiles:
                    if 0<=tx<COLS and 0<=ty<ROWS and self.farm.soil[tx][ty] in (1,2):
                        self.farm.soil[tx][ty]=2
                        c=self.farm.crops.get((tx,ty))
                        if c: c.watered=True
        self.eco.roll()
        for (x,y),c in list(self.farm.crops.items()):
            if SEASONS[self.time.season_idx] not in DATA_CROPS[c.kind]["seasons"]:
                del self.farm.crops[(x,y)]
                continue
            fert = self.farm.fertility[x][y]
            fert_bonus = max(0.0, (fert-50)/180.0)
            base_risk = 0.025
            risk = max(0.0, base_risk - (fert-50)/500.0)
            if self.time.weather in ("rain","snow"): risk *= 0.75
            c.next_day(self.time.weather in ("rain","snow"), fert_bonus=fert_bonus, disease_chance=risk)
        base=270 + self.skills.farming*2
        if self.has_flag("house_upgrade_1"): base += 2
        self.player.energy=min(300, base)
        self.toast(f"Day {self.time.day} {WEEKDAYS[self.time.weekday]} — {self.time.season().title()} — {self.time.weather.title()}  +{earnings}g", 3.0)
        self.check_quest_progress()
        self.save()

    # --------------- Interaction ---------------
    def at_house_door(self) -> bool:
        if self.scene!="farm": return False
        tx,ty = self.target_tile()
        return (tx,ty)==self.farm.house_door

    def try_house_enter_exit(self, click=False):
        if self.scene=="farm":
            tx,ty=self.target_tile()
            if (tx,ty)==self.farm.house_door and (click or True):
                self.scene="house"
                hx,hy=self.farm.house_pos; hw,hh=self.farm.house_size
                self.player.x=( (hx+hw//2)*TILE + TILE//2 )
                self.player.y=( (hy+hh-1)*TILE + TILE//2 )
                self.toast("Entered house")
                return True
        elif self.scene=="house":
            hx,hy=self.farm.house_pos; hw,hh=self.farm.house_size
            door_px=(hx+hw//2)*TILE + TILE//2
            doorway=pg.Rect(door_px-14, (hy+hh-1)*TILE-6, 28, 18)
            if doorway.colliderect(self.player.rect()):
                self.scene="farm"
                dx,dy=self.farm.house_door
                self.player.x=dx*TILE+TILE//2
                self.player.y=(dy+1)*TILE+TILE//2
                self.toast("Left house")
                return True
        return False

    def harvest_tile(self, tx:int, ty:int) -> bool:
        c=self.farm.crops.get((tx,ty))
        if not c or not c.mature():
            return False
        fert=self.farm.fertility[tx][ty]
        qroll = random.random() + (fert-50)/150.0 + self.skills.farming*0.02
        if qroll>1.15: suffix="_gold"
        elif qroll>0.95: suffix="_silver"
        else: suffix=""
        out_id = c.kind+suffix if suffix else c.kind
        self.give(out_id,1)
        self.skills.add("farming", 5)
        self.farm.fertility[tx][ty] = max(10, self.farm.fertility[tx][ty] - (8 if suffix=="" else 10))
        del self.farm.crops[(tx,ty)]
        self.toast(f"Harvested {DATA_ITEMS[out_id]['name']}")
        return True

    def current_valid_item(self) -> Optional[str]:
        if self.player.hotbar_index<5:
            return None
        return next(iter(self.player.inv.keys()), None)

    def use_tool_or_item(self):
        if self.action_cd > 0: return
        tx, ty = self.target_tile()
        if not (0 <= tx < COLS and 0 <= ty < ROWS): return
        if self.scene=="farm" and (tx,ty)==self.farm.house_door:
            self.try_house_enter_exit(click=True); return
        if not self.in_reach(tx, ty):
            self.toast("Out of reach"); return
        did=False
        tool = self.current_hotbar_tool()
        if tool and self.scene in ("farm","mine","forest","mountain","beach","town"):
            crop_here = self.farm.crops.get((tx,ty)) if self.scene=="farm" else None
            if crop_here and crop_here.mature():
                did |= self.harvest_tile(tx,ty)
            elif tool=="hoe" and self.scene=="farm":
                if self.farm.soil[tx][ty]==0:
                    self.farm.soil[tx][ty]=1; self.player.energy=max(0,self.player.energy-2); did=True; self.skills.add("farming",1)
            elif tool=="can" and self.scene=="farm":
                if self.farm.soil[tx][ty] in (1,2):
                    self.farm.soil[tx][ty]=2
                    c=self.farm.crops.get((tx,ty))
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
                if got: self.skills.add("mining", 3)
                self.toast("+ore"); did=True
            elif tool=="axe" and self.scene in ("forest","farm"):
                amt = 2 if self.scene=="forest" else 1
                for _ in range(amt): self.give("wood",1)
                self.toast("+wood"); did=True
            elif tool=="rod" and self.scene in ("farm","beach"):
                if self.scene=="farm" and (tx,ty) in WATER_TILES.get("farm_pond",[]):
                    self.start_fishing(); did=True
                elif self.scene=="beach":
                    self.start_fishing(); did=True
            if did:
                self.action_cd = max(0.12, 0.18 - self.skills.farming*0.005)
                self.effects.append({"x": tx*TILE+TILE//2, "y": ty*TILE+TILE//2, "t": 0.15})
            return
        item = self.current_valid_item()
        if item and item in self.player.inv and self.scene=="farm":
            info=DATA_ITEMS[item]; kind=info.get("kind")
            if kind=="seed":
                crop=info["crop"]
                if SEASONS[self.time.season_idx] not in DATA_CROPS[crop]["seasons"]:
                    self.toast("Out of season")
                elif self.farm.soil[tx][ty] in (1,2) and (tx,ty) not in self.farm.crops:
                    self.farm.crops[(tx,ty)]=Crop(crop); self.take(item,1); did=True
            elif kind=="placeable":
                if (tx,ty) not in self.farm.placed:
                    self.farm.placed[(tx,ty)] = item; self.take(item,1); did=True
                    if item=="furnace": self.set_flag("furnace_crafted"); self.check_quest_progress()
                    if item.startswith("sprinkler_"): self.set_flag("any_sprinkler_placed"); self.check_quest_progress()
            elif kind=="fertilizer":
                if self.farm.soil[tx][ty] in (1,2):
                    delta = 14 if item=="fertilizer" else 24
                    self.farm.fertility[tx][ty] = min(100, self.farm.fertility[tx][ty] + delta)
                    self.take(item,1); did=True; self.toast("Fertility +")
            if did:
                self.action_cd = 0.18
                self.effects.append({"x": tx*TILE+TILE//2, "y": ty*TILE+TILE//2, "t": 0.15})

    def interact(self):
        px,py = int(self.player.x)//TILE, int(self.player.y)//TILE
        tx, ty = self.target_tile()

        # Bridge worksite at north of farm
        if self.scene=="farm":
            near_bridge = (py <= 1) and (abs(px - BRIDGE_X) <= 2)
            if near_bridge and self.has_flag("bridge_worksite") and not self.has_flag("bridge_built"):
                self.draw()
                panel=pg.Rect(WIDTH//2-260, HEIGHT//2-80, 520, 160)
                pg.draw.rect(screen, UI_BG, panel, border_radius=12); pg.draw.rect(screen, UI_ACC, panel,2, border_radius=12)
                draw_text(screen, "Broken Bridge — need 50 wood + 25 stone. ENTER repair, E cancel", (panel.x+16,panel.y+16))
                pg.display.flip()
                waiting=True
                while waiting:
                    for ev2 in pg.event.get():
                        if ev2.type==pg.QUIT: pg.quit(); sys.exit(0)
                        if ev2.type==pg.KEYDOWN:
                            if ev2.key in (pg.K_e, pg.K_ESCAPE): waiting=False
                            if ev2.key in (pg.K_RETURN, pg.K_SPACE):
                                if self.player.inv.get("wood",0)>=50 and self.player.inv.get("stone",0)>=25:
                                    for _ in range(50): self.take("wood",1)
                                    for _ in range(25): self.take("stone",1)
                                    self.set_flag("bridge_built"); self.set_flag("mountain_access")
                                    self.toast("Bridge repaired!"); self.check_quest_progress()
                                else:
                                    self.toast("Need 50 wood + 25 stone")
                                waiting=False
                return

        # house door from farm
        if self.scene=="farm" and (tx,ty)==self.farm.house_door:
            if self.try_house_enter_exit(click=True): return
        # bed
        bx,by = self.farm.bed
        if self.scene=="farm" and abs(px-bx)<=1 and abs(py-by)<=1:
            self.sleep(); return
        # shipping bin
        sx,sy = self.farm.bin
        if self.scene=="farm" and abs(px-sx)<=1 and abs(py-sy)<=1:
            self.open_shipping(); return
        # TV forecast
        tvx,tvy = self.farm.tv
        if self.scene=="farm" and abs(px-tvx)<=1 and abs(py-tvy)<=1:
            self.tv_ui(); return
        # town shop
        if self.scene=="town":
            self.shop_ui(); return

    def open_shipping(self):
        running=True; items=list(self.player.inv.keys()); idx=0
        while running:
            for ev in pg.event.get():
                if ev.type==pg.QUIT: pg.quit(); sys.exit(0)
                if ev.type==pg.KEYDOWN:
                    if ev.key in (pg.K_ESCAPE, pg.K_e): running=False
                    if ev.key in (pg.K_RIGHT, pg.K_d): idx=(idx+1)%max(1,len(items))
                    if ev.key in (pg.K_LEFT, pg.K_a): idx=(idx-1)%max(1,len(items))
                    if ev.key in (pg.K_RETURN, pg.K_SPACE) and items:
                        item=items[idx]
                        if DATA_ITEMS.get(item,{}).get("sell",0)>0 and self.take(item,1):
                            self.shipping[item]=self.shipping.get(item,0)+1
                            if self.player.inv.get(item,0)==0:
                                items=list(self.player.inv.keys()); idx=min(idx, max(0,len(items)-1))
            self.draw()
            panel=pg.Rect(WIDTH//2-300, HEIGHT//2-120, 600, 240)
            pg.draw.rect(screen, UI_BG, panel, border_radius=12); pg.draw.rect(screen, UI_ACC, panel,2, border_radius=12)
            draw_text(screen, "Shipping Bin — ENTER: deposit, E: close", (panel.x+16,panel.y+12))
            draw_text(screen, f"Queued: {sum(self.shipping.values())} items", (panel.x+16,panel.y+40))
            if items:
                item=items[idx]; info=DATA_ITEMS.get(item,{}); sell=info.get("sell",0)
                draw_text(screen, f"Select: {info.get('name',item)}  x{self.player.inv.get(item,0)}  (sells {sell}g)", (panel.x+16,panel.y+80))
            else:
                draw_text(screen, "Inventory empty", (panel.x+16,panel.y+80))
            pg.display.flip(); clock.tick(FPS)

    def tv_ui(self):
        running=True
        while running:
            for ev in pg.event.get():
                if ev.type==pg.QUIT: pg.quit(); sys.exit(0)
                if ev.type==pg.KEYDOWN and ev.key in (pg.K_ESCAPE, pg.K_e, pg.K_SPACE):
                    running=False
            self.draw()
            panel=pg.Rect(WIDTH//2-280, HEIGHT//2-120, 560, 220)
            pg.draw.rect(screen, UI_BG, panel, border_radius=12); pg.draw.rect(screen, UI_ACC, panel,2, border_radius=12)
            draw_text(screen, "TV Weather — press E to close", (panel.x+16,panel.y+12))
            draw_text(screen, f"Today:   {self.time.weather.title()}", (panel.x+16,panel.y+60), YELLOW)
            draw_text(screen, f"Tomorrow:{self.time.tomorrow.title()}", (panel.x+16,panel.y+96), YELLOW)
            pg.display.flip(); clock.tick(FPS)

    def shop_ui(self):
        base=["parsnip_seeds","turnip_seeds","fertilizer","quality_fertilizer"]
        wk=self.time.weekday
        if wk in (1,4): base += ["sprinkler_copper"]
        if wk in (2,5): base += ["sprinkler_iron"]
        if wk==6: base += ["sprinkler_gold"]
        stock=base
        if self.has_flag("shop_plus"):
            stock += ["sprinkler_copper","sprinkler_iron","quality_fertilizer"]
        idx=0; running=True
        def cat_price(it):
            info=DATA_ITEMS[it]
            p=info.get("price", info.get("sell",10))
            cat = CATEGORY_OF.get(it, "res")
            price = int(round(p * (self.eco.drift.get(cat,1.0))))
            if self.has_flag("market_unlocked") and self.time.weekday==5:
                price = int(price * 0.9)
            return max(1, price)
        while running:
            for ev in pg.event.get():
                if ev.type==pg.QUIT: pg.quit(); sys.exit(0)
                if ev.type==pg.KEYDOWN:
                    if ev.key in (pg.K_ESCAPE, pg.K_e): running=False
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
            if self.has_flag("market_unlocked") and self.time.weekday==5:
                draw_text(screen, "Market Day Discount!", (panel.x+16,panel.y+128), YELLOW)
            pg.display.flip(); clock.tick(FPS)

    # --------------- Crafting ---------------
    def open_crafting(self):
        running=True; outs=list(DATA_RECIPES.keys()); idx=0
        while running:
            for ev in pg.event.get():
                if ev.type==pg.QUIT: pg.quit(); sys.exit(0)
                if ev.type==pg.KEYDOWN:
                    if ev.key in (pg.K_ESCAPE, pg.K_c): running=False
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
                            if out=="furnace": self.set_flag("furnace_crafted"); self.check_quest_progress()
                        else:
                            self.toast("Missing items")
            self.draw()
            panel=pg.Rect(WIDTH//2-300, HEIGHT//2-140, 600, 260)
            pg.draw.rect(screen, UI_BG, panel, border_radius=12); pg.draw.rect(screen, UI_ACC, panel,2, border_radius=12)
            draw_text(screen, "Crafting — ←/→ select, ENTER craft, C close", (panel.x+16,panel.y+12))
            out=outs[idx]; req=DATA_RECIPES[out]["req"]
            draw_text(screen, f"{out}", (panel.x+16,panel.y+52), YELLOW)
            y=82
            for it,q in req.items():
                draw_text(screen, f"{it} x{q}  (have {self.player.inv.get(it,0)})", (panel.x+26,y)); y+=24
            pg.display.flip(); clock.tick(FPS)

    # --------------- Update / Draw ---------------
    def start_fishing(self):
        self.fishing_state = {"phase":"wait","timer": 1.0}
        self.toast("Fishing…")

    def update_fishing(self, dt: float):
        if not self.fishing_state: return
        st=self.fishing_state; st["timer"]-=dt
        if st["phase"]=="wait" and st["timer"]<=0:
            thresh = 0.65
            if self.has_flag("fishing_bonus"): thresh -= 0.10
            if random.random()+self.skills.fishing*0.03>thresh:
                self.skills.add("fishing", 4)
                self.toast("Caught a fish (stub)")
            else:
                self.toast("Fish escaped")
            self.fishing_state=None

    def update(self, dt: float):
        if not self.paused:
            self.time.advance(dt)
            if self.action_cd>0:
                self.action_cd=max(0.0, self.action_cd-dt)
            self.effects=[{**e, "t":e["t"]-dt} for e in self.effects if e["t"]-dt>0]
            self.update_fishing(dt)
        if self.toast_timer>0: self.toast_timer-=dt

    def move_player(self, dt: float):
        if self.paused: return
        keys=pg.key.get_pressed()
        dx=(keys[pg.K_d] or keys[pg.K_RIGHT])-(keys[pg.K_a] or keys[pg.K_LEFT])
        dy=(keys[pg.K_s] or keys[pg.K_DOWN])-(keys[pg.K_w] or keys[pg.K_UP])
        mag=math.hypot(dx,dy) or 1
        speed=220
        self.player.x += (dx/mag)*speed*dt
        self.player.y += (dy/mag)*speed*dt
        if dx or dy:
            self.player.fx = 1 if dx>0 else (-1 if dx<0 else 0)
            self.player.fy = 1 if dy>0 else (-1 if dy<0 else 0)
        self.player.x = max(16, min(WIDTH-16, self.player.x))
        self.player.y = max(16, min(HEIGHT-16, self.player.y))
        # world edge transitions (segment travel)
        if self.scene=="farm":
            if self.player.x>WIDTH-8:  self.scene="town";     self.player.x=20
            if self.player.x<8:        self.scene="forest";   self.player.x=WIDTH-20
            if self.player.y<8:
                if self.has_flag("mountain_access"):
                    self.scene="mountain"; self.player.y=HEIGHT-20
                else:
                    self.toast("A broken bridge blocks the way north.")
                    self.player.y = 12
            if self.player.y>HEIGHT-8: self.scene="beach";    self.player.y=20
        elif self.scene=="town" and self.player.x<8:
            self.scene="farm"; self.player.x=WIDTH-20
        elif self.scene=="forest" and self.player.x>WIDTH-8:
            self.scene="farm"; self.player.x=20
        elif self.scene=="mountain":
            if self.player.y>HEIGHT-8:
                self.scene="farm"; self.player.y=20
            if self.player.y<8:
                self.scene="mine"; self.player.y=HEIGHT-20
        elif self.scene=="mine" and self.player.y>HEIGHT-8:
            self.scene="mountain"; self.player.y=20
        elif self.scene=="beach" and self.player.y<8:
            self.scene="farm"; self.player.y=HEIGHT-20
        elif self.scene=="house":
            self.try_house_enter_exit()

    def draw_world(self):
        # background per scene
        if self.scene=="farm":
            season=self.time.season()
            bg1=SNOW if season=="winter" else GRASS1; bg2=SNOW if season=="winter" else GRASS2
        elif self.scene=="town":
            bg1=bg2=(90,110,160)
        elif self.scene=="forest":
            bg1=bg2=FOREST
        elif self.scene=="mountain":
            bg1=bg2=MOUNTAIN
        elif self.scene=="beach":
            bg1=bg2=SAND
        elif self.scene=="mine":
            bg1=bg2=(40,40,48)
        elif self.scene=="house":
            bg1=bg2=(80,70,60)
        else:
            bg1=bg2=GRASS1
        for x in range(COLS):
            for y in range(ROWS):
                color = bg1 if (x+y)%2==0 else bg2
                pg.draw.rect(screen, color, (x*TILE, y*TILE, TILE, TILE))

        if self.scene=="farm":
            # pond
            for (x,y) in WATER_TILES["farm_pond"]:
                pg.draw.rect(screen, WATER, (x*TILE, y*TILE, TILE, TILE))
            # house
            hx,hy=self.farm.house_pos; hw,hh=self.farm.house_size
            house_rect=pg.Rect(hx*TILE, hy*TILE, hw*TILE, hh*TILE)
            pg.draw.rect(screen, (140,110,80), house_rect, border_radius=6)
            pg.draw.rect(screen, (120,60,40), (house_rect.x, house_rect.y-8, house_rect.w, 12))
            dx,dy=self.farm.house_door
            pg.draw.rect(screen, (70,40,20), (dx*TILE+8, dy*TILE, TILE-16, TILE))
            # soil + fertility + crops + placed
            for x in range(COLS):
                for y in range(ROWS):
                    st=self.farm.soil[x][y]
                    if st in (1,2):
                        pg.draw.rect(screen, (DIRT if st==1 else WET), (x*TILE+2,y*TILE+2,TILE-4,TILE-4), border_radius=4)
                        f=self.farm.fertility[x][y]
                        idx=min(len(FERT_COLORS)-1, max(0, f//20))
                        tint=pg.Surface((TILE-6, TILE-6), pg.SRCALPHA)
                        tr,tg,tb=FERT_COLORS[idx]
                        tint.fill((tr,tg,tb,40))
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
                color = (ORANGE if name=="chest" else
                         GRAY if name=="furnace" else
                         (90,130,190) if name.startswith("sprinkler_") else (120,110,90))
                pg.draw.rect(screen, color, (x*TILE+2,y*TILE+2,TILE-4,TILE-4), border_radius=6)
                if name.startswith("sprinkler_"):
                    pg.draw.circle(screen, (200,220,255), (x*TILE+TILE//2, y*TILE+TILE//2), 3)
            # bridge visual
            bx=BRIDGE_X
            color = (110,90,70) if self.has_flag("bridge_built") else (90,50,40)
            for i in range(-2,3):
                xi = bx+i
                if 0 <= xi < COLS:
                    pg.draw.rect(screen, color, (xi*TILE, 0, TILE, 6))
            if not self.has_flag("bridge_built") and self.has_flag("bridge_worksite"):
                draw_text(screen, "Broken bridge (50 wood + 25 stone)", (max(0,(bx-6))*TILE, 10), ORANGE)

        elif self.scene=="house":
            for x in range(COLS):
                for y in range(ROWS):
                    pg.draw.rect(screen, (96,84,70) if (x+y)%2==0 else (104,92,78), (x*TILE, y*TILE, TILE, TILE))
            # bed
            pg.draw.rect(screen, (180,140,120), (4*TILE, 3*TILE, TILE*2, TILE))
            pg.draw.rect(screen, (220,200,200), (4*TILE+6, 3*TILE+6, TILE-12, TILE-12))
            # door area (bottom middle visual)
            hx,hy=self.farm.house_pos; hw,hh=self.farm.house_size
            door_px=(hx+hw//2)*TILE + TILE//2
            pg.draw.rect(screen, (60,50,40), (door_px-14, (hy+hh-1)*TILE-6, 28, 18))

        elif self.scene=="mountain":
            # draw mine doorway at top center
            door = pg.Rect((COLS//2-1)*TILE, 0, TILE*2, TILE)
            pg.draw.rect(screen, (40,40,50), door)

        # targeting highlight (not in house)
        if self.scene!="house":
            tx,ty = self.target_tile()
            if 0<=tx<COLS and 0<=ty<ROWS:
                color = HILITE_OK if self.in_reach(tx,ty) else HILITE_BAD
                pg.draw.rect(screen, color, (tx*TILE+2, ty*TILE+2, TILE-4, TILE-4), 2, border_radius=6)
        # player
        pg.draw.rect(screen, BLUE, self.player.rect(), border_radius=6)

    def draw_ui(self):
        bar=pg.Rect(0,0, WIDTH, 36)
        pg.draw.rect(screen, UI_BG, bar)
        draw_text(screen, f"{self.scene.upper()}  |  {self.time.season().title()} Day {self.time.day} {WEEKDAYS[self.time.weekday]}  {self.time.clock_str()}  {self.time.weather.title()}", (12,8))
        draw_text(screen, f"Gold:{self.player.gold}", (WIDTH-220,8))
        draw_text(screen, f"Energy:{self.player.energy}", (WIDTH-120,8))
        draw_text(screen, f"Aim:{self.aim_mode}", (WIDTH-320,8))
        # quest hint
        if self.active_quest:
            q = QUESTS[self.active_quest]
            draw_text(screen, f"Quest: {q['title']}", (12, 36), YELLOW)

        hb=pg.Rect(0, HEIGHT-48, WIDTH, 48)
        pg.draw.rect(screen, UI_BG, hb)
        tool_abbrev=["Hoe","Can","Rod","Pick","Axe"]
        for i in range(10):
            r=pg.Rect(16+i*64, HEIGHT-42, 56, 36)
            sel=(i==self.player.hotbar_index)
            pg.draw.rect(screen, UI_ACC, r, 0 if sel else 2, border_radius=8)
            draw_text(screen, str((i+1)%10), (r.x+2, r.y+2))
            if i<5:
                draw_text(screen, tool_abbrev[i], (r.x+18, r.y+10))
            else:
                itm=self.current_hotbar_item()
                if itm:
                    name=DATA_ITEMS.get(itm,{}).get("name", itm)
                    draw_text(screen, name[:6], (r.x+12, r.y+10))
        draw_text(screen, f"Selected: {self.selected_name()}", (16, HEIGHT-70), YELLOW)
        if self.toast_timer>0 and self.toast_msg:
            draw_text(screen, self.toast_msg, (WIDTH//2-160, HEIGHT-76))

    def draw(self):
        screen.fill(BLACK)
        self.draw_world()
        self.draw_ui()
        pg.display.flip()

    # --------------- Input ----------------
    def handle_event(self, ev):
        if ev.type==pg.KEYDOWN:
            if ev.key==pg.K_ESCAPE: pg.quit(); sys.exit(0)
            if ev.key==pg.K_p: self.paused=not self.paused
            if ev.key==pg.K_f:
                self.fullscreen=not self.fullscreen
                pg.display.set_mode((WIDTH,HEIGHT), pg.FULLSCREEN if self.fullscreen else 0)
            if ev.key==pg.K_i: self.inventory_open=not self.inventory_open
            if ev.key==pg.K_c: self.open_crafting()
            if ev.key==pg.K_e: self.interact()
            if ev.key==pg.K_r:
                self.aim_mode = "mouse" if self.aim_mode=="front" else "front"
                self.toast(f"Aim: {self.aim_mode}")
            if ev.key==pg.K_F5: self.save()
            if ev.key==pg.K_F9: self.load()
            if ev.key in (pg.K_1,pg.K_2,pg.K_3,pg.K_4,pg.K_5,pg.K_6,pg.K_7,pg.K_8,pg.K_9,pg.K_0):
                self.player.hotbar_index = (ev.key - pg.K_1) % 10
            if ev.key==pg.K_SPACE:
                if self.action_cd<=0: self.use_tool_or_item()
        if ev.type==pg.MOUSEBUTTONDOWN:
            if ev.button==1:  # LMB: try door first, then use
                if not self.try_house_enter_exit(click=True):
                    if self.action_cd<=0: self.use_tool_or_item()
            if ev.button==4: self.player.hotbar_index=(self.player.hotbar_index-1)%10
            if ev.button==5: self.player.hotbar_index=(self.player.hotbar_index+1)%10

# ------------------------------- Main ---------------------------------------
def main():
    random.seed(42)
    game=Game(); last=time.time()
    while True:
        now=time.time(); dt=now-last; last=now
        for ev in pg.event.get():
            if ev.type==pg.QUIT: pg.quit(); sys.exit(0)
            game.handle_event(ev)
        game.move_player(dt)
        game.update(dt)
        game.draw()
        clock.tick(FPS)

if __name__=="__main__":
    try:
        main()
    except Exception as e:
        # Write crash log next to the EXE/script and show a Windows message box
        log_path = os.path.join(app_dir(), "crash.log")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"{e}\n\nA crash.log was written to:\n{log_path}",
                "MeadowLite++ crashed",
                0x00000010  # MB_ICONHAND
            )
        except Exception:
            pass
        raise
