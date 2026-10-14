# ==========================================
# [ 1a2. Cross-Engine Bridge Client Templates ]
# These are the client-side counterparts to /api/bridge/* (defined later, in
# section [2F0]). Each one is a real, working polling client for a common
# language/runtime — same protocol as VMAXBridge.cs, just written natively
# per-language so you don't need Unity specifically to talk to this game.
# For any language NOT listed here, /api/bridge/client/<lang> falls back to
# asking your own local AI to write one on the spot (see api_bridge_client()
# near the bridge routes) — that's the honest way to cover "every language",
# since nobody can hand-write correct native clients for every language that
# exists ahead of time; the common ones are pre-written and verified-by-eye,
# anything else is generated fresh from the same protocol description.
# ==========================================

BRIDGE_PROTOCOL_DESC = (
    "REST bridge protocol served by this game at http://127.0.0.1:5000 :\n"
    "  GET  /api/bridge/pull?since=<int>  -> {st, events:[{id, ts, source, type, data}]}\n"
    "  POST /api/bridge/push  body: {source, type, data}  -> {st, event}\n"
    "  GET  /api/bridge/state              -> {<shared key/value>}\n"
    "  POST /api/bridge/state body: {<key>: <value>, ...} -> merges into shared state\n"
    "\n"
    "  Special event type for cross-game map sharing: push type=\"map_object_position\"\n"
    "  with data={id, x, y, label?} to report a position from your game/engine — it\n"
    "  shows up on this game's /map page as a separately-colored point tagged with your\n"
    "  'source' name, alongside this game's own objects. Re-push periodically (e.g. every\n"
    "  0.5-2s); entries expire after ~20s of no update (BRIDGE_MAP_OBJECT_TTL_SEC).\n"
)

# --- Unity / C# (this is VMAXBridge.cs, embedded verbatim) -------------------
UNITY_BRIDGE_CS = r'''// VMAXBridge.cs — วางใน Assets/Scripts/ ของโปรเจกต์ Unity คุณ
using System;
using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

[Serializable]
public class BridgeEvent {
    public int id; public double ts; public string source; public string type; public string data;
}
[Serializable]
public class BridgeEventList { public string st; public BridgeEvent[] events; }

public class VMAXBridge : MonoBehaviour {
    public string baseUrl = "http://127.0.0.1:5000";
    public float pollIntervalSeconds = 2f;
    private int lastEventId = 0;

    void Start() { StartCoroutine(PollLoop()); }

    IEnumerator PollLoop() {
        while (true) {
            yield return StartCoroutine(PullEvents());
            yield return new WaitForSeconds(pollIntervalSeconds);
        }
    }

    IEnumerator PullEvents() {
        using (UnityWebRequest req = UnityWebRequest.Get($"{baseUrl}/api/bridge/pull?since={lastEventId}")) {
            yield return req.SendWebRequest();
            if (req.result != UnityWebRequest.Result.Success) {
                Debug.LogWarning($"[VMAXBridge] pull failed: {req.error}");
                yield break;
            }
            var list = JsonUtility.FromJson<BridgeEventList>(req.downloadHandler.text);
            if (list?.events == null) yield break;
            foreach (var ev in list.events) {
                HandleEvent(ev);
                if (ev.id > lastEventId) lastEventId = ev.id;
            }
        }
    }

    void HandleEvent(BridgeEvent ev) {
        switch (ev.type) {
            case "player_leveled_up":
                Debug.Log($"[VMAXBridge] python side leveled up: {ev.data}");
                break;
            default:
                Debug.Log($"[VMAXBridge] unhandled event: {ev.type} data:{ev.data}");
                break;
        }
    }

    public IEnumerator PushEvent(string type, string jsonData) {
        string body = $"{{\"source\":\"unity\",\"type\":\"{type}\",\"data\":{jsonData}}}";
        using (UnityWebRequest req = new UnityWebRequest($"{baseUrl}/api/bridge/push", "POST")) {
            req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(body));
            req.downloadHandler = new DownloadHandlerBuffer();
            req.SetRequestHeader("Content-Type", "application/json");
            yield return req.SendWebRequest();
            if (req.result != UnityWebRequest.Result.Success)
                Debug.LogWarning($"[VMAXBridge] push failed: {req.error}");
        }
    }

    // เรียกทุกครั้งที่ตำแหน่ง object ในเกม Unity ของคุณขยับ (เช่นทุกเฟรม/ทุก 0.5 วิ)
    // เพื่อให้หน้า /map ของอีกเกม (Python/Flask ตัวนี้) ดึงไปวาดจุดของ Unity แยกสี
    // ให้เห็นชัดว่าเป็นคนละเกมกัน — objId ต้องคงที่ต่อวัตถุนั้นๆ (เช่น instance id)
    public IEnumerator PushMapObjectPosition(string objId, float x, float y, string label = null) {
        string labelJson = label != null ? $",\"label\":\"{label}\"" : "";
        string data = $"{{\"id\":\"{objId}\",\"x\":{x},\"y\":{y}{labelJson}}}";
        yield return PushEvent("map_object_position", data);
    }
}
'''

# --- Python (a second, separate Python process talking to this game) --------
PYTHON_BRIDGE_CLIENT = r'''# vmax_bridge_client.py — a SEPARATE Python process, not this game.
import requests, time

BASE_URL = "http://127.0.0.1:5000"
last_id = 0

def handle_event(ev):
    if ev["type"] == "player_leveled_up":
        print(f"[bridge] python side leveled up: {ev['data']}")
    else:
        print(f"[bridge] unhandled event: {ev['type']} data:{ev['data']}")

def push_event(ev_type, data):
    requests.post(f"{BASE_URL}/api/bridge/push",
                  json={"source": "python_client", "type": ev_type, "data": data})

def push_map_object_position(obj_id, x, y, label=None):
    """เรียกทุกครั้งที่ object ในเกม/โปรแกรมฝั่งนี้ขยับ ให้หน้า /map ของอีกฝั่ง
    ดึงไปวาดจุดแยกสีตาม source ('python_client') ว่าเป็นคนละเกมกัน"""
    data = {"id": obj_id, "x": x, "y": y}
    if label:
        data["label"] = label
    push_event("map_object_position", data)

if __name__ == "__main__":
    while True:
        r = requests.get(f"{BASE_URL}/api/bridge/pull", params={"since": last_id}, timeout=10)
        for ev in r.json().get("events", []):
            handle_event(ev)
            last_id = max(last_id, ev["id"])
        time.sleep(2)
'''

# --- Competitive netcode reference client (Python + python-socketio) --------
# นี่คนละอันกับ PYTHON_BRIDGE_CLIENT ด้านบน (อันนั้นคือ event bridge ทั่วไป
# ผ่าน HTTP polling ทุก 2 วิ ซึ่ง "ช้าเกินไป" สำหรับควบคุมตัวละครแบบเรียลไทม์)
# ตัวนี้ต่อผ่าน SocketIO เพื่อ latency ต่ำ และสาธิต pattern ที่ถูกต้องของ
# client-side prediction + server reconciliation ที่ตรงกับ /api/physics/*
# และ event 'player_input' / 'physics_sync' / 'player_shoot' ฝั่ง server —
# ผมทดสอบ logic นี้ได้จริงเพราะเป็น Python เหมือนฝั่ง server ส่วนภาษาอื่น
# (C#/Unity, JS ฯลฯ) ให้ port pattern เดียวกันนี้ ผมไม่ auto-gen ให้เพราะ
# hit-registration ที่ผิดพลาดแม้เล็กน้อยจะทำให้เกมโกงได้/รู้สึกกระตุก และ
# ไม่มีทางเทสต์ความถูกต้องได้จากตรงนี้โดยไม่มี client จริงรัน
PYTHON_PREDICTION_CLIENT = r'''# vmax_prediction_client.py — ตัวอย่าง client-side prediction + reconciliation
# pip install python-socketio[client]
import socketio, time, threading

sio = socketio.Client()
BASE_URL = "http://127.0.0.1:5000"

seq = 0
pending_inputs = {}          # seq -> (dx, dy, dt)  ยังไม่ถูก server ack
local_x, local_y = 0.0, 0.0  # ตำแหน่งที่ "ทำนายไว้ล่วงหน้า" ฝั่ง client

@sio.event
def connect():
    print("[client] connected, sid =", sio.sid)

@sio.on('physics_sync')
def on_sync(data):
    """server ส่งตำแหน่ง authoritative + ack_seq มา — snap แล้ว replay input
    ที่ยังไม่ถูก ack เพื่อไม่ให้ตัวละครกระตุกตอนแก้ตำแหน่ง (reconciliation)"""
    global local_x, local_y
    self_state = data.get('self')
    if not self_state:
        return
    ack_seq = self_state['ack_seq']
    local_x, local_y = self_state['x'], self_state['y']   # 1) snap ไปตำแหน่งจริงจาก server
    for s in list(pending_inputs):                        # 2) เอา input เก่าที่ ack แล้วทิ้ง
        if s <= ack_seq:
            pending_inputs.pop(s)
    for s in sorted(pending_inputs):                       # 3) replay input ที่เหลือ (ยังไม่ ack)
        dx, dy, dt = pending_inputs[s]
        _apply_move(dx, dy, dt)
    # ตำแหน่งอื่นๆ (pawns/vehicles/projectiles) ใน data ใช้ interpolate วาดผลได้เลย

def _apply_move(dx, dy, dt):
    global local_x, local_y
    import math
    norm = math.hypot(dx, dy) or 1.0
    local_x += (dx / norm) * 6.0 * dt   # ต้องตรงกับ MOVE_SPEED ฝั่ง server เป๊ะๆ
    local_y += (dy / norm) * 6.0 * dt

def send_input(dx, dy, dt):
    """เรียกทุกเฟรม — ทำนายทันที (prediction) แล้วค่อยส่งให้ server ยืนยันทีหลัง"""
    global seq
    seq += 1
    pending_inputs[seq] = (dx, dy, dt)
    _apply_move(dx, dy, dt)   # ขยับ local ทันที ไม่รอ server ตอบ (นี่คือ "prediction")
    sio.emit('player_input', {"seq": seq, "dx": dx, "dy": dy, "dt": dt})

def shoot(target_sid, aim_x, aim_y, dmg=25):
    """ส่ง client_time ไปด้วย — server จะย้อนเวลาไปดูตำแหน่งเป้าหมาย ณ ตอนนี้
    (lag compensation) แทนที่จะเช็คจากตำแหน่งปัจจุบันของเป้าหมาย"""
    sio.emit('player_shoot', {"target_sid": target_sid, "aim_x": aim_x, "aim_y": aim_y,
                              "dmg": dmg, "client_time": time.time()})

@sio.on('shoot_result')
def on_shoot_result(data):
    print("[client] shoot result:", data)

if __name__ == "__main__":
    sio.connect(BASE_URL)
    # ตัวอย่าง: ส่ง input ทุกเฟรมที่ ~60Hz (เกมจริงเรียก send_input จาก game loop)
    def game_loop():
        while True:
            send_input(dx=1.0, dy=0.0, dt=1/60)
            time.sleep(1/60)
    threading.Thread(target=game_loop, daemon=True).start()
    sio.wait()
'''

# --- Client-side integrity scanner (รันบนเครื่องผู้เล่น ไม่ใช่ server) --------
# ตรวจ process/connection ต้องสงสัยบนเครื่องผู้เล่นเอง แล้วส่งผลเข้า
# /api/anticheat/report — server มองไม่เห็นสิ่งเหล่านี้ได้เองเพราะเป็นข้อมูล
# บนเครื่อง client ล้วนๆ จึงต้องมีตัวสแกนนี้รันอยู่ฝั่งนั้น
# ข้อจำกัดที่ต้องรู้ตรงๆ: การเช็คด้วยชื่อโปรเซส/พอร์ตแบบนี้เลี่ยงง่ายมาก (แค่
# เปลี่ยนชื่อไฟล์ .exe ก็หลบได้แล้ว) นี่คือ anti-cheat ระดับพื้นฐานสุด ไม่ใช่
# ของแบบ EasyAntiCheat/BattlEye ที่ทำงานระดับ kernel ซึ่งซับซ้อนและเสี่ยงกว่า
# มาก (ต้องมี driver เซ็นชื่อรับรอง ฯลฯ) — เหมาะเป็นด่านแรกที่กรองคนโกงทั่วไป
# ออกไปได้บ้าง ไม่ใช่การป้องกันที่แน่นหนา
CLIENT_INTEGRITY_SCANNER = r'''# vmax_integrity_scanner.py — รันบนเครื่องผู้เล่นเอง (ไม่ใช่ server)
# pip install psutil requests
import psutil, requests, time

SERVER_URL = "http://127.0.0.1:5000"
MY_UID = "VMAX-OP-01"   # เปลี่ยนเป็น uid ผู้เล่นจริง
GAME_PORT = 5000

# รายชื่อโปรเซสที่พบบ่อยในเครื่องมือโกง/แก้ไขหน่วยความจำ/injector ทั่วไป —
# เป็นจุดเริ่มต้นเท่านั้น ไม่ครบทุกตัว และเลี่ยงได้ง่ายด้วยการเปลี่ยนชื่อไฟล์
SUSPICIOUS_PROCESS_NAMES = {
    "cheatengine", "cheat engine", "artmoney", "processhacker",
    "extremeinjector", "xenos", "dll injector",
}

def scan_processes():
    hits = []
    for proc in psutil.process_iter(['name']):
        name = (proc.info.get('name') or '').lower()
        if any(bad in name for bad in SUSPICIOUS_PROCESS_NAMES):
            hits.append(name)
    return hits

def scan_suspicious_connections():
    """เช็ค connection ที่เข้าพอร์ตเกมจาก IP ที่ไม่ใช่ localhost — ตรวจแบบง่ายๆ
    เท่านั้น ไม่รับประกันว่าจับได้ทุกกรณี (proxy/tunnel บางแบบเลี่ยงได้)"""
    hits = []
    for conn in psutil.net_connections(kind='tcp'):
        if conn.laddr and conn.laddr.port == GAME_PORT:
            if conn.raddr and conn.raddr.ip not in ("127.0.0.1", "::1"):
                hits.append(f"{conn.raddr.ip}:{conn.raddr.port}")
    return hits

def report(reason, evidence):
    try:
        requests.post(f"{SERVER_URL}/api/anticheat/report",
                      json={"uid": MY_UID, "game_id": "vmax",
                           "reason": reason, "evidence": evidence}, timeout=5)
    except Exception as e:
        print("[scanner] report failed:", e)

if __name__ == "__main__":
    while True:
        procs = scan_processes()
        if procs:
            report("suspicious_process", {"processes": procs})
            print("[scanner] flagged processes:", procs)
        conns = scan_suspicious_connections()
        if conns:
            report("suspicious_connection", {"remote_addrs": conns})
            print("[scanner] flagged connections:", conns)
        time.sleep(30)
'''

# --- JavaScript / Node.js ----------------------------------------------------
JAVASCRIPT_BRIDGE_CLIENT = r'''// vmax_bridge_client.js — run with: node vmax_bridge_client.js  (Node 18+, has fetch built-in)
const BASE_URL = "http://127.0.0.1:5000";
let lastId = 0;

function handleEvent(ev) {
    if (ev.type === "player_leveled_up") console.log("[bridge] python side leveled up:", ev.data);
    else console.log("[bridge] unhandled event:", ev.type, ev.data);
}

async function pushEvent(type, data) {
    await fetch(`${BASE_URL}/api/bridge/push`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: "js_client", type, data }),
    });
}

async function pollLoop() {
    while (true) {
        const r = await fetch(`${BASE_URL}/api/bridge/pull?since=${lastId}`);
        const d = await r.json();
        for (const ev of d.events || []) { handleEvent(ev); lastId = Math.max(lastId, ev.id); }
        await new Promise(res => setTimeout(res, 2000));
    }
}
pollLoop();
'''

# --- C++ (libcurl) ------------------------------------------------------------
CPP_BRIDGE_CLIENT = r'''// vmax_bridge_client.cpp — needs libcurl (compile: g++ file.cpp -lcurl -o bridge)
#include <curl/curl.h>
#include <iostream>
#include <string>
#include <thread>
#include <chrono>

static size_t write_cb(char* ptr, size_t size, size_t nmemb, std::string* out) {
    out->append(ptr, size * nmemb);
    return size * nmemb;
}

std::string http_get(const std::string& url) {
    CURL* curl = curl_easy_init();
    std::string response;
    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
    curl_easy_perform(curl);
    curl_easy_cleanup(curl);
    return response;
}

int main() {
    const std::string base_url = "http://127.0.0.1:5000";
    int last_id = 0;
    while (true) {
        std::string resp = http_get(base_url + "/api/bridge/pull?since=" + std::to_string(last_id));
        // NOTE: for real use, parse `resp` with a JSON library (e.g. nlohmann/json)
        // instead of printing raw text — kept minimal here to stay dependency-light.
        std::cout << "[bridge] raw response: " << resp << std::endl;
        std::this_thread::sleep_for(std::chrono::seconds(2));
    }
}
'''

# --- C++ / GLFW -------------------------------------------------------------
GLFW_BRIDGE_CLIENT = r'''// vmax_bridge_glfw_client.cpp — needs GLFW3 + OpenGL + libcurl
//
// Windows (MSVC, using the official glfw-3.4.bin.WIN64 package):
// cl vmax_bridge_glfw_client.cpp /I glfw-3.4.bin.WIN64\include
// /link /LIBPATH:glfw-3.4.bin.WIN64\lib-vc2022 glfw3.lib opengl32.lib

//
// Linux:
//   g++ vmax_bridge_glfw_client.cpp -lglfw -lGL -lcurl -lpthread -o bridge
//
// This client opens a bare GLFW window just to hold a valid OpenGL context;
// it does not render anything. The actual bridge polling happens on a
// background thread and prints raw responses to the console, same as the
// plain libcurl C++ client above.
#include <GLFW/glfw3.h>
#include <curl/curl.h>
#include <iostream>
#include <string>
#include <thread>
#include <atomic>
#include <chrono>

static size_t write_cb(char* ptr, size_t size, size_t nmemb, std::string* out) {
    out->append(ptr, size * nmemb);
    return size * nmemb;
}

static std::string http_get(const std::string& url) {
    CURL* curl = curl_easy_init();
    std::string response;
    if (curl) {
        curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_cb);
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
        curl_easy_setopt(curl, CURLOPT_TIMEOUT, 5L);
        curl_easy_perform(curl);
        curl_easy_cleanup(curl);
    }
    return response;
}

static std::atomic<bool> g_running{true};

static void poll_loop() {
    const std::string base_url = "http://127.0.0.1:5000";
    int last_id = 0;
    while (g_running.load()) {
        std::string resp = http_get(base_url + "/api/bridge/pull?since=" + std::to_string(last_id));
        // NOTE: for real use, parse `resp` with a JSON library (e.g. nlohmann/json)
        // instead of printing raw text — kept minimal here to stay dependency-light.
        std::cout << "[bridge] raw response: " << resp << std::endl;
        std::this_thread::sleep_for(std::chrono::seconds(2));
    }
}

int main() {
    if (!glfwInit()) {
        std::cerr << "[bridge] glfwInit failed" << std::endl;
        return 1;
    }

    // Empty window — just enough to hold a valid OpenGL context.
    GLFWwindow* window = glfwCreateWindow(640, 480, "vmax bridge (glfw)", nullptr, nullptr);
    if (!window) {
        std::cerr << "[bridge] glfwCreateWindow failed" << std::endl;
        glfwTerminate();
        return 1;
    }
    glfwMakeContextCurrent(window);
    glfwSwapInterval(1);

    curl_global_init(CURL_GLOBAL_DEFAULT);
    std::thread poller(poll_loop);

    while (!glfwWindowShouldClose(window)) {
        glClearColor(0.08f, 0.08f, 0.10f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
        glfwSwapBuffers(window);
        glfwPollEvents();
    }

    g_running.store(false);
    poller.join();
    curl_global_cleanup();

    glfwDestroyWindow(window);
    glfwTerminate();
    return 0;
}
'''

# --- Java ---------------------------------------------------------------------
JAVA_BRIDGE_CLIENT = r'''// VmaxBridgeClient.java — needs Java 11+ (built-in HttpClient)
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

public class VmaxBridgeClient {
    static final String BASE_URL = "http://127.0.0.1:5000";
    static int lastId = 0;

    public static void main(String[] args) throws Exception {
        HttpClient client = HttpClient.newHttpClient();
        while (true) {
            HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(BASE_URL + "/api/bridge/pull?since=" + lastId))
                .GET().build();
            HttpResponse<String> resp = client.send(req, HttpResponse.BodyHandlers.ofString());
            // NOTE: for real use, parse resp.body() with a JSON library (e.g. Jackson/Gson)
            System.out.println("[bridge] raw response: " + resp.body());
            Thread.sleep(2000);
        }
    }
}
'''

# --- Go -------------------------------------------------------------------
GO_BRIDGE_CLIENT = r'''// vmax_bridge_client.go — run with: go run vmax_bridge_client.go
package main

import (
    "fmt"
    "io"
    "net/http"
    "time"
)

const baseURL = "http://127.0.0.1:5000"

func main() {
    lastID := 0
    for {
        resp, err := http.Get(fmt.Sprintf("%s/api/bridge/pull?since=%d", baseURL, lastID))
        if err != nil {
            fmt.Println("[bridge] error:", err)
            time.Sleep(2 * time.Second)
            continue
        }
        body, _ := io.ReadAll(resp.Body)
        resp.Body.Close()
        // NOTE: for real use, parse `body` as JSON (encoding/json) instead of printing raw
        fmt.Println("[bridge] raw response:", string(body))
        time.Sleep(2 * time.Second)
    }
}
'''

# --- Verse (UEFN / Fortnite Creative) -----------------------------------------
# หมายเหตุ: Verse ยังไม่มี HTTP client มาตรฐานที่เปิดกว้างเท่าภาษาอื่นในไฟล์นี้ —
# ใช้ได้เฉพาะบางบริบท/ต้อง publish เกาะแบบ verified และเปิดใช้ HTTP module ก่อน
# นี่คือโครงตาม HTTP module ปัจจุบันของ UEFN (namespace อาจเปลี่ยนตามเวอร์ชัน)
VERSE_BRIDGE_CLIENT = r'''# vmax_bridge_client.verse — วางใน UEFN project ของคุณ (ต้องเปิดใช้ HTTP module
# ผ่าน Project Settings > Allow HTTP Requests และ publish เกาะแบบ verified ก่อน
# ฟีเจอร์นี้ถึงจะทำงานได้จริงใน published session)
using { /Fortnite.com/Devices }
using { /Verse.org/Simulation }
using { /UnrealEngine.com/Temporary/Diagnostics }
using { /UnrealEngine.com/Temporary/HTTP }
using { /UnrealEngine.com/Temporary/JSON }

vmax_bridge_client := class(creative_device):

    BaseUrl<constant>:string = "http://127.0.0.1:5000"
    var LastId<public>:int = 0

    OnBegin<override>()<suspends>:void=
        HttpClient := HTTPClient{}
        loop:
            PollOnce(HttpClient)
            Sleep(2.0)

    PollOnce(HttpClient:http_client)<suspends>:void=
        Url := "{BaseUrl}/api/bridge/pull?since={ToString(LastId)}"
        Request := HTTPRequest{ Url := Url, Verb := HTTPRequestVerb.Get }
        if (Response := HttpClient.Request(Request)?, Response.ResponseCode = 200):
            # หมายเหตุ: parse Response.Body ด้วย JSON module จริงเพื่อดึง events[]
            # แล้วอัปเดต LastId ตาม ev.id ที่มากสุด — ตัดออกเพื่อให้โครงสั้นและอ่านง่าย
            Print("[bridge] raw response: {Response.Body}")

    PushEvent(HttpClient:http_client, EventType:string, JsonData:string)<suspends>:void=
        Body := "{\"source\":\"verse\",\"type\":\"{EventType}\",\"data\":{JsonData}}"
        Request := HTTPRequest{
            Url := "{BaseUrl}/api/bridge/push",
            Verb := HTTPRequestVerb.Post,
            Headers := array{ HTTPHeader{ Name := "Content-Type", Value := "application/json" } },
            Body := option{Body}
        }
        if (Response := HttpClient.Request(Request)?, Response.ResponseCode <> 200):
            Print("[bridge] push failed, code: {ToString(Response.ResponseCode)}")
'''

# --- Luau (Roblox) --------------------------------------------------------------
LUAU_BRIDGE_CLIENT = r'''-- vmax_bridge_client.luau — วางใน ServerScriptService ของ Roblox place คุณ
-- ต้องเปิด "Allow HTTP Requests" ใน Game Settings > Security ก่อน HttpService ถึงจะยิงออกได้
local HttpService = game:GetService("HttpService")

local BASE_URL = "http://127.0.0.1:5000"
local lastId = 0

local function handleEvent(ev)
    if ev.type == "player_leveled_up" then
        print("[bridge] python side leveled up:", HttpService:JSONEncode(ev.data))
    else
        print("[bridge] unhandled event:", ev.type, HttpService:JSONEncode(ev.data))
    end
end

local function pushEvent(eventType, data)
    local body = HttpService:JSONEncode({ source = "luau_client", type = eventType, data = data })
    local ok, err = pcall(function()
        HttpService:PostAsync(BASE_URL .. "/api/bridge/push", body, Enum.HttpContentType.ApplicationJson)
    end)
    if not ok then
        warn("[bridge] push failed:", err)
    end
end

local function pollLoop()
    while true do
        local ok, result = pcall(function()
            return HttpService:GetAsync(BASE_URL .. "/api/bridge/pull?since=" .. tostring(lastId))
        end)
        if ok then
            local decoded = HttpService:JSONDecode(result)
            for _, ev in ipairs(decoded.events or {}) do
                handleEvent(ev)
                if ev.id > lastId then
                    lastId = ev.id
                end
            end
        else
            warn("[bridge] pull failed:", result)
        end
        task.wait(2)
    end
end

task.spawn(pollLoop)
'''

BRIDGE_CLIENT_TEMPLATES = {
    "unity":      {"code": UNITY_BRIDGE_CS,        "ext": "cs",    "label": "Unity / C#"},
    "csharp":     {"code": UNITY_BRIDGE_CS,        "ext": "cs",    "label": "Unity / C#"},
    "python":     {"code": PYTHON_BRIDGE_CLIENT,   "ext": "py",    "label": "Python (separate process)"},
    "javascript": {"code": JAVASCRIPT_BRIDGE_CLIENT,"ext": "js",   "label": "JavaScript / Node.js"},
    "cpp":        {"code": CPP_BRIDGE_CLIENT,      "ext": "cpp",   "label": "C++ (libcurl)"},
    "glfw":       {"code": GLFW_BRIDGE_CLIENT,     "ext": "cpp",   "label": "C++ (GLFW + libcurl)"},
    "java":       {"code": JAVA_BRIDGE_CLIENT,     "ext": "java",  "label": "Java 11+"},
    "go":         {"code": GO_BRIDGE_CLIENT,       "ext": "go",    "label": "Go"},
    "verse":      {"code": VERSE_BRIDGE_CLIENT,    "ext": "verse", "label": "Verse (UEFN / Fortnite Creative)"},
    "luau":       {"code": LUAU_BRIDGE_CLIENT,     "ext": "luau",  "label": "Luau (Roblox)"},
}
