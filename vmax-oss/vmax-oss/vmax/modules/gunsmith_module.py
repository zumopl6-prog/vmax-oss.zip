# =====================================================================
# VMAX Module: Gunsmith (หน้าแต่งปืน) — แต่งรอบที่แล้ว / พรีเซ็ต + ยืนยัน Yes/No พร้อมภาษี 7%
# =====================================================================
# แพทเทิร์นเดียวกับโมดูลอื่น: ฝังเป็น base64 ในไฟล์หลัก -> self-extract -> attach(globals())
#
# ที่หน้าแต่งปืน:
#   - ช่องอุปกรณ์เสริมอยู่ข้าง ๆ รูปปืน (ศูนย์เล็ง/ปากกระบอก/ด้ามหน้า/พานท้าย/แม็กกาซีน/ไฟ-เลเซอร์/ขาทราย)
#   - การ์ด "แต่งรอบที่แล้ว" = ชุดอุปกรณ์ที่ปืนกระบอกนั้นเคยใส่ก่อนหน้า (หรือที่เซฟตอนจบเรด)
#     + พรีเซ็ตที่เซฟเองได้ 5 ช่องต่อปืน
#   - กดการ์ด -> ขึ้นกล่อง "คุณต้องการแต่งปืนนี้หรือไม่?" มีรายการที่ต้องจ่าย, ค่าอุปกรณ์,
#     ภาษี 7%, ยอดรวม, เงินคงเหลือ และปุ่ม Yes / No ด้านล่าง
#   - กด Yes -> เซิร์ฟเวอร์คำนวณราคาใหม่เอง หักเงิน แล้วติดตั้งทั้งชุดในครั้งเดียว
# ราคา/ภาษีคำนวณฝั่งเซิร์ฟเวอร์ทั้งหมด (client ส่งมาแค่ยอดที่เห็นบนหน้าจอเพื่อกันราคาเปลี่ยนระหว่างกด)
# อุปกรณ์ที่ถอดออกจะเก็บเข้า "คลังอุปกรณ์เสริม" ใส่กลับครั้งหน้าไม่ต้องจ่ายซ้ำ
# ตัวเลขสเตตัสเป็นค่าเชิงเกมล้วน ๆ (ไม่เกี่ยวกับข้อมูลทางเทคนิคของอาวุธจริง)
#
# [v2] สเตตัสที่ผูกกับการยิง/ตีจริงในเกม (ฝั่งเซิร์ฟเวอร์เป็นคนคิดเองจาก build ที่ติดตั้งอยู่):
#   - noise  = รัศมีเสียงปืน (ม. เชิงเกม) — ตัวเก็บเสียงลดรัศมีที่ศัตรู/ซอมบี้/หิ่งห้อยได้ยิน, เบรก/คอมเพนเซเตอร์ทำให้ดังขึ้น
#   - flash  = แสงปากกระบอก (% ของปกติ) — ตัวซ่อนแสง/ตัวเก็บเสียงลดแสง; ตัวเก็บเสียงทำให้สกิลอ่านแสงปลายกระบอกเห็นได้เฉพาะใกล้
#   - stab   = ดาเมจแทงของดาบปลายปืน (0 = ไม่มีดาบปลายปืน) — ใช้ในโหมดแทงของระบบทุบด้วยปืน
#   - fire_profile(uid, weapon_id) = ฟังก์ชันที่ระบบยิง (ballistic_fire / endpoint shoot) เรียกเพื่อดึงค่าเหล่านี้
# =====================================================================
from __future__ import annotations

import json
import os
import threading
import time

_ATTACHED = False
_READY = False
_LOCK = threading.RLock()

STATE_FILE = "vmax_gunsmith_state.json"
TAX_RATE_PERCENT = 7            # ภาษี 7% (ตรงกับ VAT ไทยในตาราง VAT_RATES_TABLE ของไฟล์หลัก)
CURRENCY_KEY = "credits"        # เงินที่ใช้จ่าย = P["credits"] ของผู้เล่น (เปลี่ยนคีย์ได้ที่นี่ที่เดียว)
CURRENCY_LABEL = "เครดิต"
PRESET_SLOTS = 5

SLOT_INFO = {
    "optic":     {"name": "ศูนย์เล็ง", "icon": "🔭"},
    "backup":    {"name": "ศูนย์สำรอง", "icon": "🎯"},
    "muzzle":    {"name": "ปากกระบอก", "icon": "🔩"},
    "barrel":    {"name": "ลำกล้อง", "icon": "📏"},
    "handguard": {"name": "แฮนด์การ์ด", "icon": "🛡️"},
    "foregrip":  {"name": "ด้ามหน้า", "icon": "✊"},
    "grip":      {"name": "ด้ามจับปืน", "icon": "🤚"},
    "bipod":     {"name": "ขาทราย", "icon": "🦴"},
    "stock":     {"name": "พานท้าย", "icon": "🧱"},
    "magazine":  {"name": "แม็กกาซีน", "icon": "📦"},
    "light":     {"name": "ไฟ/เลเซอร์", "icon": "🔦"},
    "sling":     {"name": "สายสะพาย", "icon": "🎗️"},
    "bayonet":   {"name": "ดาบปลายปืน", "icon": "🗡️"},
}
SLOT_ORDER = ["optic", "backup", "muzzle", "barrel", "handguard", "foregrip", "grip", "bipod",
              "stock", "magazine", "light", "sling", "bayonet"]

# base: recoil(ยิ่งต่ำยิ่งดี) ergo acc (0-100) range(เมตร เชิงเกม) mag(นัด) weight(กก.)
WEAPONS = {
    "vx9":   {"name": "VX-9 ปืนพก",        "cls": "pistol",  "slots": ["optic", "muzzle", "barrel", "grip", "magazine", "light"],
              "base": {"recoil": 38, "ergo": 70, "acc": 55, "range": 80,  "mag": 15, "weight": 0.9}},
    "vx45":  {"name": "VX-45 SMG",         "cls": "smg",     "slots": ["optic", "backup", "muzzle", "barrel", "handguard", "foregrip", "grip", "stock", "magazine", "light", "sling", "bayonet"],
              "base": {"recoil": 45, "ergo": 60, "acc": 50, "range": 120, "mag": 30, "weight": 2.8}},
    "vx12":  {"name": "VX-12 ลูกซอง",      "cls": "shotgun", "slots": ["optic", "backup", "muzzle", "barrel", "foregrip", "grip", "stock", "magazine", "light", "sling", "bayonet"],
              "base": {"recoil": 75, "ergo": 45, "acc": 35, "range": 45,  "mag": 8,  "weight": 3.4}},
    "vx556": {"name": "VX-556 ไรเฟิล",     "cls": "rifle",   "slots": ["optic", "backup", "muzzle", "barrel", "handguard", "foregrip", "grip", "bipod", "stock", "magazine", "light", "sling", "bayonet"],
              "base": {"recoil": 50, "ergo": 55, "acc": 60, "range": 400, "mag": 30, "weight": 3.6}},
    "vxdmr": {"name": "VX-DMR ไรเฟิลระยะไกล", "cls": "dmr",  "slots": ["optic", "backup", "muzzle", "barrel", "handguard", "grip", "bipod", "stock", "magazine", "sling"],
              "base": {"recoil": 60, "ergo": 40, "acc": 75, "range": 600, "mag": 20, "weight": 4.8}},
    "vx50":  {"name": "VX-50 สไนเปอร์",    "cls": "sniper",  "slots": ["optic", "muzzle", "barrel", "bipod", "stock", "magazine", "sling"],
              "base": {"recoil": 80, "ergo": 30, "acc": 90, "range": 900, "mag": 5,  "weight": 6.5}},
}

# เสียงปืนพื้นฐานตามคลาส = รัศมีที่ศัตรูได้ยิน (ม. เชิงเกม) — ไรเฟิล 420 ตรงกับค่าเดิมที่เกมใช้อยู่ก่อนมีระบบนี้
NOISE_BASE = {"pistol": 300.0, "smg": 360.0, "shotgun": 480.0, "rifle": 420.0, "dmr": 450.0, "sniper": 520.0}
DEFAULT_NOISE_M = 420.0          # ใช้เมื่อไม่รู้ว่าผู้เล่นถือปืนกระบอกไหน (เท่าเดิมทุกประการ)
MIN_NOISE_M = 25.0               # ติดตัวเก็บเสียงเต็มที่ก็ยังไม่เงียบสนิท
MIN_NOISE_FACTOR = 0.10          # ตัวคูณเสียงต่ำสุด (กันเลข % ซ้อนกันจนติดลบ)
MIN_FLASH_FACTOR = 0.05
SUPPRESSED_NOISE_PCT = -40       # noise_pct รวมต่ำกว่าหรือเท่านี้ = นับว่า "ติดตัวเก็บเสียง"
BASE_FLASH_RANGE_M = 200.0       # ระยะที่เห็นแสงปากกระบอกปกติ (ตรงกับ VMAX_BSK_FLASH_RANGE_M)
CLASS_TO_WID = {"pistol": "vx9", "smg": "vx45", "shotgun": "vx12", "rifle": "vx556", "dmr": "vxdmr", "sniper": "vx50"}
for _w in WEAPONS.values():
    _w["base"].setdefault("noise", NOISE_BASE[_w["cls"]])

ALL = None  # = ทุกคลาส
# d = ตัวปรับสเตตัส: recoil/ergo/acc เป็นค่าบวก-ลบตรง ๆ, range_pct/mag_pct/noise_pct/flash_pct เป็น %, weight เป็น กก.,
#     stab = ดาเมจแทง (ดาบปลายปืน)
# wiki = หัวข้อที่ตรงกับ WEAPON_ATTACHMENT_WIKI_CATALOG ของไฟล์หลัก (ใช้เป็นคำอธิบาย)
ATTACH = {
    "reflex": {"slot": "optic", "name": "ศูนย์สะท้อนแสง", "price": 1200, "cls": ALL, "wiki": "Reflex sight",
               "d": {"acc": 4, "ergo": -1, "weight": 0.1}},
    "red_dot": {"slot": "optic", "name": "เรดดอต", "price": 1800, "cls": ALL, "wiki": "Red dot sight",
               "d": {"acc": 6, "ergo": -1, "weight": 0.2}},
    "mini_dot": {"slot": "optic", "name": "เรดดอตจิ๋ว", "price": 1500, "cls": ["pistol", "smg"], "wiki": "Red dot sight",
               "d": {"acc": 4, "weight": 0.06}},
    "night_sights": {"slot": "optic", "name": "ศูนย์เหล็กเรืองแสง", "price": 1000, "cls": ["pistol"], "wiki": "Iron sights",
               "d": {"acc": 5, "weight": 0.02}},
    "ghost_ring": {"slot": "optic", "name": "ศูนย์วงแหวน (ลูกซอง)", "price": 1300, "cls": ["shotgun"], "wiki": "Iron sights",
               "d": {"acc": 6, "ergo": -1, "weight": 0.08}},
    "holo": {"slot": "optic", "name": "ศูนย์โฮโลกราฟิก", "price": 3200, "cls": ["smg", "shotgun", "rifle", "dmr"], "wiki": "Holographic weapon sight",
               "d": {"acc": 8, "ergo": -2, "weight": 0.35}},
    "prism3x": {"slot": "optic", "name": "ศูนย์พริซึม 3 เท่า", "price": 3600, "cls": ["smg", "shotgun", "rifle", "dmr"], "wiki": "Optical sight",
               "d": {"acc": 10, "ergo": -3, "range_pct": 10, "weight": 0.45}},
    "scope4x": {"slot": "optic", "name": "กล้องเล็ง 4 เท่า", "price": 4500, "cls": ["rifle", "dmr", "sniper"], "wiki": "Telescopic sight",
               "d": {"acc": 12, "ergo": -4, "range_pct": 15, "weight": 0.5}},
    "lpvo": {"slot": "optic", "name": "กล้องเล็งปรับกำลัง 1-6 เท่า", "price": 6200, "cls": ["rifle", "dmr"], "wiki": "Telescopic sight",
               "d": {"acc": 15, "ergo": -5, "range_pct": 22, "weight": 0.65}},
    "scope8x": {"slot": "optic", "name": "กล้องเล็ง 8 เท่า", "price": 7800, "cls": ["dmr", "sniper"], "wiki": "Rifle scope",
               "d": {"acc": 18, "ergo": -8, "range_pct": 30, "weight": 0.8}},
    "nv_scope": {"slot": "optic", "name": "กล้องเล็งมองกลางคืน", "price": 9800, "cls": ["rifle", "dmr", "sniper"], "wiki": "Night-vision device",
               "d": {"acc": 11, "ergo": -8, "range_pct": 20, "weight": 0.8}},
    "scope12x": {"slot": "optic", "name": "กล้องเล็ง 12 เท่า", "price": 10500, "cls": ["sniper"], "wiki": "Rifle scope",
               "d": {"acc": 22, "ergo": -10, "range_pct": 40, "weight": 0.95}},
    "thermal_scope": {"slot": "optic", "name": "กล้องเล็งความร้อน", "price": 13000, "cls": ["rifle", "dmr", "sniper"], "wiki": "Thermal weapon sight",
               "d": {"acc": 14, "ergo": -9, "range_pct": 25, "weight": 0.9}},
    "scope20x": {"slot": "optic", "name": "กล้องเล็งไกลพิเศษ 20 เท่า", "price": 14500, "cls": ["sniper"], "wiki": "Rifle scope",
               "d": {"acc": 26, "ergo": -14, "range_pct": 60, "weight": 1.3}},
    "flip_irons": {"slot": "backup", "name": "ศูนย์เหล็กพับได้", "price": 1000, "cls": ["smg", "shotgun", "rifle", "dmr"], "wiki": "Iron sights",
               "d": {"acc": 3, "weight": 0.12}},
    "offset_irons": {"slot": "backup", "name": "ศูนย์เหล็กเอียง 45°", "price": 1200, "cls": ["smg", "rifle", "dmr"], "wiki": "Iron sights",
               "d": {"acc": 2, "ergo": 1, "weight": 0.12}},
    "offset_dot": {"slot": "backup", "name": "เรดดอตสำรองเอียง 45°", "price": 2100, "cls": ["smg", "rifle", "dmr"], "wiki": "Red dot sight",
               "d": {"acc": 4, "ergo": -1, "weight": 0.15}},
    "flash_hider": {"slot": "muzzle", "name": "ตัวซ่อนแสงปากกระบอก", "price": 1500, "cls": ["smg", "rifle", "dmr", "sniper"], "wiki": "Flash suppressor",
               "d": {"recoil": -3, "weight": 0.15, "flash_pct": -60}},
    "compensator": {"slot": "muzzle", "name": "คอมเพนเซเตอร์", "price": 2200, "cls": ALL, "wiki": "Compensator (firearms)",
               "d": {"recoil": -6, "ergo": -1, "weight": 0.2, "noise_pct": 8}},
    "linear_comp": {"slot": "muzzle", "name": "ลิเนียร์คอมเพนเซเตอร์", "price": 2600, "cls": ["pistol", "smg"], "wiki": "Compensator (firearms)",
               "d": {"recoil": -5, "weight": 0.15, "noise_pct": 6}},
    "muzzle_brake": {"slot": "muzzle", "name": "เบรกปากกระบอก", "price": 3000, "cls": ["shotgun", "rifle", "dmr", "sniper"], "wiki": "Muzzle brake",
               "d": {"recoil": -10, "ergo": -2, "weight": 0.3, "noise_pct": 15}},
    "choke_wide": {"slot": "muzzle", "name": "ชอคกระจาย", "price": 1400, "cls": ["shotgun"], "wiki": "Choke (firearms)",
               "d": {"recoil": -1, "ergo": 2, "range_pct": -15, "weight": 0.06}},
    "choke_full": {"slot": "muzzle", "name": "ชอคแน่น", "price": 1800, "cls": ["shotgun"], "wiki": "Choke (firearms)",
               "d": {"acc": 8, "recoil": 2, "range_pct": 25, "weight": 0.1}},
    "suppressor_short": {"slot": "muzzle", "name": "ตัวเก็บเสียงสั้น", "price": 5200, "cls": ["pistol", "smg", "rifle", "dmr"], "wiki": "Suppressor",
               "d": {"recoil": -3, "ergo": -3, "range_pct": -3, "weight": 0.35, "noise_pct": -45, "flash_pct": -75}},
    "suppressor": {"slot": "muzzle", "name": "ตัวเก็บเสียงมาตรฐาน", "price": 6800, "cls": ["smg", "rifle", "dmr", "sniper"], "wiki": "Suppressor",
               "d": {"recoil": -4, "acc": 2, "ergo": -4, "range_pct": -5, "weight": 0.55, "noise_pct": -60, "flash_pct": -85}},
    "suppressor_long": {"slot": "muzzle", "name": "ตัวเก็บเสียงยาว", "price": 9000, "cls": ["dmr", "sniper"], "wiki": "Suppressor",
               "d": {"recoil": -6, "acc": 3, "ergo": -6, "range_pct": -4, "weight": 0.8, "noise_pct": -70, "flash_pct": -90}},
    "ported_barrel": {"slot": "barrel", "name": "ลำกล้องเจาะรูระบาย", "price": 2800, "cls": ["pistol", "smg", "shotgun"], "wiki": "Gun barrel",
               "d": {"recoil": -5, "ergo": -1, "weight": 0.1, "noise_pct": 8}},
    "short_barrel": {"slot": "barrel", "name": "ลำกล้องสั้น", "price": 3200, "cls": ["pistol", "smg", "shotgun", "rifle"], "wiki": "Gun barrel",
               "d": {"recoil": 4, "ergo": 6, "acc": -4, "range_pct": -20, "weight": -0.25, "noise_pct": 10}},
    "long_barrel": {"slot": "barrel", "name": "ลำกล้องยาว", "price": 3800, "cls": ["pistol", "smg", "shotgun", "rifle", "dmr", "sniper"], "wiki": "Gun barrel",
               "d": {"acc": 5, "ergo": -5, "range_pct": 20, "weight": 0.4}},
    "match_barrel": {"slot": "barrel", "name": "ลำกล้องแมตช์", "price": 5200, "cls": ["pistol", "smg", "rifle", "dmr", "sniper"], "wiki": "Gun barrel",
               "d": {"acc": 9, "ergo": -2, "weight": 0.3}},
    "heavy_barrel": {"slot": "barrel", "name": "ลำกล้องหนา", "price": 4600, "cls": ["rifle", "dmr", "sniper"], "wiki": "Gun barrel",
               "d": {"recoil": -6, "acc": 6, "ergo": -6, "weight": 0.8}},
    "rail_hg": {"slot": "handguard", "name": "แฮนด์การ์ดมีราง", "price": 2000, "cls": ["smg", "rifle", "dmr"], "wiki": "Handguard",
               "d": {"ergo": 2, "weight": 0.2}},
    "light_hg": {"slot": "handguard", "name": "แฮนด์การ์ดน้ำหนักเบา", "price": 2600, "cls": ["smg", "rifle", "dmr"], "wiki": "Handguard",
               "d": {"recoil": 2, "ergo": 4, "weight": -0.2}},
    "heat_hg": {"slot": "handguard", "name": "แฮนด์การ์ดกันความร้อน", "price": 2800, "cls": ["smg", "rifle", "dmr"], "wiki": "Handguard",
               "d": {"recoil": -2, "acc": 2, "weight": 0.3}},
    "freefloat_hg": {"slot": "handguard", "name": "แฮนด์การ์ดฟรีโฟลต", "price": 3400, "cls": ["smg", "rifle", "dmr"], "wiki": "Handguard",
               "d": {"acc": 6, "ergo": -1, "weight": 0.25}},
    "stubby_grip": {"slot": "foregrip", "name": "ด้ามจับหน้าแบบสั้น", "price": 1200, "cls": ["smg", "shotgun", "rifle"], "wiki": "Forward grip",
               "d": {"recoil": -2, "ergo": 2, "weight": 0.1}},
    "vert_grip": {"slot": "foregrip", "name": "ด้ามจับหน้าแนวตั้ง", "price": 1400, "cls": ["smg", "shotgun", "rifle"], "wiki": "Forward grip",
               "d": {"recoil": -5, "acc": 2, "weight": 0.15}},
    "angled_grip": {"slot": "foregrip", "name": "ด้ามจับหน้าแนวเฉียง", "price": 1600, "cls": ["smg", "shotgun", "rifle"], "wiki": "Forward grip",
               "d": {"recoil": -3, "ergo": 5, "weight": 0.15}},
    "folding_grip": {"slot": "foregrip", "name": "ด้ามจับหน้าพับได้", "price": 1900, "cls": ["smg", "shotgun", "rifle"], "wiki": "Forward grip",
               "d": {"recoil": -3, "ergo": 1, "weight": 0.1}},
    "grip_pod": {"slot": "foregrip", "name": "ด้ามจับหน้าพร้อมขาตั้งสั้น", "price": 2800, "cls": ["smg", "rifle"], "wiki": "Forward grip",
               "d": {"recoil": -4, "acc": 3, "ergo": -2, "weight": 0.3}},
    "rubber_grip": {"slot": "grip", "name": "ด้ามยางกันลื่น", "price": 1200, "cls": ["pistol", "smg", "shotgun", "rifle", "dmr"], "wiki": "Pistol grip",
               "d": {"recoil": -1, "ergo": 4, "weight": 0.05}},
    "ergo_grip": {"slot": "grip", "name": "ด้ามจับสรีระ", "price": 2000, "cls": ["pistol", "smg", "shotgun", "rifle", "dmr"], "wiki": "Pistol grip",
               "d": {"acc": 1, "ergo": 6, "weight": 0.08}},
    "tac_grip": {"slot": "grip", "name": "ด้ามจับลาดชัน", "price": 2600, "cls": ["smg", "rifle", "dmr"], "wiki": "Pistol grip",
               "d": {"recoil": -3, "ergo": 2, "weight": 0.1}},
    "light_bipod": {"slot": "bipod", "name": "ขาทรายน้ำหนักเบา", "price": 1800, "cls": ["rifle", "dmr", "sniper"], "wiki": "Bipod",
               "d": {"recoil": -8, "acc": 5, "ergo": -3, "weight": 0.35}},
    "bipod": {"slot": "bipod", "name": "ขาทราย", "price": 2600, "cls": ["dmr", "sniper"], "wiki": "Bipod",
               "d": {"recoil": -12, "acc": 8, "ergo": -5, "weight": 0.5}},
    "bipod_pro": {"slot": "bipod", "name": "ขาทรายปรับระดับ", "price": 3800, "cls": ["dmr", "sniper"], "wiki": "Bipod",
               "d": {"recoil": -15, "acc": 10, "ergo": -7, "weight": 0.7}},
    "folding_stock": {"slot": "stock", "name": "พานท้ายพับได้", "price": 2000, "cls": ["smg", "shotgun", "rifle"], "wiki": "Buttstock",
               "d": {"recoil": 3, "ergo": 6, "weight": -0.15}},
    "skeleton_stock": {"slot": "stock", "name": "พานท้ายโครงเหล็ก", "price": 2200, "cls": ["smg", "rifle", "dmr"], "wiki": "Buttstock",
               "d": {"recoil": 2, "ergo": 5, "weight": -0.2}},
    "adj_stock": {"slot": "stock", "name": "พานท้ายปรับระยะ", "price": 2400, "cls": ["smg", "shotgun", "rifle", "dmr", "sniper"], "wiki": "Buttstock",
               "d": {"recoil": -4, "ergo": 4, "acc": 2, "weight": 0.25}},
    "recoil_pad": {"slot": "stock", "name": "แผ่นรองรับแรงถีบ", "price": 1700, "cls": ["smg", "shotgun", "rifle", "dmr", "sniper"], "wiki": "Recoil pad",
               "d": {"recoil": -5, "ergo": -1, "weight": 0.1}},
    "cheek_stock": {"slot": "stock", "name": "พานท้ายแก้มปรับระดับ", "price": 3600, "cls": ["rifle", "dmr", "sniper"], "wiki": "Cheek riser",
               "d": {"recoil": -7, "acc": 5, "ergo": -2, "weight": 0.4}},
    "heavy_stock": {"slot": "stock", "name": "พานท้ายหนัก", "price": 3400, "cls": ["rifle", "dmr", "sniper"], "wiki": "Buttstock",
               "d": {"recoil": -9, "acc": 2, "ergo": -4, "weight": 0.5}},
    "fast_mag": {"slot": "magazine", "name": "แม็กกาซีนเปลี่ยนไว", "price": 1100, "cls": ["pistol", "smg", "rifle", "dmr"], "wiki": "Magazine (firearms)",
               "d": {"ergo": 4, "weight": 0.05}},
    "ext_mag": {"slot": "magazine", "name": "แม็กกาซีนขยาย", "price": 1300, "cls": ["pistol", "smg", "rifle", "dmr"], "wiki": "Magazine (firearms)",
               "d": {"mag_pct": 33, "ergo": -2, "weight": 0.1}},
    "ext_tube": {"slot": "magazine", "name": "ท่อกระสุนต่อขยาย", "price": 1500, "cls": ["shotgun"], "wiki": "Magazine (firearms)",
               "d": {"mag_pct": 50, "ergo": -3, "weight": 0.25}},
    "sniper_box_mag": {"slot": "magazine", "name": "แม็กกาซีนกล่อง 10 นัด", "price": 2400, "cls": ["sniper"], "wiki": "Box magazine",
               "d": {"mag_pct": 100, "ergo": -4, "weight": 0.3}},
    "drum_mag": {"slot": "magazine", "name": "แม็กกาซีนดรัม", "price": 4200, "cls": ["smg", "rifle"], "wiki": "Drum magazine",
               "d": {"mag_pct": 100, "ergo": -8, "weight": 0.8}},
    "tac_light": {"slot": "light", "name": "ไฟฉายติดปืน", "price": 900, "cls": ["pistol", "smg", "shotgun", "rifle"], "wiki": "Weapon-mounted light",
               "d": {"ergo": 1, "weight": 0.1}},
    "laser": {"slot": "light", "name": "เลเซอร์ชี้เป้า", "price": 1100, "cls": ["pistol", "smg", "shotgun", "rifle"], "wiki": "Laser sight",
               "d": {"acc": 3, "ergo": 1, "weight": 0.05}},
    "green_laser": {"slot": "light", "name": "เลเซอร์เขียว", "price": 1400, "cls": ["pistol", "smg", "shotgun", "rifle"], "wiki": "Laser sight",
               "d": {"acc": 4, "weight": 0.06}},
    "ir_laser": {"slot": "light", "name": "เลเซอร์อินฟราเรด", "price": 2000, "cls": ["pistol", "smg", "shotgun", "rifle", "dmr"], "wiki": "Night-vision device",
               "d": {"acc": 3, "weight": 0.06}},
    "laser_light": {"slot": "light", "name": "ไฟฉาย+เลเซอร์ในตัว", "price": 2100, "cls": ["pistol", "smg", "shotgun", "rifle"], "wiki": "Laser sight",
               "d": {"acc": 3, "ergo": 1, "weight": 0.15}},
    "sling_1pt": {"slot": "sling", "name": "สายสะพายจุดเดียว", "price": 800, "cls": ["smg", "shotgun", "rifle", "dmr", "sniper"], "wiki": "Sling (firearms)",
               "d": {"ergo": 2, "weight": 0.1}},
    "sling_2pt": {"slot": "sling", "name": "สายสะพายสองจุด", "price": 1000, "cls": ["smg", "shotgun", "rifle", "dmr", "sniper"], "wiki": "Sling (firearms)",
               "d": {"ergo": 3, "weight": 0.12}},
    "sling_tac": {"slot": "sling", "name": "สายสะพายยุทธวิธี", "price": 1600, "cls": ["smg", "shotgun", "rifle", "dmr", "sniper"], "wiki": "Sling (firearms)",
               "d": {"recoil": -1, "ergo": 4, "weight": 0.18}},
    "sling_loop": {"slot": "sling", "name": "สายรัดเล็งยิง", "price": 1500, "cls": ["rifle", "dmr", "sniper"], "wiki": "Sling (firearms)",
               "d": {"acc": 4, "ergo": -1, "weight": 0.1}},
    "bayonet": {"slot": "bayonet", "name": "ดาบปลายปืน", "price": 1500, "cls": ["smg", "shotgun", "rifle"], "wiki": "Bayonet",
               "d": {"ergo": -2, "weight": 0.35, "stab": 28}},
    "folding_bayonet": {"slot": "bayonet", "name": "ดาบปลายปืนพับได้", "price": 1900, "cls": ["smg", "shotgun", "rifle"], "wiki": "Bayonet",
               "d": {"ergo": -1, "weight": 0.22, "stab": 22}},
}

STATE: dict = {}   # uid -> {"weapons": {wid: {"installed":{}, "last":{}|None, "presets":{"1":{name,build}}}}, "stash": {att_id: qty}}
_DIRTY = {"v": False}


# ---------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------
def _load():
    global STATE
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            STATE = json.load(f)
    except Exception:
        STATE = {}


def _flush(force=False):
    with _LOCK:
        if not (force or _DIRTY["v"]):
            return
        _DIRTY["v"] = False
        snap = json.loads(json.dumps(STATE))
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        print(f"[Gunsmith] save failed: {e}")


def _flusher():
    while True:
        time.sleep(10)
        try:
            _flush()
        except Exception as e:
            print(f"[Gunsmith] flusher error: {e}")


def _user(uid):
    u = STATE.setdefault(uid, {"weapons": {}, "stash": {}})
    u.setdefault("weapons", {})
    u.setdefault("stash", {})
    return u


def _weapon(uid, wid):
    w = _user(uid)["weapons"].setdefault(wid, {"installed": {}, "last": None, "presets": {}})
    w.setdefault("installed", {})
    w.setdefault("presets", {})
    w.setdefault("last", None)
    return w


# ---------------------------------------------------------------------
# core logic
# ---------------------------------------------------------------------
def tax_of(subtotal: int) -> int:
    return (subtotal * TAX_RATE_PERCENT + 50) // 100   # ปัดเศษแบบครึ่งขึ้น (จำนวนเต็มล้วน)


def compat(att_id, wid) -> bool:
    a, w = ATTACH.get(att_id), WEAPONS.get(wid)
    if not a or not w or a["slot"] not in w["slots"]:
        return False
    return a["cls"] is None or w["cls"] in a["cls"]


def compute_stats(wid, build):
    w = WEAPONS[wid]
    b = dict(w["base"])
    recoil, ergo, acc = b["recoil"], b["ergo"], b["acc"]
    rng_pct = mag_pct = noise_pct = flash_pct = 0
    stab = 0
    weight = b["weight"]
    for att in (build or {}).values():
        a = ATTACH.get(att)
        if not a:
            continue
        d = a["d"]
        recoil += d.get("recoil", 0)
        ergo += d.get("ergo", 0)
        acc += d.get("acc", 0)
        rng_pct += d.get("range_pct", 0)
        mag_pct += d.get("mag_pct", 0)
        noise_pct += d.get("noise_pct", 0)
        flash_pct += d.get("flash_pct", 0)
        stab += d.get("stab", 0)
        weight += d.get("weight", 0)
    cl = lambda v: max(0, min(100, int(round(v))))
    noise_m = max(MIN_NOISE_M, b["noise"] * max(MIN_NOISE_FACTOR, 1 + noise_pct / 100.0))
    return {"recoil": cl(recoil), "ergo": cl(ergo), "acc": cl(acc),
            "range": int(round(b["range"] * (1 + rng_pct / 100))),
            "mag": int(round(b["mag"] * (1 + mag_pct / 100))),
            "weight": round(weight, 2),
            "noise": int(round(noise_m)),
            "flash": int(round(100 * max(MIN_FLASH_FACTOR, 1 + flash_pct / 100.0))),
            "stab": int(stab),
            "suppressed": noise_pct <= SUPPRESSED_NOISE_PCT}


def clean_build(wid, raw, base_build=None):
    """ตรวจ build จาก client/ข้อมูลที่เซฟไว้ -> (build เต็มทุกช่อง {slot: att|None}, error)
    base_build ถ้ามี = ช่องที่ไม่ได้ส่งมาจะคงตามเดิม; ไม่มี = ช่องที่ไม่ได้ส่งมาถือว่าว่าง"""
    w = WEAPONS.get(wid)
    if not w:
        return None, "ไม่พบปืนนี้"
    if not isinstance(raw, dict):
        return None, "build ต้องเป็น object"
    out = {s: (base_build or {}).get(s) for s in w["slots"]}
    for k in raw:
        if k not in w["slots"]:
            return None, f"ปืนนี้ไม่มีช่อง {k}"
    for s in w["slots"]:
        if s in raw:
            v = raw[s]
            if v is None or v == "":
                out[s] = None
            elif isinstance(v, str) and compat(v, wid) and ATTACH[v]["slot"] == s:
                out[s] = v
            else:
                return None, f"อุปกรณ์ไม่ถูกต้องหรือใช้กับปืนนี้/ช่องนี้ไม่ได้: {v!r}"
    return out, None


def make_plan(uid, wid, target):
    """คำนวณสิ่งที่ต้องทำเพื่อเปลี่ยนจากชุดที่ใส่อยู่ไปเป็น target (ยังไม่แตะข้อมูลจริง)"""
    w = _weapon(uid, wid)
    cur = {s: w["installed"].get(s) for s in WEAPONS[wid]["slots"]}
    temp = dict(_user(uid)["stash"])
    removes, installs = [], []
    for s in WEAPONS[wid]["slots"]:
        if cur.get(s) != target.get(s):
            if cur.get(s):
                removes.append({"slot": s, "att": cur[s]})
                temp[cur[s]] = temp.get(cur[s], 0) + 1
    buys, from_stash = [], []
    for s in WEAPONS[wid]["slots"]:
        if cur.get(s) != target.get(s) and target.get(s):
            att = target[s]
            if temp.get(att, 0) > 0:
                temp[att] -= 1
                from_stash.append({"slot": s, "att": att})
            else:
                buys.append({"slot": s, "att": att, "price": ATTACH[att]["price"]})
            installs.append({"slot": s, "att": att})
    subtotal = sum(b["price"] for b in buys)
    tax = tax_of(subtotal)
    return {"weapon_id": wid, "current": cur, "target": target, "removes": removes, "installs": installs,
            "buys": buys, "from_stash": from_stash, "subtotal": subtotal, "tax_percent": TAX_RATE_PERCENT,
            "tax": tax, "total": subtotal + tax, "no_change": not removes and not installs,
            "_temp_stash": {k: v for k, v in temp.items() if v > 0}}


def public_plan(plan, balance):
    p = {k: v for k, v in plan.items() if not k.startswith("_")}
    p["currency"] = CURRENCY_LABEL
    p["balance"] = balance
    p["balance_after"] = balance - plan["total"]
    p["can_afford"] = balance >= plan["total"]
    p["stats_before"] = compute_stats(plan["weapon_id"], plan["current"])
    p["stats_after"] = compute_stats(plan["weapon_id"], plan["target"])
    return p


def resolve_target(uid, wid, body):
    """source: 'last' | 'preset:N' | 'custom'(+build) -> (target build, label, error)"""
    w = _weapon(uid, wid)
    src = str(body.get("source") or "custom")
    cur = {s: w["installed"].get(s) for s in WEAPONS[wid]["slots"]}
    if src == "last":
        if not w["last"]:
            return None, "", "ยังไม่มีชุด 'แต่งรอบที่แล้ว' ของปืนกระบอกนี้"
        b, err = clean_build(wid, w["last"])
        return b, "แต่งรอบที่แล้ว", err
    if src.startswith("preset:"):
        n = src.split(":", 1)[1]
        p = w["presets"].get(n)
        if not p:
            return None, "", "ไม่พบพรีเซ็ตนี้"
        b, err = clean_build(wid, p["build"])
        return b, p.get("name") or f"พรีเซ็ต {n}", err
    if src == "custom":
        b, err = clean_build(wid, body.get("build"), base_build=cur)
        return b, "ชุดที่เลือกเอง", err
    return None, "", "source ไม่ถูกต้อง"


def snapshot_last(uid, only_wid=None):
    """เซฟชุดที่ใส่อยู่ของทุกกระบอก (หรือกระบอกเดียว) เป็น 'แต่งรอบที่แล้ว' — เรียกตอนจบเรดได้
    (เช่น vmax_gunsmith_snapshot(uid) จากโค้ดจบเรด) ข้ามกระบอกที่ไม่มีอุปกรณ์ติดอยู่"""
    n = 0
    with _LOCK:
        for wid in WEAPONS:
            if only_wid and wid != only_wid:
                continue
            w = _weapon(uid, wid)
            inst = {s: a for s, a in w["installed"].items() if a}
            if inst:
                w["last"] = dict(inst)
                n += 1
        if n:
            _DIRTY["v"] = True
    return n


# ---------------------------------------------------------------------
# fire profile — ระบบยิง/ตีในเกมเรียกใช้ (คิดฝั่งเซิร์ฟเวอร์จาก build ที่ติดตั้งอยู่จริง)
# ---------------------------------------------------------------------
def resolve_wid(weapon_id):
    """รับได้ทั้ง id ของแต่งปืน (vx556) และชื่อคลาส/ชื่อปืนของระบบกระสุน (rifle, sniper_x ...) -> wid หรือ None
    lmg / railgun / plasma ไม่มีในหน้าแต่งปืน -> None (ระบบเรียกจะใช้ค่าเดิมของเกม)"""
    k = str(weapon_id or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not k:
        return None
    if k in WEAPONS:
        return k
    if k in CLASS_TO_WID:
        return CLASS_TO_WID[k]
    for kw, cls in (("sniper", "sniper"), ("dmr", "dmr"), ("smg", "smg"), ("shotgun", "shotgun"),
                    ("pistol", "pistol"), ("rifle", "rifle")):
        if kw in k:
            return CLASS_TO_WID[cls]
    return None


def set_active(uid, weapon_id):
    """จำว่าผู้เล่นกำลังถือกระบอกไหน (ใช้ตอน endpoint ยิงไม่ได้ส่ง weapon_id มา) -> wid หรือ None"""
    wid = resolve_wid(weapon_id)
    if not wid:
        return None
    with _LOCK:
        u = _user(str(uid))
        if u.get("active_wid") != wid:
            u["active_wid"] = wid
            _DIRTY["v"] = True
    return wid


def fire_profile(uid, weapon_id=None):
    """คืน dict ค่าที่มีผลตอนยิง/แทงของปืนกระบอกนั้นของผู้เล่น หรือ None ถ้าระบุปืนไม่ได้
    {wid, cls, noise_radius_m, flash_pct, flash_range_m, suppressed, stab_damage, bayonet, installed, stats}
    - ไม่ส่ง weapon_id = ใช้ปืนที่ set_active() จำไว้ (ไม่มี = None -> ผู้เรียกใช้ค่าเดิม 420 ม.)
    - ไม่แก้/สร้างข้อมูลผู้เล่นใหม่ (อ่านอย่างเดียว) — เรียกทุกนัดได้"""
    uid = str(uid)
    with _LOCK:
        u = STATE.get(uid) or {}
        wid = resolve_wid(weapon_id) if weapon_id else u.get("active_wid")
        if not wid or wid not in WEAPONS:
            return None
        inst = ((u.get("weapons") or {}).get(wid) or {}).get("installed") or {}
        build = {s_: a for s_, a in inst.items() if a and compat(a, wid)}
    st = compute_stats(wid, build)
    bay = next((a for a in build.values() if ATTACH[a]["slot"] == "bayonet"), None)
    return {"wid": wid, "cls": WEAPONS[wid]["cls"], "noise_radius_m": float(st["noise"]),
            "flash_pct": st["flash"], "flash_range_m": round(BASE_FLASH_RANGE_M * st["flash"] / 100.0, 1),
            "suppressed": bool(st["suppressed"]), "stab_damage": int(st["stab"]), "bayonet": bay,
            "installed": build, "stats": st}


# ---------------------------------------------------------------------
# attach
# ---------------------------------------------------------------------
def attach(main_globals: dict):
    global _ATTACHED, _READY
    if _ATTACHED:
        return
    _ATTACHED = True

    app = main_globals.get("app")
    require_auth = main_globals.get("require_auth")
    VMAX_MODULES = main_globals.get("VMAX_MODULES")
    audit_log = main_globals.get("audit_log") or (lambda *a, **k: None)
    player_state_for = main_globals.get("_player_state_for")

    if app is None or require_auth is None or player_state_for is None:
        print("[Gunsmith] ⚠️  ไม่พบ app/require_auth/_player_state_for — ข้ามการต่อโมดูลนี้")
        _ATTACHED = False
        return

    from flask import request, jsonify

    _load()
    _READY = True
    threading.Thread(target=_flusher, daemon=True).start()

    def _uid():
        return str(getattr(request, "vmax_uid", "") or "")

    def _balance(uid):
        try:
            return int(player_state_for(uid).get(CURRENCY_KEY, 0))
        except Exception:
            return 0

    def _wiki(att):
        cat = main_globals.get("WEAPON_ATTACHMENT_WIKI_CATALOG") or {}
        e = cat.get(att.get("wiki"))
        if not e or not e.get("extract"):
            return None
        t = e["extract"].strip()
        if len(t) > 320:
            cut = t[:320]
            p = cut.rfind(". ")
            t = cut[:p + 1] if p > 120 else cut.rstrip() + "…"
        return {"title": e.get("title"), "extract": t, "wiki_url": e.get("wiki_url")}

    def _w_public(uid, wid):
        w = _weapon(uid, wid)
        cur = {s: w["installed"].get(s) for s in WEAPONS[wid]["slots"]}
        return {"installed": cur, "stats": compute_stats(wid, cur),
                "last": w["last"], "presets": w["presets"]}

    @app.route("/api/gunsmith/catalog")
    def api_gs_catalog():
        atts = []
        for aid, a in ATTACH.items():
            atts.append({"id": aid, "slot": a["slot"], "name": a["name"], "price": a["price"], "cls": a["cls"],
                         "d": a["d"], "wiki": _wiki(a)})
        return jsonify({"st": "ok", "slots": SLOT_INFO, "slot_order": SLOT_ORDER,
                        "weapons": {k: {"name": v["name"], "cls": v["cls"], "slots": v["slots"], "base": v["base"]}
                                    for k, v in WEAPONS.items()},
                        "attachments": atts, "tax_percent": TAX_RATE_PERCENT, "currency": CURRENCY_LABEL,
                        "preset_slots": PRESET_SLOTS})

    @app.route("/api/gunsmith/me")
    @require_auth
    def api_gs_me():
        uid = _uid()
        with _LOCK:
            return jsonify({"st": "ok", "balance": _balance(uid), "currency": CURRENCY_LABEL,
                            "stash": dict(_user(uid)["stash"]),
                            "weapons": {wid: _w_public(uid, wid) for wid in WEAPONS}})

    def _plan_from_request(uid):
        body = request.get_json(force=True, silent=True) or {}
        wid = str(body.get("weapon_id") or "")
        if wid not in WEAPONS:
            return None, None, (jsonify({"st": "error", "msg": "ไม่พบปืนนี้"}), 400)
        target, label, err = resolve_target(uid, wid, body)
        if err:
            return None, None, (jsonify({"st": "error", "msg": err}), 400)
        return make_plan(uid, wid, target), (body, label), None

    @app.route("/api/gunsmith/quote", methods=["POST"])
    @require_auth
    def api_gs_quote():
        uid = _uid()
        with _LOCK:
            plan, meta, err = _plan_from_request(uid)
            if err:
                return err
            out = public_plan(plan, _balance(uid))
            out["label"] = meta[1]
            return jsonify({"st": "ok", "quote": out})

    @app.route("/api/gunsmith/apply", methods=["POST"])
    @require_auth
    def api_gs_apply():
        uid = _uid()
        with _LOCK:
            plan, meta, err = _plan_from_request(uid)
            if err:
                return err
            body, label = meta
            if body.get("confirm") is not True:
                return jsonify({"st": "error", "msg": "ต้องยืนยัน (confirm: true) ก่อนแต่งปืน"}), 400
            if plan["no_change"]:
                return jsonify({"st": "error", "msg": "ปืนกระบอกนี้เป็นแบบนี้อยู่แล้ว"}), 400
            try:
                expected = int(body.get("expected_total"))
            except Exception:
                return jsonify({"st": "error", "msg": "ต้องส่ง expected_total (ยอดที่แสดงบนหน้าจอ)"}), 400
            if expected != plan["total"]:
                return jsonify({"st": "error", "code": "price_changed",
                                "msg": "ราคาเปลี่ยนไปจากที่แสดง กรุณาดูยอดใหม่แล้วยืนยันอีกครั้ง",
                                "quote": public_plan(plan, _balance(uid))}), 409
            bal = _balance(uid)
            if bal < plan["total"]:
                return jsonify({"st": "error", "code": "no_money",
                                "msg": f"{CURRENCY_LABEL}ไม่พอ (มี {bal:,} ต้องใช้ {plan['total']:,})"}), 400
            wid = plan["weapon_id"]
            w = _weapon(uid, wid)
            prev = {s: a for s, a in w["installed"].items() if a}
            if plan["total"] > 0:
                st = player_state_for(uid)
                st[CURRENCY_KEY] = int(st.get(CURRENCY_KEY, 0)) - plan["total"]
            _user(uid)["stash"] = plan["_temp_stash"]
            w["installed"] = {s: a for s, a in plan["target"].items() if a}
            if prev and prev != w["installed"]:
                w["last"] = prev     # ชุดก่อนหน้า -> 'แต่งรอบที่แล้ว'
            _user(uid)["active_wid"] = wid     # กระบอกที่เพิ่งแต่ง = กระบอกที่ถืออยู่ (ระบบยิงใช้คิดเสียง/ดาบปลายปืน)
            _DIRTY["v"] = True
            result = public_plan(make_plan(uid, wid, plan["target"]), _balance(uid))
            paid = {"subtotal": plan["subtotal"], "tax": plan["tax"], "total": plan["total"]}
        _flush(True)
        audit_log("gunsmith_apply", uid=uid, weapon=wid, source=str(body.get("source")), **paid,
                  buys=[b["att"] for b in plan["buys"]])
        return jsonify({"st": "ok", "paid": paid, "label": label, "balance": _balance(uid),
                        "weapon": _w_public(uid, wid), "stash": dict(_user(uid)["stash"])})

    @app.route("/api/gunsmith/strip", methods=["POST"])
    @require_auth
    def api_gs_strip():
        """ถอดอุปกรณ์ทั้งหมดออกจากปืน (เก็บเข้าคลัง ไม่เสียเงิน) และจำชุดเดิมเป็น 'แต่งรอบที่แล้ว'"""
        d = request.get_json(force=True, silent=True) or {}
        uid, wid = _uid(), str(d.get("weapon_id") or "")
        if wid not in WEAPONS:
            return jsonify({"st": "error", "msg": "ไม่พบปืนนี้"}), 400
        with _LOCK:
            w = _weapon(uid, wid)
            inst = {s: a for s, a in w["installed"].items() if a}
            if not inst:
                return jsonify({"st": "error", "msg": "ปืนกระบอกนี้ไม่มีอุปกรณ์เสริมอยู่แล้ว"}), 400
            stash = _user(uid)["stash"]
            for a in inst.values():
                stash[a] = stash.get(a, 0) + 1
            w["last"] = dict(inst)
            w["installed"] = {}
            _DIRTY["v"] = True
        _flush(True)
        return jsonify({"st": "ok", "weapon": _w_public(uid, wid), "stash": dict(_user(uid)["stash"])})

    @app.route("/api/gunsmith/snapshot", methods=["POST"])
    @require_auth
    def api_gs_snapshot():
        """เซฟชุดที่ใส่อยู่ทุกกระบอกเป็น 'แต่งรอบที่แล้ว' (ปกติเรียกตอนจบเรด)"""
        n = snapshot_last(_uid())
        _flush(True)
        return jsonify({"st": "ok", "saved_weapons": n})

    @app.route("/api/gunsmith/equip", methods=["POST"])
    @require_auth
    def api_gs_equip():
        """บอกเซิร์ฟเวอร์ว่ากำลังถือปืนกระบอกไหน (เสียงปืน/ดาบปลายปืนจะคิดจากกระบอกนี้ถ้า endpoint ยิงไม่ได้ส่ง weapon_id)"""
        d = request.get_json(force=True, silent=True) or {}
        uid = _uid()
        wid = set_active(uid, d.get("weapon_id"))
        if not wid:
            return jsonify({"st": "error", "msg": "ไม่พบปืนนี้"}), 400
        return jsonify({"st": "ok", "weapon_id": wid, "fire_profile": fire_profile(uid, wid)})

    @app.route("/api/gunsmith/fire-profile")
    @require_auth
    def api_gs_fire_profile():
        """ดูค่าเสียง/แสง/ดาเมจแทงที่ใช้จริงตอนยิงของปืนกระบอกที่เลือก (หรือกระบอกที่ถืออยู่)"""
        fp = fire_profile(_uid(), request.args.get("weapon_id") or None)
        if fp is None:
            return jsonify({"st": "error", "msg": "ยังไม่ได้เลือกปืน (ส่ง weapon_id หรือเรียก /api/gunsmith/equip ก่อน)"}), 400
        return jsonify({"st": "ok", "fire_profile": fp})

    @app.route("/api/gunsmith/preset/save", methods=["POST"])
    @require_auth
    def api_gs_preset_save():
        d = request.get_json(force=True, silent=True) or {}
        uid, wid = _uid(), str(d.get("weapon_id") or "")
        n = str(d.get("slot_no") or "")
        if wid not in WEAPONS or n not in {str(i) for i in range(1, PRESET_SLOTS + 1)}:
            return jsonify({"st": "error", "msg": f"ต้องมี weapon_id และ slot_no 1-{PRESET_SLOTS}"}), 400
        with _LOCK:
            w = _weapon(uid, wid)
            if "build" in d:
                build, err = clean_build(wid, d["build"], base_build={s: w["installed"].get(s) for s in WEAPONS[wid]["slots"]})
                if err:
                    return jsonify({"st": "error", "msg": err}), 400
            else:
                build = {s: w["installed"].get(s) for s in WEAPONS[wid]["slots"]}
            build = {s: a for s, a in build.items() if a}
            if not build:
                return jsonify({"st": "error", "msg": "ชุดว่างเปล่า เซฟเป็นพรีเซ็ตไม่ได้"}), 400
            w["presets"][n] = {"name": str(d.get("name") or f"พรีเซ็ต {n}")[:24], "build": build}
            _DIRTY["v"] = True
        _flush(True)
        return jsonify({"st": "ok", "weapon": _w_public(uid, wid)})

    @app.route("/api/gunsmith/preset/delete", methods=["POST"])
    @require_auth
    def api_gs_preset_delete():
        d = request.get_json(force=True, silent=True) or {}
        uid, wid, n = _uid(), str(d.get("weapon_id") or ""), str(d.get("slot_no") or "")
        if wid not in WEAPONS:
            return jsonify({"st": "error", "msg": "ไม่พบปืนนี้"}), 400
        with _LOCK:
            if _weapon(uid, wid)["presets"].pop(n, None) is None:
                return jsonify({"st": "error", "msg": "ไม่พบพรีเซ็ตนี้"}), 404
            _DIRTY["v"] = True
        _flush(True)
        return jsonify({"st": "ok", "weapon": _w_public(uid, wid)})

    @app.route("/widgets/gunsmith")
    def widget_gunsmith():
        return GUNSMITH_WIDGET_HTML

    if isinstance(VMAX_MODULES, dict):
        VMAX_MODULES["gunsmith"] = {
            "desc": "หน้าแต่งปืน: ช่องอุปกรณ์เสริม + แต่งรอบที่แล้ว/พรีเซ็ต กด Yes/No ยืนยันพร้อมแสดงภาษี 7% และค่าแต่ง",
            "routes": ["/widgets/gunsmith", "/api/gunsmith/catalog", "/api/gunsmith/me", "/api/gunsmith/quote",
                       "/api/gunsmith/apply", "/api/gunsmith/strip", "/api/gunsmith/snapshot",
                       "/api/gunsmith/preset/save", "/api/gunsmith/preset/delete"],
        }
    print("[Gunsmith] ต่อโมดูลหน้าแต่งปืนเสร็จ — /widgets/gunsmith /api/gunsmith/*")


# ---------------------------------------------------------------------
# widget
# ---------------------------------------------------------------------
GUNSMITH_WIDGET_HTML = r"""<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>แต่งปืน</title>
<style>
:root{--bg:#0b1016;--panel:#131b26;--line:#2a374b;--txt:#dfe8f5;--mut:#8da2c0;--acc:#ffb347;--ok:#4cd18a;--bad:#ff7070}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font-family:system-ui,"Noto Sans Thai",sans-serif;padding:10px;max-width:980px;margin:auto}
.wtabs{display:flex;gap:6px;overflow-x:auto;padding-bottom:6px}
.wtabs button{flex:0 0 auto;padding:8px 12px;background:var(--panel);color:var(--txt);border:1px solid var(--line);border-radius:8px;cursor:pointer;font:inherit}
.wtabs button.on{background:#2f6bff;border-color:#2f6bff}
.top{display:flex;justify-content:space-between;align-items:center;margin:6px 2px;font-size:13px;color:var(--mut)}
.main{display:grid;grid-template-columns:200px 1fr 240px;gap:10px}
@media(max-width:820px){.main{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px}
.slots{display:flex;flex-direction:column;gap:6px}
.slot{display:flex;align-items:center;gap:8px;padding:8px;background:#0f1620;border:1px solid var(--line);border-radius:8px;cursor:pointer}
.slot.sel{border-color:var(--acc)}.slot.chg{background:#1b2536}
.slot .t{font-size:11px;color:var(--mut)}.slot .n{font-size:13px;font-weight:600}
.gun{width:100%;height:auto;display:block}
.stats{display:grid;grid-template-columns:1fr 1fr;gap:4px 12px;font-size:12px;margin-top:8px}
.stats b.up{color:var(--ok)}.stats b.dn{color:var(--bad)}
.last{cursor:pointer;border:1px dashed var(--acc);margin-bottom:8px}
.last:hover{background:#1a2230}
.last h4,.pre h4{margin:0 0 4px;font-size:14px}
.sm{font-size:12px;color:var(--mut);line-height:1.5}
.opts{margin-top:10px}
.opt{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:8px;border:1px solid var(--line);border-radius:8px;margin-bottom:6px;cursor:pointer;background:#0f1620}
.opt.on{border-color:var(--ok)}
.opt .p{white-space:nowrap;color:var(--acc);font-size:13px}
.opt .x{font-size:11px;color:var(--mut)}
button.b{padding:8px 14px;border:0;border-radius:8px;background:#2f6bff;color:#fff;font:inherit;cursor:pointer}
button.b.sec{background:#243049;color:var(--txt)}button.b:disabled{opacity:.4;cursor:not-allowed}
.msg{min-height:20px;font-size:13px;margin:6px 2px}.err{color:var(--bad)}.ok{color:var(--ok)}
.ov{position:fixed;inset:0;background:#000b;display:none;align-items:center;justify-content:center;padding:14px;z-index:20}
.dlg{width:min(420px,100%);background:#16202e;border:1px solid #3a4c68;border-radius:12px;overflow:hidden}
.dlg .hd{padding:14px 16px;font-weight:700;font-size:17px;border-bottom:1px solid var(--line)}
.dlg .bd{padding:12px 16px;font-size:14px;max-height:50vh;overflow:auto}
.dlg .row{display:flex;justify-content:space-between;padding:3px 0}
.dlg .items .row{font-size:13px;color:#c9d6ea}
.dlg .sum{border-top:1px solid var(--line);margin-top:8px;padding-top:8px}
.dlg .sum .tot{font-weight:700;font-size:16px;color:var(--acc)}
.dlg .ft{display:flex;gap:10px;padding:12px 16px;border-top:1px solid var(--line)}
.dlg .ft button{flex:1;padding:11px;font-size:16px;font-weight:700}
.dlg .warn{color:var(--bad);font-size:13px;margin-top:6px}
a{color:#8fc0ff}
</style></head><body>
<div class="wtabs" id="wtabs"></div>
<div class="top"><span id="bal"></span><span id="stashinfo"></span></div>
<div class="msg" id="msg"></div>
<div class="main">
  <div class="card"><div class="slots" id="slots"></div></div>
  <div class="card">
    <svg class="gun" id="gun" viewBox="0 0 520 190" xmlns="http://www.w3.org/2000/svg"></svg>
    <div class="stats" id="stats"></div>
    <div class="opts" id="opts"></div>
    <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
      <button class="b" id="bApply">แต่งปืนด้วยชุดที่เลือก</button>
      <button class="b sec" id="bReset">ล้างที่เลือก</button>
      <button class="b sec" id="bStrip">ถอดทั้งหมด</button>
    </div>
  </div>
  <div class="card">
    <div id="lastBox"></div>
    <div id="presets"></div>
  </div>
</div>
<div class="ov" id="ov"><div class="dlg">
  <div class="hd" id="dTitle">คุณต้องการแต่งปืนนี้หรือไม่?</div>
  <div class="bd">
    <div class="sm" id="dName" style="margin-bottom:6px"></div>
    <div class="items" id="dItems"></div>
    <div class="sum" id="dSum"></div>
    <div class="warn" id="dWarn"></div>
  </div>
  <div class="ft"><button class="b" id="dYes">Yes</button><button class="b sec" id="dNo">No</button></div>
</div></div>
<script>
const TOKEN=()=>{try{return localStorage.getItem('vmax_token')||''}catch(e){return ''}};
async function api(path,opt){
  opt=opt||{}; opt.headers=Object.assign({'Content-Type':'application/json'},opt.headers||{});
  const t=TOKEN(); if(t) opt.headers['Authorization']='Bearer '+t;
  let r; try{ r=await fetch(path,opt); }catch(e){ return {st:'error',msg:'เชื่อมต่อเซิร์ฟเวอร์ไม่ได้'}; }
  let j={}; try{ j=await r.json(); }catch(e){ j={st:'error',msg:'เซิร์ฟเวอร์ตอบกลับผิดรูปแบบ'}; }
  j._status=r.status; return j;
}
function el(tag,attrs,kids){
  const e=document.createElement(tag);
  for(const k in (attrs||{})){
    if(attrs[k]==null) continue;
    if(k==='class') e.className=attrs[k]; else if(k==='text') e.textContent=attrs[k];
    else if(k==='style') e.style.cssText=attrs[k]; else if(k.startsWith('on')) e.addEventListener(k.slice(2),attrs[k]);
    else e.setAttribute(k,attrs[k]);
  }
  (kids||[]).forEach(c=>{ if(c!=null) e.appendChild(typeof c==='string'?document.createTextNode(c):c); });
  return e;
}
const $=id=>document.getElementById(id);
const fmt=n=>Number(n).toLocaleString('th-TH');
let CAT=null,ME=null,wid=null,draft={},selSlot=null,pending=null;
const att=id=>CAT.attachments.find(a=>a.id===id);
function setMsg(t,c){$('msg').textContent=t||'';$('msg').className='msg '+(c||'');}
function curInstalled(){return ME.weapons[wid].installed;}
function draftBuild(){const b={};CAT.weapons[wid].slots.forEach(s=>{b[s]=(s in draft)?draft[s]:(curInstalled()[s]||null);});return b;}
function dirty(){return CAT.weapons[wid].slots.some(s=>(draftBuild()[s]||null)!==(curInstalled()[s]||null));}
function statsOf(build){
  const w=CAT.weapons[wid],b=w.base;let r=b.recoil,e=b.ergo,a=b.acc,rp=0,mp=0,wt=b.weight,np=0,fp=0,sb=0;
  Object.values(build).forEach(id=>{if(!id)return;const d=att(id).d;r+=d.recoil||0;e+=d.ergo||0;a+=d.acc||0;rp+=d.range_pct||0;mp+=d.mag_pct||0;wt+=d.weight||0;np+=d.noise_pct||0;fp+=d.flash_pct||0;sb+=d.stab||0;});
  const c=v=>Math.max(0,Math.min(100,Math.round(v)));
  return {recoil:c(r),ergo:c(e),acc:c(a),range:Math.round(b.range*(1+rp/100)),mag:Math.round(b.mag*(1+mp/100)),weight:Math.round(wt*100)/100,noise:Math.round(Math.max(25,b.noise*Math.max(0.10,1+np/100))),flash:Math.round(100*Math.max(0.05,1+fp/100)),stab:sb};
}
function buildList(build){
  const parts=[];CAT.weapons[wid].slots.forEach(s=>{if(build&&build[s])parts.push(att(build[s]).name);});
  return parts.length?parts.join(' · '):'(ไม่มีอุปกรณ์เสริม)';
}
function drawGun(){
  const g=$('gun'); g.innerHTML='';
  const NS='http://www.w3.org/2000/svg';
  const mk=(t,a)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);return e;};
  const body='#3a4558',dark='#242c3a';
  g.appendChild(mk('rect',{x:20,y:20,width:480,height:150,rx:10,fill:'#0f1620'}));
  g.appendChild(mk('polygon',{points:'60,92 130,84 150,84 150,112 128,116 70,130 40,128 40,100',fill:dark}));     // พานท้าย
  g.appendChild(mk('rect',{x:150,y:80,width:190,height:34,rx:4,fill:body}));                                         // ตัวปืน
  g.appendChild(mk('rect',{x:340,y:88,width:110,height:14,fill:dark}));                                              // ลำกล้อง
  g.appendChild(mk('polygon',{points:'196,114 230,114 222,152 192,152',fill:dark}));                                 // ด้ามจับ
  g.appendChild(mk('rect',{x:238,y:114,width:30,height:42,rx:3,fill:'#2c3546'}));                                    // แม็กกาซีน
  g.appendChild(mk('rect',{x:160,y:74,width:110,height:8,fill:dark}));                                               // ราง
  const pos={optic:[215,60],backup:[160,48],muzzle:[462,95],barrel:[435,66],handguard:[300,52],foregrip:[330,128],grip:[178,150],bipod:[420,118],stock:[70,70],magazine:[253,168],light:[385,80],sling:[105,150],bayonet:[482,132]};
  const b=draftBuild();
  CAT.weapons[wid].slots.forEach(s=>{
    const p=pos[s],on=!!b[s],sel=selSlot===s;
    const c=mk('circle',{cx:p[0],cy:p[1],r:13,fill:on?'#1e7f55':'#1a2230',stroke:sel?'#ffb347':(on?'#4cd18a':'#5f7fb0'),'stroke-width':sel?3:2,style:'cursor:pointer'});
    c.addEventListener('click',()=>{selSlot=s;renderAll();});
    g.appendChild(c);
    const t=mk('text',{x:p[0],y:p[1]+5,'text-anchor':'middle','font-size':'13','pointer-events':'none'});t.textContent=CAT.slots[s].icon;g.appendChild(t);
  });
}
function renderStats(){
  const a=statsOf(curInstalled()),b=statsOf(draftBuild()),box=$('stats');box.innerHTML='';
  [['recoil','แรงถีบ',true],['ergo','ความคล่อง'],['acc','ความแม่น'],['range','ระยะ (ม.)'],['mag','ความจุ'],['weight','น้ำหนัก (กก.)',true],['noise','เสียงปืน (รัศมี ม.)',true],['flash','แสงปากกระบอก (%)',true]].concat(CAT.weapons[wid].slots.includes('bayonet')?[['stab','ดาเมจแทง']]:[]).forEach(r=>{
    const k=r[0],low=!!r[2],d=b[k]-a[k],good=low?d<0:d>0;
    box.appendChild(el('div',{},[el('span',{text:r[1]+': '}),el('b',{class:d===0?'':(good?'up':'dn'),text:String(b[k])+(d?(' ('+(d>0?'+':'')+Math.round(d*100)/100+')'):'')})]));
  });
}
function renderSlots(){
  const box=$('slots');box.innerHTML='';const b=draftBuild();
  CAT.weapons[wid].slots.forEach(s=>{
    const id=b[s],chg=(id||null)!==(curInstalled()[s]||null);
    box.appendChild(el('div',{class:'slot'+(selSlot===s?' sel':'')+(chg?' chg':''),onclick:()=>{selSlot=s;renderAll();}},[
      el('span',{text:CAT.slots[s].icon,style:'font-size:20px'}),
      el('div',{},[el('div',{class:'t',text:CAT.slots[s].name}),el('div',{class:'n',text:id?att(id).name:'— ว่าง —'})])]));
  });
}
function renderOpts(){
  const box=$('opts');box.innerHTML='';
  if(!selSlot){box.appendChild(el('div',{class:'sm',text:'แตะช่องอุปกรณ์เพื่อเลือกอุปกรณ์เสริม'}));return;}
  const w=CAT.weapons[wid],b=draftBuild();
  box.appendChild(el('div',{style:'font-weight:700;margin-bottom:6px',text:CAT.slots[selSlot].name}));
  box.appendChild(el('div',{class:'opt'+(!b[selSlot]?' on':''),onclick:()=>{draft[selSlot]=null;renderAll();}},[el('span',{text:'ไม่ติดตั้ง'})]));
  CAT.attachments.filter(a=>a.slot===selSlot&&(a.cls==null||a.cls.includes(w.cls))).forEach(a=>{
    const own=(ME.stash[a.id]||0),here=curInstalled()[selSlot]===a.id;
    const eff=Object.keys(a.d).map(k=>({recoil:'แรงถีบ',ergo:'คล่อง',acc:'แม่น',range_pct:'ระยะ%',mag_pct:'ความจุ%',weight:'หนัก',noise_pct:'เสียง%',flash_pct:'แสง%',stab:'ดาเมจแทง'}[k]+' '+(a.d[k]>0?'+':'')+a.d[k])).join(' · ');
    const kids=[el('div',{},[el('div',{text:a.name}),el('div',{class:'x',text:eff}),a.wiki?el('div',{class:'x',text:a.wiki.extract.slice(0,110)+'…'}):null])];
    kids.push(el('span',{class:'p',text:here?'ติดตั้งอยู่':(own>0?'มีในคลัง ×'+own:fmt(a.price))}));
    box.appendChild(el('div',{class:'opt'+(b[selSlot]===a.id?' on':''),onclick:()=>{draft[selSlot]=a.id;renderAll();}},kids));
  });
}
function renderSide(){
  const w=ME.weapons[wid],lb=$('lastBox');lb.innerHTML='';
  if(w.last){
    lb.appendChild(el('div',{class:'card last',onclick:()=>openConfirm({source:'last'},'แต่งรอบที่แล้ว')},[
      el('h4',{text:'⏪ แต่งรอบที่แล้ว'}),el('div',{class:'sm',text:buildList(w.last)}),el('div',{class:'sm',style:'margin-top:4px;color:#ffb347',text:'แตะเพื่อใช้ชุดนี้'})]));
  } else lb.appendChild(el('div',{class:'card sm',style:'margin-bottom:8px',text:'ยังไม่มีชุด "แต่งรอบที่แล้ว" ของปืนกระบอกนี้ — จะบันทึกให้อัตโนมัติเมื่อคุณเปลี่ยนชุดอุปกรณ์'}));
  const pb=$('presets');pb.innerHTML='';pb.appendChild(el('div',{class:'sm',style:'margin:4px 2px',text:'พรีเซ็ตของฉัน'}));
  for(let i=1;i<=CAT.preset_slots;i++){
    const p=w.presets[String(i)];
    const c=el('div',{class:'card pre',style:'margin-bottom:6px'});
    if(p){
      c.appendChild(el('h4',{text:p.name,style:'cursor:pointer',onclick:()=>openConfirm({source:'preset:'+i},p.name)}));
      c.appendChild(el('div',{class:'sm',text:buildList(p.build),style:'cursor:pointer',onclick:()=>openConfirm({source:'preset:'+i},p.name)}));
      c.appendChild(el('div',{style:'margin-top:6px'},[el('button',{class:'b sec',style:'padding:4px 10px;font-size:12px',text:'ลบ',onclick:()=>delPreset(i)})]));
    } else {
      c.appendChild(el('div',{class:'sm',text:'ช่อง '+i+' ว่าง'}));
      c.appendChild(el('div',{style:'margin-top:6px'},[el('button',{class:'b sec',style:'padding:4px 10px;font-size:12px',text:'เซฟชุดที่ใส่อยู่ที่นี่',onclick:()=>savePreset(i)})]));
    }
    pb.appendChild(c);
  }
}
function renderAll(){
  $('bal').textContent='เงินคงเหลือ: '+fmt(ME.balance)+' '+CAT.currency;
  const st=Object.entries(ME.stash).filter(e=>e[1]>0).map(e=>att(e[0]).name+' ×'+e[1]);
  $('stashinfo').textContent=st.length?'คลังอุปกรณ์: '+st.join(', '):'';
  $('bApply').disabled=!dirty();$('bReset').disabled=!dirty();
  $('bStrip').disabled=!Object.values(curInstalled()).some(Boolean);
  drawGun();renderStats();renderSlots();renderOpts();renderSide();
}
function renderTabs(){
  const t=$('wtabs');t.innerHTML='';
  Object.keys(CAT.weapons).forEach(id=>t.appendChild(el('button',{class:id===wid?'on':'',text:CAT.weapons[id].name,onclick:()=>{wid=id;draft={};selSlot=null;renderTabs();renderAll();}})));
}
async function openConfirm(src,label){
  setMsg('');
  const body=Object.assign({weapon_id:wid},src);
  if(src.source==='custom') body.build=draftBuild();
  const j=await api('/api/gunsmith/quote',{method:'POST',body:JSON.stringify(body)});
  if(j.st!=='ok'){setMsg(j.msg||'คำนวณราคาไม่สำเร็จ','err');return;}
  pending={body:body,quote:j.quote,label:label};showDlg();
}
function showDlg(){
  const q=pending.quote;
  $('dName').textContent=CAT.weapons[wid].name+' — '+(q.label||pending.label);
  const it=$('dItems');it.innerHTML='';
  q.buys.forEach(b=>it.appendChild(el('div',{class:'row'},[el('span',{text:CAT.slots[b.slot].name+': '+att(b.att).name}),el('span',{text:fmt(b.price)})])));
  q.from_stash.forEach(b=>it.appendChild(el('div',{class:'row'},[el('span',{text:CAT.slots[b.slot].name+': '+att(b.att).name+' (จากคลัง)'}),el('span',{text:'ฟรี'})])));
  q.removes.forEach(b=>{if(!q.installs.some(i=>i.slot===b.slot))it.appendChild(el('div',{class:'row'},[el('span',{text:CAT.slots[b.slot].name+': ถอด '+att(b.att).name}),el('span',{text:'ฟรี'})]));});
  if(q.no_change) it.appendChild(el('div',{class:'sm',text:'ปืนกระบอกนี้เป็นแบบนี้อยู่แล้ว'}));
  const s=$('dSum');s.innerHTML='';
  const row=(a,b,c)=>s.appendChild(el('div',{class:'row'+(c?' tot':'')},[el('span',{text:a}),el('span',{text:b,class:c||''})]));
  row('ค่าอุปกรณ์',fmt(q.subtotal)+' '+q.currency);
  row('ภาษี '+q.tax_percent+'%',fmt(q.tax)+' '+q.currency);
  const t=el('div',{class:'row tot'},[el('span',{text:'ยอดรวม'}),el('span',{text:fmt(q.total)+' '+q.currency})]);s.appendChild(t);
  row('เงินคงเหลือ',fmt(q.balance)+' → '+fmt(q.balance_after));
  $('dWarn').textContent=q.can_afford?'':q.currency+'ไม่พอสำหรับการแต่งชุดนี้';
  $('dYes').disabled=!q.can_afford||q.no_change;
  $('ov').style.display='flex';
}
function closeDlg(){$('ov').style.display='none';pending=null;}
$('dNo').onclick=closeDlg;
$('dYes').onclick=async()=>{
  if(!pending)return; $('dYes').disabled=true;
  const body=Object.assign({},pending.body,{confirm:true,expected_total:pending.quote.total});
  const j=await api('/api/gunsmith/apply',{method:'POST',body:JSON.stringify(body)});
  if(j.st==='ok'){
    closeDlg();setMsg('แต่งปืนเรียบร้อย — จ่ายรวม '+fmt(j.paid.total)+' '+CAT.currency+' (ภาษี '+fmt(j.paid.tax)+')','ok');
    draft={};await reload();
  } else if(j.code==='price_changed'&&j.quote){
    pending.quote=j.quote;showDlg();$('dWarn').textContent=j.msg;
  } else {$('dWarn').textContent=j.msg||'แต่งปืนไม่สำเร็จ';$('dYes').disabled=false;}
};
$('bApply').onclick=()=>openConfirm({source:'custom'},'ชุดที่เลือกเอง');
$('bReset').onclick=()=>{draft={};renderAll();};
$('bStrip').onclick=async()=>{
  const j=await api('/api/gunsmith/strip',{method:'POST',body:JSON.stringify({weapon_id:wid})});
  if(j.st==='ok'){setMsg('ถอดอุปกรณ์ทั้งหมดแล้ว (เก็บเข้าคลัง) — ใช้ "แต่งรอบที่แล้ว" เพื่อใส่กลับได้','ok');draft={};await reload();} else setMsg(j.msg||'ไม่สำเร็จ','err');
};
async function savePreset(n){
  const name=prompt('ตั้งชื่อพรีเซ็ต',"พรีเซ็ต "+n); if(name===null)return;
  const j=await api('/api/gunsmith/preset/save',{method:'POST',body:JSON.stringify({weapon_id:wid,slot_no:n,name:name})});
  if(j.st==='ok'){setMsg('เซฟพรีเซ็ตแล้ว','ok');await reload();} else setMsg(j.msg||'เซฟไม่สำเร็จ','err');
}
async function delPreset(n){
  const j=await api('/api/gunsmith/preset/delete',{method:'POST',body:JSON.stringify({weapon_id:wid,slot_no:n})});
  if(j.st==='ok') await reload(); else setMsg(j.msg||'ลบไม่สำเร็จ','err');
}
async function reload(){
  const m=await api('/api/gunsmith/me'); if(m.st!=='ok'){setMsg(m._status===401?'ต้องล็อกอินก่อน (ไม่พบ vmax_token)':(m.msg||'โหลดไม่สำเร็จ'),'err');return false;}
  ME=m;renderAll();return true;
}
(async()=>{
  const c=await api('/api/gunsmith/catalog'); if(c.st!=='ok'){setMsg('โหลดข้อมูลไม่สำเร็จ','err');return;}
  CAT=c; wid=new URLSearchParams(location.search).get('weapon'); if(!CAT.weapons[wid]) wid=Object.keys(CAT.weapons)[3]||Object.keys(CAT.weapons)[0];
  const m=await api('/api/gunsmith/me'); if(m.st!=='ok'){setMsg(m._status===401?'ต้องล็อกอินก่อน (ไม่พบ vmax_token)':(m.msg||'โหลดไม่สำเร็จ'),'err');return;}
  ME=m; renderTabs(); renderAll();
})();
</script></body></html>
"""
