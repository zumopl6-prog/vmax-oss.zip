# =====================================================================
# VMAX Module: Protective Gear (อุปกรณ์ป้องกัน) + Wikipedia Gear Catalog
# =====================================================================
# แพทเทิร์นเดียวกับโมดูลอื่น: ฝังเป็น base64 ในไฟล์หลัก -> self-extract -> attach(globals())
#
#   1) อุปกรณ์ป้องกัน 4 ช่อง: หัว / ลำตัว / แขน (ปลอกแขน) / ขา (เกราะเข่า-หน้าแข้ง)
#      แต่ละชิ้นมี ความทนทาน, เกราะระดับ (AC 1-6), ลดดาเมจกระสุน/กระแทก, น้ำหนัก
#   2) คำนวณ "โอกาสทะลุเกราะ" (penetration chance) + "ดาเมจที่เกราะดูดซับ" ฝั่งเซิร์ฟเวอร์
#      — จุดที่โดนสุ่มฝั่งเซิร์ฟเวอร์ตามสัดส่วนพื้นที่ร่างกาย (ไม่เชื่อ zone จาก client)
#   3) ดึงข้อมูลจาก Wikipedia ว่ามีอุปกรณ์ป้องกันอะไรบ้าง -> เก็บเป็นคลัง + ใช้เป็นคำอธิบายไอเทม
#      + แนะนำหัวข้อที่ยังไม่มีไอเทมในเกม (ไว้ใช้คิดไอเทมใหม่)
# ข้อมูลจาก Wikipedia เป็นสารานุกรมทั่วไป (CC BY-SA) แสดงพร้อมลิงก์ต้นทางเสมอ
# =====================================================================
from __future__ import annotations

import json
import os
import random
import re
import threading
import time
import uuid

_ATTACHED = False
_READY = False
_LOCK = threading.RLock()

STATE_FILE = "vmax_armor_state.json"
WIKI_CACHE_FILE = "vmax_armor_wiki_cache.json"
WIKI_REFRESH_SEC = 7 * 24 * 3600
MAX_OWNED = 60
REPAIR_KIT_NAME = "ชุดซ่อมเกราะ"
REPAIR_KIT_AMOUNT = 40

SLOTS = {
    "head":  {"name": "ศีรษะ", "weight": 10, "icon": "⛑️"},
    "torso": {"name": "ลำตัว", "weight": 40, "icon": "🦺"},
    "arms":  {"name": "แขน",   "weight": 20, "icon": "💪"},
    "legs":  {"name": "ขา",    "weight": 30, "icon": "🦵"},
}

# red = สัดส่วนดาเมจที่ลดได้เมื่อ "กันได้เต็ม" ; ac = ระดับเกราะ 1-6 (เทียบกับค่า pen ของกระสุน)
# speed = ตัวคูณความเร็ววิ่ง (น้ำหนัก/ความอึดอัด) ; wiki = หัวข้อ Wikipedia ที่ใช้เป็นคำอธิบาย
GEAR = {
    # ----- แขน -----
    "padded_forearm": {"slot": "arms", "name": "ปลอกแขนผ้าบุนวม", "tier": 1, "ac": 1, "dur": 60, "weight": 0.3, "speed": 1.0,
        "red": {"ballistic": 0.05, "melee": 0.35}, "wiki": "Gambeson",
        "desc": "ปลอกแขนผ้ายืดบุฟองน้ำ กันแรงกระแทกและการปัดป้องระยะประชิด แทบไม่กันกระสุน"},
    "foam_forearm": {"slot": "arms", "name": "ปลอกแขนโฟมรังผึ้ง", "tier": 2, "ac": 2, "dur": 90, "weight": 0.5, "speed": 1.0,
        "red": {"ballistic": 0.10, "melee": 0.45}, "wiki": "Elbow pad",
        "desc": "แผ่นโฟมโครงสร้างรังผึ้งดูดซับแรงกระแทกได้ดีกว่าผ้าบุธรรมดา"},
    "composite_vambrace": {"slot": "arms", "name": "เกราะท่อนแขนคอมโพสิต", "tier": 3, "ac": 3, "dur": 120, "weight": 0.9, "speed": 0.995,
        "red": {"ballistic": 0.30, "melee": 0.55}, "wiki": "Vambrace",
        "desc": "เปลือกแข็งซ้อนชั้นบุนวม คลุมตั้งแต่ข้อมือถึงข้อศอก"},
    # ----- ขา -----
    "padded_shin": {"slot": "legs", "name": "สนับแข้งบุนวม", "tier": 1, "ac": 1, "dur": 70, "weight": 0.6, "speed": 1.0,
        "red": {"ballistic": 0.05, "melee": 0.35}, "wiki": "Shin guard",
        "desc": "สนับแข้งผ้าบุฟองน้ำ รัดด้วยเวลโคร กันแรงกระแทกที่หน้าแข้ง"},
    "knee_shin_set": {"slot": "legs", "name": "เกราะเข่า-หน้าแข้งยางแข็ง", "tier": 2, "ac": 2, "dur": 100, "weight": 1.4, "speed": 0.99,
        "red": {"ballistic": 0.15, "melee": 0.50}, "wiki": "Knee pad",
        "desc": "กะลาเข่าพลาสติกแข็ง + แผ่นหน้าแข้งหุ้มผ้า ใส่ทับกางเกงได้"},
    "long_knee_guard": {"slot": "legs", "name": "เกราะขายาวเข่า-หน้าแข้งหนา", "tier": 3, "ac": 3, "dur": 140, "weight": 2.4, "speed": 0.96,
        "red": {"ballistic": 0.35, "melee": 0.55}, "wiki": "Greave",
        "desc": "แผ่นหนาคลุมตั้งแต่เหนือเข่าถึงข้อเท้า มีกะลาเข่าแข็ง ทนทานแต่หนักและเคลื่อนไหวช้าลง"},
    # ----- ลำตัว -----
    "padded_jacket": {"slot": "torso", "name": "เสื้อบุนวมกันกระแทก", "tier": 1, "ac": 1, "dur": 80, "weight": 1.0, "speed": 1.0,
        "red": {"ballistic": 0.05, "melee": 0.25}, "wiki": "Padded jack",
        "desc": "เสื้อบุหนาแบบโบราณ-สมัยใหม่ ลดแรงกระแทก ไม่กันกระสุน"},
    "soft_vest": {"slot": "torso", "name": "เสื้อเกราะอ่อน", "tier": 2, "ac": 2, "dur": 120, "weight": 2.0, "speed": 0.99,
        "red": {"ballistic": 0.30, "melee": 0.30}, "wiki": "Bulletproof vest",
        "desc": "เสื้อเกราะเส้นใยทอซ้อนชั้น ใส่ซ่อนใต้เสื้อได้ กันกระสุนความเร็วต่ำ"},
    "plate_vest": {"slot": "torso", "name": "เสื้อเกราะพร้อมแผ่นเพลท", "tier": 4, "ac": 4, "dur": 200, "weight": 5.0, "speed": 0.92,
        "red": {"ballistic": 0.55, "melee": 0.40}, "wiki": "Plate carrier",
        "desc": "เสื้อเกราะใส่แผ่นเพลทแข็งหน้า-หลัง กันได้ดีที่สุดในหมวดลำตัวแต่หนักมาก"},
    # ----- หัว -----
    "hard_cap": {"slot": "head", "name": "หมวกนิรภัย", "tier": 1, "ac": 1, "dur": 80, "weight": 0.4, "speed": 1.0,
        "red": {"ballistic": 0.10, "melee": 0.30}, "wiki": "Hard hat",
        "desc": "หมวกเปลือกแข็งกันของตกและแรงกระแทก"},
    "combat_helmet": {"slot": "head", "name": "หมวกรบ", "tier": 3, "ac": 3, "dur": 140, "weight": 1.4, "speed": 0.99,
        "red": {"ballistic": 0.35, "melee": 0.35}, "wiki": "Combat helmet",
        "desc": "หมวกเปลือกคอมโพสิต มีรางติดอุปกรณ์เสริม"},
}

# หัวข้อ Wikipedia ที่ดึงมาศึกษาว่า "มีอุปกรณ์ป้องกันอะไรบ้าง" (ภาษาอังกฤษ — ใช้ค้นหา)
ARMOR_WIKI_TOPICS = [
    "Body armor", "Bulletproof vest", "Plate carrier", "Flak jacket", "Combat helmet", "Hard hat",
    "Shin guard", "Knee pad", "Elbow pad", "Greave", "Vambrace", "Gauntlet", "Bracer",
    "Gambeson", "Padded jack", "Brigandine", "Cuirass", "Gorget", "Chain mail", "Riot shield",
    "Ballistic face mask", "Mouthguard", "Kevlar", "Ceramic armor", "Motorcycle protective clothing",
    "Hockey protective equipment", "Cut-resistant gloves", "Ballistic shield",
]

_SLOT_KEYWORDS = [
    ("head", ("helmet", "hat", "cap", "mask", "mouthguard", "gorget", "coif")),
    ("arms", ("vambrace", "bracer", "gauntlet", "elbow", "glove", "sleeve")),
    ("legs", ("greave", "knee", "shin", "cuisse", "leg", "boot")),
    ("torso", ("vest", "jacket", "cuirass", "mail", "plate", "flak", "brigandine", "gambeson", "jack", "body armor", "armor", "armour")),
]

STATE: dict = {}      # uid -> {"owned":[{iid,id,dur}], "equipped":{slot:iid}}
WIKI: dict = {}       # topic -> {title, extract, thumbnail, wiki_url, queried_as, fetched_at}
_DIRTY = {"state": False}
_WIKI_SYNCING = {"on": False}


# ---------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------
def _load():
    global STATE, WIKI
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            STATE = json.load(f)
    except Exception:
        STATE = {}
    try:
        with open(WIKI_CACHE_FILE, "r", encoding="utf-8") as f:
            WIKI = json.load(f)
    except Exception:
        WIKI = {}


def _atomic_dump(path, obj):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[Armor] save {path} failed: {e}")


def _flush_state(force=False):
    with _LOCK:
        if not (force or _DIRTY["state"]):
            return
        _DIRTY["state"] = False
        snap = json.loads(json.dumps(STATE))
    _atomic_dump(STATE_FILE, snap)


def _flusher_loop():
    while True:
        time.sleep(10)
        try:
            _flush_state()
        except Exception as e:
            print(f"[Armor] flusher error: {e}")


def _user(uid):
    st = STATE.setdefault(uid, {"owned": [], "equipped": {}})
    st.setdefault("owned", [])
    st.setdefault("equipped", {})
    return st


def _find(st, iid):
    for it in st["owned"]:
        if it["iid"] == iid:
            return it
    return None


def _new_instance(item_id):
    return {"iid": uuid.uuid4().hex[:10], "id": item_id, "dur": GEAR[item_id]["dur"]}


# ---------------------------------------------------------------------
# combat math (server-authoritative)
# ---------------------------------------------------------------------
def _roll_zone():
    r = random.uniform(0, sum(s["weight"] for s in SLOTS.values()))
    acc = 0
    for k, s in SLOTS.items():
        acc += s["weight"]
        if r <= acc:
            return k
    return "torso"


def pen_chance(ac: int, pen: int) -> float:
    """โอกาสกระสุนทะลุเกราะ: pen==ac -> 50%, ต่างกัน 1 ระดับ -> ±17% (จำกัด 5%-95%)"""
    return max(0.05, min(0.95, 0.5 + 0.17 * (pen - ac)))


def mitigate(uid, dmg, dtype="ballistic", pen=3):
    """คืน (ดาเมจสุดท้าย, รายละเอียด|None) — เรียกจากทุกเส้นทางดาเมจได้
    โดนที่ไหนสุ่มฝั่งเซิร์ฟเวอร์ตามสัดส่วนพื้นที่; ถ้าเกราะที่ช่องนั้นยังไม่พัง:
      - ทะลุ (ตามโอกาส pen_chance) -> เกราะดูดซับ 50% ของ red
      - ไม่ทะลุ                     -> เกราะดูดซับเต็ม red
    เกราะสึก = ดาเมจที่ดูดซับ x0.6 (ขั้นต่ำ 1) ; ความทนทานหมด = พัง ไม่กันอีก"""
    try:
        dmg = int(dmg)
    except Exception:
        return dmg, None
    if not _READY or dmg <= 0 or not uid:
        return dmg, None
    dtype = dtype if dtype in ("ballistic", "melee") else "ballistic"
    pen = max(1, min(6, int(pen)))
    with _LOCK:
        st = STATE.get(uid)
        if not st or not st.get("equipped"):
            return dmg, None
        zone = _roll_zone()
        iid = st["equipped"].get(zone)
        inst = _find(st, iid) if iid else None
        if not inst:
            return dmg, {"zone": zone, "absorbed": 0, "item": None}
        spec = GEAR.get(inst["id"])
        if not spec or inst["dur"] <= 0:
            return dmg, {"zone": zone, "absorbed": 0, "item": inst["id"], "broken": True}
        red = min(0.8, spec["red"].get(dtype, 0))
        penetrated = (random.random() < pen_chance(spec["ac"], pen)) if dtype == "ballistic" else False
        eff = red * (0.5 if penetrated else 1.0)
        absorbed = int(round(dmg * eff))
        final = max(1, dmg - absorbed)
        absorbed = dmg - final
        wear = max(1, int(round(absorbed * 0.6))) if absorbed > 0 else 0
        inst["dur"] = max(0, inst["dur"] - wear)
        if wear:
            _DIRTY["state"] = True
        return final, {"zone": zone, "item": inst["id"], "name": spec["name"], "absorbed": absorbed,
                       "penetrated": penetrated, "dur": inst["dur"], "dur_max": spec["dur"],
                       "broken": inst["dur"] <= 0}


def mitigate_for_sid(target_sid, dmg, main_globals, dtype="ballistic", pen=3):
    """ตัวต่อกับเส้นทางยิง PvP หลัก: หา uid จาก sid -> ลดดาเมจ -> แจ้งผู้ถูกยิงว่าเกราะรับไว้เท่าไหร่"""
    try:
        uid = (main_globals.get("PLAYERS") or {}).get(target_sid, {}).get("uid")
        final, info = mitigate(uid, dmg, dtype, pen)
        if info and info.get("item"):
            sio = main_globals.get("sio")
            if sio is not None:
                sio.emit("armor_hit", info, room=target_sid)
        return final
    except Exception as e:
        print(f"[Armor] mitigate_for_sid error: {e}")
        return dmg


def summary(uid):
    with _LOCK:
        st = STATE.get(uid) or {"owned": [], "equipped": {}}
        weight, speed, reds = 0.0, 1.0, {"ballistic": 0.0, "melee": 0.0}
        eq = {}
        for slot, iid in st["equipped"].items():
            inst = _find(st, iid)
            spec = GEAR.get(inst["id"]) if inst else None
            if not spec:
                continue
            eq[slot] = {"iid": inst["iid"], "id": inst["id"], "dur": inst["dur"], "dur_max": spec["dur"]}
            weight += spec["weight"]
            speed *= spec["speed"]
            w = SLOTS[slot]["weight"] / 100.0
            if inst["dur"] > 0:
                for t in reds:
                    reds[t] += w * spec["red"].get(t, 0)
        return {"equipped": eq, "weight": round(weight, 2), "speed_mult": round(speed, 3),
                "coverage_reduction": {k: round(v, 3) for k, v in reds.items()},
                "owned": [dict(i) for i in st["owned"]]}


# ---------------------------------------------------------------------
# Wikipedia catalog
# ---------------------------------------------------------------------
def _trim(text, n=700):
    text = (text or "").strip()
    if len(text) <= n:
        return text
    cut = text[:n]
    p = max(cut.rfind(". "), cut.rfind("。"))
    return (cut[:p + 1] if p > 200 else cut.rstrip() + "…")


def _guess_slot(topic, title):
    s = (topic + " " + (title or "")).lower()
    for slot, kws in _SLOT_KEYWORDS:
        if any(k in s for k in kws):
            return slot
    return None


def wiki_sync(main_globals, topics=None):
    """ดึงสรุปบทความจาก Wikipedia ทีละหัวข้อ (ใช้ฟังก์ชันค้นหา/ดึงสรุปเดิมของไฟล์หลัก
    ที่ตั้ง User-Agent และ timeout ไว้แล้ว) แล้วเก็บลงแคชไฟล์ — กัน rate limit ด้วยหน่วง 0.3 วิ"""
    if _WIKI_SYNCING["on"]:
        return {"synced": [], "failed": [], "busy": True}
    _WIKI_SYNCING["on"] = True
    search = main_globals.get("_wiki_search_best_title")
    fetch = main_globals.get("_wiki_fetch_summary")
    topics = topics or ARMOR_WIKI_TOPICS
    synced, failed = [], []
    try:
        if not search or not fetch:
            print("[Armor/Wiki] ไม่พบฟังก์ชัน Wikipedia ของไฟล์หลัก — ข้ามการซิงก์")
            return {"synced": [], "failed": list(topics)}
        for topic in topics:
            try:
                title = search(topic) or topic
                s = fetch(title)
            except Exception as e:
                print(f"[Armor/Wiki] {topic}: {e}")
                s = None
            if s and s.get("extract"):
                with _LOCK:
                    WIKI[topic] = {"title": s.get("title", topic), "extract": _trim(s["extract"]),
                                   "thumbnail": s.get("thumbnail"), "wiki_url": s.get("wiki_url"),
                                   "queried_as": topic, "fetched_at": time.time()}
                synced.append(topic)
            else:
                failed.append(topic)
            time.sleep(0.3)
        with _LOCK:
            snap = json.loads(json.dumps(WIKI))
        _atomic_dump(WIKI_CACHE_FILE, snap)
        print(f"[Armor/Wiki] ซิงก์อุปกรณ์ป้องกันจาก Wikipedia: สำเร็จ {len(synced)}/{len(topics)}")
    finally:
        _WIKI_SYNCING["on"] = False
    return {"synced": synced, "failed": failed}


def _wiki_for(item):
    w = WIKI.get(item.get("wiki"))
    if not w:
        return None
    return {"title": w["title"], "extract": w["extract"], "wiki_url": w.get("wiki_url"), "thumbnail": w.get("thumbnail")}


def catalog_public():
    out = []
    with _LOCK:
        for iid, g in GEAR.items():
            d = {k: g[k] for k in ("slot", "name", "tier", "ac", "dur", "weight", "speed", "red", "desc")}
            d["id"] = iid
            d["wiki"] = _wiki_for(g)
            out.append(d)
    return out


def wiki_ideas():
    """หัวข้อที่ดึงมาแล้วแต่ยังไม่มีไอเทมในเกมผูกอยู่ — เดาช่องจากชื่อ (แค่คำแนะนำ ไม่ใช่ข้อเท็จจริง)"""
    used = {g.get("wiki") for g in GEAR.values()}
    ideas = []
    with _LOCK:
        for topic, w in WIKI.items():
            if topic in used:
                continue
            ideas.append({"topic": topic, "title": w["title"], "slot_guess": _guess_slot(topic, w["title"]),
                          "extract": _trim(w["extract"], 300), "wiki_url": w.get("wiki_url")})
    return ideas


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
    require_staff_rank = main_globals.get("require_staff_rank")
    INVENTORY = main_globals.get("INVENTORY")
    VMAX_MODULES = main_globals.get("VMAX_MODULES")
    audit_log = main_globals.get("audit_log") or (lambda *a, **k: None)

    if app is None or require_auth is None or require_staff_rank is None or INVENTORY is None:
        print("[Armor] ⚠️  ไม่พบ app/require_auth/require_staff_rank/INVENTORY — ข้ามการต่อโมดูลนี้")
        _ATTACHED = False
        return

    from flask import request, jsonify

    _load()
    _READY = True
    threading.Thread(target=_flusher_loop, daemon=True).start()

    def _uid():
        return str(getattr(request, "vmax_uid", "") or "")

    @app.route("/api/armor/catalog")
    def api_armor_catalog():
        return jsonify({"st": "ok", "slots": SLOTS, "items": catalog_public(),
                        "repair_kit": {"name": REPAIR_KIT_NAME, "amount": REPAIR_KIT_AMOUNT}})

    @app.route("/api/armor/me")
    @require_auth
    def api_armor_me():
        uid = _uid()
        s = summary(uid)
        s["repair_kits"] = int(INVENTORY.get(uid, {}).get(REPAIR_KIT_NAME, 0))
        s["inventory_gear"] = {g["name"]: int(INVENTORY.get(uid, {}).get(g["name"], 0))
                               for g in GEAR.values() if INVENTORY.get(uid, {}).get(g["name"], 0)}
        return jsonify({"st": "ok", **s})

    @app.route("/api/armor/equip", methods=["POST"])
    @require_auth
    def api_armor_equip():
        d = request.get_json(force=True, silent=True) or {}
        uid = _uid()
        with _LOCK:
            st = _user(uid)
            iid = str(d.get("iid") or "")
            item_id = str(d.get("item_id") or "")
            if iid:
                inst = _find(st, iid)
                if not inst:
                    return jsonify({"st": "error", "msg": "ไม่พบชิ้นนี้ในคลังเกราะของคุณ"}), 404
            elif item_id in GEAR:
                inv = INVENTORY.setdefault(uid, {})
                name = GEAR[item_id]["name"]
                if int(inv.get(name, 0)) < 1:
                    return jsonify({"st": "error", "msg": f"ไม่มี {name} ในกระเป๋า"}), 400
                if len(st["owned"]) >= MAX_OWNED:
                    return jsonify({"st": "error", "msg": "คลังเกราะเต็ม"}), 400
                inv[name] -= 1
                if inv[name] <= 0:
                    inv.pop(name, None)
                inst = _new_instance(item_id)
                st["owned"].append(inst)
            else:
                return jsonify({"st": "error", "msg": "ต้องระบุ iid หรือ item_id ที่ถูกต้อง"}), 400
            slot = GEAR[inst["id"]]["slot"]
            st["equipped"][slot] = inst["iid"]
            _DIRTY["state"] = True
        _flush_state(True)
        audit_log("armor_equip", uid=uid, item=inst["id"], slot=slot)
        return jsonify({"st": "ok", **summary(uid)})

    @app.route("/api/armor/unequip", methods=["POST"])
    @require_auth
    def api_armor_unequip():
        d = request.get_json(force=True, silent=True) or {}
        uid = _uid()
        slot = str(d.get("slot") or "")
        with _LOCK:
            st = _user(uid)
            if slot not in SLOTS or slot not in st["equipped"]:
                return jsonify({"st": "error", "msg": "ช่องนี้ไม่มีเกราะ"}), 400
            st["equipped"].pop(slot, None)
            _DIRTY["state"] = True
        _flush_state(True)
        return jsonify({"st": "ok", **summary(uid)})

    @app.route("/api/armor/repair", methods=["POST"])
    @require_auth
    def api_armor_repair():
        d = request.get_json(force=True, silent=True) or {}
        uid = _uid()
        iid = str(d.get("iid") or "")
        with _LOCK:
            st = _user(uid)
            inst = _find(st, iid)
            if not inst:
                return jsonify({"st": "error", "msg": "ไม่พบชิ้นนี้"}), 404
            spec = GEAR[inst["id"]]
            if inst["dur"] >= spec["dur"]:
                return jsonify({"st": "error", "msg": "ความทนทานเต็มแล้ว"}), 400
            inv = INVENTORY.setdefault(uid, {})
            if int(inv.get(REPAIR_KIT_NAME, 0)) < 1:
                return jsonify({"st": "error", "msg": f"ไม่มี {REPAIR_KIT_NAME}"}), 400
            inv[REPAIR_KIT_NAME] -= 1
            if inv[REPAIR_KIT_NAME] <= 0:
                inv.pop(REPAIR_KIT_NAME, None)
            inst["dur"] = min(spec["dur"], inst["dur"] + REPAIR_KIT_AMOUNT)
            _DIRTY["state"] = True
        _flush_state(True)
        return jsonify({"st": "ok", **summary(uid)})

    @app.route("/api/armor/admin/grant", methods=["POST"])
    @require_staff_rank("admin")
    def api_armor_admin_grant():
        d = request.get_json(force=True, silent=True) or {}
        target = str(d.get("uid") or "").strip()
        item = str(d.get("item_id") or "")
        try:
            count = int(d.get("count", 1))
        except Exception:
            count = 0
        if not target or not (1 <= count <= 50) or (item not in GEAR and item != "repair_kit"):
            return jsonify({"st": "error", "msg": "ต้องมี uid, item_id (ของใน catalog หรือ repair_kit), count 1-50"}), 400
        name = REPAIR_KIT_NAME if item == "repair_kit" else GEAR[item]["name"]
        inv = INVENTORY.setdefault(target, {})
        inv[name] = int(inv.get(name, 0)) + count
        audit_log("armor_admin_grant", uid=_uid(), target=target, item=item, count=count)
        return jsonify({"st": "ok", "uid": target, "item": name, "now": inv[name]})

    @app.route("/api/armor/wiki")
    def api_armor_wiki():
        with _LOCK:
            return jsonify({"st": "ok", "total": len(WIKI), "syncing": _WIKI_SYNCING["on"],
                            "attribution": "Wikipedia (CC BY-SA 4.0)", "items": WIKI})

    @app.route("/api/armor/wiki/ideas")
    def api_armor_wiki_ideas():
        return jsonify({"st": "ok", "ideas": wiki_ideas(),
                        "note": "slot_guess เดาจากชื่อหัวข้อ เป็นแค่คำแนะนำสำหรับคิดไอเทมใหม่"})

    @app.route("/api/armor/wiki/sync", methods=["POST"])
    @require_staff_rank("admin")
    def api_armor_wiki_sync():
        d = request.get_json(force=True, silent=True) or {}
        topics = d.get("topics")
        if topics is not None:
            if (not isinstance(topics, list) or not (1 <= len(topics) <= 30)
                    or any((not isinstance(t, str)) or not (2 <= len(t) <= 60) for t in topics)):
                return jsonify({"st": "error", "msg": "topics ต้องเป็นลิสต์ข้อความ 1-30 หัวข้อ (2-60 ตัวอักษร)"}), 400
        if _WIKI_SYNCING["on"]:
            return jsonify({"st": "error", "msg": "กำลังซิงก์อยู่แล้ว"}), 409
        threading.Thread(target=wiki_sync, args=(main_globals, topics), daemon=True).start()
        audit_log("armor_wiki_sync", uid=_uid(), topics=topics or "default")
        return jsonify({"st": "ok", "msg": "เริ่มซิงก์ใน background แล้ว ดูผลที่ GET /api/armor/wiki"})

    @app.route("/widgets/armor")
    def widget_armor():
        return ARMOR_WIDGET_HTML

    if isinstance(VMAX_MODULES, dict):
        VMAX_MODULES["protective_gear"] = {
            "desc": "อุปกรณ์ป้องกัน 4 ช่อง (ปลอกแขน/เกราะเข่า-หน้าแข้ง/หมวก/เสื้อเกราะ) มีความทนทาน "
                    "โอกาสทะลุเกราะ และคลังข้อมูลอุปกรณ์ป้องกันจาก Wikipedia",
            "routes": ["/widgets/armor", "/api/armor/catalog", "/api/armor/me", "/api/armor/equip",
                       "/api/armor/unequip", "/api/armor/repair", "/api/armor/admin/grant",
                       "/api/armor/wiki", "/api/armor/wiki/ideas", "/api/armor/wiki/sync"],
        }

    # ซิงก์ตอนสตาร์ท ถ้าแคชว่างหรือเก่าเกิน 7 วัน (ไม่บล็อกการเปิดเซิร์ฟเวอร์)
    with _LOCK:
        newest = max((w.get("fetched_at", 0) for w in WIKI.values()), default=0)
    if time.time() - newest > WIKI_REFRESH_SEC:
        threading.Thread(target=wiki_sync, args=(main_globals,), daemon=True).start()
    print("[Armor] ต่อโมดูลอุปกรณ์ป้องกันเสร็จ — /widgets/armor /api/armor/*")


# ---------------------------------------------------------------------
# widget
# ---------------------------------------------------------------------
ARMOR_WIDGET_HTML = r"""<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>อุปกรณ์ป้องกัน</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#0c1118;color:#dde6f3;font-family:system-ui,"Noto Sans Thai",sans-serif;padding:10px}
.tabs{display:flex;gap:6px;margin-bottom:10px}
.tabs button{flex:1;padding:9px;background:#18202c;color:#dde6f3;border:1px solid #2a3547;border-radius:8px;cursor:pointer;font:inherit}
.tabs button.on{background:#2f6bff;border-color:#2f6bff}
.card{background:#141b26;border:1px solid #263246;border-radius:10px;padding:10px;margin-bottom:8px}
.slots{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.slot .h{font-size:12px;color:#8fa3c2}.slot .n{font-weight:700;margin:3px 0}
.bar{height:7px;background:#263246;border-radius:4px;overflow:hidden;margin:5px 0}
.bar i{display:block;height:100%;background:#4cd18a}.bar i.low{background:#ffb347}.bar i.bad{background:#ff6b6b}
button.s{padding:5px 10px;background:#243049;color:#dde6f3;border:1px solid #33425e;border-radius:6px;cursor:pointer;font:inherit;font-size:12px;margin-right:4px}
button.s:disabled{opacity:.4;cursor:not-allowed}
.sum{font-size:13px;line-height:1.6;color:#b9c7dd}
.sm{font-size:12px;color:#8fa3c2;line-height:1.5}
.pill{display:inline-block;padding:1px 7px;border-radius:9px;background:#243049;font-size:11px;margin-right:4px}
a{color:#8fc0ff}
.msg{min-height:20px;font-size:13px;margin:6px 0}.err{color:#ff8a8a}.ok{color:#8affb0}
.ex{font-size:12px;color:#aebcd3;margin-top:6px;border-left:3px solid #33425e;padding-left:8px}
</style></head><body>
<div class="tabs"><button id="t1" class="on">ตัวละครของฉัน</button><button id="t2">รายการอุปกรณ์</button><button id="t3">คลังข้อมูล Wikipedia</button></div>
<div class="msg" id="msg"></div>
<div id="v1"></div><div id="v2" style="display:none"></div><div id="v3" style="display:none"></div>
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
let CAT=null,ME=null;
const byId=id=>CAT.items.find(i=>i.id===id);
function setMsg(t,c){$('msg').textContent=t||'';$('msg').className='msg '+(c||'');}
function durBar(d,m){const p=Math.max(0,Math.min(100,d/m*100));return el('div',{class:'bar'},[el('i',{class:p<=0?'bad':(p<30?'low':''),style:'width:'+p+'%'})]);}
function lore(g){
  if(!g.wiki) return null;
  const a=g.wiki.wiki_url?el('a',{href:g.wiki.wiki_url,target:'_blank',rel:'noopener noreferrer',text:'Wikipedia: '+g.wiki.title}):el('span',{text:'Wikipedia: '+g.wiki.title});
  return el('div',{class:'ex'},[el('div',{text:g.wiki.extract}),a]);
}
function stats(g){
  return el('div',{class:'sm'},[
    el('span',{class:'pill',text:'AC '+g.ac}),el('span',{class:'pill',text:'กระสุน −'+Math.round(g.red.ballistic*100)+'%'}),
    el('span',{class:'pill',text:'กระแทก −'+Math.round(g.red.melee*100)+'%'}),el('span',{class:'pill',text:g.weight+' กก.'}),
    el('span',{class:'pill',text:'ทน '+g.dur})]);
}
function render1(){
  const v=$('v1'); v.innerHTML='';
  if(!ME){v.appendChild(el('div',{class:'card',text:'ต้องล็อกอินก่อน (ไม่พบ vmax_token)'}));return;}
  const sl=el('div',{class:'slots'});
  Object.keys(CAT.slots).forEach(s=>{
    const e=ME.equipped[s], g=e?byId(e.id):null;
    const c=el('div',{class:'card slot'},[el('div',{class:'h',text:CAT.slots[s].icon+' '+CAT.slots[s].name})]);
    if(g){
      c.appendChild(el('div',{class:'n',text:g.name}));c.appendChild(durBar(e.dur,e.dur_max));
      c.appendChild(el('div',{class:'sm',text:(e.dur<=0?'พัง — ไม่ป้องกันแล้ว · ':'')+e.dur+'/'+e.dur_max}));
      c.appendChild(el('div',{style:'margin-top:6px'},[
        el('button',{class:'s',text:'ถอด',onclick:()=>act('/api/armor/unequip',{slot:s})}),
        el('button',{class:'s',text:'ซ่อม',disabled:(ME.repair_kits<1||e.dur>=e.dur_max)?'disabled':null,onclick:()=>act('/api/armor/repair',{iid:e.iid})})]));
    } else c.appendChild(el('div',{class:'sm',text:'— ว่าง —'}));
    sl.appendChild(c);
  });
  v.appendChild(sl);
  const cr=ME.coverage_reduction;
  v.appendChild(el('div',{class:'card sum'},[
    el('div',{text:'ลดดาเมจเฉลี่ยทั้งตัว: กระสุน '+(cr.ballistic*100).toFixed(1)+'% · กระแทก '+(cr.melee*100).toFixed(1)+'%'}),
    el('div',{text:'น้ำหนักเกราะ '+ME.weight+' กก. · ความเร็ววิ่ง ×'+ME.speed_mult}),
    el('div',{text:'ชุดซ่อมเกราะ: '+ME.repair_kits+' ชิ้น (ซ่อม +'+CAT.repair_kit.amount+')'})]));
  const inv=Object.keys(ME.inventory_gear||{});
  const spare=ME.owned.filter(o=>!Object.values(ME.equipped).some(e=>e.iid===o.iid));
  if(inv.length||spare.length){
    const c=el('div',{class:'card'},[el('div',{class:'h',style:'font-size:12px;color:#8fa3c2;margin-bottom:6px',text:'ในกระเป๋า / คลังเกราะ'})]);
    inv.forEach(n=>{const g=CAT.items.find(i=>i.name===n);c.appendChild(el('div',{style:'margin:6px 0'},[
      el('span',{text:n+' ×'+ME.inventory_gear[n]+'  '}),el('button',{class:'s',text:'สวมใส่',onclick:()=>act('/api/armor/equip',{item_id:g.id})})]));});
    spare.forEach(o=>{const g=byId(o.id);c.appendChild(el('div',{style:'margin:6px 0'},[
      el('span',{text:g.name+' ('+o.dur+'/'+g.dur+')  '}),el('button',{class:'s',text:'สวมใส่',onclick:()=>act('/api/armor/equip',{iid:o.iid})}),
      el('button',{class:'s',text:'ซ่อม',disabled:(ME.repair_kits<1||o.dur>=g.dur)?'disabled':null,onclick:()=>act('/api/armor/repair',{iid:o.iid})})]));});
    v.appendChild(c);
  }
}
function render2(){
  const v=$('v2'); v.innerHTML='';
  ['head','torso','arms','legs'].forEach(s=>{
    v.appendChild(el('div',{class:'sm',style:'margin:8px 2px 4px',text:CAT.slots[s].icon+' '+CAT.slots[s].name}));
    CAT.items.filter(i=>i.slot===s).sort((a,b)=>a.tier-b.tier).forEach(g=>{
      const c=el('div',{class:'card'},[el('div',{style:'font-weight:700',text:g.name+'  (ระดับ '+g.tier+')'}),el('div',{class:'sm',text:g.desc}),stats(g)]);
      const l=lore(g); if(l)c.appendChild(l); v.appendChild(c);
    });
  });
}
async function render3(){
  const v=$('v3'); v.innerHTML='กำลังโหลด…';
  const [w,i]=await Promise.all([api('/api/armor/wiki'),api('/api/armor/wiki/ideas')]);
  v.innerHTML='';
  if(w.st!=='ok'){v.textContent=w.msg||'โหลดไม่สำเร็จ';return;}
  v.appendChild(el('div',{class:'sm',style:'margin-bottom:8px',text:'ดึงมาแล้ว '+w.total+' หัวข้อ'+(w.syncing?' (กำลังซิงก์…)':'')+' · แหล่งข้อมูล: '+w.attribution}));
  if(i.st==='ok'&&i.ideas.length){
    v.appendChild(el('div',{style:'font-weight:700;margin:6px 2px',text:'ไอเดียอุปกรณ์ที่ยังไม่มีในเกม'}));
    i.ideas.forEach(x=>{const c=el('div',{class:'card'},[el('div',{style:'font-weight:700',text:x.title}),
      el('div',{class:'sm',text:'ช่องที่น่าจะใส่ (เดาจากชื่อ): '+(x.slot_guess?CAT.slots[x.slot_guess].name:'ไม่แน่ใจ')}),el('div',{class:'ex',text:x.extract})]);
      if(x.wiki_url)c.appendChild(el('a',{href:x.wiki_url,target:'_blank',rel:'noopener noreferrer',text:'ดูบทความเต็ม',style:'font-size:12px;display:block;margin-top:4px'}));
      v.appendChild(c);});
  } else v.appendChild(el('div',{class:'card sm',text:w.total?'ทุกหัวข้อที่ดึงมามีไอเทมในเกมครบแล้ว':'ยังไม่มีข้อมูล — เซิร์ฟเวอร์กำลังซิงก์ครั้งแรก หรือเชื่อมต่ออินเทอร์เน็ตไม่ได้'}));
}
async function act(path,body){
  const j=await api(path,{method:'POST',body:JSON.stringify(body)});
  if(j.st==='ok'){setMsg('สำเร็จ','ok');await load();} else setMsg(j.msg||'ไม่สำเร็จ','err');
}
function tab(n){['1','2','3'].forEach(k=>{$('t'+k).classList.toggle('on',k===n);$('v'+k).style.display=k===n?'':'none';});if(n==='3')render3();}
['1','2','3'].forEach(k=>$('t'+k).onclick=()=>tab(k));
async function load(){
  const c=await api('/api/armor/catalog'); if(c.st!=='ok'){setMsg(c.msg||'โหลดไม่สำเร็จ','err');return;} CAT=c;
  const m=await api('/api/armor/me'); ME=m.st==='ok'?m:null;
  if(!ME&&m._status===401) setMsg('ต้องล็อกอินก่อน (ไม่พบ vmax_token)','err');
  render1(); render2();
}
load();
</script></body></html>
"""
