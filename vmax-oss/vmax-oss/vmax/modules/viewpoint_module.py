# ==========================================
# VMAX Module: Viewpoint (จุดชมวิว / Scenic Viewpoint)
# ==========================================
# ไฟล์นี้เป็น "module เสมือน" แยกจากไฟล์หลัก ใช้แพทเทิร์นเดียวกับ
# vmax_module_anniversary_gift.py ทุกอย่าง: ไม่แก้/ไม่ทับโค้ดเดิมสักบรรทัด แค่ต่อ
# (attach) เข้าไปตอนที่ app/sio/central_store_* ถูกประกาศครบแล้ว (ก่อน sio.run())
#
# สเปค:
#   1) Viewpoint node: id, ชื่อ, map_id, ตำแหน่ง (x,y,z), รัศมี/เงื่อนไขปลดล็อก,
#      เส้นทางกล้อง (camera path) แยก 2 ชุด: exterior flyover / interior walkthrough
#   2) แหล่งเก็บวิดีโอ: ฝากไว้ที่คลังกลาง (CENTRAL_STORE pattern เดิม — ตาราง
#      central_artifacts + โฟลเดอร์ไฟล์) ไม่มีเซิร์ฟเวอร์เกมย่อยตัวใดตัวหนึ่ง
#      โดยเฉพาะ ใช้ kind="viewpoint_video"
#   3) activate: ผู้เล่นกดจุด → เช็คระยะ/ปลดล็อกแล้ว → คืน metadata + URL วิดีโอ
#      (exterior/interior) จากคลังกลาง
#   4) download: ผู้เล่นโหลดไฟล์เก็บในเครื่องได้ → ระบบจำว่าผู้เล่นคนไหนโหลดจุดไหน
#      ไปแล้ว (ไม่ต้องโหลดซ้ำ)
#   5) admin upload: แอดมิน/ทีมสร้างคอนเทนต์ อัปโหลดคลิปไว้แล้วเข้าคลังกลางต่อจุด
#
# ถ้าวันไหนอยากแก้โมดูลนี้ ไปแก้ที่ไฟล์ vmax_module_viewpoint.py ที่ถูกสร้างขึ้น
# ข้างๆ vmax_kernel_merged.py ได้เลย (ไฟล์หลักจะไม่เขียนทับไฟล์นี้ซ้ำถ้ามันมีอยู่แล้ว)

from __future__ import annotations

import json
import math
import os
import threading
import time
import uuid

# --- state ในหน่วยความจำ (ตัวไฟล์จริงอยู่ในคลังกลาง central_artifacts) ---
VIEWPOINT_NODES: dict[str, dict] = {}          # node_id -> node dict
VIEWPOINT_DOWNLOADS: dict[str, set] = {}       # uid -> set(node_id) ที่โหลดไปแล้ว
VIEWPOINT_UNLOCKED: dict[str, set] = {}        # uid -> set(node_id) ที่ปลดล็อกแล้ว

_ATTACHED = False
_LOCK = threading.Lock()

VIEWPOINT_CAMERA_KINDS = ("exterior_flyover", "interior_walkthrough")
VIEWPOINT_ACTIVATE_RADIUS_DEFAULT = 6.0  # หน่วยเดียวกับ world_engine grid


# ==========================================
# ฟังก์ชันภายใน / ไม่ผูกกับ Flask
# ==========================================
def _dist3(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _node_public(node: dict) -> dict:
    """ตัด field ภายใน (เช่น admin-only) ออกก่อนส่งให้ client"""
    return {
        "id": node["id"],
        "name": node["name"],
        "map_id": node["map_id"],
        "position": node["position"],
        "unlock_condition": node.get("unlock_condition"),
        "activate_radius": node.get("activate_radius", VIEWPOINT_ACTIVATE_RADIUS_DEFAULT),
        "has_video": {k: bool(node.get("videos", {}).get(k)) for k in VIEWPOINT_CAMERA_KINDS},
    }


def create_viewpoint_node(name: str, map_id: str, position, unlock_condition=None,
                           activate_radius: float = VIEWPOINT_ACTIVATE_RADIUS_DEFAULT) -> dict:
    node_id = f"vp_{uuid.uuid4().hex[:10]}"
    node = {
        "id": node_id,
        "name": name,
        "map_id": map_id,
        "position": list(position),           # [x, y, z]
        "unlock_condition": unlock_condition,  # เช่น {"kind": "level", "value": 5} หรือ None = ปลดล็อกทันที
        "activate_radius": activate_radius,
        "videos": {k: None for k in VIEWPOINT_CAMERA_KINDS},  # k -> central_artifacts id
        "created_ts": time.time(),
    }
    VIEWPOINT_NODES[node_id] = node
    return node


def _check_unlock(uid: str, node: dict) -> bool:
    if node["id"] in VIEWPOINT_UNLOCKED.get(uid, set()):
        return True
    cond = node.get("unlock_condition")
    if not cond:
        VIEWPOINT_UNLOCKED.setdefault(uid, set()).add(node["id"])
        return True
    return False  # เงื่อนไขที่ซับซ้อนกว่านี้ (level/quest) ต่อเข้ากับระบบเดิมทีหลังได้ที่นี่จุดเดียว


def _unlock_reason(node: dict) -> str:
    cond = node.get("unlock_condition")
    if not cond:
        return ""
    return f"ต้องผ่านเงื่อนไข: {cond}"


# ==========================================
# attach(): จุดต่อเข้ากับไฟล์หลัก
# ==========================================
def attach(main_globals: dict):
    """เรียกตอน app/sio/central_store_push/central_store_get/central_store_list/
    central_store_update/watchdog_register_thread ถูกประกาศครบแล้ว (ก่อน sio.run()
    ท้ายไฟล์) — ต่อโมดูลจุดชมวิวเข้ากับไฟล์หลักแบบไม่แก้/ไม่ทับโค้ดเดิมสักบรรทัด"""
    global _ATTACHED
    if _ATTACHED:
        return
    _ATTACHED = True

    app = main_globals.get("app")
    sio = main_globals.get("sio")
    VMAX_MODULES = main_globals.get("VMAX_MODULES")

    # คลังกลาง (CENTRAL_STORE) — ใช้ของเดิมทั้งหมด ไม่สร้างเซิร์ฟเวอร์ย่อยใหม่
    central_store_push = main_globals.get("central_store_push")
    central_store_get = main_globals.get("central_store_get")
    central_store_list = main_globals.get("central_store_list")
    central_store_update = main_globals.get("central_store_update")
    CENTRAL_STORE_DIR = main_globals.get("CENTRAL_STORE_DIR", "central_store_files")
    VIEWPOINT_VIDEO_DIR = os.path.join(CENTRAL_STORE_DIR, "viewpoint_videos")
    os.makedirs(VIEWPOINT_VIDEO_DIR, exist_ok=True)

    if central_store_push is None or central_store_get is None:
        print("[Viewpoint] ⚠️  ไม่พบ central_store_* ในไฟล์หลัก — ต้อง attach() หลังจากส่วน "
              "CENTRAL_STORE ถูกประกาศแล้วเท่านั้น (ข้ามการต่อโมดูลนี้)")
        _ATTACHED = False
        return

    def _current_uid(explicit_uid=None):
        if explicit_uid:
            return explicit_uid
        P = main_globals.get("P")
        if isinstance(P, dict):
            return P.get("uid")
        return None

    # --- 1) admin upload: อัปโหลดคลิปเข้าคลังกลาง ผูกกับ node + camera kind ---
    if app is not None:

        @app.route("/api/viewpoint/admin/upload", methods=["POST"])
        def api_viewpoint_admin_upload():
            from flask import request, jsonify
            from werkzeug.utils import secure_filename

            node_id = request.form.get("node_id")
            camera_kind = request.form.get("camera_kind")  # exterior_flyover / interior_walkthrough
            f = request.files.get("file")

            if camera_kind not in VIEWPOINT_CAMERA_KINDS:
                return jsonify({"st": "error", "msg": f"camera_kind ต้องเป็นหนึ่งใน {VIEWPOINT_CAMERA_KINDS}"}), 400
            node = VIEWPOINT_NODES.get(node_id)
            if not node:
                return jsonify({"st": "error", "msg": f"ไม่พบ viewpoint node '{node_id}'"}), 404
            if not f:
                return jsonify({"st": "error", "msg": "ไม่มีไฟล์แนบ (field 'file')"}), 400

            fname = f"{node_id}_{camera_kind}_{uuid.uuid4().hex[:8]}_{secure_filename(f.filename)}"
            fpath = os.path.join(VIEWPOINT_VIDEO_DIR, fname)
            f.save(fpath)

            artifact_id = central_store_push(
                kind="viewpoint_video",
                file_path=fpath,
                source_module="viewpoint",
                meta={"node_id": node_id, "camera_kind": camera_kind, "original_name": f.filename},
                status="done",
            )
            node["videos"][camera_kind] = artifact_id
            return jsonify({"st": "ok", "node_id": node_id, "camera_kind": camera_kind, "artifact_id": artifact_id})

        @app.route("/api/viewpoint/admin/create_node", methods=["POST"])
        def api_viewpoint_admin_create_node():
            from flask import request, jsonify
            data = request.get_json(force=True, silent=True) or {}
            name = data.get("name")
            map_id = data.get("map_id")
            position = data.get("position")
            if not name or not map_id or not position or len(position) != 3:
                return jsonify({"st": "error", "msg": "ต้องมี name, map_id, position [x,y,z]"}), 400
            node = create_viewpoint_node(
                name=name, map_id=map_id, position=position,
                unlock_condition=data.get("unlock_condition"),
                activate_radius=data.get("activate_radius", VIEWPOINT_ACTIVATE_RADIUS_DEFAULT),
            )
            return jsonify({"st": "ok", "node": _node_public(node)})

        # --- 2) รายการจุดในแมพ (ไม่รวมข้อมูลวิดีโอโดยตรง เอาแค่ has_video flag) ---
        @app.route("/api/viewpoint/list")
        def api_viewpoint_list():
            from flask import request, jsonify
            map_id = request.args.get("map_id")
            nodes = [_node_public(n) for n in VIEWPOINT_NODES.values() if not map_id or n["map_id"] == map_id]
            return jsonify({"st": "ok", "nodes": nodes})

        # --- 3) activate: ผู้เล่นกดจุด -> เช็คระยะ/ปลดล็อก -> metadata + URL วิดีโอ ---
        @app.route("/api/viewpoint/activate", methods=["POST"])
        def api_viewpoint_activate():
            from flask import request, jsonify
            data = request.get_json(force=True, silent=True) or {}
            uid = _current_uid(data.get("uid"))
            node_id = data.get("node_id")
            player_pos = data.get("position")  # [x,y,z] ตำแหน่งผู้เล่นตอนกด (client ส่งมาเช็คระยะฝั่ง server)

            node = VIEWPOINT_NODES.get(node_id)
            if not node:
                return jsonify({"st": "error", "msg": f"ไม่พบ viewpoint node '{node_id}'"}), 404
            if not uid:
                return jsonify({"st": "error", "msg": "ไม่พบ uid ผู้เล่น"}), 400

            if player_pos and len(player_pos) == 3:
                d = _dist3(player_pos, node["position"])
                radius = node.get("activate_radius", VIEWPOINT_ACTIVATE_RADIUS_DEFAULT)
                if d > radius:
                    return jsonify({"st": "error", "msg": f"อยู่ไกลจากจุดเกินไป ({d:.1f} > {radius})"}), 409

            if not _check_unlock(uid, node):
                return jsonify({"st": "error", "msg": "ยังไม่ปลดล็อกจุดนี้", "reason": _unlock_reason(node)}), 403

            videos_out = {}
            for kind in VIEWPOINT_CAMERA_KINDS:
                artifact_id = node["videos"].get(kind)
                if artifact_id:
                    videos_out[kind] = {
                        "artifact_id": artifact_id,
                        "stream_url": f"/api/viewpoint/stream/{artifact_id}",
                    }
                else:
                    videos_out[kind] = None

            if sio is not None:
                try:
                    sio.emit("viewpoint_activated", {"uid": uid, "node_id": node_id})
                except Exception:
                    pass

            return jsonify({"st": "ok", "node": _node_public(node), "videos": videos_out})

        # --- ให้ client เล่นวิดีโอ (stream) จากคลังกลางตรงๆ ผ่าน artifact id ---
        @app.route("/api/viewpoint/stream/<int:artifact_id>")
        def api_viewpoint_stream(artifact_id):
            from flask import jsonify, send_from_directory
            artifact = central_store_get(artifact_id)
            if not artifact or artifact["kind"] != "viewpoint_video":
                return jsonify({"st": "error", "msg": "ไม่พบวิดีโอนี้ในคลังกลาง"}), 404
            directory, fname = os.path.split(artifact["file_path"])
            return send_from_directory(directory, fname)

        # --- 4) download: โหลดไฟล์เก็บเครื่อง + จำว่าโหลดจุดไหนไปแล้ว ---
        @app.route("/api/viewpoint/download", methods=["POST"])
        def api_viewpoint_download():
            from flask import request, jsonify
            data = request.get_json(force=True, silent=True) or {}
            uid = _current_uid(data.get("uid"))
            node_id = data.get("node_id")
            camera_kind = data.get("camera_kind")

            node = VIEWPOINT_NODES.get(node_id)
            if not node:
                return jsonify({"st": "error", "msg": f"ไม่พบ viewpoint node '{node_id}'"}), 404
            if not uid:
                return jsonify({"st": "error", "msg": "ไม่พบ uid ผู้เล่น"}), 400
            if camera_kind not in VIEWPOINT_CAMERA_KINDS:
                return jsonify({"st": "error", "msg": f"camera_kind ต้องเป็นหนึ่งใน {VIEWPOINT_CAMERA_KINDS}"}), 400
            if node_id in VIEWPOINT_DOWNLOADS.get(uid, set()):
                return jsonify({"st": "ok", "already_downloaded": True,
                                "msg": "โหลดจุดนี้ไปแล้วก่อนหน้านี้ ไม่ต้องโหลดซ้ำ"})

            artifact_id = node["videos"].get(camera_kind)
            if not artifact_id:
                return jsonify({"st": "error", "msg": "ยังไม่มีวิดีโอของ camera_kind นี้ในจุดนี้"}), 404

            VIEWPOINT_DOWNLOADS.setdefault(uid, set()).add(node_id)
            return jsonify({
                "st": "ok", "already_downloaded": False,
                "download_url": f"/api/viewpoint/stream/{artifact_id}",
            })

        # --- สถานะการโหลด/ปลดล็อกของผู้เล่นคนหนึ่ง (ไว้ให้ client sync ตอนเปิดแอพ) ---
        @app.route("/api/viewpoint/player_status")
        def api_viewpoint_player_status():
            from flask import request, jsonify
            uid = _current_uid(request.args.get("uid"))
            if not uid:
                return jsonify({"st": "error", "msg": "ไม่พบ uid ผู้เล่น"}), 400
            return jsonify({
                "st": "ok", "uid": uid,
                "unlocked": sorted(VIEWPOINT_UNLOCKED.get(uid, set())),
                "downloaded": sorted(VIEWPOINT_DOWNLOADS.get(uid, set())),
            })

    # --- 5) ลงทะเบียนใน VMAX_MODULES (ตัวเดียวกับที่เห็นในเมนูโหลดโมดูล) ---
    if isinstance(VMAX_MODULES, dict):
        VMAX_MODULES["viewpoint"] = {
            "desc": "จุดชมวิว (Viewpoint) — ผู้เล่นกดจุดในแมพเพื่อดู/โหลดคลิป exterior "
                    "flyover และ interior walkthrough ที่แอดมินอัปโหลดไว้ล่วงหน้า วิดีโอฝาก "
                    "อยู่ในคลังกลาง (CENTRAL_STORE) เดียวกับระบบอื่น ไม่มีเซิร์ฟเวอร์ย่อย",
            "routes": ["/api/viewpoint/list", "/api/viewpoint/activate", "/api/viewpoint/stream/<id>",
                       "/api/viewpoint/download", "/api/viewpoint/player_status",
                       "/api/viewpoint/admin/upload", "/api/viewpoint/admin/create_node"],
        }

    print(f"[Viewpoint] ต่อโมดูลจุดชมวิวสำเร็จ — เก็บวิดีโอที่ {VIEWPOINT_VIDEO_DIR} "
          f"ผ่านคลังกลาง CENTRAL_STORE (kind='viewpoint_video')")
