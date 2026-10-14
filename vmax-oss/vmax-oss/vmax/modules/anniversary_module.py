# ==========================================
# VMAX Module: Anniversary Gift (จดหมายอวยพรครบ 4,500 วัน)
# ==========================================
# ไฟล์นี้เป็น "module เสริม" แยกออกจากไฟล์หลักโดยสมบูรณ์ ไม่ไปแก้/แทรกโค้ด
# ในไฟล์หลัก 33,000+ บรรทัดเลย — วิธีต่อเข้าไฟล์หลักคือเรียก attach(globals())
# จากไฟล์หลัก ซึ่งจะ "หยิบยืม" ของที่ไฟล์หลักมีอยู่แล้ว (app, sio, INVENTORY,
# USER_STORE, LAUNCHER_CATALOG, register_user, watchdog_register_thread ฯลฯ)
# มาต่อยอด แทนที่จะประกาศซ้ำ/ชนกัน — ถ้าไฟล์หลักไม่มีตัวไหนบางตัว โมดูลนี้จะ
# fallback เป็นของตัวเองแทนอัตโนมัติ ไม่ error
#
# สเปคตามที่ตกลงไว้:
#   1) นับวันจริงจากวันสร้างตัวละคร (created_ts ต่อ uid) — ครบ 4,500 วัน
#      ระบบส่งไอเทม "จดหมายอวยพร" เข้ากล่องจดหมายอัตโนมัติ ครั้งเดียว ไม่ซ้ำ
#   2) ไอเทมนี้ใช้ได้กับเกมไหนก็ได้ที่ลงทะเบียนอยู่ใน VMAX_MODULES/LAUNCHER_CATALOG
#      ตอนใช้: เลือกเกมเป้าหมาย -> สุ่มของรางวัล (ของรางวัลถาวร + บัฟชั่วคราว)
#      แบบผสมกัน โดย scale ตามประเภท (genre) ของเกมนั้น
#   3) ใช้ได้ครั้งเดียวแล้วหมด (ได้รับตอนครบ 4,500 วันครั้งเดียว ใช้ปุ๊บไอเทมหมดปุ๊บ)
#
# ⚠️ หมายเหตุเรื่องวันที่ย้อนหลัง: ไฟล์หลักเดิมไม่มีการบันทึก created_ts ตอน
# สร้างบัญชี (register_user ไม่มี field นี้) โมดูลนี้จะ "แปะ" การบันทึกเวลาเข้าไป
# ให้อัตโนมัติตอน attach() (ดู _wrap_register_user ด้านล่าง) แต่บัญชีที่มีอยู่
# ก่อนหน้านี้แล้ว (สร้างไปแล้วในอดีต) จะไม่มีวันสร้างจริงให้อ้างอิง — โมดูลนี้
# จะเริ่มนับจาก "ตอนที่ attach() ถูกเรียกครั้งแรก" ให้แทน (ระบุ backfilled=True
# ในสถานะเพื่อความโปร่งใส) ถ้าต้องการวันที่ย้อนหลังจริง ต้องส่งมาป้อนเองผ่าน
# seed_created_ts(uid, ts) ก่อน attach() หรือหลัง attach() ก็ได้

from __future__ import annotations

import time
import uuid
import random
import threading

ANNIVERSARY_DAYS = 4500
ANNIVERSARY_SECONDS = ANNIVERSARY_DAYS * 86400
ANNIVERSARY_ITEM_ID = "item_anniversary_letter_4500"
ANNIVERSARY_ITEM_NAME = "จดหมายอวยพรครบ 4,500 วัน"
ANNIVERSARY_CHECK_INTERVAL_SEC = 3600     # เช็คทุก 1 ชม. พอ ไม่ต้องถี่กว่านี้เพราะหน่วยเป็นวัน
ANNIVERSARY_BUFF_DEFAULT_TTL_SEC = 24 * 3600   # บัฟชั่วคราวอยู่ได้ 24 ชม. หลังใช้ไอเทม

# --- state เฉพาะของโมดูลนี้ (แยกจากไฟล์หลักเด็ดขาด กันชื่อชนกัน) --------------
ACCOUNT_CREATED_TS: dict[str, float] = {}     # uid -> เวลาที่ถือว่า "สร้างตัวละคร"
ACCOUNT_CREATED_BACKFILLED: set[str] = set()  # uid ที่ไม่มีวันสร้างจริง (ถูก backfill ให้)
ANNIVERSARY_GRANTED: set[str] = set()         # uid ที่ได้รับไอเทมนี้ไปแล้ว (กันส่งซ้ำ)
ANNIVERSARY_MAILBOX: dict[str, list[dict]] = {}   # uid -> [{mail_id, item_id, claimed, granted_ts}]
ANNIVERSARY_BUFFS: dict[str, list[dict]] = {}     # uid -> [{buff_id, game_id, kind, value, expires_ts}]

_ATTACHED = False
_LOCK = threading.Lock()

# --- ของรางวัลสุ่ม แบ่งตาม genre ของเกม (scale ตามเกมที่เลือกใช้ไอเทม) --------
# แต่ละรายการ: (น้ำหนักสุ่ม, ฟังก์ชันสร้างรางวัล)
def _reward_currency(genre: str) -> dict:
    amount = random.randint(300, 1200)
    return {"kind": "currency", "label": f"เครดิต +{amount}", "credits": amount}

def _reward_cosmetic(genre: str) -> dict:
    theme = {
        "shooter": ["Eclipse", "Aurora", "Nightfall", "Vanta"],
        "fighting": ["Crimson Fist", "Iron Wraith", "Storm Guard"],
        "farm": ["Golden Scarecrow", "Harvest Moon", "Starlight Barn"],
    }.get(genre, ["Anniversary", "Timeless", "Golden Hour"])
    return {"kind": "cosmetic", "label": f"สกินพิเศษ: {random.choice(theme)} (4500 Days Edition)"}

def _reward_buff(genre: str) -> dict:
    buff_table = {
        "shooter": [("dmg_boost", 0.08, 0.20), ("fire_rate_boost", 0.05, 0.15), ("reload_speed", 0.10, 0.25)],
        "fighting": [("stamina_regen", 0.10, 0.25), ("combo_window", 0.05, 0.15), ("guard_break", 0.05, 0.15)],
        "farm": [("crop_growth_speed", 0.10, 0.30), ("yield_boost", 0.10, 0.25), ("stamina_regen", 0.10, 0.20)],
    }
    options = buff_table.get(genre, [("exp_boost", 0.10, 0.30), ("credit_boost", 0.05, 0.20)])
    kind, lo, hi = random.choice(options)
    value = round(random.uniform(lo, hi), 3)
    return {"kind": "buff", "buff_kind": kind, "value": value,
            "label": f"บัฟชั่วคราว {kind} +{value*100:.1f}% (24 ชม.)"}

_REWARD_TABLE = [
    (0.45, _reward_currency),
    (0.30, _reward_cosmetic),
    (0.25, _reward_buff),
]

def _roll_rewards(genre: str, n: int = 2) -> list[dict]:
    """สุ่มของรางวัลผสมกัน n ชิ้น (ค่าเริ่มต้น 2: อย่างน้อย 1 ของถาวร + 1 บัฟ ถ้าเป็นไปได้)"""
    pool_funcs = [f for _, f in _REWARD_TABLE]
    weights = [w for w, _ in _REWARD_TABLE]
    picked = random.choices(pool_funcs, weights=weights, k=n)
    return [fn(genre) for fn in picked]


# ==========================================
# ตัวนับวัน / ให้ไอเทม
# ==========================================
def seed_created_ts(uid: str, ts: float):
    """ป้อนวันสร้างตัวละครจริงย้อนหลังเอง (ถ้ามีข้อมูลเก่าเก็บไว้ที่อื่น) เรียกก่อนหรือหลัง
    attach() ก็ได้ — เรียกซ้ำได้ ค่าล่าสุดจะทับค่าเดิม"""
    ACCOUNT_CREATED_TS[uid] = ts
    ACCOUNT_CREATED_BACKFILLED.discard(uid)

def _days_elapsed(uid: str) -> float:
    created = ACCOUNT_CREATED_TS.get(uid)
    if created is None:
        return 0.0
    return max(0.0, (time.time() - created) / 86400.0)

def _grant_if_eligible(uid: str):
    if uid in ANNIVERSARY_GRANTED:
        return
    if _days_elapsed(uid) < ANNIVERSARY_DAYS:
        return
    mail_id = uuid.uuid4().hex[:8]
    ANNIVERSARY_MAILBOX.setdefault(uid, []).append({
        "mail_id": mail_id, "item_id": ANNIVERSARY_ITEM_ID,
        "item_name": ANNIVERSARY_ITEM_NAME, "claimed": False,
        "granted_ts": time.time(),
    })
    ANNIVERSARY_GRANTED.add(uid)

def _check_all_accounts():
    with _LOCK:
        for uid in list(ACCOUNT_CREATED_TS.keys()):
            _grant_if_eligible(uid)

def _anniversary_check_loop():
    while True:
        try:
            _check_all_accounts()
        except Exception as e:
            print(f"[Anniversary Gift] เช็ครอบผิดพลาด: {e}")
        time.sleep(ANNIVERSARY_CHECK_INTERVAL_SEC)


# ==========================================
# attach(): จุดต่อเดียวเข้ากับไฟล์หลัก
# ==========================================
def attach(main_globals: dict):
    """เรียกจากไฟล์หลักบรรทัดเดียว (หลังจากที่ app/sio/register_user/INVENTORY
    ถูกประกาศไปแล้ว, ก่อน sio.run(...)):

        import vmax_module_anniversary_gift as anniv
        anniv.attach(globals())

    ทำ 4 อย่าง:
      1. ห่อ (wrap) register_user เดิมในไฟล์หลัก ให้บันทึก created_ts อัตโนมัติ
      2. backfill uid เก่าที่มีอยู่แล้วใน USER_STORE ให้เริ่มนับจากตอนนี้
      3. เพิ่ม Flask routes + background thread (ผูกกับ watchdog ถ้ามี)
      4. ไม่ทับ/ไม่แก้ตัวแปรเดิมของไฟล์หลักเลยแม้แต่บรรทัดเดียว
    """
    global _ATTACHED
    if _ATTACHED:
        return
    _ATTACHED = True

    app = main_globals.get("app")
    sio = main_globals.get("sio")
    INVENTORY = main_globals.setdefault("INVENTORY", {})
    USER_STORE = main_globals.get("USER_STORE", {})
    LAUNCHER_CATALOG = main_globals.get("LAUNCHER_CATALOG", {})
    VMAX_MODULES = main_globals.get("VMAX_MODULES")
    watchdog_register_thread = main_globals.get("watchdog_register_thread")

    # --- 1) ห่อ register_user เดิม เพื่อจับวันสร้างตัวละครแบบไปข้างหน้า -------
    _orig_register_user = main_globals.get("register_user")
    if _orig_register_user is not None:
        def _patched_register_user(uid: str, password: str):
            ok, msg = _orig_register_user(uid, password)
            if ok:
                seed_created_ts(uid, time.time())
            return ok, msg
        main_globals["register_user"] = _patched_register_user

    # --- 2) backfill บัญชีเก่าที่มีอยู่แล้วก่อน attach() ------------------------
    for uid in list(USER_STORE.keys()):
        if uid not in ACCOUNT_CREATED_TS:
            ACCOUNT_CREATED_TS[uid] = time.time()
            ACCOUNT_CREATED_BACKFILLED.add(uid)

    # --- 3) Flask routes --------------------------------------------------
    if app is not None:

        @app.route('/api/anniversary/status')
        def api_anniversary_status():
            from flask import request, jsonify
            uid = request.args.get("uid") or main_globals.get("P", {}).get("uid")
            days = _days_elapsed(uid)
            return jsonify({
                "st": "ok", "uid": uid,
                "days_elapsed": round(days, 2),
                "days_required": ANNIVERSARY_DAYS,
                "days_remaining": max(0.0, round(ANNIVERSARY_DAYS - days, 2)),
                "eligible": days >= ANNIVERSARY_DAYS,
                "already_granted": uid in ANNIVERSARY_GRANTED,
                "created_ts_is_backfilled": uid in ACCOUNT_CREATED_BACKFILLED,
            })

        @app.route('/api/anniversary/mailbox')
        def api_anniversary_mailbox():
            from flask import request, jsonify
            uid = request.args.get("uid") or main_globals.get("P", {}).get("uid")
            _grant_if_eligible(uid)   # เช็คสด เผื่อ background loop ยังไม่ถึงรอบ
            mail = ANNIVERSARY_MAILBOX.get(uid, [])
            return jsonify({"st": "ok", "mail": [m for m in mail if not m["claimed"]]})

        @app.route('/api/anniversary/mailbox/claim', methods=['POST'])
        def api_anniversary_mailbox_claim():
            from flask import request, jsonify
            data = request.get_json(force=True, silent=True) or {}
            uid = data.get("uid") or main_globals.get("P", {}).get("uid")
            mail_id = data.get("mail_id")
            mail = ANNIVERSARY_MAILBOX.get(uid, [])
            entry = next((m for m in mail if m["mail_id"] == mail_id), None)
            if not entry:
                return jsonify({"st": "error", "msg": "ไม่พบจดหมายชิ้นนี้"}), 404
            if entry["claimed"]:
                return jsonify({"st": "error", "msg": "รับของชิ้นนี้ไปแล้ว"}), 409
            entry["claimed"] = True
            inv = INVENTORY.setdefault(uid, {})
            inv[ANNIVERSARY_ITEM_NAME] = inv.get(ANNIVERSARY_ITEM_NAME, 0) + 1
            if sio is not None:
                try:
                    sio.emit('anniversary_mail_claimed', {"uid": uid, "mail_id": mail_id})
                except Exception:
                    pass
            return jsonify({"st": "ok", "received": ANNIVERSARY_ITEM_NAME})

        @app.route('/api/anniversary/use', methods=['POST'])
        def api_anniversary_use():
            """body: {uid, game_id} -> ใช้ไอเทมกับเกมที่เลือก (เกมไหนก็ได้ที่อยู่ใน
            LAUNCHER_CATALOG) สุ่มของรางวัล + บัฟผสมกัน scale ตาม genre ของเกมนั้น
            แล้วไอเทมถูกใช้ทิ้ง (ครั้งเดียวหมด)"""
            from flask import request, jsonify
            data = request.get_json(force=True, silent=True) or {}
            uid = data.get("uid") or main_globals.get("P", {}).get("uid")
            game_id = data.get("game_id")

            inv = INVENTORY.setdefault(uid, {})
            if inv.get(ANNIVERSARY_ITEM_NAME, 0) <= 0:
                return jsonify({"st": "error", "msg": "ไม่มีไอเทมนี้ในคลัง (ต้องรับจากกล่องจดหมายก่อน)"}), 400

            game = LAUNCHER_CATALOG.get(game_id)
            if not game:
                return jsonify({"st": "error", "msg": f"ไม่พบเกม '{game_id}' ใน LAUNCHER_CATALOG"}), 404
            genre = game.get("genre", "default")

            rewards = _roll_rewards(genre, n=2)
            granted_currency = 0
            for r in rewards:
                if r["kind"] == "currency":
                    granted_currency += r["credits"]
                    P = main_globals.get("P")
                    if isinstance(P, dict) and P.get("uid") == uid:
                        P["credits"] = P.get("credits", 0) + r["credits"]
                elif r["kind"] == "cosmetic":
                    inv[r["label"]] = inv.get(r["label"], 0) + 1
                elif r["kind"] == "buff":
                    buff_id = uuid.uuid4().hex[:8]
                    ANNIVERSARY_BUFFS.setdefault(uid, []).append({
                        "buff_id": buff_id, "game_id": game_id,
                        "kind": r["buff_kind"], "value": r["value"],
                        "expires_ts": time.time() + ANNIVERSARY_BUFF_DEFAULT_TTL_SEC,
                    })

            # ใช้ครั้งเดียวหมด
            inv[ANNIVERSARY_ITEM_NAME] -= 1
            if inv[ANNIVERSARY_ITEM_NAME] <= 0:
                inv.pop(ANNIVERSARY_ITEM_NAME, None)

            if sio is not None:
                try:
                    sio.emit('anniversary_item_used', {"uid": uid, "game_id": game_id, "rewards": rewards})
                except Exception:
                    pass

            return jsonify({"st": "ok", "game_id": game_id, "genre": genre,
                            "rewards": rewards, "credits_granted": granted_currency})

        @app.route('/api/anniversary/buffs')
        def api_anniversary_buffs():
            from flask import request, jsonify
            uid = request.args.get("uid") or main_globals.get("P", {}).get("uid")
            game_id = request.args.get("game_id")
            now = time.time()
            buffs = [b for b in ANNIVERSARY_BUFFS.get(uid, []) if b["expires_ts"] > now]
            ANNIVERSARY_BUFFS[uid] = buffs   # เก็บกวาดตัวที่หมดอายุไปในตัว
            if game_id:
                buffs = [b for b in buffs if b["game_id"] == game_id]
            return jsonify({"st": "ok", "buffs": buffs})

    # --- 4) ลงทะเบียนใน VMAX_MODULES (ถ้ามี) เพื่อให้โชว์ในแคตตาล็อกโมดูล -----
    if isinstance(VMAX_MODULES, dict):
        VMAX_MODULES["anniversary_gift"] = {
            "desc": f"ไอเทม '{ANNIVERSARY_ITEM_NAME}' — นับวันจริงจากวันสร้างตัวละคร (created_ts ต่อ uid) "
                    f"ครบ {ANNIVERSARY_DAYS} วันปุ๊บ ส่งเข้ากล่องจดหมายอัตโนมัติครั้งเดียว ใช้ได้กับเกมไหนก็ได้ "
                    "ใน LAUNCHER_CATALOG โดยสุ่มของรางวัล+บัฟผสมกัน scale ตาม genre ของเกมนั้น ใช้ครั้งเดียวหมด",
            "routes": ["/api/anniversary/status", "/api/anniversary/mailbox",
                       "/api/anniversary/mailbox/claim", "/api/anniversary/use",
                       "/api/anniversary/buffs"],
        }

    # --- 5) background thread (เช็คทุกชั่วโมงว่ามีใครครบ 4,500 วันหรือยัง) -----
    if watchdog_register_thread is not None:
        watchdog_register_thread("anniversary_check_loop", _anniversary_check_loop)
    else:
        threading.Thread(target=_anniversary_check_loop, daemon=True).start()

    print(f"[Anniversary Gift] ต่อเข้าไฟล์หลักสำเร็จ — เฝ้า {len(ACCOUNT_CREATED_TS)} บัญชี "
          f"เช็คทุก {ANNIVERSARY_CHECK_INTERVAL_SEC}s")
