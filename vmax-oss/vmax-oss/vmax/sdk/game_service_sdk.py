"""VMAX Game Service SDK for Python v1.0.0 (stdlib only)."""
import json
import math
import threading
import time
import urllib.error
import urllib.request

__version__ = "1.0.0"
__all__ = ["VMAXGameServiceClient", "VMAXGameSession", "VMAXGameServiceError"]


class VMAXGameServiceError(Exception):
    """Raised for any non-ok response. .status = HTTP status (0 = network), .code = service error code, .data = raw JSON."""

    def __init__(self, message, status=0, code=None, data=None):
        super().__init__(message)
        self.status, self.code, self.data = status, code, data


def _default_transport(method, url, headers, body, timeout):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    except (urllib.error.URLError, OSError) as e:
        raise VMAXGameServiceError("network error: %s" % e, 0, "network")
    try:
        return status, json.loads(raw.decode("utf-8")) if raw else None
    except ValueError:
        return status, None


class VMAXGameSession:
    def __init__(self, client, data):
        self.client = client
        self.id = data["session_id"]
        self.game_id = data.get("game_id", client.game_id)
        self.config = data.get("config") or {}
        self.effects = data.get("effects") or {}
        self.closed = False
        self._pos = {"x": 0.0, "y": 0.0, "aim": 0.0}
        self._listeners = {}
        self._lock = threading.RLock()        # เรียงลำดับคำสั่งที่เปลี่ยน state ไม่ให้ชนกัน
        self._seen_fx = set()
        self._auto = None
        self._auto_stop = threading.Event()

    # ---- events: effects | damage | dead | enemies | error | <fx type เช่น arc_flash, sparks, smoke_pop> ----
    def on(self, event, fn):
        self._listeners.setdefault(event, []).append(fn)
        return self

    def off(self, event, fn):
        self._listeners[event] = [f for f in self._listeners.get(event, []) if f is not fn]
        return self

    def _emit(self, event, value):
        for fn in list(self._listeners.get(event, [])):
            try:
                fn(value)
            except Exception as exc:  # listener พังต้องไม่ทำให้เกมล้ม
                print("[VMAXGameService] listener error:", repr(exc))

    def _path(self, suffix=""):
        from urllib.parse import quote
        base = "/api/game-service/%s/session/%s" % (quote(self.game_id, safe=""), quote(self.id, safe=""))
        return base + ("/" + suffix if suffix else "")

    def _apply(self, data):
        fx = data.get("effects")
        if not fx:
            return data
        self.effects = fx
        self._emit("effects", fx)
        if fx.get("hp_delta", 0) < 0:
            self._emit("damage", {"amount": -fx["hp_delta"], "hp": fx.get("hp")})
        if fx.get("dead"):
            self._emit("dead", fx)
        if fx.get("enemies"):
            self._emit("enemies", fx["enemies"])
        for f in fx.get("fx", []):
            if f.get("id") not in self._seen_fx:
                self._seen_fx.add(f.get("id"))
                if len(self._seen_fx) > 256:
                    self._seen_fx = set(list(self._seen_fx)[-64:])
                self._emit(f.get("type"), f)
        return data

    def _call(self, method, suffix="", body=None):
        if self.closed:
            raise VMAXGameServiceError("session closed", 0, "closed")
        with self._lock:
            try:
                data = self.client._request(method, self._path(suffix), body)
            except VMAXGameServiceError as exc:
                self._emit("error", exc)
                raise
            return self._apply(data)

    # ---- state ----
    def refresh(self):
        return self._call("GET")

    def sync(self, **state):
        """x, y, aim, hp, max_hp, glasses_equipped, mode, enemies=[{id,x,y,hp,alive}]"""
        for k in ("x", "y", "aim"):
            if state.get(k) is not None:
                self._pos[k] = float(state[k])
        return self._call("POST", "sync", state)

    def start_auto_sync(self, get_state, interval=0.25):
        """get_state() -> dict ของ kwargs ที่จะส่งเข้า sync(); รันใน thread แยกจนกว่าจะ stop/close"""
        self.stop_auto_sync()
        self._auto_stop.clear()

        def loop():
            while not self._auto_stop.wait(interval) and not self.closed:
                try:
                    self.sync(**(get_state() or {}))
                except VMAXGameServiceError:
                    pass  # ส่ง error event ไปแล้วใน _call
                except Exception as exc:
                    print("[VMAXGameService] auto-sync error:", repr(exc))
        self._auto = threading.Thread(target=loop, name="vmax-gs-autosync", daemon=True)
        self._auto.start()
        return self

    def stop_auto_sync(self):
        self._auto_stop.set()
        t, self._auto = self._auto, None
        if t is not None and t is not threading.current_thread():
            t.join(timeout=2.0)
        return self

    # ---- flashlight / smoke ----
    def set_light(self, on=None, preset=None):
        body = {}
        if on is not None:
            body["on"] = bool(on)
        if preset is not None:
            body["preset"] = preset
        return self._call("POST", "light", body)

    def toggle_light(self):
        return self.set_light()

    def set_preset(self, preset):
        return self.set_light(preset=preset)

    def cycle_preset(self):
        ids = [p["id"] for p in self.config.get("presets", [])]
        if not ids:
            return None
        cur = (self.effects.get("light") or {}).get("preset")
        return self.set_preset(ids[(ids.index(cur) + 1) % len(ids)] if cur in ids else ids[0])

    def throw_smoke(self, target_x=None, target_y=None):
        body = {} if target_x is None else {"target_x": target_x, "target_y": target_y}
        return self._call("POST", "smoke", body)

    def shot(self, heavy_armor=False):
        """-> {miss, reason, beacon, beacon_bonus_damage} — เรียกก่อนคำนวณการยิงของเกม"""
        return self._call("POST", "shot", {"heavy_armor": bool(heavy_armor)})["shot"]

    # ---- breaker ----
    def nearest_breaker(self, x=None, y=None, max_dist=None):
        px = self._pos["x"] if x is None else x
        py = self._pos["y"] if y is None else y
        best, bd = None, math.inf
        for b in self.effects.get("breakers", []):
            d = math.hypot(b["x"] - px, b["y"] - py)
            if d < bd:
                best, bd = b, d
        return best if best is not None and (max_dist is None or bd <= max_dist) else None

    def _bid(self, breaker_id):
        if breaker_id:
            return breaker_id
        b = self.nearest_breaker()
        if b is None:
            raise VMAXGameServiceError("ไม่มีตู้เบรกเกอร์ใน session นี้", 0, "no_breaker")
        return b["id"]

    def shoot_breaker(self, breaker_id=None, hit_zone="auto"):
        """-> result {outcome: miss|jam|jam_no_arc|arc_fault|already_destroyed, breaker_id, ...}"""
        return self._call("POST", "breaker/shoot", {"breaker_id": self._bid(breaker_id), "hit_zone": hit_zone})["result"]

    def switch_breaker(self, breaker_id=None):
        return self._call("POST", "breaker/switch", {"breaker_id": self._bid(breaker_id)})

    def repair_breaker(self, breaker_id=None, wait=False):
        """เริ่มซ่อม (เซิร์ฟเวอร์นับ 5 วิ). wait=True = บล็อกรอแล้วเรียกซ่อมเสร็จให้ (อย่าใช้ใน game loop หลัก — ใช้ thread แยก)"""
        bid = self._bid(breaker_id)
        d = self._call("POST", "breaker/repair", {"breaker_id": bid})
        if wait and (d.get("repair") or {}).get("started"):
            time.sleep(float(d["repair"].get("seconds", 5)) + 0.25)
            d = self._call("POST", "breaker/repair", {"breaker_id": bid})
        return d

    def close(self):
        if self.closed:
            return
        self.stop_auto_sync()
        self.closed = True
        try:
            self.client._request("DELETE", self._path())
        except VMAXGameServiceError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class VMAXGameServiceClient:
    def __init__(self, base_url, game_id, token=None, token_provider=None, timeout=8.0, transport=None):
        """token = JWT ของผู้เล่น | token_provider = callable คืน token ล่าสุด
        transport(method, url, headers, body, timeout) -> (status, json) — override ได้ (เทส/proxy/async)"""
        self.base_url = str(base_url or "").rstrip("/")
        self.game_id = str(game_id).strip().lower()
        self.token, self.token_provider = token, token_provider
        self.timeout = timeout
        self._transport = transport or _default_transport

    def _request(self, method, path, body=None):
        tok = self.token_provider() if self.token_provider else self.token
        headers = {"Authorization": "Bearer %s" % (tok or ""), "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        status, data = self._transport(method, self.base_url + path, headers, body, self.timeout)
        if status >= 400 or not isinstance(data, dict) or data.get("st") != "ok":
            d = data if isinstance(data, dict) else {}
            raise VMAXGameServiceError(d.get("msg") or "HTTP %s" % status, status, d.get("code"), data)
        return data

    def list_games(self):
        return self._request("GET", "/api/game-service/games")["games"]

    def spec(self):
        return self._request("GET", "/api/game-service/spec")

    def create_session(self, **opts):
        """x, y, hp, max_hp, aim, mode, glasses_equipped, zones=[{id,name,x,y,w,h}], breakers=[{id,x,y,zone}]"""
        from urllib.parse import quote
        d = self._request("POST", "/api/game-service/%s/session" % quote(self.game_id, safe=""), opts)
        return VMAXGameSession(self, d)
