# ==========================================
# VMAX Module: Ad Overlay (โฆษณาแบ่งจอ + QR Code + ส่งไปที่โทรศัพท์)
# ==========================================
# ไฟล์นี้เป็น "module เสมือน" แยกจากไฟล์หลัก ใช้เทคนิคเดียวกับโมดูลอื่นในไฟล์ VMAX:
# ถูกฝังเป็น base64 ในไฟล์หลัก รันครั้งแรกจะเขียนออกมาเป็น vmax_module_ad_overlay.py
# ข้างสคริปต์ แล้ว import แล้วถูก "ต่อ" (attach) ตอนท้ายไฟล์ก่อน sio.run(...)
#
# หลักการ (เทียบตามที่ถามมา 3 ส่วน):
#  1) Dynamic UI Overlay  -> /ads/overlay.js  แบ่งจอ: ซ้ายคือเกม/วิดีโอเดิม (ย่อ),
#                            ขวาคือการ์ดโฆษณา + QR Code ที่ server สร้างให้ "เฉพาะ impression นั้น"
#  2) Device Graph        -> ใช้บัญชี VMAX (uid) เดียวกันบนจอใหญ่/พีซี กับมือถือ
#                            (account-based) — โทรศัพท์ที่ล็อกอิน uid เดียวกันและต่อ Socket.IO อยู่
#                            จะอยู่ใน room=uid อยู่แล้ว
#  3) Push                -> กด "ส่งไปที่โทรศัพท์" => server บันทึกลง inbox + sio.emit('ad_push', room=uid)
#                            (และเรียก push backend เสริมได้ผ่าน register_push_backend เช่น FCM/LINE/Web Push)
#
# Endpoint:
#   POST /api/ads/request            (login) ขอโฆษณา 1 ชิ้นสำหรับ placement
#   POST /api/ads/event              (login) {imp_id, event: skip|complete}
#   POST /api/ads/send_phone         (login) {imp_id} ส่งลิงก์ไปที่อุปกรณ์อื่นของบัญชีเดียวกัน
#   GET  /api/ads/inbox              (login) รายการที่ถูกส่งมาที่มือถือ (polling สำรองถ้า socket ไม่ต่อ)
#   POST /api/ads/inbox/ack          (login) {push_id}
#   GET  /ads/c/<token>              สาธารณะ: ลิงก์ติดตามจาก QR / ปุ่มมือถือ -> นับคลิกแล้ว redirect
#   GET  /ads/overlay.js             สคริปต์ฝั่งหน้าเว็บ (window.VMAXAds)
#   GET  /ads/demo                   หน้าเดโมแบ่งจอ
#   Admin (ยศ admin ขึ้นไป):
#   GET  /api/ads/admin/campaigns, POST /api/ads/admin/campaign, POST /api/ads/admin/toggle,
#   GET  /api/ads/admin/stats
#
# ข้อควรทำตามกฎ/มารยาท: ป้าย "โฆษณา" ติดทุกชิ้น (บังคับใน overlay.js), ไม่เก็บข้อมูลเกินจำเป็น
# (เก็บแค่ uid + เวลา + ชนิด event), และผู้เล่นกดข้ามได้หลัง skip_after วินาที
# ==========================================
import hashlib as _ad_hashlib
import hmac as _ad_hmac
import html as _ad_html
import json as _ad_json
import os as _ad_os
import secrets as _ad_secrets
import sqlite3 as _ad_sqlite
import threading as _ad_threading
import time as _ad_time
from urllib.parse import urlparse as _ad_urlparse

_READY = False
_DB_LOCK = _ad_threading.Lock()
_BASE_DIR = _ad_os.path.dirname(_ad_os.path.abspath(__file__))
DB_PATH = _ad_os.environ.get("VMAX_ADS_DB", _ad_os.path.join(_BASE_DIR, "vmax_ads.db"))
SECRET_PATH = _ad_os.path.join(_BASE_DIR, ".vmax_ads_secret")
PUSH_BACKENDS = []   # ฟังก์ชัน fn(uid, payload:dict) -> bool  (ต่อ FCM / LINE Notify / Web Push ได้ที่นี่)

# ------------------------------------------------------------------
# QR Code (pure python, byte mode, ECC M) — ใช้ lib qrcode/segno ก่อนถ้ามี
# ------------------------------------------------------------------
_ECC_PER_BLOCK_M = [None, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28]
_NUM_BLOCKS_M = [None, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23]
_MAX_VER = 26


def _qr_raw_modules(ver):
    r = (16 * ver + 128) * ver + 64
    if ver >= 2:
        n = ver // 7 + 2
        r -= (25 * n - 10) * n - 55
        if ver >= 7:
            r -= 36
    return r


def _gf_mul(x, y):
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(deg):
    res = [0] * (deg - 1) + [1]
    root = 1
    for _ in range(deg):
        for j in range(deg):
            res[j] = _gf_mul(res[j], root)
            if j + 1 < deg:
                res[j] ^= res[j + 1]
        root = _gf_mul(root, 0x02)
    return res


def _rs_remainder(data, div):
    res = [0] * len(div)
    for b in data:
        f = b ^ res.pop(0)
        res.append(0)
        for i, c in enumerate(div):
            res[i] ^= _gf_mul(c, f)
    return res


def _qr_matrix(text):
    data = text.encode("utf-8")
    ver = None
    for v in range(1, _MAX_VER + 1):
        cap = _qr_raw_modules(v) // 8 - _ECC_PER_BLOCK_M[v] * _NUM_BLOCKS_M[v]
        ccbits = 8 if v < 10 else 16
        if 4 + ccbits + 8 * len(data) <= cap * 8:
            ver = v
            break
    if ver is None:
        raise ValueError("ข้อความยาวเกินไปสำหรับ QR")
    ccbits = 8 if ver < 10 else 16
    bits = []

    def put(val, n):
        for i in range(n - 1, -1, -1):
            bits.append((val >> i) & 1)
    put(0b0100, 4)
    put(len(data), ccbits)
    for b in data:
        put(b, 8)
    cap_bits = (_qr_raw_modules(ver) // 8 - _ECC_PER_BLOCK_M[ver] * _NUM_BLOCKS_M[ver]) * 8
    put(0, min(4, cap_bits - len(bits)))
    while len(bits) % 8:
        bits.append(0)
    pad = 0xEC
    while len(bits) < cap_bits:
        put(pad, 8)
        pad ^= 0xEC ^ 0x11
    cw = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    # interleave + ECC
    nb, el = _NUM_BLOCKS_M[ver], _ECC_PER_BLOCK_M[ver]
    raw = _qr_raw_modules(ver) // 8
    nshort = nb - raw % nb
    slen = raw // nb
    div = _rs_divisor(el)
    blocks, k = [], 0
    for i in range(nb):
        dat = cw[k:k + slen - el + (0 if i < nshort else 1)]
        k += len(dat)
        ecc = _rs_remainder(dat, div)
        if i < nshort:
            dat = dat + [0]
        blocks.append(dat + ecc)
    final = []
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != slen - el or j >= nshort:
                final.append(blk[i])
    size = ver * 4 + 17
    mod = [[False] * size for _ in range(size)]
    isfn = [[False] * size for _ in range(size)]

    def setfn(x, y, v):
        mod[y][x] = bool(v)
        isfn[y][x] = True

    for i in range(size):
        setfn(6, i, i % 2 == 0)
        setfn(i, 6, i % 2 == 0)

    def finder(cx, cy):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < size and 0 <= y < size:
                    setfn(x, y, max(abs(dx), abs(dy)) not in (2, 4))
    finder(3, 3)
    finder(size - 4, 3)
    finder(3, size - 4)
    if ver > 1:
        n = ver // 7 + 2
        step = 26 if ver == 32 else (ver * 4 + n * 2 + 1) // (n * 2 - 2) * 2
        pos = list(reversed([size - 7 - i * step for i in range(n - 1)] + [6]))
        for i in range(n):
            for j in range(n):
                if (i == 0 and j == 0) or (i == 0 and j == n - 1) or (i == n - 1 and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        setfn(pos[i] + dx, pos[j] + dy, max(abs(dx), abs(dy)) != 1)

    def fmt(mask):
        d = (0 << 3) | mask   # ECC M = 0b00
        r = d
        for _ in range(10):
            r = (r << 1) ^ ((r >> 9) * 0x537)
        b = ((d << 10) | r) ^ 0x5412
        g = lambda i: (b >> i) & 1
        for i in range(0, 6):
            setfn(8, i, g(i))
        setfn(8, 7, g(6))
        setfn(8, 8, g(7))
        setfn(7, 8, g(8))
        for i in range(9, 15):
            setfn(14 - i, 8, g(i))
        for i in range(0, 8):
            setfn(size - 1 - i, 8, g(i))
        for i in range(8, 15):
            setfn(8, size - 15 + i, g(i))
        setfn(8, size - 8, True)
    fmt(0)
    if ver >= 7:
        r = ver
        for _ in range(12):
            r = (r << 1) ^ ((r >> 11) * 0x1F25)
        b = (ver << 12) | r
        for i in range(18):
            bit = (b >> i) & 1
            a, c = size - 11 + i % 3, i // 3
            setfn(a, c, bit)
            setfn(c, a, bit)
    # วางข้อมูล
    i = 0
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = (size - 1 - vert) if upward else vert
                if not isfn[y][x] and i < len(final) * 8:
                    mod[y][x] = ((final[i >> 3] >> (7 - (i & 7))) & 1) == 1
                    i += 1
        right -= 2
    masks = [
        lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
        lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
        lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
        lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
    ]

    def penalty(m):
        p = 0
        for grid in (m, [list(c) for c in zip(*m)]):
            for row in grid:
                run, prev = 1, row[0]
                for v in row[1:]:
                    if v == prev:
                        run += 1
                    else:
                        if run >= 5:
                            p += 3 + (run - 5)
                        run, prev = 1, v
                if run >= 5:
                    p += 3 + (run - 5)
                s = "".join("1" if v else "0" for v in row)
                p += 40 * (s.count("10111010000") + s.count("00001011101"))
        for y in range(size - 1):
            for x in range(size - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    p += 3
        dark = sum(sum(r) for r in m)
        k = (abs(dark * 20 - size * size * 10) + size * size - 1) // (size * size) - 1
        return p + max(k, 0) * 10

    best, best_p, best_m = None, None, 0
    for mi, fn in enumerate(masks):
        cand = [row[:] for row in mod]
        for y in range(size):
            for x in range(size):
                if not isfn[y][x] and fn(x, y):
                    cand[y][x] = not cand[y][x]
        pen = penalty(cand)
        if best_p is None or pen < best_p:
            best, best_p, best_m = cand, pen, mi
    mod = best
    fmt(best_m)   # เขียน format bits ใหม่ด้วย mask ที่เลือก (isfn กันไม่ให้ทับข้อมูล)
    return mod


def make_qr_svg(text, border=4):
    """คืน <svg> ของ QR (พื้นขาว/จุดดำ) — พยายามใช้ segno/qrcode ก่อน ถ้าไม่มีใช้ตัว encode ในไฟล์"""
    try:
        import segno  # type: ignore
        import io
        buf = io.BytesIO()
        segno.make(text, error="m").save(buf, kind="svg", scale=1, border=border, xmldecl=False,
                                         svgns=True, nl=False, omitsize=True)
        s = buf.getvalue().decode("utf-8")
        if "<svg" in s:
            return s
    except Exception:
        pass
    m = _qr_matrix(text)
    n = len(m)
    dim = n + border * 2
    parts = []
    for y, row in enumerate(m):
        x = 0
        while x < n:
            if row[x]:
                x0 = x
                while x < n and row[x]:
                    x += 1
                parts.append("M%d %dh%dv1h-%dz" % (x0 + border, y + border, x - x0, x - x0))
            else:
                x += 1
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" shape-rendering="crispEdges">'
            '<rect width="100%%" height="100%%" fill="#fff"/><path d="%s" fill="#000"/></svg>' % (dim, dim, "".join(parts)))


# ------------------------------------------------------------------
# DB
# ------------------------------------------------------------------
def _db():
    c = _ad_sqlite.connect(DB_PATH, timeout=10)
    c.row_factory = _ad_sqlite.Row
    return c


def _init_db():
    with _DB_LOCK, _db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS ad_campaigns(
            id TEXT PRIMARY KEY, title TEXT, advertiser TEXT, body TEXT, image_url TEXT,
            click_url TEXT, cta TEXT, placements TEXT, weight INTEGER DEFAULT 1,
            skip_after INTEGER DEFAULT 5, duration INTEGER DEFAULT 15,
            max_impressions INTEGER DEFAULT 0, per_user_daily_cap INTEGER DEFAULT 3,
            starts_at REAL DEFAULT 0, ends_at REAL DEFAULT 0, enabled INTEGER DEFAULT 1,
            created_at REAL);
        CREATE TABLE IF NOT EXISTS ad_impressions(
            id TEXT PRIMARY KEY, campaign_id TEXT, uid TEXT, placement TEXT, created_at REAL,
            skipped_at REAL DEFAULT 0, completed_at REAL DEFAULT 0, sent_phone_at REAL DEFAULT 0,
            clicks_qr INTEGER DEFAULT 0, clicks_phone INTEGER DEFAULT 0);
        CREATE INDEX IF NOT EXISTS ix_imp_uid ON ad_impressions(uid, created_at);
        CREATE INDEX IF NOT EXISTS ix_imp_camp ON ad_impressions(campaign_id);
        CREATE TABLE IF NOT EXISTS ad_inbox(
            id TEXT PRIMARY KEY, uid TEXT, imp_id TEXT, title TEXT, url TEXT,
            created_at REAL, acked_at REAL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS ix_inbox_uid ON ad_inbox(uid, acked_at);
        """)


def _secret():
    s = _ad_os.environ.get("VMAX_ADS_SECRET")
    if s:
        return s.encode()
    try:
        with open(SECRET_PATH, "rb") as f:
            return f.read().strip()
    except Exception:
        k = _ad_secrets.token_hex(32).encode()
        try:
            with open(SECRET_PATH, "wb") as f:
                f.write(k)
            try:
                _ad_os.chmod(SECRET_PATH, 0o600)
            except Exception:
                pass
        except Exception:
            pass
        return k


def _sign(imp_id):
    return _ad_hmac.new(_secret(), imp_id.encode(), _ad_hashlib.sha256).hexdigest()[:20]


def make_token(imp_id):
    return imp_id + "." + _sign(imp_id)


def parse_token(tok):
    try:
        imp_id, sig = tok.rsplit(".", 1)
    except ValueError:
        return None
    return imp_id if _ad_hmac.compare_digest(sig, _sign(imp_id)) else None


def _safe_url(u, allow_data=False):
    u = (u or "").strip()
    if allow_data and u.startswith("data:image/"):
        return u
    p = _ad_urlparse(u)
    return u if p.scheme in ("http", "https") and p.netloc else ""


def _public_base(request):
    return (_ad_os.environ.get("VMAX_PUBLIC_URL") or request.host_url).rstrip("/")


# ------------------------------------------------------------------
# Overlay JS (ฝั่งหน้าเกม) + demo page
# ------------------------------------------------------------------
OVERLAY_JS = r"""
/* VMAXAds — แบ่งจอโฆษณา + QR + ส่งไปที่โทรศัพท์  (ใช้: VMAXAds.show({placement:'lobby', target:'#game'})) */
(function(){
  if (window.VMAXAds) return;
  var css = '.vmax-ad-wrap{position:fixed;inset:0;z-index:99999;pointer-events:none;font-family:system-ui,sans-serif}'
   +'.vmax-ad-card{position:absolute;right:2vw;top:50%;transform:translateY(-50%);width:min(30vw,340px);min-width:240px;background:#f4f1ea;color:#222;border-radius:22px;box-shadow:0 10px 40px rgba(0,0,0,.5);overflow:hidden;pointer-events:auto}'
   +'.vmax-ad-head{display:flex;align-items:center;gap:8px;padding:10px 12px;background:#fff}'
   +'.vmax-ad-badge{font-size:11px;font-weight:700;background:#ffd400;color:#000;border-radius:6px;padding:2px 6px}'
   +'.vmax-ad-title{flex:1;font-weight:700;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}'
   +'.vmax-ad-cta{background:#e8334a;color:#fff;border:0;border-radius:999px;padding:8px 18px;font-weight:700;cursor:pointer}'
   +'.vmax-ad-img{width:100%;aspect-ratio:4/5;background:#ddd center/cover no-repeat}'
   +'.vmax-ad-body{padding:8px 12px;font-size:13px;line-height:1.4}'
   +'.vmax-ad-qr{width:46%;margin:-60px auto 8px;background:#fff;padding:6px;border-radius:12px;box-shadow:0 2px 10px rgba(0,0,0,.3);position:relative}'
   +'.vmax-ad-qr svg{display:block;width:100%;height:auto}'
   +'.vmax-ad-bar{position:absolute;right:2vw;bottom:5vh;width:min(30vw,340px);min-width:240px;display:flex;gap:8px;justify-content:center;pointer-events:auto}'
   +'.vmax-ad-pill{background:rgba(255,255,255,.88);color:#222;border:0;border-radius:999px;padding:9px 16px;font-size:13px;cursor:pointer}'
   +'.vmax-ad-pill[disabled]{opacity:.55;cursor:default}'
   +'.vmax-ad-toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:#222;color:#fff;padding:12px 18px;border-radius:12px;z-index:100000;font-size:14px}'
   +'@media (max-width:700px){.vmax-ad-card{right:50%;transform:translate(50%,-50%);width:86vw}.vmax-ad-bar{right:50%;transform:translateX(50%);width:86vw}}';
  var st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

  function el(tag, cls, txt){ var e=document.createElement(tag); if(cls) e.className=cls; if(txt!=null) e.textContent=txt; return e; }
  function getToken(opts){
    var t = opts && opts.token; if (typeof t === 'function') t = t();
    if (t) return t;
    var ks=['vmax_token','token','jwt','access_token','vmaxToken','authToken'];
    for (var i=0;i<ks.length;i++){ try{ var v=localStorage.getItem(ks[i])||sessionStorage.getItem(ks[i]); if(v) return v; }catch(e){} }
    return '';
  }
  function api(path, body, tok){
    return fetch(path,{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+tok},body:JSON.stringify(body||{})}).then(function(r){return r.json();});
  }
  function toast(msg, ms){ var t=el('div','vmax-ad-toast',msg); document.body.appendChild(t); setTimeout(function(){t.remove();}, ms||3500); }

  var current = null;
  function close(reason){
    if(!current) return; var c=current; current=null;
    clearInterval(c.timer); c.wrap.remove();
    if(c.target){ c.target.style.transform=c.prevT; c.target.style.transformOrigin=c.prevO; c.target.style.transition=c.prevTr; }
    if(c.opts && c.opts.onClose) try{ c.opts.onClose(reason); }catch(e){}
  }

  function show(opts){
    opts = opts || {};
    if (current) return Promise.resolve(null);
    var tok = getToken(opts);
    if (!tok) return Promise.resolve(null);
    return api('/api/ads/request', {placement: opts.placement || 'default'}, tok).then(function(res){
      if (!res || res.st !== 'ok' || !res.ad) return null;       // ไม่มีโฆษณาที่เข้าเงื่อนไข -> เงียบ ไม่รบกวนผู้เล่น
      var ad = res.ad, wrap = el('div','vmax-ad-wrap'), card = el('div','vmax-ad-card');
      var head = el('div','vmax-ad-head');
      head.appendChild(el('span','vmax-ad-badge','โฆษณา'));
      head.appendChild(el('span','vmax-ad-title', ad.advertiser || ad.title));
      var cta = el('button','vmax-ad-cta', ad.cta || 'ดูเพิ่มเติม');
      cta.onclick = function(){ window.open(res.track_url + '?s=screen','_blank','noopener'); };
      head.appendChild(cta); card.appendChild(head);
      var img = el('div','vmax-ad-img'); if (ad.image_url) img.style.backgroundImage = 'url("' + ad.image_url.replace(/"/g,'%22') + '")'; card.appendChild(img);
      var qr = el('div','vmax-ad-qr'); qr.innerHTML = res.qr_svg; card.appendChild(qr);   // SVG สร้างโดย server เอง (ไม่รับ input ผู้ใช้)
      if (ad.body) card.appendChild(el('div','vmax-ad-body', ad.body));
      wrap.appendChild(card);
      var bar = el('div','vmax-ad-bar');
      var phone = el('button','vmax-ad-pill','🔔 ส่งไปที่โทรศัพท์');
      var skip = el('button','vmax-ad-pill'); skip.disabled = true;
      bar.appendChild(phone); bar.appendChild(skip); wrap.appendChild(bar);
      document.body.appendChild(wrap);

      var target = opts.target ? document.querySelector(opts.target) : null, prevT='', prevO='', prevTr='';
      if (target){ prevT=target.style.transform; prevO=target.style.transformOrigin; prevTr=target.style.transition;
        target.style.transition='transform .35s'; target.style.transformOrigin='left center'; target.style.transform='scale(.66)'; }

      var left = res.skip_after, total = res.duration, elapsed = 0;
      function paint(){ if (left>0){ skip.textContent='ข้ามใน '+left+' วิ'; } else { skip.disabled=false; skip.textContent='ข้าม ▶'; } }
      paint();
      var timer = setInterval(function(){
        elapsed++; if (left>0) left--; paint();
        if (elapsed >= total){ api('/api/ads/event',{imp_id:res.imp_id,event:'complete'},tok); close('complete'); }
      },1000);
      skip.onclick = function(){ if(skip.disabled) return; api('/api/ads/event',{imp_id:res.imp_id,event:'skip'},tok); close('skip'); };
      phone.onclick = function(){
        phone.disabled = true;
        api('/api/ads/send_phone',{imp_id:res.imp_id},tok).then(function(r){
          if (r && r.st==='ok'){ phone.textContent='ส่งแล้ว ✓'; toast('ส่งแล้ว — มือถือที่ล็อกอินบัญชีเดียวกันและเปิดเกมอยู่จะมีลิงก์เด้งขึ้นมา'); }
          else { phone.disabled=false; toast((r&&r.msg)||'ส่งไม่สำเร็จ'); }
        }).catch(function(){ phone.disabled=false; toast('ส่งไม่สำเร็จ'); });
      };
      current = {wrap:wrap, timer:timer, target:target, prevT:prevT, prevO:prevO, prevTr:prevTr, opts:opts};
      return res;
    }).catch(function(){ return null; });
  }

  /* ฝั่งมือถือ: รับลิงก์ที่ถูกส่งมา — เรียก VMAXAds.attachSocket(socket) หรือ VMAXAds.pollInbox({token:..}) */
  function handlePush(p){
    if (!p || !p.url) return;
    var t = el('div','vmax-ad-toast'); t.style.pointerEvents='auto';
    t.appendChild(document.createTextNode((p.title||'ลิงก์จากหน้าจอ')+'  '));
    var a = el('button','vmax-ad-cta','เปิด'); a.style.padding='4px 14px';
    a.onclick=function(){ window.open(p.url,'_blank','noopener'); t.remove(); };
    t.appendChild(a); document.body.appendChild(t); setTimeout(function(){t.remove();},15000);
  }
  function attachSocket(sock){ if (sock && sock.on) sock.on('ad_push', function(p){ handlePush(p); if(p&&p.push_id){ var tk=getToken(); if(tk) api('/api/ads/inbox/ack',{push_id:p.push_id},tk);} }); }
  function pollInbox(opts){
    var ms=(opts&&opts.interval)||8000;
    setInterval(function(){ var tk=getToken(opts); if(!tk) return;
      fetch('/api/ads/inbox',{headers:{Authorization:'Bearer '+tk}}).then(function(r){return r.json();}).then(function(r){
        if(r&&r.st==='ok'&&r.items) r.items.forEach(function(p){ handlePush(p); api('/api/ads/inbox/ack',{push_id:p.push_id},tk); });
      }).catch(function(){});
    }, ms);
  }
  window.VMAXAds = {show:show, close:close, attachSocket:attachSocket, pollInbox:pollInbox, handlePush:handlePush};
  try{ if (window.socket && window.socket.on) attachSocket(window.socket); }catch(e){}
})();
"""

DEMO_HTML = """<!doctype html><html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>VMAX Ad Overlay Demo</title>
<style>body{margin:0;background:#111;color:#eee;font-family:system-ui}
#game{width:100vw;height:100vh;background:linear-gradient(135deg,#223,#456);display:flex;align-items:center;justify-content:center;font-size:28px}
.ctl{position:fixed;left:12px;top:12px;z-index:5}.ctl input,.ctl button{padding:8px;margin:2px}</style></head><body>
<div class="ctl"><input id="tk" placeholder="วาง Bearer token (JWT)" size="34"><button id="go">แสดงโฆษณา</button></div>
<div id="game">พื้นที่เกม / วิดีโอ (ถูกย่อซ้ายเมื่อโฆษณาขึ้น)</div>
<script src="/ads/overlay.js"></script>
<script>document.getElementById('go').onclick=function(){VMAXAds.show({placement:'demo',target:'#game',token:document.getElementById('tk').value})};</script>
</body></html>"""


# ------------------------------------------------------------------
# attach
# ------------------------------------------------------------------
def attach(g):
    """ต่อโมดูลเข้าไฟล์หลักผ่าน globals(): ต้องมี app, sio, require_auth, require_staff_rank, audit_log"""
    global _READY
    if g.get("_ADS_ATTACHED"):
        return
    from flask import jsonify, request, redirect, Response
    app = g["app"]
    sio = g.get("sio")
    require_auth = g["require_auth"]
    require_staff_rank = g["require_staff_rank"]
    audit = g.get("audit_log") or (lambda *a, **k: None)
    _init_db()
    g["_ADS_ATTACHED"] = True
    _READY = True

    def _uid():
        return str(getattr(request, "vmax_uid", "") or "")

    def _live_campaign(c, uid, placement, now):
        if not c["enabled"]:
            return False
        if c["starts_at"] and now < c["starts_at"]:
            return False
        if c["ends_at"] and now > c["ends_at"]:
            return False
        pl = [p.strip() for p in (c["placements"] or "").split(",") if p.strip()]
        if pl and placement not in pl and "*" not in pl:
            return False
        return True

    @app.route("/api/ads/request", methods=["POST"])
    @require_auth
    def api_ads_request():
        uid = _uid()
        body = request.get_json(silent=True) or {}
        placement = str(body.get("placement") or "default")[:40]
        now = _ad_time.time()
        day_start = now - 86400
        with _DB_LOCK, _db() as c:
            rows = [r for r in c.execute("SELECT * FROM ad_campaigns").fetchall() if _live_campaign(r, uid, placement, now)]
            pool = []
            for r in rows:
                if r["max_impressions"]:
                    n = c.execute("SELECT COUNT(*) FROM ad_impressions WHERE campaign_id=?", (r["id"],)).fetchone()[0]
                    if n >= r["max_impressions"]:
                        continue
                if r["per_user_daily_cap"]:
                    n = c.execute("SELECT COUNT(*) FROM ad_impressions WHERE campaign_id=? AND uid=? AND created_at>?",
                                  (r["id"], uid, day_start)).fetchone()[0]
                    if n >= r["per_user_daily_cap"]:
                        continue
                pool.append(r)
            if not pool:
                return jsonify({"st": "ok", "ad": None})
            total = sum(max(1, int(r["weight"] or 1)) for r in pool)
            pick = _ad_secrets.randbelow(total)
            chosen = pool[-1]
            for r in pool:
                pick -= max(1, int(r["weight"] or 1))
                if pick < 0:
                    chosen = r
                    break
            imp_id = _ad_secrets.token_urlsafe(12)
            c.execute("INSERT INTO ad_impressions(id,campaign_id,uid,placement,created_at) VALUES(?,?,?,?,?)",
                      (imp_id, chosen["id"], uid, placement, now))
        tok = make_token(imp_id)
        track = _public_base(request) + "/ads/c/" + tok
        return jsonify({
            "st": "ok", "imp_id": imp_id, "token": tok,
            "track_url": track, "qr_svg": make_qr_svg(track + "?s=qr"),
            "skip_after": int(chosen["skip_after"] or 5), "duration": int(chosen["duration"] or 15),
            "ad": {"id": chosen["id"], "title": chosen["title"], "advertiser": chosen["advertiser"],
                   "body": chosen["body"], "image_url": chosen["image_url"], "cta": chosen["cta"]},
        })

    @app.route("/api/ads/event", methods=["POST"])
    @require_auth
    def api_ads_event():
        body = request.get_json(silent=True) or {}
        ev = body.get("event")
        col = {"skip": "skipped_at", "complete": "completed_at"}.get(ev)
        if not col:
            return jsonify({"st": "error", "msg": "event ต้องเป็น skip หรือ complete"}), 400
        with _DB_LOCK, _db() as c:
            r = c.execute("SELECT uid, created_at, %s FROM ad_impressions WHERE id=?" % col, (str(body.get("imp_id") or ""),)).fetchone()
            if not r or r["uid"] != _uid():
                return jsonify({"st": "error", "msg": "ไม่พบ impression"}), 404
            if r[col]:
                return jsonify({"st": "ok", "dup": True})
            c.execute("UPDATE ad_impressions SET %s=? WHERE id=?" % col, (_ad_time.time(), body.get("imp_id")))
        return jsonify({"st": "ok"})

    @app.route("/api/ads/send_phone", methods=["POST"])
    @require_auth
    def api_ads_send_phone():
        uid = _uid()
        body = request.get_json(silent=True) or {}
        imp_id = str(body.get("imp_id") or "")
        with _DB_LOCK, _db() as c:
            imp = c.execute("SELECT i.*, k.title, k.advertiser FROM ad_impressions i JOIN ad_campaigns k ON k.id=i.campaign_id WHERE i.id=?",
                            (imp_id,)).fetchone()
            if not imp or imp["uid"] != uid:
                return jsonify({"st": "error", "msg": "ไม่พบ impression"}), 404
            recent = c.execute("SELECT COUNT(*) FROM ad_inbox WHERE uid=? AND created_at>?", (uid, _ad_time.time() - 60)).fetchone()[0]
            if recent >= 5:
                return jsonify({"st": "error", "msg": "ส่งถี่เกินไป ลองใหม่อีกสักครู่"}), 429
            push_id = _ad_secrets.token_urlsafe(10)
            url = _public_base(request) + "/ads/c/" + make_token(imp_id) + "?s=phone"
            title = imp["advertiser"] or imp["title"] or "ลิงก์โฆษณา"
            c.execute("INSERT INTO ad_inbox(id,uid,imp_id,title,url,created_at) VALUES(?,?,?,?,?,?)",
                      (push_id, uid, imp_id, title, url, _ad_time.time()))
            c.execute("UPDATE ad_impressions SET sent_phone_at=? WHERE id=?", (_ad_time.time(), imp_id))
        payload = {"push_id": push_id, "title": title, "url": url}
        live = 0
        try:
            if sio is not None:
                sio.emit("ad_push", payload, room=uid)   # ทุก connection ของ uid นี้ (join_room(uid) ตอน connect)
                live = 1
        except Exception:
            pass
        for fn in list(PUSH_BACKENDS):
            try:
                if fn(uid, payload):
                    live = max(live, 1)
            except Exception:
                pass
        audit("ad_send_phone", uid=uid, imp_id=imp_id)
        return jsonify({"st": "ok", "push_id": push_id, "live": live})

    @app.route("/api/ads/inbox", methods=["GET"])
    @require_auth
    def api_ads_inbox():
        with _DB_LOCK, _db() as c:
            rows = c.execute("SELECT id,title,url,created_at FROM ad_inbox WHERE uid=? AND acked_at=0 AND created_at>? ORDER BY created_at DESC LIMIT 20",
                             (_uid(), _ad_time.time() - 86400)).fetchall()
        return jsonify({"st": "ok", "items": [{"push_id": r["id"], "title": r["title"], "url": r["url"]} for r in rows]})

    @app.route("/api/ads/inbox/ack", methods=["POST"])
    @require_auth
    def api_ads_inbox_ack():
        body = request.get_json(silent=True) or {}
        with _DB_LOCK, _db() as c:
            c.execute("UPDATE ad_inbox SET acked_at=? WHERE id=? AND uid=?", (_ad_time.time(), str(body.get("push_id") or ""), _uid()))
        return jsonify({"st": "ok"})

    @app.route("/ads/c/<token>", methods=["GET"])
    def ads_click(token):
        imp_id = parse_token(token)
        if not imp_id:
            return Response("ลิงก์ไม่ถูกต้อง", status=404)
        src = request.args.get("s", "qr")
        with _DB_LOCK, _db() as c:
            r = c.execute("SELECT k.click_url FROM ad_impressions i JOIN ad_campaigns k ON k.id=i.campaign_id WHERE i.id=?", (imp_id,)).fetchone()
            if not r:
                return Response("ไม่พบโฆษณา", status=404)
            col = "clicks_phone" if src == "phone" else "clicks_qr"
            c.execute("UPDATE ad_impressions SET %s=%s+1 WHERE id=?" % (col, col), (imp_id,))
        url = _safe_url(r["click_url"])
        if not url:
            return Response("ปลายทางไม่ถูกต้อง", status=404)
        resp = redirect(url, code=302)
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/ads/overlay.js", methods=["GET"])
    def ads_overlay_js():
        return Response(OVERLAY_JS, mimetype="application/javascript", headers={"Cache-Control": "public, max-age=300"})

    @app.route("/ads/demo", methods=["GET"])
    def ads_demo():
        return Response(DEMO_HTML, mimetype="text/html")

    # ---------------- admin ----------------
    @app.route("/api/ads/admin/campaigns", methods=["GET"])
    @require_staff_rank("admin")
    def api_ads_admin_campaigns():
        with _DB_LOCK, _db() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM ad_campaigns ORDER BY created_at DESC").fetchall()]
        return jsonify({"st": "ok", "campaigns": rows})

    @app.route("/api/ads/admin/campaign", methods=["POST"])
    @require_staff_rank("admin")
    def api_ads_admin_campaign():
        b = request.get_json(silent=True) or {}
        click = _safe_url(b.get("click_url"))
        if not click:
            return jsonify({"st": "error", "msg": "click_url ต้องเป็น http/https"}), 400
        cid = str(b.get("id") or _ad_secrets.token_urlsafe(6))
        img = _safe_url(b.get("image_url"), allow_data=True)
        vals = (
            cid, str(b.get("title") or "")[:120], str(b.get("advertiser") or "")[:80], str(b.get("body") or "")[:300], img, click,
            str(b.get("cta") or "ดูเพิ่มเติม")[:24], str(b.get("placements") or "*")[:200], max(1, int(b.get("weight", 1))),
            max(0, int(b.get("skip_after", 5))), max(3, int(b.get("duration", 15))), max(0, int(b.get("max_impressions", 0))),
            max(0, int(b.get("per_user_daily_cap", 3))), float(b.get("starts_at", 0) or 0), float(b.get("ends_at", 0) or 0),
            1 if b.get("enabled", True) else 0, _ad_time.time(),
        )
        with _DB_LOCK, _db() as c:
            c.execute("""INSERT INTO ad_campaigns(id,title,advertiser,body,image_url,click_url,cta,placements,weight,skip_after,duration,
                         max_impressions,per_user_daily_cap,starts_at,ends_at,enabled,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(id) DO UPDATE SET title=excluded.title,advertiser=excluded.advertiser,body=excluded.body,
                         image_url=excluded.image_url,click_url=excluded.click_url,cta=excluded.cta,placements=excluded.placements,
                         weight=excluded.weight,skip_after=excluded.skip_after,duration=excluded.duration,
                         max_impressions=excluded.max_impressions,per_user_daily_cap=excluded.per_user_daily_cap,
                         starts_at=excluded.starts_at,ends_at=excluded.ends_at,enabled=excluded.enabled""", vals)
        audit("ad_campaign_saved", uid=_uid(), campaign=cid)
        return jsonify({"st": "ok", "id": cid})

    @app.route("/api/ads/admin/toggle", methods=["POST"])
    @require_staff_rank("admin")
    def api_ads_admin_toggle():
        b = request.get_json(silent=True) or {}
        with _DB_LOCK, _db() as c:
            c.execute("UPDATE ad_campaigns SET enabled=? WHERE id=?", (1 if b.get("enabled") else 0, str(b.get("id") or "")))
        return jsonify({"st": "ok"})

    @app.route("/api/ads/admin/stats", methods=["GET"])
    @require_staff_rank("admin")
    def api_ads_admin_stats():
        with _DB_LOCK, _db() as c:
            rows = c.execute("""SELECT k.id, k.title, COUNT(i.id) AS impressions,
                SUM(i.completed_at>0) AS completed, SUM(i.skipped_at>0) AS skipped, SUM(i.sent_phone_at>0) AS sent_phone,
                COALESCE(SUM(i.clicks_qr),0) AS clicks_qr, COALESCE(SUM(i.clicks_phone),0) AS clicks_phone
                FROM ad_campaigns k LEFT JOIN ad_impressions i ON i.campaign_id=k.id GROUP BY k.id""").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            imp = d["impressions"] or 0
            d["ctr"] = round(((d["clicks_qr"] or 0) + (d["clicks_phone"] or 0)) / imp, 4) if imp else 0
            out.append(d)
        return jsonify({"st": "ok", "stats": out})

    # ---------------- เสียบสคริปต์เข้า "/" อัตโนมัติ (ปิดได้: VMAX_ADS_AUTOINJECT=0) ----------------
    @app.after_request
    def _ads_autoinject(resp):
        try:
            if (_ad_os.environ.get("VMAX_ADS_AUTOINJECT", "1") != "0" and request.path == "/"
                    and resp.mimetype == "text/html" and not resp.direct_passthrough):
                html = resp.get_data(as_text=True)
                tag = '<script src="/ads/overlay.js" defer></script>'
                if "/ads/overlay.js" not in html and "</body>" in html:
                    resp.set_data(html.replace("</body>", tag + "</body>", 1))
        except Exception:
            pass
        return resp

    vm = g.get("VMAX_MODULES")
    if isinstance(vm, dict):
        vm["ad_overlay"] = {
            "desc": "โฆษณาแบ่งจอ + QR Code ติดตามเฉพาะ impression + ปุ่มส่งไปที่โทรศัพท์ (account-based push ผ่าน Socket.IO) "
                    "พร้อมแคมเปญ/ขีดจำกัดต่อวัน/สถิติ CTR สำหรับแอดมิน",
            "routes": ["/api/ads/request", "/api/ads/event", "/api/ads/send_phone", "/api/ads/inbox", "/api/ads/inbox/ack",
                       "/ads/overlay.js", "/ads/demo", "/api/ads/admin/campaigns", "/api/ads/admin/campaign",
                       "/api/ads/admin/toggle", "/api/ads/admin/stats"],
        }
    print("[Ad Overlay] ✅ ต่อโมดูลโฆษณาแล้ว — เดโม: /ads/demo  | เพิ่มแคมเปญ: POST /api/ads/admin/campaign")


def register_push_backend(fn):
    """ต่อช่องทางเสริม เช่น FCM/LINE: fn(uid, payload)->bool"""
    PUSH_BACKENDS.append(fn)
