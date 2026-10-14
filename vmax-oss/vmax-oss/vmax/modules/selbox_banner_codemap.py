# =====================================================================
# VMAX Module: Select-Box (กล่องเลือกของ) + Profile Banner (แบนเนอร์โปรไฟล์
# แบบ TikTok) + Code Map (แผนผังโค้ด)
# =====================================================================
# ไฟล์นี้เป็น "module เสมือน" แยกจากไฟล์หลัก ใช้แพทเทิร์นเดียวกับ Viewpoint /
# Anniversary Gift: ฝังเป็น base64 ในไฟล์หลัก -> self-extract -> attach(globals())
# ก่อน sio.run() — ไม่แก้/ไม่ทับโค้ดเดิมสักบรรทัด
#
#   1) Select-Box  : เปิดกล่อง "เลือก 1 จาก N" (เช่น สกินมีด 5 แบบ + เหรียญ 1,200)
#                    ใช้บัตรเปิดกล่องจาก INVENTORY เดิม, หักบัตรและแจกของแบบ atomic
#   2) Profile Banner : แบนเนอร์/อวาตาร์/ไบโอ/ไฮไลต์ ปรับแต่งได้แบบหน้าโปรไฟล์ TikTok
#                    มี API ให้แอปบันเทิงของคุณเรียกใช้ + widget ฝังได้
#   3) Code Map    : แผนผังโค้ด (treemap 2D/3D) ของไฟล์หลัก ดูได้เฉพาะแอดมิน
# =====================================================================
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import threading
import time
import uuid

_ATTACHED = False
_LOCK = threading.RLock()

# ---------------------------------------------------------------------
# 1) Select-Box
# ---------------------------------------------------------------------
SELECTBOX_STATE_FILE = "vmax_selectbox_state.json"

# ชื่อสกิน/ไอเทมด้านล่างเป็น "ตัวอย่าง" — แก้ได้ผ่าน POST /api/selectbox/admin/save
DEFAULT_BOXES = {
    "knife_pick_box": {
        "id": "knife_pick_box",
        "name": "กล่องเลือกสกินมีด",
        "desc": "เลือกได้ 1 อย่างต่อ 1 กล่อง",
        "ticket_item": "บัตรกล่องเลือกมีด",
        "ticket_cost": 1,
        "pick_total": 1,
        "enabled": True,
        "items": [
            {"id": "knife_1", "name": "มีดสกิน Prism Edge", "rarity": "epic", "grant_item": "สกินมีด Prism Edge", "qty": 1,
             "desc": "สกินมีดเอฟเฟกต์รุ้ง"},
            {"id": "knife_2", "name": "มีดสกิน Frost Blade", "rarity": "epic", "grant_item": "สกินมีด Frost Blade", "qty": 1,
             "desc": "สกินมีดน้ำแข็ง"},
            {"id": "knife_3", "name": "มีดสกิน Violet Fang", "rarity": "epic", "grant_item": "สกินมีด Violet Fang", "qty": 1,
             "desc": "สกินมีดม่วงเรืองแสง"},
            {"id": "knife_4", "name": "มีดสกิน Bone Reaper", "rarity": "legendary", "grant_item": "สกินมีด Bone Reaper", "qty": 1,
             "desc": "สกินมีดกระดูก"},
            {"id": "knife_5", "name": "มีดสกิน Thorn Saw", "rarity": "legendary", "grant_item": "สกินมีด Thorn Saw", "qty": 1,
             "desc": "สกินมีดฟันเลื่อย"},
            {"id": "coin_1200", "name": "เหรียญสามเหลี่ยม x1,200", "rarity": "rare", "grant_item": "เหรียญสามเหลี่ยม", "qty": 1200,
             "desc": "เหรียญสะสมจำนวน 1,200"},
        ],
    }
}
_BOXES: dict = {}
_BOX_HISTORY: dict = {}  # uid -> [ {ts, box_id, picks, boxes} ]  (เก็บล่าสุด 50)


def _sb_load():
    global _BOXES, _BOX_HISTORY
    try:
        with open(SELECTBOX_STATE_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        _BOXES = d.get("boxes") or {}
        _BOX_HISTORY = d.get("history") or {}
    except Exception:
        _BOXES = {}
        _BOX_HISTORY = {}
    for k, v in DEFAULT_BOXES.items():
        _BOXES.setdefault(k, json.loads(json.dumps(v)))


def _sb_save():
    tmp = SELECTBOX_STATE_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"boxes": _BOXES, "history": _BOX_HISTORY}, f, ensure_ascii=False)
        os.replace(tmp, SELECTBOX_STATE_FILE)
    except Exception as e:
        print(f"[SelectBox] save failed: {e}")


def _sb_validate_box(b: dict):
    """คืน (box_ที่ทำความสะอาดแล้ว, error)"""
    if not isinstance(b, dict):
        return None, "ต้องเป็น object"
    bid = str(b.get("id") or "").strip()
    if not re.fullmatch(r"[a-zA-Z0-9_\-]{2,40}", bid):
        return None, "id ต้องเป็น a-z 0-9 _ - ยาว 2-40 ตัว"
    items = b.get("items")
    if not isinstance(items, list) or not (1 <= len(items) <= 40):
        return None, "items ต้องมี 1-40 รายการ"
    clean_items, seen = [], set()
    for it in items:
        if not isinstance(it, dict):
            return None, "item ต้องเป็น object"
        iid = str(it.get("id") or "").strip()
        if not re.fullmatch(r"[a-zA-Z0-9_\-]{1,40}", iid) or iid in seen:
            return None, f"item id ไม่ถูกต้องหรือซ้ำ: {iid!r}"
        seen.add(iid)
        try:
            qty = int(it.get("qty", 1))
        except Exception:
            return None, "qty ต้องเป็นจำนวนเต็ม"
        if not (1 <= qty <= 10_000_000):
            return None, "qty ต้องอยู่ระหว่าง 1 ถึง 10,000,000"
        gi = str(it.get("grant_item") or "").strip()
        if not gi or len(gi) > 80:
            return None, f"grant_item ว่าง/ยาวเกินใน {iid}"
        clean_items.append({
            "id": iid, "name": str(it.get("name") or gi)[:80], "rarity": str(it.get("rarity") or "common")[:20],
            "grant_item": gi, "qty": qty, "desc": str(it.get("desc") or "")[:300],
        })
    try:
        cost = int(b.get("ticket_cost", 1))
        total = int(b.get("pick_total", 1))
    except Exception:
        return None, "ticket_cost / pick_total ต้องเป็นจำนวนเต็ม"
    if not (0 <= cost <= 1000) or not (1 <= total <= 50):
        return None, "ticket_cost 0-1000, pick_total 1-50"
    ticket = str(b.get("ticket_item") or "").strip()
    if cost > 0 and not ticket:
        return None, "ต้องระบุ ticket_item"
    return {
        "id": bid, "name": str(b.get("name") or bid)[:80], "desc": str(b.get("desc") or "")[:300],
        "ticket_item": ticket[:80], "ticket_cost": cost, "pick_total": total,
        "enabled": bool(b.get("enabled", True)), "items": clean_items,
    }, None


# ---------------------------------------------------------------------
# 2) Profile Banner
# ---------------------------------------------------------------------
PB_DIR = "profile_banners"
PB_DATA_FILE = os.path.join(PB_DIR, "profiles.json")
PB_MAX_BYTES = {"banner": 8 * 1024 * 1024, "avatar": 3 * 1024 * 1024, "highlight": 3 * 1024 * 1024}
PB_MAX_HIGHLIGHTS = 12
_PB: dict = {}


def _pb_load():
    global _PB
    os.makedirs(PB_DIR, exist_ok=True)
    try:
        with open(PB_DATA_FILE, "r", encoding="utf-8") as f:
            _PB = json.load(f)
    except Exception:
        _PB = {}


def _pb_save():
    tmp = PB_DATA_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_PB, f, ensure_ascii=False)
        os.replace(tmp, PB_DATA_FILE)
    except Exception as e:
        print(f"[ProfileBanner] save failed: {e}")


def _pb_default(uid: str) -> dict:
    return {
        "uid": uid, "display_name": uid[:30], "handle": "@" + re.sub(r"[^a-zA-Z0-9_.]", "", uid)[:24],
        "bio": "", "theme": "light",
        "banner": {"type": "gradient", "file": "", "color1": "#cfd8ff", "color2": "#ffe3f1",
                   "fade": 70, "blur": 0, "pos_y": 50, "brightness": 100},
        "avatar_file": "", "highlights": [],
    }


def _pb_get(uid: str) -> dict:
    p = _PB.get(uid)
    if not p:
        p = _pb_default(uid)
    return p


_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _pb_clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(v)))
    except Exception:
        return default


def _pb_sniff_image(head: bytes):
    """ตรวจชนิดไฟล์จาก magic bytes (ไม่เชื่อนามสกุล/Content-Type จากผู้ใช้; ไม่รับ SVG)"""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:3] == b"\xff\xd8\xff":
        return "jpg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def _pb_public(p: dict) -> dict:
    out = json.loads(json.dumps(p))
    b = out.get("banner", {})
    b["url"] = f"/profile_banners/files/{b['file']}" if b.get("file") else ""
    out["avatar_url"] = f"/profile_banners/files/{out['avatar_file']}" if out.get("avatar_file") else ""
    for h in out.get("highlights", []):
        h["cover_url"] = f"/profile_banners/files/{h['cover_file']}" if h.get("cover_file") else ""
    return out


def _pb_remove_file(name: str):
    if name and re.fullmatch(r"[a-f0-9]{12}_[a-z]+_[a-f0-9]{8}\.(png|jpg|gif|webp)", name):
        try:
            os.remove(os.path.join(PB_DIR, name))
        except OSError:
            pass


# ---------------------------------------------------------------------
# 3) Code Map
# ---------------------------------------------------------------------
_CM = {"state": "idle", "tree": None, "sig": None, "built_at": 0, "error": ""}
_SEC_RE = re.compile(r"^#\s*\[\s*(.{2,90}?)\s*\]\s*$")


def _cm_kind(node: ast.AST) -> str:
    if isinstance(node, ast.ClassDef):
        return "class"
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for d in node.decorator_list:
            try:
                s = ast.unparse(d)
            except Exception:
                s = ""
            if ".route(" in s or ".on(" in s or "on_event" in s:
                return "route"
        return "func"
    return "data"


def _cm_build(path: str):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            src = f.read()
        lines = src.split("\n")
        total = len(lines)
        # หัวข้อ section จากคอมเมนต์ "# [ ... ]"
        secs = [(0, "(ส่วนหัวไฟล์)")]
        for i, ln in enumerate(lines):
            m = _SEC_RE.match(ln)
            if m:
                secs.append((i + 1, m.group(1)))
        tree_ast = ast.parse(src)
        sec_nodes = [[] for _ in secs]
        import bisect
        starts = [s[0] for s in secs]
        for node in tree_ast.body:
            if not hasattr(node, "end_lineno"):
                continue
            lo, hi = node.lineno, node.end_lineno
            size = hi - lo + 1
            kind = None
            name = ""
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = _cm_kind(node)
                name = node.name
            elif isinstance(node, (ast.Assign, ast.AnnAssign)) and size >= 15:
                kind = "data"
                try:
                    t = node.targets[0] if isinstance(node, ast.Assign) else node.target
                    name = ast.unparse(t)[:60]
                except Exception:
                    name = "(assign)"
            elif isinstance(node, (ast.If, ast.Try, ast.With, ast.For)) and size >= 15:
                kind = "block"
                name = type(node).__name__.lower() + " block"
            if not kind:
                continue
            item = {"n": name, "v": size, "k": kind, "s": lo, "e": hi}
            if isinstance(node, ast.ClassDef):
                kids = []
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        kids.append({"n": sub.name, "v": sub.end_lineno - sub.lineno + 1, "k": "func",
                                     "s": sub.lineno, "e": sub.end_lineno})
                if len(kids) > 1:
                    item["c"] = kids
            idx = max(0, bisect.bisect_right(starts, lo) - 1)
            sec_nodes[idx].append(item)
        children = []
        for (start, title), nodes in zip(secs, sec_nodes):
            if not nodes:
                continue
            big = [n for n in nodes if n["v"] >= 4]
            small = [n for n in nodes if n["v"] < 4]
            if small:
                big.append({"n": f"(เล็ก ๆ อีก {len(small)} รายการ)", "v": sum(n["v"] for n in small),
                            "k": "small", "s": min(n["s"] for n in small), "e": max(n["e"] for n in small)})
            children.append({"n": title, "v": sum(n["v"] for n in nodes), "k": "section",
                             "s": start or nodes[0]["s"], "e": max(n["e"] for n in nodes), "c": big})
        root = {"n": os.path.basename(path), "v": sum(c["v"] for c in children), "k": "root",
                "s": 1, "e": total, "c": children, "total_lines": total}
        stats = {"lines": total, "sections": len(children),
                 "funcs": sum(1 for c in children for n in c["c"] if n["k"] in ("func", "route")),
                 "routes": sum(1 for c in children for n in c["c"] if n["k"] == "route"),
                 "classes": sum(1 for c in children for n in c["c"] if n["k"] == "class")}
        root["stats"] = stats
        with _LOCK:
            _CM.update(state="ready", tree=root, built_at=time.time(), error="")
    except Exception as e:
        with _LOCK:
            _CM.update(state="error", error=f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------
# attach
# ---------------------------------------------------------------------
def attach(main_globals: dict):
    global _ATTACHED
    if _ATTACHED:
        return
    _ATTACHED = True

    app = main_globals.get("app")
    require_auth = main_globals.get("require_auth")
    require_staff_rank = main_globals.get("require_staff_rank")
    INVENTORY = main_globals.get("INVENTORY")
    VMAX_MODULES = main_globals.get("VMAX_MODULES")
    audit_log = main_globals.get("audit_log") or (lambda *a, **k: None)
    main_file = main_globals.get("__file__") or os.path.abspath(__file__)

    if app is None or require_auth is None or require_staff_rank is None or INVENTORY is None:
        print("[SelectBox/Banner/CodeMap] ⚠️  ไม่พบ app/require_auth/require_staff_rank/INVENTORY — ข้ามการต่อโมดูลนี้")
        _ATTACHED = False
        return

    from flask import request, jsonify, send_from_directory

    _sb_load()
    _pb_load()

    def _uid():
        return str(getattr(request, "vmax_uid", "") or "")

    def _inv(uid):
        return INVENTORY.setdefault(uid, {})

    # ============ Select-Box routes ============
    def _box_public(b, uid=None):
        out = json.loads(json.dumps(b))
        if uid is not None:
            inv = INVENTORY.get(uid, {})
            out["ticket_owned"] = int(inv.get(b["ticket_item"], 0)) if b.get("ticket_item") else 0
            for it in out["items"]:
                it["owned"] = int(inv.get(it["grant_item"], 0))
        return out

    @app.route("/api/selectbox/list")
    @require_auth
    def api_selectbox_list():
        uid = _uid()
        with _LOCK:
            boxes = [_box_public(b, uid) for b in _BOXES.values() if b.get("enabled")]
        return jsonify({"st": "ok", "boxes": boxes})

    @app.route("/api/selectbox/<box_id>")
    @require_auth
    def api_selectbox_get(box_id):
        with _LOCK:
            b = _BOXES.get(box_id)
            if not b or not b.get("enabled"):
                return jsonify({"st": "error", "msg": "ไม่พบกล่องนี้"}), 404
            return jsonify({"st": "ok", "box": _box_public(b, _uid())})

    @app.route("/api/selectbox/open", methods=["POST"])
    @require_auth
    def api_selectbox_open():
        data = request.get_json(force=True, silent=True) or {}
        uid = _uid()
        box_id = str(data.get("box_id") or "")
        picks_in = data.get("picks")
        try:
            boxes = int(data.get("boxes", 1))
        except Exception:
            boxes = 0
        if not isinstance(picks_in, dict) or not (1 <= boxes <= 100):
            return jsonify({"st": "error", "msg": "ส่ง picks เป็น object และ boxes 1-100"}), 400
        with _LOCK:
            b = _BOXES.get(box_id)
            if not b or not b.get("enabled"):
                return jsonify({"st": "error", "msg": "ไม่พบกล่องนี้"}), 404
            by_id = {it["id"]: it for it in b["items"]}
            picks = {}
            for k, v in picks_in.items():
                if k not in by_id:
                    return jsonify({"st": "error", "msg": f"ไม่มีไอเทม {k} ในกล่อง"}), 400
                try:
                    q = int(v)
                except Exception:
                    return jsonify({"st": "error", "msg": "จำนวนต้องเป็นจำนวนเต็ม"}), 400
                if q < 0:
                    return jsonify({"st": "error", "msg": "จำนวนติดลบไม่ได้"}), 400
                if q:
                    picks[k] = q
            need = b["pick_total"] * boxes
            if sum(picks.values()) != need:
                return jsonify({"st": "error", "msg": f"ต้องเลือกให้ครบ {need} ชิ้นพอดี"}), 400
            inv = _inv(uid)
            cost = b["ticket_cost"] * boxes
            if cost > 0:
                have = int(inv.get(b["ticket_item"], 0))
                if have < cost:
                    return jsonify({"st": "error", "msg": f"บัตรไม่พอ ({have}/{cost})"}), 400
                inv[b["ticket_item"]] = have - cost
                if inv[b["ticket_item"]] <= 0:
                    inv.pop(b["ticket_item"], None)
            granted = []
            for k, q in picks.items():
                it = by_id[k]
                amount = it["qty"] * q
                inv[it["grant_item"]] = int(inv.get(it["grant_item"], 0)) + amount
                granted.append({"id": k, "name": it["name"], "item": it["grant_item"], "amount": amount})
            hist = _BOX_HISTORY.setdefault(uid, [])
            hist.append({"ts": int(time.time()), "box_id": box_id, "boxes": boxes, "picks": picks})
            del hist[:-50]
            _sb_save()
        audit_log("selectbox_open", uid=uid, box_id=box_id, boxes=boxes, picks=picks)
        return jsonify({"st": "ok", "granted": granted, "ticket_left": int(inv.get(b["ticket_item"], 0)) if b["ticket_item"] else 0})

    @app.route("/api/selectbox/history")
    @require_auth
    def api_selectbox_history():
        with _LOCK:
            return jsonify({"st": "ok", "history": list(reversed(_BOX_HISTORY.get(_uid(), [])))})

    @app.route("/api/selectbox/admin/save", methods=["POST"])
    @require_staff_rank("admin")
    def api_selectbox_admin_save():
        box, err = _sb_validate_box(request.get_json(force=True, silent=True))
        if err:
            return jsonify({"st": "error", "msg": err}), 400
        with _LOCK:
            _BOXES[box["id"]] = box
            _sb_save()
        audit_log("selectbox_admin_save", uid=_uid(), box_id=box["id"])
        return jsonify({"st": "ok", "box": box})

    @app.route("/api/selectbox/admin/grant_ticket", methods=["POST"])
    @require_staff_rank("admin")
    def api_selectbox_admin_grant():
        d = request.get_json(force=True, silent=True) or {}
        target = str(d.get("uid") or "").strip()
        try:
            count = int(d.get("count", 1))
        except Exception:
            count = 0
        with _LOCK:
            b = _BOXES.get(str(d.get("box_id") or ""))
            if not target or not b or not b["ticket_item"] or not (1 <= count <= 1000):
                return jsonify({"st": "error", "msg": "ต้องมี uid, box_id ที่มีบัตร และ count 1-1000"}), 400
            inv = _inv(target)
            inv[b["ticket_item"]] = int(inv.get(b["ticket_item"], 0)) + count
        audit_log("selectbox_admin_grant_ticket", uid=_uid(), target=target, box_id=b["id"], count=count)
        return jsonify({"st": "ok", "uid": target, "ticket_item": b["ticket_item"], "now": inv[b["ticket_item"]]})

    @app.route("/widgets/selectbox")
    def widget_selectbox():
        return SELECTBOX_WIDGET_HTML

    # ============ Profile Banner routes ============
    @app.route("/api/profile_banner/me", methods=["GET"])
    @require_auth
    def api_pb_me():
        with _LOCK:
            return jsonify({"st": "ok", "profile": _pb_public(_pb_get(_uid()))})

    @app.route("/api/profile_banner/me", methods=["POST"])
    @require_auth
    def api_pb_update():
        d = request.get_json(force=True, silent=True) or {}
        uid = _uid()
        with _LOCK:
            p = json.loads(json.dumps(_pb_get(uid)))
            if "display_name" in d:
                p["display_name"] = str(d["display_name"]).strip()[:40] or p["display_name"]
            if "handle" in d:
                h = re.sub(r"[^a-zA-Z0-9_.]", "", str(d["handle"]).lstrip("@"))[:24]
                if h:
                    p["handle"] = "@" + h
            if "bio" in d:
                p["bio"] = str(d["bio"])[:200]
            if d.get("theme") in ("light", "dark"):
                p["theme"] = d["theme"]
            nb = d.get("banner")
            if isinstance(nb, dict):
                b = p["banner"]
                if nb.get("type") in ("image", "gradient", "color"):
                    b["type"] = nb["type"]
                for ck in ("color1", "color2"):
                    if isinstance(nb.get(ck), str) and _HEX.match(nb[ck]):
                        b[ck] = nb[ck]
                b["fade"] = _pb_clamp(nb.get("fade", b["fade"]), 0, 100, b["fade"])
                b["blur"] = _pb_clamp(nb.get("blur", b["blur"]), 0, 20, b["blur"])
                b["pos_y"] = _pb_clamp(nb.get("pos_y", b["pos_y"]), 0, 100, b["pos_y"])
                b["brightness"] = _pb_clamp(nb.get("brightness", b.get("brightness", 100)), 30, 150, 100)
                if b["type"] == "image" and not b.get("file"):
                    b["type"] = "gradient"
            hl = d.get("highlights")
            if isinstance(hl, list):
                old = {h["id"]: h for h in p["highlights"]}
                new = []
                for h in hl[:PB_MAX_HIGHLIGHTS]:
                    if isinstance(h, dict) and h.get("id") in old:
                        o = dict(old[h["id"]])
                        o["title"] = str(h.get("title", o["title"]))[:16]
                        new.append(o)
                for gone in set(old) - {n["id"] for n in new}:
                    _pb_remove_file(old[gone].get("cover_file", ""))
                p["highlights"] = new
            _PB[uid] = p
            _pb_save()
            return jsonify({"st": "ok", "profile": _pb_public(p)})

    @app.route("/api/profile_banner/upload", methods=["POST"])
    @require_auth
    def api_pb_upload():
        uid = _uid()
        kind = request.form.get("kind", "")
        if kind not in PB_MAX_BYTES:
            return jsonify({"st": "error", "msg": "kind ต้องเป็น banner / avatar / highlight"}), 400
        f = request.files.get("file")
        if not f:
            return jsonify({"st": "error", "msg": "ไม่มีไฟล์ (field 'file')"}), 400
        raw = f.read(PB_MAX_BYTES[kind] + 1)
        if len(raw) > PB_MAX_BYTES[kind]:
            return jsonify({"st": "error", "msg": f"ไฟล์ใหญ่เกิน {PB_MAX_BYTES[kind] // (1024 * 1024)}MB"}), 413
        ext = _pb_sniff_image(raw[:16])
        if not ext:
            return jsonify({"st": "error", "msg": "รองรับเฉพาะ PNG / JPG / GIF / WebP"}), 400
        owner = hashlib.sha256(uid.encode("utf-8")).hexdigest()[:12]
        name = f"{owner}_{kind}_{uuid.uuid4().hex[:8]}.{ext}"
        with _LOCK:
            p = json.loads(json.dumps(_pb_get(uid)))
            if kind == "highlight" and len(p["highlights"]) >= PB_MAX_HIGHLIGHTS:
                return jsonify({"st": "error", "msg": f"ไฮไลต์ได้สูงสุด {PB_MAX_HIGHLIGHTS} อัน"}), 400
            os.makedirs(PB_DIR, exist_ok=True)
            with open(os.path.join(PB_DIR, name), "wb") as out:
                out.write(raw)
            if kind == "banner":
                _pb_remove_file(p["banner"].get("file", ""))
                p["banner"]["file"] = name
                p["banner"]["type"] = "image"
            elif kind == "avatar":
                _pb_remove_file(p.get("avatar_file", ""))
                p["avatar_file"] = name
            else:
                p["highlights"].append({"id": uuid.uuid4().hex[:8],
                                        "title": (request.form.get("title") or "ใหม่")[:16], "cover_file": name})
            _PB[uid] = p
            _pb_save()
            return jsonify({"st": "ok", "profile": _pb_public(p)})

    @app.route("/api/profile_banner/user/<target>")
    def api_pb_public(target):
        with _LOCK:
            if target not in _PB:
                return jsonify({"st": "error", "msg": "ผู้ใช้นี้ยังไม่ได้ตั้งแบนเนอร์"}), 404
            return jsonify({"st": "ok", "profile": _pb_public(_PB[target])})

    @app.route("/profile_banners/files/<path:name>")
    def pb_serve(name):
        if not re.fullmatch(r"[a-f0-9]{12}_[a-z]+_[a-f0-9]{8}\.(png|jpg|gif|webp)", name):
            return jsonify({"st": "error", "msg": "not found"}), 404
        resp = send_from_directory(os.path.abspath(PB_DIR), name, max_age=3600)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    @app.route("/widgets/profile-banner")
    def widget_profile_banner():
        return PROFILE_BANNER_WIDGET_HTML

    @app.route("/widgets/profile-banner/lib.js")
    def widget_profile_banner_lib():
        return PROFILE_BANNER_LIB_JS, 200, {"Content-Type": "application/javascript; charset=utf-8"}

    # ============ Code Map routes (admin only) ============
    @app.route("/api/codemap/tree")
    @require_staff_rank("admin")
    def api_codemap_tree():
        try:
            sig = (os.path.getmtime(main_file), os.path.getsize(main_file))
        except OSError:
            return jsonify({"st": "error", "msg": "อ่านไฟล์หลักไม่ได้"}), 500
        with _LOCK:
            stale = _CM["sig"] != sig
            if _CM["state"] in ("idle", "error") or (stale and _CM["state"] != "building"):
                _CM.update(state="building", sig=sig)
                threading.Thread(target=_cm_build, args=(main_file,), daemon=True).start()
            if _CM["state"] == "building":
                return jsonify({"st": "building"})
            if _CM["state"] == "error":
                return jsonify({"st": "error", "msg": _CM["error"]}), 500
            return jsonify({"st": "ok", "tree": _CM["tree"], "built_at": _CM["built_at"]})

    @app.route("/api/codemap/snippet")
    @require_staff_rank("admin")
    def api_codemap_snippet():
        try:
            s = max(1, int(request.args.get("start", 1)))
            e = max(s, int(request.args.get("end", s)))
        except Exception:
            return jsonify({"st": "error", "msg": "start/end ต้องเป็นตัวเลข"}), 400
        e = min(e, s + 299)  # ครั้งละไม่เกิน 300 บรรทัด
        out = []
        try:
            with open(main_file, "r", encoding="utf-8", errors="replace") as f:
                for i, ln in enumerate(f, 1):
                    if i < s:
                        continue
                    if i > e:
                        break
                    ln = ln.rstrip("\n")
                    out.append(ln if len(ln) <= 300 else ln[:300] + f" …[ตัด {len(ln) - 300} ตัวอักษร]")
        except OSError:
            return jsonify({"st": "error", "msg": "อ่านไฟล์หลักไม่ได้"}), 500
        audit_log("codemap_snippet", uid=_uid(), start=s, end=e)
        return jsonify({"st": "ok", "start": s, "end": s + len(out) - 1, "lines": out})

    @app.route("/widgets/code-map")
    def widget_code_map():
        return CODEMAP_WIDGET_HTML

    if isinstance(VMAX_MODULES, dict):
        VMAX_MODULES["select_box"] = {
            "desc": "กล่องเลือกของ (เลือก 1 จาก N) ใช้บัตรจาก INVENTORY เดิม หักบัตร+แจกของแบบ atomic",
            "routes": ["/widgets/selectbox", "/api/selectbox/list", "/api/selectbox/open",
                       "/api/selectbox/history", "/api/selectbox/admin/save", "/api/selectbox/admin/grant_ticket"],
        }
        VMAX_MODULES["profile_banner"] = {
            "desc": "แบนเนอร์/อวาตาร์/ไบโอ/ไฮไลต์โปรไฟล์ปรับแต่งได้แบบ TikTok สำหรับแอปบันเทิง",
            "routes": ["/widgets/profile-banner", "/api/profile_banner/me", "/api/profile_banner/upload",
                       "/profile_banners/files/<path:name>"],
        }
        VMAX_MODULES["code_map"] = {
            "desc": "แผนผังโค้ด (treemap 2D/3D) ของไฟล์หลัก — เฉพาะแอดมิน",
            "routes": ["/widgets/code-map", "/api/codemap/tree", "/api/codemap/snippet"],
        }
    print("[SelectBox/Banner/CodeMap] ต่อโมดูลเสร็จ — /widgets/selectbox /widgets/profile-banner /widgets/code-map")


# =====================================================================
# Widget assets (หน้าเต็มแบบ standalone — ฝังด้วย <iframe src="/widgets/..."> หรือเปิดตรง ๆ ได้)
# token อ่านจาก localStorage คีย์ 'vmax_token' (เหมือน widget อื่นในไฟล์หลัก)
# =====================================================================

_WIDGET_COMMON_JS = r"""
const TOKEN=()=>{try{return localStorage.getItem('vmax_token')||''}catch(e){return ''}};
async function api(path,opt){
  opt=opt||{}; opt.headers=Object.assign({},opt.headers||{});
  if(!(opt.body instanceof FormData)) opt.headers['Content-Type']='application/json';
  const t=TOKEN(); if(t) opt.headers['Authorization']='Bearer '+t;
  let r; try{ r=await fetch(path,opt); }catch(e){ return {st:'error',msg:'เชื่อมต่อเซิร์ฟเวอร์ไม่ได้'}; }
  let j={}; try{ j=await r.json(); }catch(e){ j={st:'error',msg:'เซิร์ฟเวอร์ตอบกลับผิดรูปแบบ'}; }
  j._status=r.status; return j;
}
function el(tag,attrs,kids){
  const e=document.createElement(tag);
  for(const k in (attrs||{})){
    if(k==='class') e.className=attrs[k];
    else if(k==='text') e.textContent=attrs[k];
    else if(k==='style') e.style.cssText=attrs[k];
    else if(k.startsWith('on')) e.addEventListener(k.slice(2),attrs[k]);
    else e.setAttribute(k,attrs[k]);
  }
  (kids||[]).forEach(c=>{ if(c!=null) e.appendChild(typeof c==='string'?document.createTextNode(c):c); });
  return e;
}
"""

# ---------------------------------------------------------------------
# Select-Box widget
# ---------------------------------------------------------------------
SELECTBOX_WIDGET_HTML = r"""<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>กล่องเลือกของ</title>
<style>
:root{--bg:#0d1b33;--panel:#14284a;--line:#5f7fb0;--accent:#ffd36a;--tile:#9a5a32;--tile2:#b0452f;--txt:#e8f0ff;--mut:#8fa6c9}
*{box-sizing:border-box}
body{margin:0;background:#07101f;color:var(--txt);font-family:system-ui,"Noto Sans Thai",sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:10px}
.dlg{width:min(860px,100%);background:linear-gradient(180deg,#16305a,#0d1b33);border:1px solid var(--line);box-shadow:0 0 0 1px #0a1424,0 12px 40px #000a}
.hd{display:flex;align-items:center;gap:8px;padding:10px 14px;border-bottom:1px solid var(--line);font-weight:700;font-size:18px}
.hd select{margin-left:auto;background:#0b1730;color:var(--txt);border:1px solid var(--line);padding:4px 8px}
.bd{display:grid;grid-template-columns:1fr 280px;gap:12px;padding:14px}
@media(max-width:640px){.bd{grid-template-columns:1fr}}
.hint{font-size:13px;color:var(--mut);margin-bottom:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(92px,1fr));gap:8px}
.tile{position:relative;aspect-ratio:1/1;background:var(--tile);border:2px solid #0006;cursor:pointer;display:flex;align-items:center;justify-content:center;text-align:center;font-size:12px;padding:6px;overflow:hidden;user-select:none}
.tile.coin{background:var(--tile2)}
.tile.sel{outline:3px solid #fff;outline-offset:-3px}
.tile .q{position:absolute;right:4px;bottom:3px;font-weight:700;color:var(--accent);text-shadow:0 1px 2px #000}
.tile .badge{position:absolute;left:4px;top:3px;font-size:10px;background:#000a;padding:1px 5px;border-radius:2px}
.side{background:#0a1630;border:1px solid var(--line);display:flex;flex-direction:column}
.side .t{padding:8px 10px;background:#3b5379;font-weight:700}
.side .b{padding:10px;flex:1;font-size:14px;line-height:1.5}
.side .own{color:var(--mut);border-bottom:1px solid #35507a;padding-bottom:6px;margin-bottom:8px}
.qty{padding:10px;border-top:1px solid var(--line);font-size:13px}
.qty .row{display:flex;align-items:center;gap:8px;margin-top:6px}
.qty button{width:30px;height:28px;background:#1b3560;color:var(--txt);border:1px solid var(--line);cursor:pointer;font-size:18px;line-height:1}
.qty input[type=range]{flex:1}
.ft{display:flex;align-items:center;gap:12px;padding:12px 14px;border-top:1px solid var(--line)}
.ft .cost{font-size:14px}
.ft .cost b{color:var(--accent)}
.ft .cost b.bad{color:#ff7b7b}
.ft button{margin-left:auto;padding:9px 34px;font-size:16px;font-weight:700;background:#2f7bff;color:#fff;border:0;cursor:pointer}
.ft button:disabled{background:#3a4a66;color:#8a97ad;cursor:not-allowed}
.msg{padding:8px 14px;font-size:14px;min-height:34px}
.msg.err{color:#ff8a8a}.msg.ok{color:#8affb0}
</style></head><body>
<div class="dlg">
  <div class="hd"><span id="title">เปิดกล่องเลือกของ</span><select id="boxsel" style="display:none"></select></div>
  <div class="bd">
    <div><div class="hint" id="hint">แตะไอเทมเพื่อเลือก</div><div class="grid" id="grid"></div></div>
    <div class="side">
      <div class="t" id="itname">—</div>
      <div class="b"><div class="own" id="itown"></div><div id="itdesc">เลือกไอเทมจากด้านซ้ายเพื่อดูรายละเอียด</div></div>
      <div class="qty"><div id="qlabel">จำนวนที่เลือก: 0/1</div>
        <div class="row"><button id="qm">−</button><input id="qr" type="range" min="0" max="1" value="0"><button id="qp">+</button></div></div>
    </div>
  </div>
  <div class="ft"><div class="cost" id="cost"></div><button id="ok" disabled>ยืนยัน</button></div>
  <div class="msg" id="msg"></div>
</div>
<script>
""" + _WIDGET_COMMON_JS + r"""
let boxes=[],box=null,picks={},selId=null;
const $=id=>document.getElementById(id);
const need=()=>box?box.pick_total:1;
const used=()=>Object.values(picks).reduce((a,b)=>a+b,0);
function setMsg(t,c){const m=$('msg');m.textContent=t||'';m.className='msg '+(c||'')}
async function load(keep){
  const j=await api('/api/selectbox/list');
  if(j.st!=='ok'){ setMsg(j._status===401?'ต้องล็อกอินก่อน (ไม่พบ vmax_token)':(j.msg||'โหลดไม่สำเร็จ'),'err'); return; }
  boxes=j.boxes;
  if(!boxes.length){ setMsg('ยังไม่มีกล่องที่เปิดใช้งาน','err'); return; }
  const want=keep&&box?box.id:(new URLSearchParams(location.search).get('box')||boxes[0].id);
  box=boxes.find(b=>b.id===want)||boxes[0];
  const sel=$('boxsel'); sel.innerHTML='';
  boxes.forEach(b=>sel.appendChild(el('option',{value:b.id,text:b.name})));
  sel.value=box.id; sel.style.display=boxes.length>1?'':'none';
  if(!keep){picks={};selId=null;}
  render();
}
function render(){
  $('title').textContent=box.name;
  $('hint').textContent=(box.desc?box.desc+' · ':'')+'แตะไอเทมเพื่อเลือก';
  const g=$('grid'); g.innerHTML='';
  box.items.forEach(it=>{
    const t=el('div',{class:'tile'+(it.id===selId?' sel':'')+(it.qty>1?' coin':''),onclick:()=>{selId=it.id;if(need()===1&&used()===0)picks[it.id]=0;render();}},
      [el('span',{text:it.name}),it.rarity?el('span',{class:'badge',text:it.rarity}):null,
       (picks[it.id]?el('span',{class:'q',text:'×'+picks[it.id]}):(it.qty>1?el('span',{class:'q',text:it.qty.toLocaleString()}):null))]);
    g.appendChild(t);
  });
  const it=box.items.find(x=>x.id===selId);
  $('itname').textContent=it?it.name:'—';
  $('itown').textContent=it?('ปัจจุบันมี: '+it.owned.toLocaleString()):'';
  $('itdesc').textContent=it?(it.desc||''):'เลือกไอเทมจากด้านซ้ายเพื่อดูรายละเอียด';
  const cur=it?(picks[it.id]||0):0, others=used()-cur, max=Math.max(0,need()-others);
  const r=$('qr'); r.max=max; r.value=cur; r.disabled=!it;
  $('qlabel').textContent='จำนวนที่เลือก: '+used()+'/'+need();
  const have=box.ticket_owned||0, cost=box.ticket_cost;
  $('cost').innerHTML=''; if(cost>0){
    $('cost').appendChild(document.createTextNode('ใช้ '+box.ticket_item+': '));
    $('cost').appendChild(el('b',{class:have>=cost?'':'bad',text:have+'/'+cost}));
  }
  $('ok').disabled=!(used()===need()&&have>=cost);
}
function setQty(v){ if(!selId)return; const o=used()-(picks[selId]||0); v=Math.max(0,Math.min(v,need()-o)); if(v)picks[selId]=v; else delete picks[selId]; render(); }
$('qr').addEventListener('input',e=>setQty(+e.target.value));
$('qm').onclick=()=>setQty((picks[selId]||0)-1);
$('qp').onclick=()=>setQty((picks[selId]||0)+1);
$('boxsel').onchange=e=>{box=boxes.find(b=>b.id===e.target.value);picks={};selId=null;render();};
$('ok').onclick=async()=>{
  $('ok').disabled=true; setMsg('กำลังเปิดกล่อง…');
  const j=await api('/api/selectbox/open',{method:'POST',body:JSON.stringify({box_id:box.id,boxes:1,picks:picks})});
  if(j.st==='ok'){
    setMsg('ได้รับ: '+j.granted.map(g=>g.name+' ×'+g.amount.toLocaleString()).join(', '),'ok');
    try{parent.postMessage({type:'vmax_selectbox_opened',granted:j.granted},'*')}catch(e){}
    picks={}; await load(true);
  } else { setMsg(j.msg||'เปิดกล่องไม่สำเร็จ','err'); render(); }
};
load(false);
</script></body></html>
"""

# ---------------------------------------------------------------------
# Profile banner: render library (ใช้ทั้งใน editor และแอปบันเทิงของคุณ)
# ---------------------------------------------------------------------
PROFILE_BANNER_LIB_JS = r"""
/* VmaxProfile.render(container, profile, opts)
   profile = ข้อมูลจาก GET /api/profile_banner/me หรือ /api/profile_banner/user/<uid> (field "profile")
   opts = { stats:{following,followers,likes}, editable:bool, onEdit:fn, onAddHighlight:fn } */
(function(){
  function mk(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e;}
  function fmt(n){n=+n||0;return n>=1e6?(n/1e6).toFixed(1)+'M':n>=1e3?(n/1e3).toFixed(1)+'K':String(n);}
  function render(root,p,opts){
    opts=opts||{}; var st=opts.stats||{following:0,followers:0,likes:0};
    var dark=p.theme==='dark', bgRGB=dark?'16,16,16':'255,255,255';
    var b=p.banner||{};
    root.innerHTML=''; root.className='vpf '+(dark?'vpf-dark':'vpf-light');
    var banner=mk('div','vpf-banner'), layer=mk('div','vpf-layer'), fade=mk('div','vpf-fade');
    layer.style.filter='blur('+(+b.blur||0)+'px) brightness('+((+b.brightness||100)/100)+')';
    if(b.type==='image'&&b.url){
      layer.style.backgroundImage='url("'+b.url.replace(/"/g,'%22')+'")';
      layer.style.backgroundPosition='center '+(+b.pos_y||0)+'%';
    }else if(b.type==='color'){ layer.style.background=b.color1||'#ddd'; }
    else{ layer.style.background='linear-gradient(135deg,'+(b.color1||'#cfd8ff')+','+(b.color2||'#ffe3f1')+')'; }
    fade.style.background='linear-gradient(to bottom,rgba('+bgRGB+',0) 25%,rgba('+bgRGB+','+((+b.fade||0)/100)+') 100%)';
    banner.appendChild(layer); banner.appendChild(fade); root.appendChild(banner);
    var body=mk('div','vpf-body'); root.appendChild(body);
    var av=mk('div','vpf-avatar'); if(p.avatar_url){av.style.backgroundImage='url("'+p.avatar_url+'")';} else {av.textContent=(p.display_name||'?').slice(0,1).toUpperCase();}
    body.appendChild(av);
    var nm=mk('div','vpf-name',p.display_name||''); body.appendChild(nm);
    body.appendChild(mk('div','vpf-handle',p.handle||''));
    var stats=mk('div','vpf-stats');
    [['following','Following'],['followers','Followers'],['likes','Likes']].forEach(function(s){
      var c=mk('div','vpf-stat'); c.appendChild(mk('b',null,fmt(st[s[0]]))); c.appendChild(mk('span',null,s[1])); stats.appendChild(c);
    });
    body.appendChild(stats);
    if(p.bio){ var bio=mk('div','vpf-bio'); bio.textContent=p.bio; body.appendChild(bio); }
    var hl=mk('div','vpf-hl');
    if(opts.editable){
      var add=mk('div','vpf-hl-item'); var ac=mk('div','vpf-hl-cover vpf-hl-add','+'); add.appendChild(ac); add.appendChild(mk('span',null,'ใหม่'));
      add.onclick=function(){opts.onAddHighlight&&opts.onAddHighlight();}; hl.appendChild(add);
    }
    (p.highlights||[]).forEach(function(h){
      var it=mk('div','vpf-hl-item'), c=mk('div','vpf-hl-cover');
      if(h.cover_url) c.style.backgroundImage='url("'+h.cover_url+'")';
      it.appendChild(c); it.appendChild(mk('span',null,h.title||'')); hl.appendChild(it);
    });
    body.appendChild(hl);
  }
  var css=''+
  '.vpf{position:relative;width:100%;max-width:430px;margin:0 auto;overflow:hidden;font-family:system-ui,"Noto Sans Thai",sans-serif}'+
  '.vpf-light{background:#fff;color:#111}.vpf-dark{background:#101010;color:#f2f2f2}'+
  '.vpf-banner{position:absolute;left:0;right:0;top:0;height:340px;overflow:hidden}'+
  '.vpf-layer{position:absolute;inset:-24px;background-size:cover}'+
  '.vpf-fade{position:absolute;inset:0}'+
  '.vpf-body{position:relative;padding:150px 16px 16px;min-height:420px}'+
  '.vpf-avatar{position:absolute;right:18px;top:112px;width:96px;height:96px;border-radius:50%;border:4px solid rgba(255,255,255,.85);background:#888 center/cover;display:flex;align-items:center;justify-content:center;font-size:36px;color:#fff;box-shadow:0 2px 10px #0003}'+
  '.vpf-name{font-size:26px;font-weight:800;padding-top:46px;padding-right:120px;word-break:break-word}'+
  '.vpf-handle{opacity:.6;margin-top:2px}'+
  '.vpf-stats{display:flex;gap:22px;margin:16px 0 12px}'+
  '.vpf-stat b{display:block;font-size:22px}.vpf-stat span{opacity:.55;font-size:14px}'+
  '.vpf-bio{white-space:pre-wrap;word-break:break-word;margin:8px 0 14px;line-height:1.45}'+
  '.vpf-hl{display:flex;gap:14px;overflow-x:auto;padding:6px 0 4px}'+
  '.vpf-hl-item{flex:0 0 74px;text-align:center;font-size:12px;cursor:pointer}'+
  '.vpf-hl-item span{display:block;margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}'+
  '.vpf-hl-cover{width:68px;height:68px;border-radius:22px;border:2px solid rgba(128,128,128,.35);background:rgba(128,128,128,.12) center/cover;margin:0 auto}'+
  '.vpf-hl-add{display:flex;align-items:center;justify-content:center;font-size:30px;opacity:.7}';
  var st=document.createElement('style'); st.textContent=css; document.head.appendChild(st);
  window.VmaxProfile={render:render};
})();
"""

PROFILE_BANNER_WIDGET_HTML = r"""<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ตั้งค่าแบนเนอร์โปรไฟล์</title>
<style>
body{margin:0;background:#eceef3;font-family:system-ui,"Noto Sans Thai",sans-serif;color:#1b1f2a}
.wrap{display:flex;flex-wrap:wrap;gap:20px;justify-content:center;padding:16px}
.prev{flex:0 0 min(430px,100%);border-radius:18px;overflow:hidden;box-shadow:0 8px 30px #0002;align-self:flex-start}
.ctl{flex:1 1 320px;max-width:520px;background:#fff;border-radius:14px;padding:16px;box-shadow:0 4px 18px #0001}
.ctl h3{margin:14px 0 6px;font-size:14px;color:#555}.ctl h3:first-child{margin-top:0}
label{display:block;font-size:13px;margin:8px 0 3px;color:#444}
input[type=text],textarea{width:100%;padding:8px;border:1px solid #cfd3dc;border-radius:8px;font:inherit;box-sizing:border-box}
textarea{resize:vertical;min-height:64px}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
button{padding:8px 14px;border:0;border-radius:8px;background:#2f6bff;color:#fff;font:inherit;cursor:pointer}
button.sec{background:#e4e8f2;color:#223}button.on{outline:2px solid #2f6bff}
button.del{background:#ff5a6a;padding:4px 10px}
input[type=range]{width:100%}
.hl-row{display:flex;gap:8px;align-items:center;margin:4px 0}.hl-row input{flex:1}
.msg{margin-top:10px;font-size:14px;min-height:20px}.err{color:#d33}.ok{color:#198754}
.swatches{display:flex;gap:6px;flex-wrap:wrap}.sw{width:30px;height:30px;border-radius:8px;border:2px solid #fff;box-shadow:0 0 0 1px #bbb;cursor:pointer}
</style></head><body>
<div class="wrap">
  <div class="prev"><div id="pv"></div></div>
  <div class="ctl">
    <h3>ข้อมูลโปรไฟล์</h3>
    <label>ชื่อที่แสดง</label><input type="text" id="f_name" maxlength="40">
    <label>แฮนเดิล</label><input type="text" id="f_handle" maxlength="25">
    <label>ไบโอ (สูงสุด 200 ตัวอักษร)</label><textarea id="f_bio" maxlength="200"></textarea>
    <div class="row" style="margin-top:8px"><span>ธีม:</span><button class="sec" id="th_l">สว่าง</button><button class="sec" id="th_d">มืด</button></div>
    <h3>แบนเนอร์ด้านบน</h3>
    <div class="row"><button class="sec" id="bt_img">รูปภาพ</button><button class="sec" id="bt_grad">ไล่สี</button><button class="sec" id="bt_col">สีเดียว</button></div>
    <div class="row" style="margin-top:8px"><button id="up_banner">อัปโหลดรูปแบนเนอร์</button><button class="sec" id="up_avatar">เปลี่ยนรูปโปรไฟล์</button></div>
    <div class="row" style="margin-top:8px"><label style="margin:0">สี 1</label><input type="color" id="c1"><label style="margin:0">สี 2</label><input type="color" id="c2"></div>
    <div class="swatches" id="sw" style="margin-top:8px"></div>
    <label>เฟดเข้าพื้นหลัง <span id="v_fade"></span></label><input type="range" id="r_fade" min="0" max="100">
    <label>ความเบลอ <span id="v_blur"></span></label><input type="range" id="r_blur" min="0" max="20">
    <label>ตำแหน่งรูปแนวตั้ง <span id="v_pos"></span></label><input type="range" id="r_pos" min="0" max="100">
    <label>ความสว่าง <span id="v_bri"></span></label><input type="range" id="r_bri" min="30" max="150">
    <h3>ไฮไลต์ (สูงสุด 12)</h3><div id="hls"></div>
    <div class="row" style="margin-top:12px"><button id="save">บันทึก</button></div>
    <div class="msg" id="msg"></div>
    <input type="file" id="file" accept="image/png,image/jpeg,image/gif,image/webp" style="display:none">
  </div>
</div>
<script src="/widgets/profile-banner/lib.js"></script>
<script>
""" + _WIDGET_COMMON_JS + r"""
const $=id=>document.getElementById(id);
let P=null, pendingKind=null;
const PRESETS=[['#cfd8ff','#ffe3f1'],['#ffd1dc','#fff2c9'],['#b8f2e6','#aed9e0'],['#2b2d42','#8d99ae'],['#ff9a9e','#fad0c4'],['#a18cd1','#fbc2eb'],['#0f2027','#2c5364'],['#f6d365','#fda085']];
function setMsg(t,c){$('msg').textContent=t||'';$('msg').className='msg '+(c||'');}
function draw(){
  VmaxProfile.render($('pv'),P,{editable:true,stats:window.VMAX_PROFILE_STATS,onAddHighlight:()=>pick('highlight')});
  const b=P.banner;
  $('f_name').value=P.display_name; $('f_handle').value=P.handle; $('f_bio').value=P.bio;
  $('c1').value=b.color1; $('c2').value=b.color2;
  [['fade','r_fade','v_fade'],['blur','r_blur','v_blur'],['pos_y','r_pos','v_pos'],['brightness','r_bri','v_bri']].forEach(a=>{$(a[1]).value=b[a[0]];$(a[2]).textContent=b[a[0]];});
  ['bt_img','bt_grad','bt_col'].forEach((id,i)=>$(id).classList.toggle('on',b.type===['image','gradient','color'][i]));
  $('th_l').classList.toggle('on',P.theme!=='dark'); $('th_d').classList.toggle('on',P.theme==='dark');
  const h=$('hls'); h.innerHTML='';
  P.highlights.forEach((x,i)=>{
    const inp=el('input',{type:'text',maxlength:'16',value:x.title,oninput:e=>{x.title=e.target.value;draw2();}});
    h.appendChild(el('div',{class:'hl-row'},[inp,el('button',{class:'del',text:'ลบ',onclick:()=>{P.highlights.splice(i,1);draw();}})]));
  });
}
function draw2(){ VmaxProfile.render($('pv'),P,{editable:true,stats:window.VMAX_PROFILE_STATS,onAddHighlight:()=>pick('highlight')}); }
function pick(kind){pendingKind=kind;$('file').value='';$('file').click();}
$('file').onchange=async e=>{
  const f=e.target.files[0]; if(!f||!pendingKind)return;
  const fd=new FormData(); fd.append('kind',pendingKind); fd.append('file',f); if(pendingKind==='highlight')fd.append('title','ใหม่');
  setMsg('กำลังอัปโหลด…');
  const j=await api('/api/profile_banner/upload',{method:'POST',body:fd});
  if(j.st!=='ok'){setMsg(j.msg||'อัปโหลดไม่สำเร็จ','err');return;}
  const q=j.profile;
  if(pendingKind==='banner'){P.banner.file=q.banner.file;P.banner.url=q.banner.url;P.banner.type='image';}
  else if(pendingKind==='avatar'){P.avatar_file=q.avatar_file;P.avatar_url=q.avatar_url;}
  else {P.highlights=q.highlights.map(h=>{const o=P.highlights.find(x=>x.id===h.id);return o?Object.assign(h,{title:o.title}):h;});}
  setMsg('อัปโหลดแล้ว — อย่าลืมกดบันทึกเพื่อเก็บการตั้งค่าอื่น ๆ','ok'); draw();
};
$('up_banner').onclick=()=>pick('banner'); $('up_avatar').onclick=()=>pick('avatar');
[['bt_img','image'],['bt_grad','gradient'],['bt_col','color']].forEach(a=>$(a[0]).onclick=()=>{
  if(a[1]==='image'&&!P.banner.file){setMsg('ยังไม่มีรูปแบนเนอร์ — กดอัปโหลดก่อน','err');return;} P.banner.type=a[1];draw();});
$('th_l').onclick=()=>{P.theme='light';draw();}; $('th_d').onclick=()=>{P.theme='dark';draw();};
$('f_name').oninput=e=>{P.display_name=e.target.value;draw2();};
$('f_handle').oninput=e=>{P.handle=e.target.value;draw2();};
$('f_bio').oninput=e=>{P.bio=e.target.value;draw2();};
$('c1').oninput=e=>{P.banner.color1=e.target.value;draw2();}; $('c2').oninput=e=>{P.banner.color2=e.target.value;draw2();};
[['r_fade','fade','v_fade'],['r_blur','blur','v_blur'],['r_pos','pos_y','v_pos'],['r_bri','brightness','v_bri']].forEach(a=>$(a[0]).oninput=e=>{P.banner[a[1]]=+e.target.value;$(a[2]).textContent=e.target.value;draw2();});
PRESETS.forEach(p=>$('sw').appendChild(el('div',{class:'sw',style:'background:linear-gradient(135deg,'+p[0]+','+p[1]+')',onclick:()=>{P.banner.color1=p[0];P.banner.color2=p[1];if(P.banner.type==='image'&&!P.banner.file)P.banner.type='gradient';if(P.banner.type==='image')P.banner.type='gradient';draw();}})));
$('save').onclick=async()=>{
  const body={display_name:P.display_name,handle:P.handle,bio:P.bio,theme:P.theme,banner:{type:P.banner.type,color1:P.banner.color1,color2:P.banner.color2,fade:P.banner.fade,blur:P.banner.blur,pos_y:P.banner.pos_y,brightness:P.banner.brightness},highlights:P.highlights.map(h=>({id:h.id,title:h.title}))};
  const j=await api('/api/profile_banner/me',{method:'POST',body:JSON.stringify(body)});
  if(j.st==='ok'){P=j.profile;draw();setMsg('บันทึกแล้ว','ok');try{parent.postMessage({type:'vmax_profile_saved',profile:P},'*')}catch(e){}}
  else setMsg(j.msg||'บันทึกไม่สำเร็จ','err');
};
(async()=>{
  const j=await api('/api/profile_banner/me');
  if(j.st!=='ok'){setMsg(j._status===401?'ต้องล็อกอินก่อน (ไม่พบ vmax_token)':(j.msg||'โหลดไม่สำเร็จ'),'err');return;}
  P=j.profile; draw();
})();
</script></body></html>
"""

# ---------------------------------------------------------------------
# Code Map widget
# ---------------------------------------------------------------------
CODEMAP_WIDGET_HTML = r"""<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>แผนผังโค้ด</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#0b0d12;color:#dfe6f5;font-family:system-ui,"Noto Sans Thai",sans-serif;height:100vh;display:flex;flex-direction:column}
.bar{display:flex;gap:8px;align-items:center;padding:8px 10px;background:#12151d;border-bottom:1px solid #232938;flex-wrap:wrap}
.bar input{background:#0b0d12;color:#dfe6f5;border:1px solid #2a3144;padding:6px 8px;border-radius:6px;min-width:160px}
.bar button{background:#1d2333;color:#dfe6f5;border:1px solid #2a3144;padding:6px 10px;border-radius:6px;cursor:pointer}
.bar button.on{background:#2f6bff;border-color:#2f6bff}
.crumb{font-size:13px;color:#8fa0c4}.crumb a{color:#9cc2ff;cursor:pointer;text-decoration:underline}
.main{flex:1;display:flex;min-height:0}
#cv{flex:1;min-width:0;display:block;cursor:grab;background:radial-gradient(circle at 50% 40%,#161b27,#0b0d12)}
.side{width:340px;max-width:44vw;border-left:1px solid #232938;background:#10131a;display:flex;flex-direction:column;min-height:0}
.side h4{margin:0;padding:10px 12px;border-bottom:1px solid #232938;font-size:14px}
.info{padding:10px 12px;font-size:13px;line-height:1.55;border-bottom:1px solid #232938}
.info b{color:#fff}
#code{flex:1;margin:0;overflow:auto;padding:8px 10px;font:12px/1.45 ui-monospace,Menlo,Consolas,monospace;white-space:pre;color:#cfe3ff}
#results{max-height:160px;overflow:auto;border-bottom:1px solid #232938}
#results div{padding:5px 12px;font-size:12px;cursor:pointer;border-bottom:1px solid #181d28}
#results div:hover{background:#1a2030}
.legend{display:flex;gap:10px;font-size:12px;color:#8fa0c4;flex-wrap:wrap}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:middle}
#tip{position:fixed;pointer-events:none;background:#000d;color:#fff;font-size:12px;padding:5px 8px;border-radius:6px;display:none;z-index:9;max-width:320px}
#status{padding:30px;text-align:center;color:#8fa0c4;position:absolute;left:0;top:60px;right:340px}
@media(max-width:760px){.main{flex-direction:column}.side{width:100%;max-width:none;height:40vh;border-left:0;border-top:1px solid #232938}#status{right:0}}
</style></head><body>
<div class="bar">
  <button id="b2d">2D</button><button id="b3d" class="on">3D</button><button id="bup">⬆ ขึ้นระดับบน</button>
  <input id="q" placeholder="ค้นหาชื่อฟังก์ชัน / ส่วน…">
  <span class="crumb" id="crumb"></span>
  <span class="legend" id="legend"></span>
</div>
<div class="main">
  <canvas id="cv"></canvas><div id="status">กำลังวิเคราะห์โค้ด…</div>
  <div class="side">
    <h4>รายละเอียด</h4>
    <div class="info" id="info">แตะบล็อกเพื่อดูรายละเอียด · ดับเบิลคลิกเพื่อเจาะลงไป · ลากเพื่อหมุน (โหมด 3D) · เลื่อนลูกกลิ้งเพื่อซูม</div>
    <div id="results"></div>
    <pre id="code"></pre>
  </div>
</div>
<div id="tip"></div>
<script>
""" + _WIDGET_COMMON_JS + r"""
const $=id=>document.getElementById(id);
const KC={func:'#5aa9ff',route:'#ffb347',class:'#c58cff',data:'#5ee0a0',block:'#aab3c5',small:'#5b6478',section:null};
const KN={func:'ฟังก์ชัน',route:'route/event',class:'คลาส',data:'ข้อมูล/ค่าคงที่',block:'บล็อกโค้ด',small:'รายการเล็ก',section:'ส่วน (section)',root:'ไฟล์'};
$('legend').innerHTML=['func','route','class','data'].map(k=>'<span><i style="background:'+KC[k]+'"></i>'+KN[k]+'</span>').join('');
let root=null,focus=null,sel=null,hover=null,mode3d=true,rot=-0.55,tilt=0.95,zoom=1,px=0,py=0,blocks=[],boxes=[];
const cv=$('cv'),ctx=cv.getContext('2d'),pk=document.createElement('canvas'),pctx=pk.getContext('2d',{willReadFrequently:true});
let CW=0,CH=0,DPR=1,dirty=true;

function squarify(items,x,y,w,h){
  const out=[]; const arr=items.filter(i=>i.v>0).sort((a,b)=>b.v-a.v);
  const total=arr.reduce((a,b)=>a+b.v,0); if(!total||w<=0||h<=0) return out;
  const scale=(w*h)/total; let i=0;
  const worst=(row,s)=>{let sm=0,mx=0,mn=Infinity;for(const r of row){const a=r.v*scale;sm+=a;if(a>mx)mx=a;if(a<mn)mn=a;}return Math.max(s*s*mx/(sm*sm),sm*sm/(s*s*mn));};
  while(i<arr.length){
    const side=Math.min(w,h); let row=[arr[i]]; let j=i+1;
    while(j<arr.length){const cand=row.concat([arr[j]]); if(worst(cand,side)<=worst(row,side)){row=cand;j++;}else break;}
    const area=row.reduce((a,r)=>a+r.v*scale,0);
    if(w>=h){const cw=area/h;let cy=y;for(const r of row){const rh=(r.v*scale)/cw;out.push({n:r,x:x,y:cy,w:cw,h:rh});cy+=rh;}x+=cw;w-=cw;}
    else{const rh=area/w;let cx=x;for(const r of row){const rw=(r.v*scale)/rh;out.push({n:r,x:cx,y:y,w:rw,h:rh});cx+=rw;}y+=rh;h-=rh;}
    i=j;
  }
  return out;
}
function hue(s){let h=0;for(let i=0;i<s.length;i++)h=(h*31+s.charCodeAt(i))>>>0;return h%360;}
function colorOf(n){return KC[n.k]||('hsl('+hue(n.n)+',45%,42%)');}

function build(){
  blocks=[]; if(!focus||!focus.c) return;
  const L1=squarify(focus.c,0,0,1000,700);
  let maxV=1; L1.forEach(r=>{(r.n.c||[r.n]).forEach(k=>{if(k.v>maxV)maxV=k.v;});});
  const zf=v=>6+70*Math.log10(1+v)/Math.log10(1+maxV);
  for(const r of L1){
    const b={n:r.n,x:r.x,y:r.y,w:r.w,h:r.h,z0:0,z1:mode3d?4:0,lvl:1,color:colorOf(r.n)};
    blocks.push(b);
    if(r.n.c&&r.w>12&&r.h>12){
      const pad=Math.min(3,r.w*0.05,r.h*0.05), head=Math.min(8,r.h*0.1);
      const inner=squarify(r.n.c,r.x+pad,r.y+pad+head,r.w-2*pad,r.h-2*pad-head);
      for(const k of inner){ if(k.w<1.2||k.h<1.2) continue;
        blocks.push({n:k.n,x:k.x,y:k.y,w:k.w,h:k.h,z0:b.z1,z1:b.z1+(mode3d?zf(k.n.v):0),lvl:2,color:colorOf(k.n)}); }
    }
  }
  dirty=true;
}
function proj(x,y,z){
  const cx=x-500,cy=y-350,ca=Math.cos(rot),sa=Math.sin(rot);
  const rx=cx*ca-cy*sa, ry=cx*sa+cy*ca, base=Math.min(CW/1000,CH/(mode3d?560:700))*0.95*zoom;
  return [CW/2+px+rx*base, CH*(mode3d?0.58:0.5)+py+(ry*Math.sin(tilt)-z*Math.cos(tilt))*base, ry];
}
function shade(hex,f){ // รองรับ #rrggbb และ hsl()
  const c=document.createElement('canvas').getContext('2d'); c.fillStyle=hex; let v=c.fillStyle;
  let r,g,b; if(v[0]==='#'){r=parseInt(v.slice(1,3),16);g=parseInt(v.slice(3,5),16);b=parseInt(v.slice(5,7),16);}
  else{const m=v.match(/\d+/g);r=+m[0];g=+m[1];b=+m[2];}
  return 'rgb('+Math.min(255,r*f|0)+','+Math.min(255,g*f|0)+','+Math.min(255,b*f|0)+')';
}
const shadeCache={}; function sh(c,f){const k=c+'|'+f;return shadeCache[k]||(shadeCache[k]=shade(c,f));}
function poly(c,pts,fill,stroke){c.beginPath();c.moveTo(pts[0][0],pts[0][1]);for(let i=1;i<pts.length;i++)c.lineTo(pts[i][0],pts[i][1]);c.closePath();c.fillStyle=fill;c.fill();if(stroke){c.strokeStyle=stroke;c.lineWidth=0.6;c.stroke();}}
function idColor(i){i=i+1;return 'rgb('+(i&255)+','+((i>>8)&255)+','+((i>>16)&255)+')';}

function draw(){
  if(!dirty) return; dirty=false;
  ctx.setTransform(DPR,0,0,DPR,0,0); ctx.clearRect(0,0,CW,CH);
  pctx.setTransform(DPR,0,0,DPR,0,0); pctx.clearRect(0,0,CW,CH);
  if(!blocks.length) return;
  const ca=Math.cos(rot),sa=Math.sin(rot);
  const order=blocks.map((b,i)=>({b,i,d:(b.lvl*1e6)+proj(b.x+b.w/2,b.y+b.h/2,0)[2]})).sort((a,c)=>a.d-c.d);
  for(const o of order){
    const b=o.b,i=o.i,id=idColor(i),isSel=(b.n===sel),isHov=(b.n===hover);
    const top=[[b.x,b.y],[b.x+b.w,b.y],[b.x+b.w,b.y+b.h],[b.x,b.y+b.h]];
    if(mode3d&&b.z1>b.z0){
      const sides=[[0,1,0,-1],[1,2,1,0],[2,3,0,1],[3,0,-1,0]];
      for(const s of sides){
        const ny=s[2]*sa+s[3]*ca; if(ny<=0.001) continue;
        const A=top[s[0]],B=top[s[1]];
        const pts=[proj(A[0],A[1],b.z0),proj(B[0],B[1],b.z0),proj(B[0],B[1],b.z1),proj(A[0],A[1],b.z1)];
        poly(ctx,pts,sh(b.color,0.55+0.2*ny));
        poly(pctx,pts,id);
      }
    }
    const tp=top.map(p=>proj(p[0],p[1],b.z1));
    poly(ctx,tp,isSel?'#fff':(isHov?sh(b.color,1.35):sh(b.color,b.lvl===1?0.8:1.0)),'rgba(0,0,0,.45)');
    poly(pctx,tp,id);
    if(!mode3d||tilt>1.15){ // ป้ายชื่อเฉพาะบล็อกที่ใหญ่พอ
      const w=Math.abs(tp[1][0]-tp[0][0]), h=Math.abs(tp[3][1]-tp[0][1]);
      if(w>70&&h>18&&Math.abs(rot)<0.01||(!mode3d&&w>70&&h>16)){
        ctx.save(); ctx.beginPath(); ctx.rect(Math.min(tp[0][0],tp[2][0]),Math.min(tp[0][1],tp[2][1]),w,h); ctx.clip();
        ctx.fillStyle=isSel?'#000':'#fff'; ctx.font=(b.lvl===1?'bold ':'')+'11px system-ui'; ctx.fillText(b.n.n,Math.min(tp[0][0],tp[2][0])+4,Math.min(tp[0][1],tp[2][1])+13); ctx.restore();
      }
    }
  }
}
function loop(){draw();requestAnimationFrame(loop);} 
function resize(){
  const r=cv.getBoundingClientRect(); DPR=Math.min(2,window.devicePixelRatio||1); CW=r.width; CH=r.height;
  cv.width=pk.width=Math.max(1,CW*DPR|0); cv.height=pk.height=Math.max(1,CH*DPR|0); dirty=true;
}
window.addEventListener('resize',resize);
function pickAt(mx,my){
  if(!blocks.length) return null;
  const d=pctx.getImageData(mx*DPR|0,my*DPR|0,1,1).data; if(d[3]<250) return null;
  const id=(d[0]|(d[1]<<8)|(d[2]<<16))-1; return blocks[id]?blocks[id].n:null;
}
let drag=null,moved=false;
cv.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,rot:rot,tilt:tilt,px:px,py:py,shift:e.shiftKey};moved=false;cv.setPointerCapture(e.pointerId);cv.style.cursor='grabbing';});
cv.addEventListener('pointermove',e=>{
  const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
  if(drag){const dx=e.clientX-drag.x,dy=e.clientY-drag.y; if(Math.abs(dx)+Math.abs(dy)>4)moved=true;
    if(moved){ if(mode3d&&!drag.shift){rot=drag.rot+dx*0.006;tilt=Math.max(0.25,Math.min(1.5,drag.tilt-dy*0.005));} else {px=drag.px+dx;py=drag.py+dy;} dirty=true; } return; }
  const n=pickAt(mx,my); if(n!==hover){hover=n;dirty=true;}
  const t=$('tip'); if(n){t.style.display='block';t.style.left=(e.clientX+14)+'px';t.style.top=(e.clientY+14)+'px';t.textContent=n.n+' · '+n.v.toLocaleString()+' บรรทัด'+(n.k?' · '+KN[n.k]:'');} else t.style.display='none';
});
cv.addEventListener('pointerup',e=>{
  cv.style.cursor='grab'; const wasDrag=moved; drag=null; if(wasDrag) return;
  const r=cv.getBoundingClientRect(); const n=pickAt(e.clientX-r.left,e.clientY-r.top); if(n) select(n);
});
cv.addEventListener('dblclick',e=>{const r=cv.getBoundingClientRect(); const n=pickAt(e.clientX-r.left,e.clientY-r.top); if(n&&n.c) goto(n);});
cv.addEventListener('pointerleave',()=>{hover=null;$('tip').style.display='none';dirty=true;});
cv.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(0.4,Math.min(8,zoom*(e.deltaY<0?1.12:0.89)));dirty=true;},{passive:false});

function path(n){const p=[];while(n){p.unshift(n);n=n._p;}return p;}
function crumb(){const c=$('crumb');c.innerHTML='';path(focus).forEach((n,i,a)=>{const s=document.createElement(i<a.length-1?'a':'span');s.textContent=(i?' › ':'')+n.n;if(i<a.length-1)s.onclick=()=>goto(n);c.appendChild(s);});}
function goto(n){focus=n;sel=null;zoom=1;px=py=0;crumb();build();$('code').textContent='';}
function select(n){
  sel=n; dirty=true; const pct=root?(n.v/root.v*100).toFixed(2):'';
  const i=$('info'); i.innerHTML='';
  const b=document.createElement('b'); b.textContent=n.n; i.appendChild(b);
  i.appendChild(document.createElement('br'));
  i.appendChild(document.createTextNode((KN[n.k]||n.k)+' · '+n.v.toLocaleString()+' บรรทัด ('+pct+'% ของไฟล์) · บรรทัด '+n.s.toLocaleString()+'–'+n.e.toLocaleString()));
  i.appendChild(document.createElement('br'));
  const btn=document.createElement('button'); btn.textContent='ดูโค้ด'; btn.style.cssText='margin-top:6px;background:#2f6bff;color:#fff;border:0;border-radius:6px;padding:5px 12px;cursor:pointer';
  btn.onclick=()=>loadCode(n.s,Math.min(n.e,n.s+119)); i.appendChild(btn);
  if(n.c){const b2=btn.cloneNode(true);b2.textContent='เจาะลงไป';b2.style.background='#1d2333';b2.style.marginLeft='6px';b2.onclick=()=>goto(n);i.appendChild(b2);}
}
async function loadCode(s,e){
  $('code').textContent='กำลังโหลด…'; const j=await api('/api/codemap/snippet?start='+s+'&end='+e);
  if(j.st!=='ok'){$('code').textContent=j.msg||'โหลดโค้ดไม่ได้';return;}
  $('code').textContent=j.lines.map((l,k)=>String(j.start+k).padStart(6)+'  '+l).join('\n');
}
function link(n,p){n._p=p;(n.c||[]).forEach(c=>link(c,n));}
$('b2d').onclick=()=>{mode3d=false;rot=0;tilt=Math.PI/2;px=py=0;$('b2d').classList.add('on');$('b3d').classList.remove('on');build();};
$('b3d').onclick=()=>{mode3d=true;rot=-0.55;tilt=0.95;px=py=0;$('b3d').classList.add('on');$('b2d').classList.remove('on');build();};
$('bup').onclick=()=>{if(focus&&focus._p)goto(focus._p);};
$('q').addEventListener('input',e=>{
  const q=e.target.value.trim().toLowerCase(), R=$('results'); R.innerHTML=''; if(q.length<2||!root) return;
  let found=[]; (function walk(n){ if(found.length>=40) return; if(n!==root&&n.n.toLowerCase().includes(q)) found.push(n); (n.c||[]).forEach(walk); })(root);
  found.forEach(n=>{const d=document.createElement('div');d.textContent=n.n+' · '+n.v+' บรรทัด';d.onclick=()=>{const parent=n._p&&n._p!==root?(n._p.k==='section'?n._p:n._p):root; goto(n.k==='section'?n:(n._p||root)); select(n); loadCode(n.s,Math.min(n.e,n.s+119));};R.appendChild(d);});
});
async function init(){
  const j=await api('/api/codemap/tree');
  if(j.st==='building'){ $('status').textContent='กำลังวิเคราะห์โค้ด… (ไฟล์ใหญ่ อาจใช้เวลาสักครู่)'; setTimeout(init,1500); return; }
  if(j.st!=='ok'){ $('status').textContent=(j._status===401?'ต้องล็อกอินก่อน (ไม่พบ vmax_token)':j._status===403?'หน้านี้สำหรับแอดมินเท่านั้น':(j.msg||'โหลดไม่สำเร็จ')); return; }
  $('status').style.display='none'; root=j.tree; link(root,null); focus=root; crumb();
  const s=root.stats; $('info').textContent='ไฟล์ '+root.n+' · '+s.lines.toLocaleString()+' บรรทัด · '+s.sections+' ส่วน · '+s.funcs.toLocaleString()+' ฟังก์ชัน ('+s.routes+' route) · '+s.classes+' คลาส';
  resize(); build();
}
resize(); requestAnimationFrame(loop); init();
</script></body></html>
"""
