/* VMAX Game Service SDK v1.0.0 — smoke / flashlight (wall of light) / breaker panels for any game
 *
 *   const svc = new VMAXGameService({ gameId: 'my-game' });          // token: localStorage 'vmax_token' หรือส่ง { token } / { tokenProvider }
 *   const s = await svc.createSession({ x: 100, y: 200, hp: 100, mode: 'normal' });
 *   s.startAutoSync(() => ({ x: player.x, y: player.y, aim: player.aim, hp: player.hp,
 *                            enemies: enemies.map(e => ({ id: e.id, x: e.x, y: e.y, hp: e.hp, alive: e.alive })) }));
 *   s.on('effects', fx => { ... });           // ทุกครั้งที่ server ตอบ
 *   s.on('damage', d => player.hp -= d.amount); // hp_delta < 0 (อาร์คแฟลช ฯลฯ)
 *   s.on('enemies', list => applyToYourEnemies(list));  // hp/alive/blind_left หลังโดนอาร์ค/ไฟฉาย
 *   await s.toggleLight(); await s.setPreset('warm_low'); await s.throwSmoke(tx, ty);
 *   const shot = await s.shot();               // { miss, reason, beacon, beacon_bonus_damage } — เรียกก่อนคำนวณการยิงของเกม
 *   await s.shootBreaker({ hitZone: 'live' }); await s.switchBreaker(); await s.repairBreaker();
 *   // ทุกเฟรมวาด:  s.draw(ctx, { camX, camY, width, height });
 *   s.close();
 */
(function (root) {
  'use strict';
  if (root.VMAXGameService) return;

  function VMAXGameError(message, status, code, data) {
    const e = new Error(message); e.name = 'VMAXGameError'; e.status = status; e.code = code; e.data = data; return e;
  }

  class VMAXGameSession {
    constructor(svc, data) {
      this.svc = svc; this.id = data.session_id; this.gameId = data.game_id; this.config = data.config || {};
      this.effects = data.effects || {}; this.closed = false;
      this._l = {}; this._q = Promise.resolve(); this._seenFx = {}; this._timer = null; this._inflight = false;
      this._pos = { x: 0, y: 0, aim: 0 };
      this._repairTimers = {};
    }
    on(evt, fn) { (this._l[evt] = this._l[evt] || []).push(fn); return this; }
    off(evt, fn) { this._l[evt] = (this._l[evt] || []).filter(f => f !== fn); return this; }
    _emit(evt, v) { (this._l[evt] || []).slice().forEach(f => { try { f(v); } catch (e) { console.error('[VMAXGameService]', e); } }); }
    _path(suffix) { return '/api/game-service/' + encodeURIComponent(this.gameId) + '/session/' + encodeURIComponent(this.id) + (suffix ? '/' + suffix : ''); }
    _apply(data) {
      const fx = data.effects; if (!fx) return data;
      this.effects = fx; this._emit('effects', fx);
      if (fx.hp_delta < 0) this._emit('damage', { amount: -fx.hp_delta, hp: fx.hp });
      if (fx.dead) this._emit('dead', fx);
      if (fx.enemies && fx.enemies.length) this._emit('enemies', fx.enemies);
      (fx.fx || []).forEach(f => { if (!this._seenFx[f.id]) { this._seenFx[f.id] = 1; this._emit(f.type, f); } });
      return data;
    }
    // คิวแบบเรียงลำดับ: คำสั่งที่เปลี่ยน state จะไม่ชนกันเอง
    _call(method, suffix, body) {
      if (this.closed) return Promise.reject(VMAXGameError('session closed', 0, 'closed'));
      const run = () => this.svc._req(method, this._path(suffix), body).then(d => this._apply(d));
      const p = this._q.then(run, run);
      this._q = p.catch(() => {});
      p.catch(err => this._emit('error', err));
      return p;
    }
    refresh() { return this._call('GET', ''); }
    sync(state) {
      if (state) { if (state.x != null) this._pos.x = state.x; if (state.y != null) this._pos.y = state.y; if (state.aim != null) this._pos.aim = state.aim; }
      return this._call('POST', 'sync', state || {});
    }
    startAutoSync(getState, intervalMs) {
      this.stopAutoSync();
      this._timer = setInterval(() => {
        if (this._inflight || this.closed) return;
        this._inflight = true;
        this.sync(getState()).catch(() => {}).then(() => { this._inflight = false; });
      }, intervalMs || 250);
      return this;
    }
    stopAutoSync() { if (this._timer) { clearInterval(this._timer); this._timer = null; } return this; }
    setLight(opts) { return this._call('POST', 'light', opts || {}); }
    toggleLight() { return this.setLight({}); }
    setPreset(preset) { return this.setLight({ preset: preset }); }
    cyclePreset() {
      const ids = (this.config.presets || []).map(p => p.id); const cur = (this.effects.light || {}).preset;
      if (!ids.length) return Promise.resolve(null);
      return this.setPreset(ids[(ids.indexOf(cur) + 1) % ids.length]);
    }
    throwSmoke(targetX, targetY) {
      const b = {}; if (targetX != null) { b.target_x = targetX; b.target_y = targetY; }
      return this._call('POST', 'smoke', b);
    }
    // เรียกก่อนคำนวณการยิงของเกม -> { miss, reason, beacon, beacon_bonus_damage }
    shot(opts) { return this._call('POST', 'shot', opts || {}).then(d => d.shot); }
    nearestBreaker(x, y, maxDist) {
      const px = x != null ? x : this._pos.x, py = y != null ? y : this._pos.y; let best = null, bd = Infinity;
      (this.effects.breakers || []).forEach(b => { const d = Math.hypot(b.x - px, b.y - py); if (d < bd) { bd = d; best = b; } });
      return best && (maxDist == null || bd <= maxDist) ? best : null;
    }
    shootBreaker(opts) {
      opts = opts || {}; const id = opts.breakerId || (this.nearestBreaker() || {}).id;
      return this._call('POST', 'breaker/shoot', { breaker_id: id, hit_zone: opts.hitZone || 'auto' }).then(d => d.result);
    }
    switchBreaker(breakerId) {
      const id = breakerId || (this.nearestBreaker() || {}).id; return this._call('POST', 'breaker/switch', { breaker_id: id });
    }
    // เริ่มซ่อม แล้วตั้งเวลาเรียกซ่อมเสร็จให้อัตโนมัติ (resolve เมื่อซ่อมเสร็จ / ถูกยกเลิกเพราะเดินออก)
    repairBreaker(breakerId) {
      const id = breakerId || (this.nearestBreaker() || {}).id;
      return this._call('POST', 'breaker/repair', { breaker_id: id }).then(d => {
        if (!(d.repair && d.repair.started)) return d;
        return new Promise((resolve, reject) => {
          clearTimeout(this._repairTimers[id]);
          this._repairTimers[id] = setTimeout(() => {
            this._call('POST', 'breaker/repair', { breaker_id: id }).then(resolve, reject);
          }, (d.repair.seconds || 5) * 1000 + 250);
        });
      });
    }
    close() {
      if (this.closed) return Promise.resolve();
      this.stopAutoSync(); Object.keys(this._repairTimers).forEach(k => clearTimeout(this._repairTimers[k]));
      this.closed = true;
      return this.svc._req('DELETE', this._path(''), undefined, true).catch(() => {});
    }
    // ---- Canvas 2D renderer (ควัน, โซนไฟดับ, ตู้เบรกเกอร์, กรวยไฟฉาย, กำแพงแสง, อาร์คแฟลช) ----
    // o = { camX, camY, width, height, playerX?, playerY? }   (world -> screen = world - cam)
    draw(ctx, o) {
      const fx = this.effects || {}, L = fx.light || {}; o = o || {};
      const cx = o.camX || 0, cy = o.camY || 0, W = o.width || ctx.canvas.width, H = o.height || ctx.canvas.height;
      const px = (o.playerX != null ? o.playerX : this._pos.x) - cx, py = (o.playerY != null ? o.playerY : this._pos.y) - cy;
      const S = (x, y) => ({ x: x - cx, y: y - cy });
      ctx.save();
      (fx.zones || []).forEach(z => {
        if (fx.power && fx.power[z.id] === false) { const q = S(z.x, z.y); ctx.fillStyle = 'rgba(2,4,14,.58)'; ctx.fillRect(q.x, q.y, z.w, z.h); }
      });
      const COL = { on: '#3fbf6f', off: '#8a8f94', jammed_on: '#e0a93a', jammed_off: '#e0a93a', arc_destroyed: '#3b2626' };
      (fx.breakers || []).forEach(b => {
        const q = S(b.x, b.y);
        ctx.fillStyle = '#22262a'; ctx.fillRect(q.x - 15, q.y - 20, 30, 40);
        ctx.fillStyle = COL[b.state] || '#888'; ctx.fillRect(q.x - 11, q.y - 16, 22, 10);
        ctx.fillStyle = '#111'; ctx.fillRect(q.x - 11, q.y - 2, 22, 14);
        ctx.fillStyle = 'rgba(255,255,255,.85)'; ctx.font = '11px system-ui'; ctx.fillText(String(b.state).replace('_', ' ').toUpperCase(), q.x - 24, q.y + 34);
      });
      (fx.smoke_clouds || []).forEach(s => {
        const q = S(s.x, s.y), a = 0.78 * (s.fade == null ? 1 : s.fade);
        for (let i = 0; i < 5; i++) {
          const ox = Math.cos(i * 1.9 + s.x) * s.r * 0.35, oy = Math.sin(i * 2.3 + s.y) * s.r * 0.3;
          const g = ctx.createRadialGradient(q.x + ox, q.y + oy, 4, q.x + ox, q.y + oy, s.r * 0.75);
          g.addColorStop(0, 'rgba(170,175,180,' + a * 0.55 + ')'); g.addColorStop(1, 'rgba(170,175,180,0)');
          ctx.fillStyle = g; ctx.beginPath(); ctx.arc(q.x + ox, q.y + oy, s.r * 0.75, 0, 6.283); ctx.fill();
        }
      });
      if (L.on) {
        const warm = L.preset === 'warm_low', col = warm ? '255,214,140' : '235,245,255', a0 = L.preset === 'ground_low' ? 0.10 : 0.2;
        ctx.save(); ctx.translate(px, py); ctx.rotate(L.aim || 0);
        const g = ctx.createRadialGradient(0, 0, 10, 0, 0, L.reach || 200);
        g.addColorStop(0, 'rgba(' + col + ',' + a0 * 2 + ')'); g.addColorStop(1, 'rgba(' + col + ',0)');
        ctx.fillStyle = g; ctx.beginPath(); ctx.moveTo(0, 0); ctx.arc(0, 0, L.reach || 200, -0.42, 0.42); ctx.closePath(); ctx.fill(); ctx.restore();
        if (L.smoke_density > 0.05) {
          const r = 60 + 170 * L.smoke_density, g2 = ctx.createRadialGradient(px, py, 6, px, py, r);
          g2.addColorStop(0, 'rgba(255,255,255,' + 0.55 * L.smoke_density + ')'); g2.addColorStop(1, 'rgba(255,255,255,0)');
          ctx.fillStyle = g2; ctx.beginPath(); ctx.arc(px, py, r, 0, 6.283); ctx.fill();
        }
      }
      (fx.fx || []).forEach(f => {
        const q = S(f.x, f.y), age = f.age || 0, k = Math.max(0, 1 - age / (f.ttl || 1));
        if (f.type === 'arc_flash') {
          const g = ctx.createRadialGradient(q.x, q.y, 4, q.x, q.y, 150);
          g.addColorStop(0, 'rgba(255,255,255,' + k + ')'); g.addColorStop(0.4, 'rgba(170,200,255,' + 0.55 * k + ')'); g.addColorStop(1, 'rgba(170,200,255,0)');
          ctx.fillStyle = g; ctx.beginPath(); ctx.arc(q.x, q.y, 150, 0, 6.283); ctx.fill();
        } else if (f.type === 'sparks' || f.type === 'spark_small') {
          ctx.strokeStyle = 'rgba(255,210,90,' + k + ')'; ctx.lineWidth = 2;
          for (let i = 0; i < 9; i++) {
            const an = i * 0.7 + f.x, ln = 8 + ((i * 7) % 5) * 5 * (1 - k * 0.4);
            ctx.beginPath(); ctx.moveTo(q.x + Math.cos(an) * 6, q.y + Math.sin(an) * 6); ctx.lineTo(q.x + Math.cos(an) * (6 + ln), q.y + Math.sin(an) * (6 + ln)); ctx.stroke();
          }
        }
      });
      const wo = Math.max(L.whiteout || 0, Math.min(1, (fx.blind_left || 0) / 1.2));
      if (wo > 0.03) {
        const g = ctx.createRadialGradient(W / 2, H / 2, 40, W / 2, H / 2, Math.max(W, H) * 0.6);
        g.addColorStop(0, 'rgba(255,255,255,' + Math.min(0.95, wo * 0.95) + ')'); g.addColorStop(1, 'rgba(245,248,255,' + Math.min(0.98, wo) + ')');
        ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
      }
      ctx.restore();
    }
  }

  class VMAXGameService {
    constructor(opts) {
      opts = opts || {};
      if (!opts.gameId) throw new Error('VMAXGameService: gameId is required');
      this.gameId = String(opts.gameId).toLowerCase(); this.baseUrl = (opts.baseUrl || '').replace(/\/+$/, '');
      this.token = opts.token || null; this.tokenProvider = opts.tokenProvider || null;
    }
    _token() {
      if (this.tokenProvider) return this.tokenProvider();
      if (this.token) return this.token;
      try { return localStorage.getItem('vmax_token') || ''; } catch (e) { return ''; }
    }
    _req(method, path, body, keepalive) {
      const headers = { 'Authorization': 'Bearer ' + this._token() };
      if (body !== undefined) headers['Content-Type'] = 'application/json';
      return fetch(this.baseUrl + path, { method: method, headers: headers, keepalive: !!keepalive,
        body: body === undefined ? undefined : JSON.stringify(body) }).then(r =>
        r.json().catch(() => null).then(d => {
          if (!r.ok || !d || d.st !== 'ok') throw VMAXGameError((d && d.msg) || ('HTTP ' + r.status), r.status, d && d.code, d);
          return d;
        }));
    }
    listGames() { return this._req('GET', '/api/game-service/games').then(d => d.games); }
    // opts: { mode, x, y, hp, max_hp, aim, glasses_equipped, zones:[{id,name,x,y,w,h}], breakers:[{id,x,y,zone}] }
    createSession(opts) {
      return this._req('POST', '/api/game-service/' + encodeURIComponent(this.gameId) + '/session', opts || {})
        .then(d => new VMAXGameSession(this, d));
    }
  }

  VMAXGameService.Session = VMAXGameSession;
  VMAXGameService.version = '1.0.0';
  root.VMAXGameService = VMAXGameService;
})(typeof window !== 'undefined' ? window : this);
