# -*- coding: utf-8 -*-
# ==========================================
# VMAX Module: Wiang Valley Region Map (แผนที่ภูมิภาค "หุบเขาเวียงสาย")
# ==========================================
# โมดูลแผนที่ที่ 2 ใช้แพทเทิร์นเดียวกับ vmax_module_ban_rimpa_map.py:
# ไฟล์เดียว ไม่แก้โค้ดเดิม แค่ attach(globals()) ก่อน sio.run(...)
#
# ที่มา: แกะ "โครงสร้างระดับภูมิภาค" จากภาพแผนที่หุบเขาในภาพตัวอย่าง
# (ทางหลวงสายหลักตัดเหนือ-ใต้, แยกสามแยกกลางแมพ, แม่น้ำคดเคี้ยวฝั่งตะวันออก, เทือกเขาเหนือ-ตะวันออก,
# เนินป่าฝั่งตะวันตก, ทุ่งนาตามหุบเขา, เมืองเล็กด้านเหนือ, ย่านวิทยาลัย-โรงพยาบาล-ตลาดด้านใต้)
# แล้ว "ลากเส้นสร้างใหม่เอง" เป็นข้อมูลเรขาคณิต — ไม่ได้ดึงภาพ/ข้อมูลของ Google และเลขทางหลวง/ชื่อ
# สถานที่ทั้งหมดเป็นชื่อสมมติ
#
# ต่างจากแมพหมู่บ้าน (ban_rimpa) ที่เป็นระดับซอย/หลังคาบ้าน — อันนี้เป็นแมพ "โลกใหญ่":
#   - ไม่มีการชนรายหลังคาบ้าน (บ้านเป็นจุดแสดงผลอย่างเดียว) ใช้ "detail_map" ต่อไปแมพละเอียดแทน
#   - มีความสูงภูมิประเทศ (elevation), ความลาดชัน, หน้าผา (ลาดเกินกำหนด = เดินไม่ได้)
#   - แม่น้ำข้ามได้เฉพาะที่ "สะพาน" ซึ่งคำนวณอัตโนมัติจากจุดที่ถนนตัดแม่น้ำ
#   - A* คิดต้นทุนตามพื้นผิว + ความลาดชัน + ถนนเร็วกว่าทุ่ง
#
# หน่วย: 1 unit = 1 พิกเซลของภาพต้นแบบที่ครอปแล้ว  โลก = 1080 x 1960
# สเกลจริง: METERS_PER_UNIT ตั้งต้น = 10 ม./unit (**ประเมินคร่าวๆ ยังไม่ได้ปรับกับแถบสเกลของภาพ**)
#   -> ตั้งใหม่ได้ด้วย env VMAX_VALLEY_M_PER_UNIT เมื่อรู้ระยะจริง
#
# ใช้งานแบบ standalone:
#   python vmax_module_wiang_valley_map.py --svg valley.svg --json valley.json --stats

from __future__ import annotations

import heapq
import json
import math
import os
import random
import threading
import time

MAP_ID = "wiang_valley"
MAP_NAME = "Wiang Valley Region (หุบเขาเวียงสาย)"
WORLD_W = 1080
WORLD_H = 1960
MAP_SEED = int(os.environ.get("VMAX_VALLEY_SEED", "20261013"))
METERS_PER_UNIT = float(os.environ.get("VMAX_VALLEY_M_PER_UNIT", "10"))
PLAYER_RADIUS_DEFAULT = 1.0     # หน่วย unit (แมพนี้ใหญ่ ไม่ใช้ระดับตัวละครละเอียด)
CLIFF_SLOPE = 0.50              # ลาด (ความสูง/ระยะราบ) เกินนี้ = หน้าผา เดินไม่ได้
_Y0 = 130                       # ตัดแถบ UI ด้านบนของภาพออก

TERRAIN = {
    "water":      {"speed": 0.00, "walkable": False, "cover": 0.0, "label": "แม่น้ำ/บ่อ"},
    "cliff":      {"speed": 0.00, "walkable": False, "cover": 0.8, "label": "หน้าผาชัน"},
    "sand":       {"speed": 0.85, "walkable": True,  "cover": 0.0, "label": "หาดทรายริมน้ำ"},
    "highway":    {"speed": 1.60, "walkable": True,  "cover": 0.0, "label": "ทางหลวง"},
    "road":       {"speed": 1.20, "walkable": True,  "cover": 0.0, "label": "ถนน"},
    "track":      {"speed": 0.95, "walkable": True,  "cover": 0.1, "label": "ทางลูกรัง"},
    "urban":      {"speed": 1.00, "walkable": True,  "cover": 0.3, "label": "ย่านชุมชน"},
    "campus":     {"speed": 1.00, "walkable": True,  "cover": 0.2, "label": "วิทยาลัย"},
    "industrial": {"speed": 1.00, "walkable": True,  "cover": 0.4, "label": "โรงงาน"},
    "village":    {"speed": 0.95, "walkable": True,  "cover": 0.2, "label": "หมู่บ้าน"},
    "farmland":   {"speed": 0.80, "walkable": True,  "cover": 0.1, "label": "ทุ่งนา/ไร่"},
    "quarry":     {"speed": 0.85, "walkable": True,  "cover": 0.05, "label": "บ่อดิน/เหมือง"},
    "grass":      {"speed": 0.90, "walkable": True,  "cover": 0.1, "label": "ทุ่งโล่ง"},
    "forest":     {"speed": 0.65, "walkable": True,  "cover": 0.6, "label": "เนินป่า"},
    "mountain":   {"speed": 0.45, "walkable": True,  "cover": 0.5, "label": "ภูเขา"},
}
_ZONE_PRIORITY = ["campus", "industrial", "urban", "village", "quarry", "farmland", "mountain", "forest"]
_ELEV_BASE = {"mountain": 380.0, "forest": 140.0, "farmland": 25.0, "village": 22.0, "urban": 20.0,
              "campus": 25.0, "industrial": 20.0, "quarry": 30.0, None: 40.0}
_ELEV_AMP = {"mountain": 150.0, "forest": 70.0, "quarry": 12.0, None: 6.0}

# ---------- ข้อมูลโครงสร้าง (พิกัดภาพ) ----------
_ZONES = [
    ("mountain_ne", "mountain", "เทือกเขาตะวันออกเฉียงเหนือ",
     [(700, 130), (1080, 130), (1080, 820), (900, 820), (780, 700), (700, 560), (680, 400), (700, 250)]),
    ("forest_nw", "forest", "ป่าเขาตะวันตกเฉียงเหนือ", [(0, 130), (430, 130), (430, 330), (300, 420), (0, 500)]),
    ("hills_west", "forest", "เนินป่าฝั่งตะวันตก",
     [(0, 600), (120, 660), (430, 810), (560, 900), (610, 1000), (570, 1180), (440, 1340), (350, 1480),
      (400, 1620), (250, 1700), (0, 1700)]),
    ("farmland_north", "farmland", "ทุ่งนาเหนือ",
     [(430, 300), (700, 300), (660, 480), (640, 560), (700, 720), (560, 860), (430, 800), (450, 600), (420, 450)]),
    ("farmland_east", "farmland", "ทุ่งนาตะวันออก",
     [(780, 960), (1080, 900), (1080, 1700), (900, 1800), (820, 1500), (880, 1250), (780, 1100)]),
    ("farmland_south", "farmland", "ทุ่งนาใต้", [(600, 1330), (760, 1330), (840, 1560), (780, 1900), (640, 1960), (600, 1700)]),
    ("urban_north", "urban", "เมืองตลาดเช้า", [(430, 370), (620, 370), (630, 520), (500, 550), (420, 480)]),
    ("urban_south", "urban", "ย่านตลาดใต้", [(600, 1850), (780, 1850), (780, 1960), (600, 1960)]),
    ("campus", "campus", "เขตวิทยาลัยและโรงพยาบาล",
     [(110, 1650), (330, 1640), (560, 1700), (680, 1800), (620, 1900), (400, 1900), (150, 1880), (90, 1780)]),
    ("industrial", "industrial", "เขตโรงงานแปรรูป", [(950, 1480), (1050, 1480), (1050, 1600), (950, 1600)]),
    ("quarry_pit", "quarry", "บ่อดินเก่า", [(480, 1245), (540, 1245), (545, 1275), (490, 1280)]),
]

# ซุ้มชุมชน (วงรี) -> สุ่มจุดบ้านเพื่อแสดงผล  (id, ชื่อ, cx, cy, rx, ry, ความหนาแน่น/unit², zone ที่ใช้ขึ้นสี)
_SETTLEMENTS = [
    ("town_north", "เมืองตลาดเช้า", 520, 440, 100, 75, 0.020),
    ("junction_town", "บ้านสามแยก", 610, 820, 60, 40, 0.016),
    ("west_village", "บ้านฝั่งตะวันตก", 170, 840, 110, 60, 0.012),
    ("pine_hamlet", "บ้านเนินสน", 430, 1175, 45, 35, 0.012),
    ("roadside_6", "บ้านริมทางหมู่หก", 735, 1470, 50, 70, 0.012),
    ("east_village", "บ้านฝั่งตะวันออก", 960, 1220, 50, 110, 0.010),
    ("fork_village", "บ้านทางแยกตะวันออก", 800, 780, 55, 60, 0.010),
    ("college_town", "ย่านวิทยาลัย", 330, 1800, 150, 80, 0.012),
    ("south_market", "ย่านตลาดใต้", 690, 1900, 90, 50, 0.018),
]
# ริบบิ้นบ้านเรือนริมทางหลวง: (road_id, y_from, y_to ในพิกัดภาพ)
_RIBBONS = [("highway_1", 540, 780), ("highway_1", 1160, 1420), ("highway_1", 1560, 1850)]

# (id, kind, ref/ชื่อ, width, [points])
_ROADS = [
    ("highway_1", "highway", "ทล.1", 12,
     [(584, 130), (560, 190), (548, 250), (545, 350), (552, 440), (560, 560), (572, 700), (588, 845), (605, 950),
      (638, 1050), (660, 1100), (655, 1160), (690, 1250), (730, 1290), (733, 1400), (727, 1520), (705, 1620),
      (695, 1750), (693, 2090)]),
    ("highway_2w", "highway", "ทล.2", 10, [(0, 575), (120, 640), (280, 722), (430, 810), (590, 845)]),
    ("highway_2e", "highway", "ทล.2", 10, [(590, 845), (700, 850), (830, 880), (940, 945), (968, 968)]),
    ("road_ne", "road", "ทช.4", 8, [(968, 968), (1080, 900)]),
    ("road_se", "road", "ทช.5", 8, [(968, 968), (940, 1030), (955, 1120), (990, 1210), (1080, 1375)]),
    ("road_west_link", "road", "ทช.6", 6, [(548, 445), (465, 465), (330, 490), (200, 505), (68, 520), (0, 540)]),
    ("road_east_north", "road", "ทช.7", 6, [(838, 330), (805, 470), (790, 600), (800, 720), (870, 800), (938, 848)]),
    ("road_south_east", "road", "ทช.8", 6, [(693, 1940), (788, 1943), (900, 1940), (1080, 1930)]),
    ("campus_ring", "road", "", 6, [(120, 1720), (250, 1712), (330, 1765), (480, 1775), (570, 1790), (690, 1860)]),
    ("campus_spur", "track", "", 4, [(250, 1712), (280, 1840), (310, 1870)]),
    ("hospital_spur", "road", "", 5, [(695, 1860), (632, 1862), (570, 1790)]),
    ("pine_link", "track", "", 4, [(655, 1160), (560, 1150), (470, 1170), (428, 1175)]),
    ("west_link", "track", "", 4, [(330, 780), (250, 850), (170, 860)]),
    ("elephant_link", "track", "", 4, [(700, 1640), (600, 1600), (480, 1545)]),
    ("east_farm_link", "track", "", 4, [(733, 1400), (800, 1440), (880, 1400)]),
]

# แม่น้ำคดเคี้ยว (จุดควบคุม -> Catmull-Rom)
_RIVER = [(690, 300), (640, 400), (615, 500), (640, 600), (720, 670), (770, 720), (740, 770), (670, 800),
          (650, 860), (690, 920), (770, 960), (800, 1020), (780, 1090), (820, 1150), (870, 1230), (900, 1300),
          (940, 1380), (950, 1470), (930, 1580), (960, 1700), (1000, 1800), (1080, 1900)]
_RIVER_HALF_W = 6.0
_SAND_W = 8.0

_PONDS = [(240, 910, 18, 12), (500, 985, 22, 14), (800, 1135, 26, 16), (520, 1710, 22, 14)]

# (id, ชื่อ, kind, x, y, tier, tags, detail_map)
_POIS = [
    ("morning_market", "ตลาดเช้าปลายทุ่ง", "market", 547, 400, "mid", ["landmark", "loot"], None),
    ("midway_fuel", "ปั๊มน้ำมันกลางทาง", "fuel", 558, 630, "mid", ["loot", "fuel"], None),
    ("old_junction", "สามแยกเมืองเก่า", "junction", 590, 845, "high", ["landmark", "chokepoint"], None),
    ("hilltop_garden", "สวนดอกไม้บนเนิน", "garden", 62, 705, "low", ["landmark"], None),
    ("pine_hamlet_poi", "บ้านเนินสน", "hamlet", 428, 1175, "low", ["hub"], "ban_rimpa"),
    ("elephant_camp", "ปางช้างริมป่า", "sanctuary", 480, 1540, "mid", ["landmark"], None),
    ("valley_college", "วิทยาลัยหุบเขา", "campus", 465, 1720, "high", ["landmark", "loot"], None),
    ("college_stadium", "สนามกีฬาวิทยาลัย", "stadium", 310, 1850, "mid", ["loot"], None),
    ("valley_hospital", "โรงพยาบาลชุมชนหุบเขา", "hospital", 632, 1862, "high", ["medical", "loot"], None),
    ("south_market_poi", "ตลาดสี่แยกใต้", "market", 688, 1945, "mid", ["loot"], None),
    ("processing_plant", "โรงงานแปรรูปเกษตร", "industrial", 1000, 1535, "high", ["loot"], None),
    ("small_reservoir", "อ่างเก็บน้ำเล็ก", "reservoir", 800, 1105, "low", ["landmark"], None),
    # ใหม่ (ไม่มีในต้นแบบ)
    ("ridge_lookout", "จุดชมวิวสันเขา", "lookout", 830, 520, "high", ["new", "overwatch"], None),
    ("ranger_post", "ด่านตรวจป่า", "post", 300, 1000, "mid", ["new", "loot"], None),
    ("bridge_checkpoint", "ด่านสะพานแม่น้ำ", "checkpoint", 655, 848, "high", ["new", "chokepoint"], None),
]
_SPAWNS = [("spawn_n", "ทางหลวงเหนือ", 582, 140), ("spawn_w", "ทางหลวงตะวันตก", 6, 576),
           ("spawn_e", "ทางหลวงตะวันออก", 1074, 905), ("spawn_se", "ถนนตะวันออกเฉียงใต้", 1074, 1370)]
_EXFILS = [("exfil_south", "ทางหลวงใต้", 693, 2080), ("exfil_east_south", "ถนนสายใต้ตะวันออก", 1074, 1930),
           ("exfil_west_north", "ทางหลวงตะวันตก-เหนือ", 6, 545)]


# ==========================================
# เรขาคณิต / noise
# ==========================================
def _T(x, y):
    return (float(x), float(y) - _Y0)


def _Tpts(pts):
    return [_T(x, y) for x, y in pts]


def _pip(x, y, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
            inside = not inside
        j = i
    return inside


def _bbox(poly):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _seg_intersect(a, b, c, d):
    """จุดตัดของ ab กับ cd (หรือ None)"""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-9:
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    if 0 <= t <= 1 and 0 <= u <= 1:
        return (a[0] + t * r[0], a[1] + t * r[1], math.atan2(r[1], r[0]))
    return None


def _catmull(pts, per=6):
    P = [pts[0]] + list(pts) + [pts[-1]]
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for k in range(per):
            t = k / per
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1[c]) + (-p0[c] + p2[c]) * t + (2 * p0[c] - 5 * p1[c] + 4 * p2[c] - p3[c]) * t2
                                    + (-p0[c] + 3 * p1[c] - 3 * p2[c] + p3[c]) * t3) for c in (0, 1)))
    out.append(tuple(pts[-1]))
    return out


def _sample_polyline(pts, step):
    out, carry = [], 0.0
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


def _hash2(ix, iy, seed):
    h = (ix * 374761393 + iy * 668265263 + seed * 1442695041) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    h ^= h >> 16
    return h / 4294967295.0


def _vnoise(x, y, seed):
    ix, iy = math.floor(x), math.floor(y)
    fx, fy = x - ix, y - iy
    sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = _hash2(ix, iy, seed), _hash2(ix + 1, iy, seed)
    c, d = _hash2(ix, iy + 1, seed), _hash2(ix + 1, iy + 1, seed)
    return (a + (b - a) * sx) + ((c + (d - c) * sx) - (a + (b - a) * sx)) * sy


# ==========================================
# ตัวแผนที่
# ==========================================
class WiangValleyMap:
    CELL = 40
    ELEV_STEP = 20.0
    NAV_STEP = 10.0

    def __init__(self, seed: int = MAP_SEED):
        self.seed = seed
        self.w, self.h = WORLD_W, WORLD_H
        self.rng = random.Random(seed)
        self.zones = [{"id": i, "kind": k, "name": n, "poly": _Tpts(p), "bbox": _bbox(_Tpts(p))}
                      for i, k, n, p in _ZONES]
        self.roads = [{"id": i, "kind": k, "ref": ref, "width": float(w), "pts": _Tpts(p)}
                      for i, k, ref, w, p in _ROADS]
        self.ponds = [{"x": float(cx), "y": cy - _Y0, "rx": rx, "ry": ry} for cx, cy, rx, ry in _PONDS]
        self.river = _catmull(_Tpts(_RIVER), 6)
        self.pois = [{"id": i, "name": n, "kind": k, "x": _T(x, y)[0], "y": _T(x, y)[1], "tier": t,
                      "tags": list(tg), "detail_map": dm} for i, n, k, x, y, t, tg, dm in _POIS]
        self.spawns = [{"id": i, "name": n, "x": _T(x, y)[0], "y": _T(x, y)[1]} for i, n, x, y in _SPAWNS]
        self.exfils = [{"id": i, "name": n, "x": _T(x, y)[0], "y": _T(x, y)[1], "radius": 14.0,
                        "kind": "road_exit"} for i, n, x, y in _EXFILS]
        self.bridges, self.homes, self.loot = [], [], []
        self._road_segs, self._road_grid = [], {}
        self._river_segs, self._river_grid = [], {}
        self._nav_cache = {}
        self._build()

    # ---------- index ----------
    def _cells(self, x0, y0, x1, y1):
        c = self.CELL
        for i in range(int(x0 // c), int(x1 // c) + 1):
            for j in range(int(y0 // c), int(y1 // c) + 1):
                yield (i, j)

    def _index(self):
        for r in self.roads:
            hw = r["width"] / 2
            for (ax, ay), (bx, by) in zip(r["pts"], r["pts"][1:]):
                k = len(self._road_segs)
                self._road_segs.append((ax, ay, bx, by, hw, r["id"], r["kind"]))
                for cell in self._cells(min(ax, bx) - hw - 2, min(ay, by) - hw - 2, max(ax, bx) + hw + 2, max(ay, by) + hw + 2):
                    self._road_grid.setdefault(cell, []).append(k)
        reach = _RIVER_HALF_W + _SAND_W + 2
        for (ax, ay), (bx, by) in zip(self.river, self.river[1:]):
            k = len(self._river_segs)
            self._river_segs.append((ax, ay, bx, by))
            for cell in self._cells(min(ax, bx) - reach, min(ay, by) - reach, max(ax, bx) + reach, max(ay, by) + reach):
                self._river_grid.setdefault(cell, []).append(k)

    def _near(self, grid, x, y):
        ci, cj = int(x // self.CELL), int(y // self.CELL)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for k in grid.get((ci + di, cj + dj), ()):
                    yield k

    def _river_dist(self, x, y):
        best = 1e9
        for k in self._near(self._river_grid, x, y):
            ax, ay, bx, by = self._river_segs[k]
            best = min(best, _seg_dist(x, y, ax, ay, bx, by))
        return best

    def _road_hit(self, x, y):
        """คืน (ช่องว่างถึงขอบถนน, kind) ของถนนที่ใกล้สุด"""
        best, kind = 1e9, None
        for k in self._near(self._road_grid, x, y):
            ax, ay, bx, by, hw, rid, rk = self._road_segs[k]
            g = _seg_dist(x, y, ax, ay, bx, by) - hw
            if g < best:
                best, kind = g, rk
        return best, kind

    def _near_bridge(self, x, y, rad=20.0):
        return any(math.hypot(x - b["x"], y - b["y"]) <= rad for b in self.bridges)

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

    # ---------- build ----------
    def _build(self):
        self._index()
        self._find_bridges()
        self._build_elevation()
        self._gen_homes()
        self._gen_loot()

    def _find_bridges(self):
        """สะพาน = จุดที่ถนน/ทางตัดแม่น้ำ (รวมจุดที่ใกล้กันเป็นจุดเดียว)"""
        for r in self.roads:
            for a, b in zip(r["pts"], r["pts"][1:]):
                for c, d in zip(self.river, self.river[1:]):
                    p = _seg_intersect(a, b, c, d)
                    if p and not any(math.hypot(p[0] - q["x"], p[1] - q["y"]) < 25 for q in self.bridges):
                        self.bridges.append({"id": f"bridge_{len(self.bridges)}", "x": round(p[0], 1),
                                             "y": round(p[1], 1), "ang": round(p[2], 3), "road": r["id"],
                                             "length": 2 * (_RIVER_HALF_W + 6)})

    def _build_elevation(self):
        S = self.ELEV_STEP
        nx, ny = int(self.w // S) + 2, int(self.h // S) + 2
        base = [[_ELEV_BASE.get(self.zone_kind_at(i * S, j * S), 40.0) for i in range(nx)] for j in range(ny)]
        amp = [[_ELEV_AMP.get(self.zone_kind_at(i * S, j * S), 6.0) for i in range(nx)] for j in range(ny)]
        for _ in range(4):  # blur ให้ขอบเขาลาดต่อเนื่อง
            for g in (base, amp):
                src = [row[:] for row in g]
                for j in range(ny):
                    for i in range(nx):
                        s, n = 0.0, 0
                        for dj in (-1, 0, 1):
                            for di in (-1, 0, 1):
                                ii, jj = i + di, j + dj
                                if 0 <= ii < nx and 0 <= jj < ny:
                                    s += src[jj][ii]
                                    n += 1
                        g[j][i] = s / n
        self._eb, self._ea, self._enx, self._eny = base, amp, nx, ny

    def _bilin(self, g, x, y):
        S = self.ELEV_STEP
        fx, fy = max(0.0, min(x / S, self._enx - 1.001)), max(0.0, min(y / S, self._eny - 1.001))
        i, j = int(fx), int(fy)
        tx, ty = fx - i, fy - j
        a = g[j][i] + (g[j][i + 1] - g[j][i]) * tx
        b = g[j + 1][i] + (g[j + 1][i + 1] - g[j + 1][i]) * tx
        return a + (b - a) * ty

    def elevation_at(self, x, y):
        """ความสูงเป็นเมตร (ประมาณ)"""
        e = self._bilin(self._eb, x, y)
        a = self._bilin(self._ea, x, y)
        n = (_vnoise(x / 70.0, y / 70.0, self.seed) * 0.65 + _vnoise(x / 28.0, y / 28.0, self.seed + 7) * 0.35 - 0.5) * 2
        e += n * a
        d = self._river_dist(x, y)
        if d < 40:
            e -= (1 - d / 40) * 12
        return max(2.0, e)

    def slope_at(self, x, y):
        d = 8.0
        dzx = self.elevation_at(x + d, y) - self.elevation_at(x - d, y)
        dzy = self.elevation_at(x, y + d) - self.elevation_at(x, y - d)
        return math.hypot(dzx, dzy) / (2 * d * METERS_PER_UNIT)

    def _gen_homes(self):
        rng = self.rng
        homes = []
        occ = set()

        def put(x, y):
            if not (1 < x < self.w - 1 and 1 < y < self.h - 1):
                return
            key = (int(x // 3), int(y // 3))
            if key in occ:
                return
            if self._in_water(x, y) or self._river_dist(x, y) < _RIVER_HALF_W + _SAND_W:
                return
            gap, _ = self._road_hit(x, y)
            if gap < 2.5:
                return
            if self.slope_at(x, y) > 0.35:
                return
            occ.add(key)
            homes.append((round(x, 1), round(y, 1)))

        for sid, name, cx, cy, rx, ry, dens in _SETTLEMENTS:
            cx, cy = _T(cx, cy)
            n = int(math.pi * rx * ry * dens)
            for _ in range(n * 3):
                if n <= 0:
                    break
                a, r = rng.uniform(0, math.tau), math.sqrt(rng.random())
                x, y = cx + math.cos(a) * rx * r, cy + math.sin(a) * ry * r
                before = len(homes)
                put(x, y)
                if len(homes) > before:
                    n -= 1
        for rid, y0, y1 in _RIBBONS:
            road = next(r for r in self.roads if r["id"] == rid)
            for x, y, ang in _sample_polyline(road["pts"], 7.0):
                if not (y0 - _Y0 <= y <= y1 - _Y0):
                    continue
                for side in (-1, 1):
                    if rng.random() < 0.55:
                        continue
                    off = rng.uniform(11, 26) * side
                    put(x - math.sin(ang) * off, y + math.cos(ang) * off)
        self.homes = homes

    def _gen_loot(self):
        rng = self.rng
        for p in self.pois:
            n = {"high": 5, "mid": 3, "low": 2}[p["tier"]]
            k = 0
            for _ in range(80):
                if k >= n:
                    break
                a, r = rng.uniform(0, math.tau), rng.uniform(3, 18)
                x, y = p["x"] + math.cos(a) * r, p["y"] + math.sin(a) * r
                if self.blocked(x, y):
                    continue
                self.loot.append({"id": f"loot_{p['id']}_{k}", "x": round(x, 1), "y": round(y, 1),
                                  "tier": p["tier"], "poi": p["id"]})
                k += 1

    # ---------- query ----------
    def _in_water(self, x, y):
        for p in self.ponds:
            dx, dy = (x - p["x"]) / p["rx"], (y - p["y"]) / p["ry"]
            if dx * dx + dy * dy <= 1.0:
                return True
        return self._river_dist(x, y) <= _RIVER_HALF_W and not self._near_bridge(x, y)

    def terrain_at(self, x, y):
        if not (0 <= x <= self.w and 0 <= y <= self.h):
            return "void"
        if self._in_water(x, y):
            return "water"
        gap, rk = self._road_hit(x, y)
        if gap <= 0:
            return {"highway": "highway", "road": "road"}.get(rk, "track")
        if self._river_dist(x, y) <= _RIVER_HALF_W + _SAND_W:
            return "sand"
        if self.slope_at(x, y) > CLIFF_SLOPE:
            return "cliff"
        return self.zone_kind_at(x, y) or "grass"

    def blocked(self, x, y, r=PLAYER_RADIUS_DEFAULT):
        if not (r <= x <= self.w - r and r <= y <= self.h - r):
            return True
        return not TERRAIN[self.terrain_at(x, y)]["walkable"]

    def probe(self, x, y):
        t = self.terrain_at(x, y)
        info = TERRAIN.get(t, {"speed": 0, "cover": 0, "walkable": False, "label": "นอกแมพ"})
        inside = 0 <= x <= self.w and 0 <= y <= self.h
        return {"x": x, "y": y, "terrain": t, "label": info["label"], "speed": info["speed"], "cover": info["cover"],
                "blocked": not info["walkable"], "elevation_m": round(self.elevation_at(x, y), 1) if inside else None,
                "slope": round(self.slope_at(x, y), 3) if inside else None}

    def query_box(self, x0, y0, x1, y1, cap=4000):
        def inb(x, y, pad=0.0):
            return x0 - pad <= x <= x1 + pad and y0 - pad <= y <= y1 + pad
        return {
            "homes": [h for h in self.homes if inb(h[0], h[1])][:cap],
            "pois": [p for p in self.pois if inb(p["x"], p["y"], 10)],
            "loot": [l for l in self.loot if inb(l["x"], l["y"])],
            "bridges": [b for b in self.bridges if inb(b["x"], b["y"], 20)],
            "roads": [r for r in self.roads if any(inb(px, py, 20) for px, py in r["pts"])],
            "spawns": [s for s in self.spawns if inb(s["x"], s["y"])],
            "exfils": [e for e in self.exfils if inb(e["x"], e["y"], e["radius"])],
        }

    # ---------- nav / A* ----------
    def _nav_info(self, i, j):
        k = (i, j)
        v = self._nav_cache.get(k)
        if v is None:
            x, y = (i + 0.5) * self.NAV_STEP, (j + 0.5) * self.NAV_STEP
            t = self.terrain_at(x, y)
            info = TERRAIN[t] if t in TERRAIN else {"walkable": False, "speed": 0}
            if not info["walkable"]:
                v = (False, 0.0)
            else:
                slope = 0.0 if t in ("highway", "road") else self.slope_at(x, y)
                v = (True, (1.0 / max(info["speed"], 0.05)) * (1.0 + 3.0 * slope))
            self._nav_cache[k] = v
        return v

    def _snap(self, x, y):
        i0, j0 = int(x // self.NAV_STEP), int(y // self.NAV_STEP)
        nx, ny = int(self.w // self.NAV_STEP), int(self.h // self.NAV_STEP)
        for rad in range(0, 8):
            for di in range(-rad, rad + 1):
                for dj in range(-rad, rad + 1):
                    if max(abs(di), abs(dj)) != rad:
                        continue
                    i, j = i0 + di, j0 + dj
                    if 0 <= i < nx and 0 <= j < ny and self._nav_info(i, j)[0]:
                        return (i, j)
        return None

    def _los(self, a, b):
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 4))
        for k in range(n + 1):
            t = k / n
            if self.blocked(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t):
                return False
        return True

    def _simplify(self, pts, tol):
        """Douglas-Peucker: เก็บรูปเส้นทางตามถนน/ทาง (ไม่ตัดตรงข้ามเนินเหมือน line-of-sight)
        และถ้าช่วงที่ย่อแล้วชนสิ่งกีดขวาง จะแบ่งต่อ"""
        keep = {0, len(pts) - 1}
        stack = [(0, len(pts) - 1)]
        while stack:
            a, b = stack.pop()
            if b <= a + 1:
                continue
            ax, ay = pts[a]
            bx, by = pts[b]
            far, fd = -1, -1.0
            for k in range(a + 1, b):
                d = _seg_dist(pts[k][0], pts[k][1], ax, ay, bx, by)
                if d > fd:
                    far, fd = k, d
            if fd > tol or not self._los(pts[a], pts[b]):
                keep.add(far)
                stack.append((a, far))
                stack.append((far, b))
        return [pts[k] for k in sorted(keep)]

    def find_path(self, x1, y1, x2, y2, max_nodes=60000):
        s, g = self._snap(x1, y1), self._snap(x2, y2)
        if s is None or g is None:
            return {"ok": False, "reason": "start/goal blocked", "path": []}
        S, nx, ny = self.NAV_STEP, int(self.w // self.NAV_STEP), int(self.h // self.NAV_STEP)
        openh, came, gs, n, found = [(0.0, 0.0, s)], {s: None}, {s: 0.0}, 0, False
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
                    if not (di or dj):
                        continue
                    nb = (cur[0] + di, cur[1] + dj)
                    if not (0 <= nb[0] < nx and 0 <= nb[1] < ny):
                        continue
                    ok, cost = self._nav_info(*nb)
                    if not ok:
                        continue
                    if di and dj and not (self._nav_info(cur[0] + di, cur[1])[0] and self._nav_info(cur[0], cur[1] + dj)[0]):
                        continue
                    ng = cg + (1.414 if di and dj else 1.0) * S * cost
                    if ng < gs.get(nb, 1e18):
                        gs[nb], came[nb] = ng, cur
                        heapq.heappush(openh, (ng + math.hypot(nb[0] - g[0], nb[1] - g[1]) * S * 0.6, ng, nb))
        if not found:
            return {"ok": False, "reason": "no path", "path": [], "expanded": n}
        cells, cur = [], g
        while cur is not None:
            cells.append(((cur[0] + 0.5) * S, (cur[1] + 0.5) * S))
            cur = came[cur]
        cells.reverse()
        pts = [(x1, y1)] + cells + [(x2, y2)]
        smooth = self._simplify(pts, 5.0)
        length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(smooth, smooth[1:]))
        return {"ok": True, "length_units": round(length, 1), "length_m": round(length * METERS_PER_UNIT),
                "expanded": n, "path": [[round(px, 1), round(py, 1)] for px, py in smooth]}

    # ---------- export ----------
    def stats(self):
        return {"counts": {"zones": len(self.zones), "roads": len(self.roads), "bridges": len(self.bridges),
                           "homes": len(self.homes), "ponds": len(self.ponds), "pois": len(self.pois),
                           "loot": len(self.loot), "spawns": len(self.spawns), "exfils": len(self.exfils)},
                "world_units": [self.w, self.h], "meters_per_unit": METERS_PER_UNIT,
                "world_km": [round(self.w * METERS_PER_UNIT / 1000, 2), round(self.h * METERS_PER_UNIT / 1000, 2)],
                "area_km2": round(self.w * self.h * METERS_PER_UNIT ** 2 / 1e6, 1)}

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
                "scale": self.stats(), "terrain": TERRAIN, "pois": self.pois, "spawns": self.spawns,
                "exfils": self.exfils, "bridges": self.bridges, "cliff_slope": CLIFF_SLOPE}

    def to_dict(self):
        d = self.meta()
        d.update({"zones": [{"id": z["id"], "kind": z["kind"], "name": z["name"],
                             "poly": [[round(x, 1), round(y, 1)] for x, y in z["poly"]]} for z in self.zones],
                  "roads": [{"id": r["id"], "kind": r["kind"], "ref": r["ref"], "width": r["width"],
                             "pts": [[round(x, 1), round(y, 1)] for x, y in r["pts"]]} for r in self.roads],
                  "river": {"half_width": _RIVER_HALF_W, "sand_width": _SAND_W,
                            "pts": [[round(x, 1), round(y, 1)] for x, y in self.river]},
                  "ponds": self.ponds, "homes": self.homes, "loot": self.loot})
        return d

    def to_svg(self, width_px=540):
        col = {"mountain": "#4a4a3a", "forest": "#3d5a35", "farmland": "#8ea65a", "urban": "#8d8574",
               "village": "#8d8574", "campus": "#9aa08a", "industrial": "#a7a7a7", "quarry": "#c9b98a"}
        rcol = {"highway": "#f2c14e", "road": "#e6e0cf", "track": "#a89a74"}
        h_px = int(width_px * self.h / self.w)
        o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{width_px}" height="{h_px}">'
             f'<rect width="{self.w}" height="{self.h}" fill="#6f8b4a"/>']
        for z in self.zones:
            o.append(f'<polygon points="{" ".join(f"{x:.0f},{y:.0f}" for x, y in z["poly"])}" fill="{col[z["kind"]]}"/>')
        rp = " ".join(f"{x:.0f},{y:.0f}" for x, y in self.river)
        o.append(f'<polyline points="{rp}" fill="none" stroke="#d8c89a" stroke-width="{2 * (_RIVER_HALF_W + _SAND_W)}" stroke-linecap="round"/>')
        o.append(f'<polyline points="{rp}" fill="none" stroke="#3f7fa6" stroke-width="{2 * _RIVER_HALF_W}" stroke-linecap="round"/>')
        for p in self.ponds:
            o.append(f'<ellipse cx="{p["x"]:.0f}" cy="{p["y"]:.0f}" rx="{p["rx"]}" ry="{p["ry"]}" fill="#3f7fa6"/>')
        for r in sorted(self.roads, key=lambda r: r["width"]):
            o.append(f'<polyline points="{" ".join(f"{x:.0f},{y:.0f}" for x, y in r["pts"])}" fill="none" '
                     f'stroke="{rcol[r["kind"]]}" stroke-width="{r["width"]}" stroke-linejoin="round"/>')
        for b in self.bridges:
            o.append(f'<rect x="-14" y="-5" width="28" height="10" fill="#666" transform="translate({b["x"]} {b["y"]}) rotate({math.degrees(b["ang"]):.0f})"/>')
        for x, y in self.homes:
            o.append(f'<rect x="{x}" y="{y}" width="2" height="2" fill="#e8e2d6"/>')
        for e in self.exfils:
            o.append(f'<circle cx="{e["x"]:.0f}" cy="{e["y"]:.0f}" r="{e["radius"]}" fill="#2ecc71" fill-opacity=".45" stroke="#2ecc71"/>')
        for s in self.spawns:
            o.append(f'<circle cx="{s["x"]:.0f}" cy="{s["y"]:.0f}" r="7" fill="#e74c3c" stroke="#fff"/>')
        for p in self.pois:
            o.append(f'<circle cx="{p["x"]:.0f}" cy="{p["y"]:.0f}" r="5" fill="#ffe14d" stroke="#000"/>'
                     f'<text x="{p["x"]:.0f}" y="{p["y"] - 9:.0f}" font-size="18" fill="#fff" stroke="#000" '
                     f'stroke-width=".7" text-anchor="middle">{p["name"]}</text>')
        o.append("</svg>")
        return "".join(o)


# ==========================================
# singleton + attach
# ==========================================
_MAP = None
_LOCK = threading.Lock()
_ATTACHED = False


def get_map() -> WiangValleyMap:
    global _MAP
    if _MAP is None:
        with _LOCK:
            if _MAP is None:
                t0 = time.time()
                _MAP = WiangValleyMap()
                print(f"[Wiang Valley] สร้างแผนที่เสร็จ {time.time() - t0:.2f}s — {_MAP.stats()['counts']}")
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
    """เรียกก่อน sio.run(...) — ลงทะเบียนแมพ + เปิด API อ่านอย่างเดียว
    ลงทะเบียนเข้า XROOM_MAP_POOL + แมพ Auction Extraction โดยค่าเริ่มต้น (ปิดด้วย VMAX_VALLEY_REGISTER_XROOM=0)
    จุดสุ่ม (airdrop/ภารกิจ/ของใน raid) ถูก snap เข้าพื้นที่เดินได้ด้วย nearest_walkable()"""
    global _ATTACHED
    if _ATTACHED:
        return
    _ATTACHED = True
    m = get_map()
    app = main_globals.get("app")
    _register_extraction(
        main_globals, m,
        auction_entry={"id": MAP_ID, "name": "Wiang Valley", "subtitle": "หุบเขาเวียงสาย / แมพใหญ่ ทางหลวง+แม่น้ำ+ภูเขา",
                       "entry_fee": int(os.environ.get("VMAX_VALLEY_AUCTION_FEE", "1000000")), "ticket": 20000,
                       "players": 4, "difficulty": "สูงมาก"},
        loot_table=[("scrap_metal", 28), ("cloth", 14), ("wood", 16), ("electronics", 16), ("iron_ingot", 10),
                    ("med_kit", 8), ("power_cell", 5), ("encrypted_drive", 3)],
        xroom_env="VMAX_VALLEY_REGISTER_XROOM", xroom_default="1",
        extra_pool={"meters_per_unit": METERS_PER_UNIT})
    mods = main_globals.get("VMAX_MODULES")
    if isinstance(mods, dict):
        mods["map_wiang_valley"] = "แผนที่ภูมิภาคหุบเขา: ทางหลวง/แม่น้ำ+สะพาน/ภูเขา/ความสูง/A*/portal ไปแมพหมู่บ้าน"
    layouts = main_globals.setdefault("VMAX_MAP_LAYOUTS", {})
    layouts[MAP_ID] = m
    if "ban_rimpa" in layouts:
        print("[Wiang Valley] เชื่อมแมพละเอียด ban_rimpa แล้ว (POI 'บ้านเนินสน' -> detail_map)")
    if app is None:
        print("[Wiang Valley] ⚠️  ไม่พบ app — ลงทะเบียนแมพแล้วแต่ไม่เปิด API")
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
        b = [_f("x0", 0), _f("y0", 0), _f("x1", WORLD_W), _f("y1", WORLD_H)]
        if None in b:
            return jsonify({"st": "error", "msg": "x0,y0,x1,y1 ต้องเป็นตัวเลข"}), 400
        return jsonify({"st": "ok", "box": b, "features": get_map().query_box(*b)})

    def api_terrain():
        x, y = _f("x"), _f("y")
        if x is None or y is None:
            return jsonify({"st": "error", "msg": "ต้องส่ง x,y เป็นตัวเลข"}), 400
        return jsonify({"st": "ok", **get_map().probe(x, y)})

    def api_path():
        v = [_f(k) for k in ("x1", "y1", "x2", "y2")]
        if None in v:
            return jsonify({"st": "error", "msg": "ต้องส่ง x1,y1,x2,y2"}), 400
        return jsonify({"st": "ok", **get_map().find_path(*v)})

    def api_svg():
        return Response(get_map().to_svg(int(_f("w", 540) or 540)), mimetype="image/svg+xml")

    for rule, fn, name in (
        (f"/api/map/{MAP_ID}", api_meta, "vmax_valley_meta"),
        (f"/api/map/{MAP_ID}/full", api_full, "vmax_valley_full"),
        (f"/api/map/{MAP_ID}/query", api_query, "vmax_valley_query"),
        (f"/api/map/{MAP_ID}/terrain", api_terrain, "vmax_valley_terrain"),
        (f"/api/map/{MAP_ID}/path", api_path, "vmax_valley_path"),
        (f"/maps/{MAP_ID}/preview.svg", api_svg, "vmax_valley_svg"),
    ):
        try:
            app.add_url_rule(rule, endpoint=name, view_func=fn, methods=["GET"])
        except Exception as exc:
            print(f"[Wiang Valley] ⚠️  ลงทะเบียน {rule} ไม่สำเร็จ ข้าม: {exc}")
    print(f"[Wiang Valley] ✅ ต่อโมดูลแล้ว — ดูตัวอย่าง: /maps/{MAP_ID}/preview.svg")


def _cli():
    import argparse
    ap = argparse.ArgumentParser(description="Wiang Valley map exporter")
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
