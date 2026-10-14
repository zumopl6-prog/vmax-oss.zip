# -*- coding: utf-8 -*-
# ==========================================
# VMAX Module: Ban Rim Pa Map (แผนที่หมู่บ้านริมป่า)
# ==========================================
# โมดูลแผนที่ใหม่ 1 ไฟล์ ใช้แพทเทิร์นเดียวกับ vmax_module_viewpoint.py / ad_overlay:
# ไม่แก้/ไม่ทับโค้ดเดิมสักบรรทัด แค่ attach(globals()) ก่อน sio.run(...)
#
# ที่มา: แกะ "โครงสร้าง" จากแผนที่หมู่บ้านชนบทริมป่าในภาพตัวอย่าง (ถนนสายหลักตัดกลางแมพ,
# หมู่บ้านผังซอยเฉียงทางตะวันตกเฉียงเหนือ, วัดกลางสี่แยก, ป่าทึบด้านเหนือ, สวนลำไย, นาข้าว,
# บ่อปลา, เหมืองทรายมุมขวาล่าง) แล้ว "สร้างใหม่เอง" เป็นข้อมูลเรขาคณิต 2D ล้วนๆ
# -> ไม่ได้คัดลอกภาพดาวเทียม/ข้อมูลแผนที่ใดๆ  ชื่อสถานที่ทั้งหมดเป็นชื่อสมมติ
#
# ของที่ "เปลี่ยน/เพิ่ม" จากต้นแบบ (ตามที่ขอ "เปลี่ยนอะไรนิดหน่อย"):
#   - เปลี่ยนชื่อทุกสถานที่ + ตัดโลโก้/ร้านจริงออก
#   - เพิ่มหอสังเกตการณ์กลางป่า, ค่ายเหมืองทราย, จุด spawn 4 จุด, จุด exfil 3 จุด
#   - เพิ่มตารางพื้นผิว (ความเร็ว/ที่กำบัง) + nav grid + A* pathfinding
#   - ผังบ้านสร้างแบบ procedural จาก seed คงที่ (ได้ผลเหมือนเดิมทุกครั้ง)
#
# หน่วย: 1 unit = 1 พิกเซลของแผนที่ต้นแบบที่ครอปแล้ว  โลก = 1080 x 1980  (origin มุมซ้ายบน, y ลงล่าง)
#
# ใช้งานแบบ standalone (ไม่ต้องมีเกม):
#   python vmax_module_ban_rimpa_map.py --svg rimpa.svg --json rimpa.json --stats
#
# ต่อเข้าไฟล์หลัก: ดู attach() ด้านล่าง — วางไฟล์นี้ข้างๆ สคริปต์หลักแล้วเรียกก่อน sio.run()

from __future__ import annotations

import heapq
import json
import math
import os
import random
import threading
import time

MAP_ID = "ban_rimpa"
MAP_NAME = "Ban Rim Pa (หมู่บ้านริมป่า)"
WORLD_W = 1080
WORLD_H = 1980
MAP_SEED = int(os.environ.get("VMAX_RIMPA_SEED", "20261013"))
PLAYER_RADIUS_DEFAULT = 4.0

# ข้อมูลดิบด้านล่างวัดมาจากภาพ (พิกัดพิกเซลภาพ) แล้วลบ Y0 ตอนแปลง เพื่อตัดแถบ UI ด้านบนออก
_Y0 = 120

TERRAIN = {
    "water":    {"speed": 0.00, "cover": 0.00, "walkable": False, "label": "บ่อน้ำ"},
    "building": {"speed": 0.00, "cover": 1.00, "walkable": False, "label": "อาคาร"},
    "road":     {"speed": 1.00, "cover": 0.00, "walkable": True,  "label": "ถนน/ซอย"},
    "dirt":     {"speed": 1.00, "cover": 0.00, "walkable": True,  "label": "ลานดิน"},
    "temple":   {"speed": 1.00, "cover": 0.10, "walkable": True,  "label": "เขตวัด"},
    "village":  {"speed": 0.95, "cover": 0.15, "walkable": True,  "label": "ชุมชน"},
    "quarry":   {"speed": 0.85, "cover": 0.05, "walkable": True,  "label": "เหมืองทราย"},
    "forest":   {"speed": 0.80, "cover": 0.65, "walkable": True,  "label": "ป่า"},
    "orchard":  {"speed": 0.90, "cover": 0.35, "walkable": True,  "label": "สวนลำไย"},
    "rice":     {"speed": 0.65, "cover": 0.10, "walkable": True,  "label": "นาข้าว"},
    "grass":    {"speed": 0.95, "cover": 0.10, "walkable": True,  "label": "ทุ่งหญ้า"},
}
# ลำดับความสำคัญของโซนเวลาซ้อนกัน (มาก่อน = ชนะ)
_ZONE_PRIORITY = ["temple", "dirt", "quarry", "rice", "orchard", "forest", "village"]

# ---------- ข้อมูลโครงสร้าง (พิกัดแบบภาพ) ----------
_ZONES = [
    ("forest_north", "forest", "ป่าหลังหมู่บ้าน",
     [(430, 560), (620, 540), (800, 590), (1080, 690), (1080, 880), (960, 930), (830, 1000),
      (640, 1060), (600, 1040), (470, 1000), (380, 880), (380, 700)]),
    ("forest_south", "forest", "ป่าเนินทางใต้",
     [(0, 1700), (250, 1800), (560, 1840), (740, 1830), (860, 1790), (860, 1880), (780, 1900),
      (560, 2000), (430, 2100), (0, 2100)]),
    ("quarry", "quarry", "เหมืองทรายร้าง",
     [(860, 1790), (1080, 1735), (1080, 2100), (920, 2060), (860, 1880)]),
    ("village_nw", "village", "ซอยบ้านฝั่งเหนือ",
     [(0, 640), (200, 500), (420, 430), (440, 560), (380, 700), (380, 880), (330, 960), (110, 900), (0, 800)]),
    ("village_core", "village", "ย่านวัด-โรงเรียน",
     [(330, 960), (380, 880), (470, 1000), (700, 1060), (840, 1060), (840, 1330), (700, 1380),
      (520, 1400), (400, 1330), (330, 1230)]),
    ("village_east", "village", "ย่านสวนปลา",
     [(840, 1090), (1080, 1090), (1080, 1300), (840, 1300)]),
    ("orchard_w", "orchard", "สวนลำไยตะวันตก", [(130, 1030), (320, 1010), (330, 1230), (140, 1250)]),
    ("orchard_s", "orchard", "สวนลำไยใต้", [(430, 1350), (560, 1340), (650, 1440), (570, 1510), (440, 1460)]),
    ("orchard_ne", "orchard", "สวนลำไยเนินเหนือ", [(800, 420), (960, 430), (980, 600), (800, 590)]),
    ("rice_nw", "rice", "นาข้าวริมทาง", [(0, 1030), (120, 1030), (120, 1170), (0, 1190)]),
    ("rice_south", "rice", "นาข้าวทุ่งใต้", [(440, 1520), (610, 1530), (620, 1720), (470, 1700)]),
    ("rice_se", "rice", "นาข้าวทุ่งตะวันออก", [(630, 1500), (830, 1500), (830, 1720), (640, 1720)]),
    ("rice_east", "rice", "นาข้าวฝั่งขวา", [(850, 1380), (1080, 1380), (1080, 1580), (850, 1580)]),
    ("rice_mid", "rice", "นาข้าวกลาง", [(660, 1400), (790, 1400), (790, 1480), (660, 1480)]),
    ("school_ground", "dirt", "ลานโรงเรียน", [(580, 1135), (680, 1135), (680, 1205), (580, 1205)]),
    ("temple_ground", "temple", "เขตวัด", [(430, 1130), (565, 1130), (565, 1215), (430, 1215)]),
]

# (id, kind, width, [points])  kind: major=ถนนใหญ่, road=ถนนรอง, track=ทางป่า, lane=ซอย
_ROADS = [
    ("main_ew", "major", 14, [(0, 1565), (110, 1480), (300, 1380), (400, 1300), (480, 1215),
                              (700, 1230), (840, 1255), (1080, 1245)]),
    ("village_diag", "road", 10, [(0, 640), (60, 700), (200, 830), (340, 1000), (430, 1120), (485, 1215)]),
    ("forest_track_ne", "track", 7, [(590, 1055), (650, 880), (790, 590)]),
    ("forest_track_e", "track", 7, [(600, 1060), (800, 990), (940, 890), (1080, 740)]),
    ("north_ring", "road", 9, [(300, 430), (540, 385), (700, 330), (900, 180)]),
    ("north_link", "road", 8, [(540, 385), (555, 525), (780, 590), (920, 615), (1080, 700)]),
    ("south_ring", "major", 12, [(110, 1480), (300, 1680), (450, 1780), (570, 1830), (900, 1790), (1080, 1730)]),
    ("resort_spur", "road", 8, [(570, 1830), (600, 1990), (610, 2100)]),
    ("resort_east", "road", 8, [(740, 1930), (900, 1990), (1080, 2040)]),
    ("core_lane_a", "lane", 5, [(490, 1215), (520, 1330), (560, 1400)]),
    ("core_lane_b", "lane", 5, [(700, 1235), (720, 1130), (700, 1060)]),
    ("core_lane_c", "lane", 5, [(420, 1130), (560, 1100), (600, 1060)]),
    ("east_lane_a", "lane", 5, [(900, 1255), (910, 1100)]),
    ("east_lane_b", "lane", 5, [(960, 1255), (980, 1090)]),
    ("east_lane_c", "lane", 5, [(840, 1105), (1080, 1115)]),
]

# (cx, cy, rx, ry, kind)
_PONDS = [
    (97, 1345, 34, 20, "pond"), (385, 1545, 20, 14, "pond"), (900, 955, 22, 36, "pond"),
    (965, 1455, 16, 22, "pond"), (180, 1665, 32, 22, "fish_pond"), (240, 1715, 20, 16, "fish_pond"),
    (1040, 1120, 18, 12, "fish_pond"),
]

# (id, ชื่อ, ชื่ออังกฤษ, kind, x, y, radius, loot_tier, tags)
_POIS = [
    ("wat_phu_khao", "วัดภูเขาน้อย", "Phu Khao Noi Temple", "temple", 505, 1170, 60, "mid", ["landmark", "neutral"]),
    ("forest_nursery", "สถานีเพาะกล้าไม้ริมป่า", "Forest Nursery Station", "compound", 630, 975, 55, "high", ["landmark", "loot"]),
    ("lan_suk_cafe", "คาเฟ่ใต้ต้นลำไย", "Longan Tree Cafe", "shop", 345, 975, 35, "mid", ["loot"]),
    ("ban_rim_pa_school", "โรงเรียนบ้านริมป่า", "Rim Pa School", "school", 625, 1170, 55, "mid", ["landmark"]),
    ("fishpond_garden", "สวนบ่อปลาริมป่า", "Fishpond Garden", "garden", 1030, 1085, 45, "mid", ["loot"]),
    ("kitchen_far_east", "ครัวไร่ปลายทาง", "Far-East Farm Kitchen", "shop", 1050, 1590, 35, "low", ["loot"]),
    ("secret_garden", "Secret Garden Lodge", "Secret Garden Lodge", "resort", 735, 1940, 55, "high", ["landmark", "loot"]),
    ("guest_house", "บ้านพักปลายทาง", "End-of-Road Guest House", "house", 950, 2020, 35, "mid", ["loot"]),
    # --- ของที่เพิ่มใหม่ (ไม่มีในต้นแบบ) ---
    ("forest_watchtower", "หอสังเกตการณ์กลางป่า", "Forest Watchtower", "tower", 700, 820, 40, "high", ["new", "overwatch"]),
    ("quarry_camp", "ค่ายเหมืองทราย", "Quarry Camp", "compound", 960, 1900, 55, "high", ["new", "loot"]),
]

_SPAWNS = [("spawn_nw", "ทางเข้าซอยเหนือ", 12, 650), ("spawn_w", "ถนนฝั่งตะวันตก", 12, 1555),
           ("spawn_e", "ถนนฝั่งตะวันออก", 1068, 1245), ("spawn_ne", "ทางป่าตะวันออกเฉียงเหนือ", 1068, 745)]
_EXFILS = [("exfil_north", "ปลายถนนเหนือ", 890, 190), ("exfil_south", "ทางลงใต้ (รีสอร์ต)", 608, 2085),
           ("exfil_southeast", "ถนนวงแหวนใต้", 1068, 1735)]


# ==========================================
# เรขาคณิตพื้นฐาน
# ==========================================
def _T(x, y):
    return (float(x), float(y) - _Y0)


def _Tpoly(pts):
    return [_T(x, y) for x, y in pts]


def _pip(x, y, poly):
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
            inside = not inside
        j = i
    return inside


def _bbox(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _sample_polyline(pts, step):
    """คืน (x, y, มุมเส้นสัมผัส) ทุก ๆ step หน่วยตามเส้น"""
    out = []
    carry = 0.0
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        seg = math.hypot(bx - ax, by - ay)
        if seg < 1e-9:
            continue
        ang = math.atan2(by - ay, bx - ax)
        d = carry
        while d <= seg:
            t = d / seg
            out.append((ax + (bx - ax) * t, ay + (by - ay) * t, ang))
            d += step
        carry = d - seg
    return out


def _clip_line_to_poly(p0, p1, poly, step=4.0):
    """ตัดเส้นตรงให้เหลือเฉพาะช่วงที่อยู่ในโพลิกอน (คืนหลาย polyline)"""
    length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    n = max(2, int(length / step))
    runs, cur = [], []
    for i in range(n + 1):
        t = i / n
        x, y = p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t
        if _pip(x, y, poly):
            cur.append((x, y))
        else:
            if len(cur) >= 3:
                runs.append([cur[0], cur[-1]])
            cur = []
    if len(cur) >= 3:
        runs.append([cur[0], cur[-1]])
    return runs


# ==========================================
# ตัวแผนที่
# ==========================================
class BanRimPaMap:
    CELL = 40  # ขนาดช่อง spatial index

    def __init__(self, seed: int = MAP_SEED):
        self.seed = seed
        self.w, self.h = WORLD_W, WORLD_H
        self.rng = random.Random(seed)
        self.zones = [{"id": i, "kind": k, "name": n, "poly": _Tpoly(p)} for i, k, n, p in _ZONES]
        self.roads = []
        for rid, kind, width, pts in _ROADS:
            self.roads.append({"id": rid, "kind": kind, "width": float(width), "pts": _Tpoly(pts)})
        self.ponds = [{"x": float(cx), "y": cy - _Y0, "rx": rx, "ry": ry, "kind": k}
                      for cx, cy, rx, ry, k in _PONDS]
        self.pois = []
        for pid, name, name_en, kind, x, y, rad, tier, tags in _POIS:
            tx, ty = _T(x, y)
            self.pois.append({"id": pid, "name": name, "name_en": name_en, "kind": kind, "x": tx, "y": ty,
                              "radius": rad, "tier": tier, "tags": list(tags)})
        self.spawns = [{"id": i, "name": n, "x": _T(x, y)[0], "y": _T(x, y)[1]} for i, n, x, y in _SPAWNS]
        self.exfils = [{"id": i, "name": n, "x": _T(x, y)[0], "y": _T(x, y)[1], "radius": 18.0,
                        "kind": "road_exit"} for i, n, x, y in _EXFILS]
        self.buildings, self.trees, self.loot = [], [], []
        self._road_segs = []
        self._road_grid, self._bld_grid, self._tree_grid = {}, {}, {}
        self._nav_cache = {}
        self._build()

    # ---------- spatial index ----------
    def _cells_for_box(self, x0, y0, x1, y1):
        c = self.CELL
        for i in range(int(x0 // c), int(x1 // c) + 1):
            for j in range(int(y0 // c), int(y1 // c) + 1):
                yield (i, j)

    def _index_roads(self):
        self._road_segs = []
        self._road_grid = {}
        for r in self.roads:
            hw = r["width"] / 2.0
            for (ax, ay), (bx, by) in zip(r["pts"], r["pts"][1:]):
                idx = len(self._road_segs)
                self._road_segs.append((ax, ay, bx, by, hw, r["id"]))
                for cell in self._cells_for_box(min(ax, bx) - hw - 2, min(ay, by) - hw - 2,
                                                max(ax, bx) + hw + 2, max(ay, by) + hw + 2):
                    self._road_grid.setdefault(cell, []).append(idx)

    def _road_gap(self, x, y, ignore=None):
        """ระยะ (ขอบถนน) ที่ใกล้ที่สุด — ติดลบ = อยู่บนถนน"""
        best = 1e9
        for idx in self._road_grid.get((int(x // self.CELL), int(y // self.CELL)), ()):
            ax, ay, bx, by, hw, rid = self._road_segs[idx]
            if rid == ignore:
                continue
            best = min(best, _seg_dist(x, y, ax, ay, bx, by) - hw)
        if best > 1e8:  # ช่องว่าง: ลองช่องข้างเคียง
            c = self.CELL
            ci, cj = int(x // c), int(y // c)
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    for idx in self._road_grid.get((ci + di, cj + dj), ()):
                        ax, ay, bx, by, hw, rid = self._road_segs[idx]
                        if rid == ignore:
                            continue
                        best = min(best, _seg_dist(x, y, ax, ay, bx, by) - hw)
        return best

    def _in_pond(self, x, y, pad=0.0):
        for p in self.ponds:
            dx, dy = (x - p["x"]) / (p["rx"] + pad), (y - p["y"]) / (p["ry"] + pad)
            if dx * dx + dy * dy <= 1.0:
                return True
        return False

    def zone_kind_at(self, x, y):
        hit = set()
        for z in self.zones:
            x0, y0, x1, y1 = z["bbox"]
            if x0 <= x <= x1 and y0 <= y <= y1 and _pip(x, y, z["poly"]):
                hit.add(z["kind"])
        for k in _ZONE_PRIORITY:
            if k in hit:
                return k
        return None

    # ---------- สร้างแมพ ----------
    def _build(self):
        for z in self.zones:
            z["bbox"] = _bbox(z["poly"])
        self._gen_village_lanes()
        self._index_roads()
        self._gen_fixed_buildings()
        self._gen_roadside_buildings()
        self._index_buildings()
        self._gen_trees()
        self._gen_loot()

    def _gen_village_lanes(self):
        """ผังซอยเฉียงของหมู่บ้านฝั่งเหนือ: ซอยขนาน + ซอยตัดขวาง ตัดให้อยู่ในโพลิกอนหมู่บ้าน"""
        poly = next(z["poly"] for z in self.zones if z["id"] == "village_nw")
        th = math.radians(52)
        d, n = (math.cos(th), math.sin(th)), (-math.sin(th), math.cos(th))
        o = _T(150, 640)
        k = 0
        for i in range(-6, 11):
            p0 = (o[0] + n[0] * i * 44 - d[0] * 500, o[1] + n[1] * i * 44 - d[1] * 500)
            p1 = (o[0] + n[0] * i * 44 + d[0] * 700, o[1] + n[1] * i * 44 + d[1] * 700)
            for run in _clip_line_to_poly(p0, p1, poly):
                self.roads.append({"id": f"vlane_{k}", "kind": "lane", "width": 5.0, "pts": run, "para": True})
                k += 1
        for j in range(-4, 8):
            p0 = (o[0] + d[0] * j * 100 - n[0] * 500, o[1] + d[1] * j * 100 - n[1] * 500)
            p1 = (o[0] + d[0] * j * 100 + n[0] * 700, o[1] + d[1] * j * 100 + n[1] * 700)
            for run in _clip_line_to_poly(p0, p1, poly):
                self.roads.append({"id": f"vcross_{k}", "kind": "lane", "width": 4.0, "pts": run})
                k += 1

    def _add_building(self, x, y, w, h, ang, kind, name=None, placed=None):
        b = {"id": f"b{len(self.buildings)}", "x": round(x, 2), "y": round(y, 2), "w": round(w, 1),
             "h": round(h, 1), "ang": round(ang, 4), "kind": kind}
        if name:
            b["name"] = name
        self.buildings.append(b)
        return b

    def _gen_fixed_buildings(self):
        def F(x, y, w, h, a, kind, name=None):
            tx, ty = _T(x, y)
            self._add_building(tx, ty, w, h, math.radians(a), kind, name)
        # วัด
        F(500, 1160, 40, 26, 8, "temple_hall", "อุโบสถ")
        F(548, 1178, 12, 12, 0, "stupa", "เจดีย์")
        F(458, 1190, 26, 18, 8, "temple_hall", "ศาลาการเปรียญ")
        # โรงเรียน (เพิ่มจากต้นแบบ: ตึกเรียนหลังคาแดง 2 หลัง)
        F(625, 1124, 72, 14, 0, "school", "อาคารเรียน 1")
        F(600, 1218, 44, 14, 0, "school", "อาคารเรียน 2")
        # สถานีเพาะกล้าไม้
        F(612, 968, 30, 16, 10, "shed", "เรือนเพาะกล้า")
        F(652, 984, 22, 14, -8, "shed")
        F(640, 946, 18, 12, 4, "shed")
        # คาเฟ่
        F(345, 972, 30, 20, 25, "shop", "คาเฟ่")
        # รีสอร์ต / บ้านพัก
        F(735, 1932, 34, 18, 0, "lodge", "ล็อดจ์หลัก")
        F(780, 1952, 20, 14, 0, "hut")
        F(705, 1960, 20, 14, 0, "hut")
        F(950, 2016, 28, 18, 0, "house", "บ้านพักปลายทาง")
        # สวนบ่อปลา / ครัว
        F(1010, 1070, 26, 16, 0, "shop", "ศาลาสวนบ่อปลา")
        F(1050, 1590, 28, 18, 0, "shop", "ครัวไร่")
        # ใหม่: หอสังเกตการณ์ + ค่ายเหมือง
        F(700, 820, 8, 8, 0, "tower", "หอสังเกตการณ์")
        F(935, 1885, 30, 12, 0, "container", "ตู้คอนเทนเนอร์")
        F(975, 1895, 30, 12, 90, "container")
        F(955, 1925, 26, 12, 0, "container")
        F(1000, 1930, 22, 14, 0, "shed", "โรงพักคนงาน")

    def _gen_roadside_buildings(self):
        rng = self.rng
        centers = {}  # spatial hash กันบ้านทับกัน
        for b in self.buildings:
            centers.setdefault((int(b["x"] // 24), int(b["y"] // 24)), []).append((b["x"], b["y"]))

        def too_close(x, y, rad=16.0):
            ci, cj = int(x // 24), int(y // 24)
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    for (cx, cy) in centers.get((ci + di, cj + dj), ()):
                        if math.hypot(cx - x, cy - y) < rad:
                            return True
            return False

        src = [r for r in self.roads if r["kind"] in ("lane", "road", "major") and
               (r.get("para") or r["id"] in ("main_ew", "village_diag", "core_lane_a", "core_lane_b",
                                            "core_lane_c", "east_lane_a", "east_lane_b", "east_lane_c"))]
        for r in src:
            major = r["kind"] in ("major", "road")
            off = 22.0 if major else 14.0
            for (x, y, ang) in _sample_polyline(r["pts"], 26.0):
                for side in (-1, 1):
                    if rng.random() < (0.28 if major else 0.17):
                        continue
                    jx = rng.uniform(-4, 4)
                    nx, ny = -math.sin(ang), math.cos(ang)
                    bx = x + nx * (off + rng.uniform(0, 3)) * side + math.cos(ang) * jx
                    by = y + ny * (off + rng.uniform(0, 3)) * side + math.sin(ang) * jx
                    if not (0 < bx < self.w and 0 < by < self.h):
                        continue
                    if self.zone_kind_at(bx, by) != "village" or self._in_pond(bx, by, 8):
                        continue
                    if self._road_gap(bx, by, ignore=r["id"]) < 10 or too_close(bx, by):
                        continue
                    w, h = rng.uniform(11, 19), rng.uniform(9, 14)
                    kind = "shop" if (major and rng.random() < 0.12) else "house"
                    self._add_building(bx, by, w, h, ang + rng.uniform(-0.08, 0.08), kind)
                    centers.setdefault((int(bx // 24), int(by // 24)), []).append((bx, by))

    def _index_buildings(self):
        self._bld_grid = {}
        for i, b in enumerate(self.buildings):
            rad = math.hypot(b["w"], b["h"]) / 2 + 1
            for cell in self._cells_for_box(b["x"] - rad, b["y"] - rad, b["x"] + rad, b["y"] + rad):
                self._bld_grid.setdefault(cell, []).append(i)

    def _bld_hit(self, x, y, r=0.0):
        for i in self._bld_grid.get((int(x // self.CELL), int(y // self.CELL)), ()):
            b = self.buildings[i]
            ca, sa = math.cos(-b["ang"]), math.sin(-b["ang"])
            dx, dy = x - b["x"], y - b["y"]
            lx, ly = dx * ca - dy * sa, dx * sa + dy * ca
            qx = max(-b["w"] / 2, min(b["w"] / 2, lx))
            qy = max(-b["h"] / 2, min(b["h"] / 2, ly))
            if math.hypot(lx - qx, ly - qy) <= r:
                return b
        return None

    def _gen_trees(self):
        rng = self.rng
        self.trees = []

        def ok(x, y, pad):
            return (0 < x < self.w and 0 < y < self.h and not self._in_pond(x, y, 6)
                    and self._road_gap(x, y) > pad and self._bld_hit(x, y, pad + 3) is None)

        for z in self.zones:
            x0, y0, x1, y1 = z["bbox"]
            if z["kind"] == "forest":
                sp = 24
                y = y0
                while y <= y1:
                    x = x0
                    while x <= x1:
                        tx, ty = x + rng.uniform(-9, 9), y + rng.uniform(-9, 9)
                        if rng.random() > 0.15 and _pip(tx, ty, z["poly"]) and self.zone_kind_at(tx, ty) == "forest" \
                                and ok(tx, ty, 6):
                            kind = "bamboo" if rng.random() < 0.18 else ("teak" if rng.random() < 0.4 else "forest")
                            self.trees.append({"x": round(tx, 1), "y": round(ty, 1),
                                               "r": round(rng.uniform(6, 10), 1), "kind": kind})
                        x += sp
                    y += sp
            elif z["kind"] == "orchard":
                sp = 22
                y = y0 + sp / 2
                while y <= y1:
                    x = x0 + sp / 2
                    while x <= x1:
                        if _pip(x, y, z["poly"]) and self.zone_kind_at(x, y) == "orchard" and ok(x, y, 7):
                            self.trees.append({"x": round(x, 1), "y": round(y, 1), "r": 7.0, "kind": "longan"})
                        x += sp
                    y += sp
        # ไม้ประดับตามบ้าน
        placed = 0
        tries = 0
        while placed < 70 and tries < 4000:
            tries += 1
            x, y = rng.uniform(0, self.w), rng.uniform(0, self.h)
            if self.zone_kind_at(x, y) == "village" and ok(x, y, 8):
                self.trees.append({"x": round(x, 1), "y": round(y, 1), "r": round(rng.uniform(5, 8), 1),
                                   "kind": "yard"})
                placed += 1
        self._tree_grid = {}
        for i, t in enumerate(self.trees):
            self._tree_grid.setdefault((int(t["x"] // self.CELL), int(t["y"] // self.CELL)), []).append(i)

    def _tree_hit(self, x, y, r=0.0):
        c = self.CELL
        ci, cj = int(x // c), int(y // c)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for i in self._tree_grid.get((ci + di, cj + dj), ()):
                    t = self.trees[i]
                    if math.hypot(x - t["x"], y - t["y"]) <= r + t["r"] * 0.35:
                        return t
        return None

    def _gen_loot(self):
        rng = self.rng
        self.loot = []
        for p in self.pois:
            n = {"high": 4, "mid": 3, "low": 2}[p["tier"]]
            k = 0
            for _ in range(60):
                if k >= n:
                    break
                a, rr = rng.uniform(0, math.tau), rng.uniform(0.2, 0.8) * p["radius"]
                x, y = p["x"] + math.cos(a) * rr, p["y"] + math.sin(a) * rr
                if self.blocked(x, y, 3.0) or not (0 < x < self.w and 0 < y < self.h):
                    continue
                self.loot.append({"id": f"loot_{p['id']}_{k}", "x": round(x, 1), "y": round(y, 1),
                                  "tier": p["tier"], "kind": "poi_cache", "poi": p["id"]})
                k += 1
        for b in self.buildings:
            if b["kind"] in ("house", "shop") and rng.random() < 0.12:
                tier = "mid" if (b["kind"] == "shop" or b["y"] > 900) else "low"
                self.loot.append({"id": f"loot_{b['id']}", "x": b["x"], "y": b["y"], "tier": tier,
                                  "kind": "house_stash", "building": b["id"]})

    # ---------- query ----------
    def blocked(self, x, y, r=PLAYER_RADIUS_DEFAULT):
        if not (r <= x <= self.w - r and r <= y <= self.h - r):
            return True
        if self._in_pond(x, y, -r * 0.5):
            return True
        if self._bld_hit(x, y, r):
            return True
        return self._tree_hit(x, y, r) is not None

    def terrain_at(self, x, y):
        if not (0 <= x <= self.w and 0 <= y <= self.h):
            return "void"
        if self._in_pond(x, y):
            return "water"
        if self._bld_hit(x, y, 0.0):
            return "building"
        if self._road_gap(x, y) <= 0:
            return "road"
        return self.zone_kind_at(x, y) or "grass"

    def probe(self, x, y, r=PLAYER_RADIUS_DEFAULT):
        t = self.terrain_at(x, y)
        info = TERRAIN.get(t, {"speed": 0.0, "cover": 0.0, "walkable": False, "label": "นอกแมพ"})
        return {"x": x, "y": y, "terrain": t, "label": info["label"], "speed": info["speed"],
                "cover": info["cover"], "blocked": self.blocked(x, y, r)}

    def query_box(self, x0, y0, x1, y1, cap=2500):
        def inb(x, y, pad=0):
            return x0 - pad <= x <= x1 + pad and y0 - pad <= y <= y1 + pad
        out = {
            "buildings": [b for b in self.buildings if inb(b["x"], b["y"], 20)][:cap],
            "trees": [t for t in self.trees if inb(t["x"], t["y"], 10)][:cap],
            "loot": [l for l in self.loot if inb(l["x"], l["y"])],
            "pois": [p for p in self.pois if inb(p["x"], p["y"], p["radius"])],
            "ponds": [p for p in self.ponds if inb(p["x"], p["y"], max(p["rx"], p["ry"]))],
            "roads": [r for r in self.roads if any(inb(px, py, 20) for px, py in r["pts"])
                      or any(inb((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, 20) for a, b in zip(r["pts"], r["pts"][1:]))],
            "spawns": [s for s in self.spawns if inb(s["x"], s["y"])],
            "exfils": [e for e in self.exfils if inb(e["x"], e["y"], e["radius"])],
        }
        return out

    # ---------- nav grid + A* ----------
    NAV_STEP = 12.0

    def _nav_blocked(self, i, j):
        key = (i, j)
        v = self._nav_cache.get(key)
        if v is None:
            x, y = (i + 0.5) * self.NAV_STEP, (j + 0.5) * self.NAV_STEP
            v = self.blocked(x, y, PLAYER_RADIUS_DEFAULT + 1.0)
            self._nav_cache[key] = v
        return v

    def _nav_cost(self, i, j):
        x, y = (i + 0.5) * self.NAV_STEP, (j + 0.5) * self.NAV_STEP
        sp = TERRAIN.get(self.terrain_at(x, y), {"speed": 0.5})["speed"]
        return 1.0 / max(sp, 0.05)

    def _snap(self, x, y):
        i0, j0 = int(x // self.NAV_STEP), int(y // self.NAV_STEP)
        for rad in range(0, 6):
            for di in range(-rad, rad + 1):
                for dj in range(-rad, rad + 1):
                    if max(abs(di), abs(dj)) != rad:
                        continue
                    i, j = i0 + di, j0 + dj
                    if 0 <= i < int(self.w // self.NAV_STEP) and 0 <= j < int(self.h // self.NAV_STEP) \
                            and not self._nav_blocked(i, j):
                        return (i, j)
        return None

    def _los(self, a, b):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(d / 5))
        for k in range(n + 1):
            t = k / n
            if self.blocked(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, PLAYER_RADIUS_DEFAULT):
                return False
        return True

    def find_path(self, x1, y1, x2, y2, max_nodes=40000):
        s, g = self._snap(x1, y1), self._snap(x2, y2)
        if s is None or g is None:
            return {"ok": False, "reason": "start/goal blocked", "path": []}
        S = self.NAV_STEP
        openh = [(0.0, 0.0, s)]
        came, gs = {s: None}, {s: 0.0}
        n = 0
        found = False
        while openh and n < max_nodes:
            _, cg, cur = heapq.heappop(openh)
            if cur == g:
                found = True
                break
            if cg > gs.get(cur, 1e18):
                continue
            n += 1
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    if di == 0 and dj == 0:
                        continue
                    nb = (cur[0] + di, cur[1] + dj)
                    if not (0 <= nb[0] < int(self.w // S) and 0 <= nb[1] < int(self.h // S)):
                        continue
                    if self._nav_blocked(*nb):
                        continue
                    if di and dj and (self._nav_blocked(cur[0] + di, cur[1]) or self._nav_blocked(cur[0], cur[1] + dj)):
                        continue
                    step = (1.414 if di and dj else 1.0) * S * self._nav_cost(*nb)
                    ng = cg + step
                    if ng < gs.get(nb, 1e18):
                        gs[nb] = ng
                        came[nb] = cur
                        hx = math.hypot(nb[0] - g[0], nb[1] - g[1]) * S * 1.0
                        heapq.heappush(openh, (ng + hx, ng, nb))
        if not found:
            return {"ok": False, "reason": "no path", "path": [], "expanded": n}
        cells = []
        cur = g
        while cur is not None:
            cells.append(((cur[0] + 0.5) * S, (cur[1] + 0.5) * S))
            cur = came[cur]
        cells.reverse()
        pts = [(x1, y1)] + cells + [(x2, y2)]
        smooth, i = [pts[0]], 0
        while i < len(pts) - 1:  # string-pulling ด้วย line-of-sight
            j = len(pts) - 1
            while j > i + 1 and not self._los(pts[i], pts[j]):
                j -= 1
            smooth.append(pts[j])
            i = j
        length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(smooth, smooth[1:]))
        return {"ok": True, "length": round(length, 1), "expanded": n,
                "path": [[round(px, 1), round(py, 1)] for px, py in smooth]}

    # ---------- export ----------
    # ---------- ตำแหน่งที่ยืนได้จริง (ใช้กับ XROOM / auction extraction) ----------
    def nearest_walkable(self, x, y, r=PLAYER_RADIUS_DEFAULT, max_radius=400.0):
        """คืน (x, y) ที่ยืนได้ใกล้จุดที่ขอที่สุด (ค้นเป็นวงรอบจุดเดิม) หรือ None ถ้าไม่เจอในรัศมี
        ใช้ดึงจุดที่สุ่มมา (เช่น airdrop/ภารกิจ) ออกจากน้ำ/หน้าผา/อาคาร/ต้นไม้"""
        x = min(max(float(x), r), self.w - r)
        y = min(max(float(y), r), self.h - r)
        if not self.blocked(x, y, r):
            return (round(x, 2), round(y, 2))
        rad = 3.0
        while rad <= max_radius:
            n = max(8, int(math.tau * rad / 3.0))
            off = (rad * 7.31) % math.tau  # หมุนจุดเริ่มต้นแต่ละวง กันเอนเอียงไปทิศเดียว
            for k in range(n):
                a = off + math.tau * k / n
                px, py = x + math.cos(a) * rad, y + math.sin(a) * rad
                if not self.blocked(px, py, r):
                    return (round(px, 2), round(py, 2))
            rad += 3.0
        return None

    def random_walkable(self, rng=None, margin=0.0, tries=600, r=PLAYER_RADIUS_DEFAULT):
        """สุ่มจุดที่ยืนได้ทั่วแมพ (margin = สัดส่วนขอบที่ไม่สุ่ม เช่น 0.12) — ไม่เจอจะคืนกลางแมพที่ snap แล้ว"""
        rng = rng or random
        x0, x1 = self.w * margin, self.w * (1 - margin)
        y0, y1 = self.h * margin, self.h * (1 - margin)
        for _ in range(tries):
            x, y = rng.uniform(x0, x1), rng.uniform(y0, y1)
            if not self.blocked(x, y, r):
                return (round(x, 2), round(y, 2))
        return self.nearest_walkable(self.w / 2, self.h / 2, r, max_radius=max(self.w, self.h))

    def meta(self):
        return {"id": MAP_ID, "name": MAP_NAME, "width": self.w, "height": self.h, "seed": self.seed,
                "unit": "1 unit = 1 px ของภาพต้นแบบที่ครอปแล้ว", "player_radius": PLAYER_RADIUS_DEFAULT,
                "terrain": TERRAIN, "counts": self.stats()["counts"],
                "pois": self.pois, "spawns": self.spawns, "exfils": self.exfils}

    def stats(self):
        kinds = {}
        for b in self.buildings:
            kinds[b["kind"]] = kinds.get(b["kind"], 0) + 1
        tk = {}
        for t in self.trees:
            tk[t["kind"]] = tk.get(t["kind"], 0) + 1
        return {"counts": {"zones": len(self.zones), "roads": len(self.roads), "buildings": len(self.buildings),
                           "trees": len(self.trees), "ponds": len(self.ponds), "pois": len(self.pois),
                           "loot": len(self.loot), "spawns": len(self.spawns), "exfils": len(self.exfils)},
                "buildings_by_kind": kinds, "trees_by_kind": tk}

    def to_dict(self):
        d = self.meta()
        d.update({"zones": [{"id": z["id"], "kind": z["kind"], "name": z["name"],
                             "poly": [[round(x, 1), round(y, 1)] for x, y in z["poly"]]} for z in self.zones],
                  "roads": [{"id": r["id"], "kind": r["kind"], "width": r["width"],
                             "pts": [[round(x, 1), round(y, 1)] for x, y in r["pts"]]} for r in self.roads],
                  "ponds": self.ponds, "buildings": self.buildings, "trees": self.trees, "loot": self.loot})
        return d

    def to_svg(self, width_px=540):
        col = {"forest": "#35552f", "orchard": "#5d7a3a", "rice": "#8fb04e", "village": "#7a7260",
               "quarry": "#c9b98a", "dirt": "#a98e6a", "temple": "#8a7f5c"}
        road_col = {"major": "#d8d2c0", "road": "#c8c2b0", "track": "#9d8a64", "lane": "#b8b2a0"}
        bcol = {"temple_hall": "#c9a227", "stupa": "#e8d98a", "school": "#b5473a", "tower": "#222",
                "container": "#3a6ea5", "lodge": "#8b5e3c", "shop": "#b07a4a"}
        h_px = int(width_px * self.h / self.w)
        o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{width_px}" '
             f'height="{h_px}"><rect width="{self.w}" height="{self.h}" fill="#6b8a45"/>']
        for z in sorted(self.zones, key=lambda z: -_ZONE_PRIORITY.index(z["kind"]) if z["kind"] in _ZONE_PRIORITY else 0):
            pts = " ".join(f"{x:.0f},{y:.0f}" for x, y in z["poly"])
            o.append(f'<polygon points="{pts}" fill="{col.get(z["kind"], "#6b8a45")}"/>')
        for p in self.ponds:
            c = "#2f7f86" if p["kind"] == "fish_pond" else "#2b4f6b"
            o.append(f'<ellipse cx="{p["x"]:.0f}" cy="{p["y"]:.0f}" rx="{p["rx"]}" ry="{p["ry"]}" fill="{c}"/>')
        for r in sorted(self.roads, key=lambda r: r["width"]):
            pts = " ".join(f"{x:.0f},{y:.0f}" for x, y in r["pts"])
            o.append(f'<polyline points="{pts}" fill="none" stroke="{road_col[r["kind"]]}" '
                     f'stroke-width="{r["width"]}" stroke-linecap="round" stroke-linejoin="round"/>')
        for t in self.trees:
            c = {"longan": "#2f5a22", "bamboo": "#6c9a3a", "teak": "#27441f", "yard": "#4f8a2c"}.get(t["kind"], "#1f3a1b")
            o.append(f'<circle cx="{t["x"]}" cy="{t["y"]}" r="{t["r"] * 0.7:.1f}" fill="{c}" fill-opacity=".85"/>')
        for b in self.buildings:
            o.append(f'<rect x="{-b["w"] / 2:.1f}" y="{-b["h"] / 2:.1f}" width="{b["w"]}" height="{b["h"]}" '
                     f'fill="{bcol.get(b["kind"], "#d9d4cc")}" stroke="#444" stroke-width=".6" '
                     f'transform="translate({b["x"]} {b["y"]}) rotate({math.degrees(b["ang"]):.1f})"/>')
        for e in self.exfils:
            o.append(f'<circle cx="{e["x"]:.0f}" cy="{e["y"]:.0f}" r="{e["radius"]}" fill="#2ecc71" fill-opacity=".45" stroke="#2ecc71"/>')
        for s in self.spawns:
            o.append(f'<circle cx="{s["x"]:.0f}" cy="{s["y"]:.0f}" r="7" fill="#e74c3c" stroke="#fff"/>')
        for p in self.pois:
            o.append(f'<circle cx="{p["x"]:.0f}" cy="{p["y"]:.0f}" r="{p["radius"]}" fill="none" stroke="#fff" '
                     f'stroke-opacity=".35" stroke-dasharray="4 4"/>'
                     f'<text x="{p["x"]:.0f}" y="{p["y"] - p["radius"] - 4:.0f}" font-size="16" fill="#fff" '
                     f'stroke="#000" stroke-width=".6" text-anchor="middle">{p["name"]}</text>')
        o.append("</svg>")
        return "".join(o)


# ==========================================
# ตัวจัดการ singleton + attach
# ==========================================
_MAP: BanRimPaMap | None = None
_LOCK = threading.Lock()
_ATTACHED = False


def get_map() -> BanRimPaMap:
    global _MAP
    if _MAP is None:
        with _LOCK:
            if _MAP is None:
                t0 = time.time()
                _MAP = BanRimPaMap()
                print(f"[Ban Rim Pa] สร้างแผนที่เสร็จ {time.time() - t0:.2f}s — {_MAP.stats()['counts']}")
    return _MAP


def _register_extraction(main_globals, m, auction_entry, loot_table, xroom_env, xroom_default, extra_pool=None):
    """ลงทะเบียนแมพเข้า XROOM_MAP_POOL + แมพ Auction Extraction + ตารางของใน raid (ไม่ทับของเดิม)"""
    pool = main_globals.get("XROOM_MAP_POOL")
    if isinstance(pool, list) and os.environ.get(xroom_env, xroom_default) != "0":
        if not any(isinstance(p, dict) and p.get("id") == MAP_ID for p in pool):
            ent = {"id": MAP_ID, "name": MAP_NAME, "width": m.w, "height": m.h, "terrain_aware": True}
            ent.update(extra_pool or {})
            pool.append(ent)
    amaps = main_globals.get("VMAX_EXTRACTION_AUCTION_MAPS")
    abyid = main_globals.get("VMAX_EXTRACTION_AUCTION_MAP_BY_ID")
    if isinstance(amaps, list) and isinstance(abyid, dict) and MAP_ID not in abyid \
            and os.environ.get("VMAX_MAP_REGISTER_AUCTION", "1") != "0":
        amaps.append(dict(auction_entry))
        abyid[MAP_ID] = amaps[-1]
    tables = main_globals.get("EXTRACTION_LOOT_TABLES")
    if isinstance(tables, dict):
        tables.setdefault(MAP_ID, list(loot_table))


def attach(main_globals: dict):
    """เรียกก่อน sio.run(...) ท้ายไฟล์หลัก (ต้องมี app / VMAX_MODULES แล้ว)
    - เพิ่มแมพเข้า XROOM_MAP_POOL (ปิดได้ด้วย env VMAX_RIMPA_REGISTER_XROOM=0)
    - เพิ่ม VMAX_MODULES["map_ban_rimpa"]
    - เปิด API อ่านอย่างเดียว: /api/map/ban_rimpa[/query|/terrain|/path|/full], /maps/ban_rimpa/preview.svg
    """
    global _ATTACHED
    if _ATTACHED:
        return
    _ATTACHED = True
    m = get_map()
    app = main_globals.get("app")

    _register_extraction(
        main_globals, m,
        auction_entry={"id": MAP_ID, "name": "Ban Rim Pa", "subtitle": "หมู่บ้านริมป่า / ซอยเฉียง / เหมืองทรายมุมแมพ",
                       "entry_fee": int(os.environ.get("VMAX_RIMPA_AUCTION_FEE", "550000")), "ticket": 20000,
                       "players": 4, "difficulty": "กลาง"},
        loot_table=[("scrap_metal", 26), ("cloth", 22), ("wood", 22), ("electronics", 12), ("iron_ingot", 8),
                    ("med_kit", 8), ("power_cell", 2)],
        xroom_env="VMAX_RIMPA_REGISTER_XROOM", xroom_default="1")
    mods = main_globals.get("VMAX_MODULES")
    if isinstance(mods, dict):
        mods["map_ban_rimpa"] = "แผนที่หมู่บ้านริมป่า: ถนน/ซอย/บ้าน/ป่า/นา/บ่อ + พื้นผิว + nav A* + spawn/exfil/loot"
    layouts = main_globals.setdefault("VMAX_MAP_LAYOUTS", {})
    layouts[MAP_ID] = m  # โค้ดส่วนอื่นเรียก VMAX_MAP_LAYOUTS["ban_rimpa"].blocked(x, y, r) ได้เลย

    if app is None:
        print("[Ban Rim Pa] ⚠️  ไม่พบ app — ลงทะเบียนแมพแล้วแต่ไม่เปิด API")
        return

    from flask import Response, jsonify, request

    def _f(name, default=None):
        try:
            return float(request.args.get(name, default))
        except (TypeError, ValueError):
            return default

    def api_meta():
        return jsonify({"st": "ok", "map": get_map().meta()})

    def api_full():
        return jsonify({"st": "ok", "map": get_map().to_dict()})

    def api_query():
        x0, y0, x1, y1 = _f("x0", 0), _f("y0", 0), _f("x1", WORLD_W), _f("y1", WORLD_H)
        if None in (x0, y0, x1, y1):
            return jsonify({"st": "error", "msg": "x0,y0,x1,y1 ต้องเป็นตัวเลข"}), 400
        return jsonify({"st": "ok", "box": [x0, y0, x1, y1], "features": get_map().query_box(x0, y0, x1, y1)})

    def api_terrain():
        x, y, r = _f("x"), _f("y"), _f("r", PLAYER_RADIUS_DEFAULT)
        if x is None or y is None or r is None:
            return jsonify({"st": "error", "msg": "ต้องส่ง x,y เป็นตัวเลข"}), 400
        return jsonify({"st": "ok", **get_map().probe(x, y, r)})

    def api_path():
        v = [_f(k) for k in ("x1", "y1", "x2", "y2")]
        if None in v:
            return jsonify({"st": "error", "msg": "ต้องส่ง x1,y1,x2,y2"}), 400
        return jsonify({"st": "ok", **get_map().find_path(*v)})

    def api_svg():
        return Response(get_map().to_svg(int(_f("w", 540) or 540)), mimetype="image/svg+xml")

    for rule, fn, name in (
        (f"/api/map/{MAP_ID}", api_meta, "vmax_rimpa_meta"),
        (f"/api/map/{MAP_ID}/full", api_full, "vmax_rimpa_full"),
        (f"/api/map/{MAP_ID}/query", api_query, "vmax_rimpa_query"),
        (f"/api/map/{MAP_ID}/terrain", api_terrain, "vmax_rimpa_terrain"),
        (f"/api/map/{MAP_ID}/path", api_path, "vmax_rimpa_path"),
        (f"/maps/{MAP_ID}/preview.svg", api_svg, "vmax_rimpa_svg"),
    ):
        try:
            app.add_url_rule(rule, endpoint=name, view_func=fn, methods=["GET"])
        except Exception as exc:
            print(f"[Ban Rim Pa] ⚠️  ลงทะเบียน {rule} ไม่สำเร็จ ข้าม: {exc}")
    print(f"[Ban Rim Pa] ✅ ต่อโมดูลแล้ว — ดูตัวอย่าง: /maps/{MAP_ID}/preview.svg")


# ==========================================
# CLI (ใช้ทดสอบ/ส่งออกไปเอนจินอื่นได้โดยไม่ต้องรันเกม)
# ==========================================
def _cli():
    import argparse
    ap = argparse.ArgumentParser(description="Ban Rim Pa map exporter")
    ap.add_argument("--svg"), ap.add_argument("--json"), ap.add_argument("--stats", action="store_true")
    ap.add_argument("--path", nargs=4, type=float, metavar=("X1", "Y1", "X2", "Y2"))
    a = ap.parse_args()
    m = get_map()
    if a.svg:
        open(a.svg, "w", encoding="utf-8").write(m.to_svg(1080))
        print("เขียน", a.svg)
    if a.json:
        json.dump(m.to_dict(), open(a.json, "w", encoding="utf-8"), ensure_ascii=False)
        print("เขียน", a.json)
    if a.stats:
        print(json.dumps(m.stats(), ensure_ascii=False, indent=2))
    if a.path:
        print(json.dumps(m.find_path(*a.path), ensure_ascii=False))


if __name__ == "__main__":
    _cli()
