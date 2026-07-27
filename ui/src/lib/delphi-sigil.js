/* eslint-disable no-unused-vars */
// <delphi-sigil state="thinking"> — Delphi's mark.
// A wireframe sphere with three "appendages" that slither along its spherical
// coordinate surface: each is a curve (theta(u), phi(u)) sampled into a tapering
// body, so they crawl over the globe, cross in front of the nucleus, and coil
// away. State changes their speed, reach, coil and colour, and the nucleus'
// pulse. Depth comes from perspective projection: what's behind the sphere is
// drawn dimmer and thinner, before the core; what's in front is drawn after it.
(() => {
  const TAU = Math.PI * 2;

  const STATES = {
    listening: { core: '#e4e7f5', core2: '#9397ab', body: '#b2b6ca', wire: 'rgba(179,182,202,0.90)',
      speed: 0.11, amp: 0.30, coil: 1.0, len: 1.6, reach: 0.05, pulse: 6.5, glow: 0.26, wireA: 0.15 },
    thinking:  { core: '#f5f4ff', core2: '#9184d9', body: '#b5abfc', wire: 'rgba(145,132,217,0.95)',
      speed: 0.40, amp: 0.55, coil: 1.7, len: 2.0, reach: 0.42, pulse: 3.2, glow: 0.52, wireA: 0.20 },
    creating:  { core: '#ffffff', core2: '#d2cefd', body: '#f5f4ff', wire: 'rgba(210,206,253,1)',
      speed: 1.05, amp: 0.85, coil: 2.6, len: 2.5, reach: 0.95, pulse: 0.9, glow: 0.9, wireA: 0.26 },
    dreaming:  { core: '#b5abfc', core2: '#5d5294', body: '#796cbf', wire: 'rgba(145,132,217,0.85)',
      speed: 0.05, amp: 0.42, coil: 0.7, len: 2.9, reach: 0.12, pulse: 7.5, glow: 0.20, wireA: 0.12 },
  };

  const rot = (p, yaw, pitch) => {
    const cy = Math.cos(yaw), sy = Math.sin(yaw);
    const x1 = p.x * cy + p.z * sy, z1 = -p.x * sy + p.z * cy;
    const cp = Math.cos(pitch), sp = Math.sin(pitch);
    return { x: x1, y: p.y * cp - z1 * sp, z: p.y * sp + z1 * cp };
  };
  const sph = (t, f, r) => ({ x: r * Math.sin(t) * Math.cos(f), y: r * Math.cos(t), z: r * Math.sin(t) * Math.sin(f) });

  class DelphiSigil extends HTMLElement {
    static get observedAttributes() { return ['state']; }

    connectedCallback() {
      if (this._built) return;
      this._built = true;
      this.style.cssText += ';display:block;position:relative;width:100%;height:100%';
      this.canvas = document.createElement('canvas');
      this.canvas.style.cssText = 'display:block;position:absolute;inset:0;width:100%;height:100%';
      this.appendChild(this.canvas);
      this.ctx = this.canvas.getContext('2d');
      this._ro = new ResizeObserver(() => this._resize());
      this._ro.observe(this);
      this._resize();
      this._t0 = performance.now();
      this._still = matchMedia('(prefers-reduced-motion: reduce)').matches;
      this._loop();
    }
    disconnectedCallback() { cancelAnimationFrame(this._raf); this._ro?.disconnect(); }
    attributeChangedCallback() { this._draw(this._last || 0); }

    _resize() {
      const dpr = Math.min(devicePixelRatio || 1, 2);
      const r = this.getBoundingClientRect();
      this.w = Math.max(1, r.width); this.h = Math.max(1, r.height);
      this.canvas.width = Math.round(this.w * dpr);
      this.canvas.height = Math.round(this.h * dpr);
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    _loop() {
      this._raf = requestAnimationFrame(() => this._loop());
      const t = this._still ? 3.2 : (performance.now() - this._t0) / 1000;
      this._draw(t);
    }

    _draw(t) {
      this._last = t;
      const c = this.ctx, w = this.w, h = this.h;
      if (!c || !w) return;
      const cfg = STATES[(this.getAttribute('state') || 'thinking').toLowerCase()] || STATES.thinking;
      const cx = w / 2, cy = h / 2;
      const R = Math.min(w, h) * 0.30;
      const f = R * 4.2;
      c.clearRect(0, 0, w, h);

      const yaw = t * 0.22 + Math.sin(t * 0.13) * 0.35;
      const pitch = -0.28 + Math.sin(t * 0.09) * 0.18;
      const P = (p) => { const q = rot(p, yaw, pitch); const s = f / (f + q.z); return { x: cx + q.x * s, y: cy + q.y * s, z: q.z, s }; };

      // ambient bloom
      const bloom = c.createRadialGradient(cx, cy, 0, cx, cy, R * 2.1);
      bloom.addColorStop(0, `rgba(145,132,217,${0.16 * cfg.glow + 0.05})`);
      bloom.addColorStop(1, 'rgba(145,132,217,0)');
      c.fillStyle = bloom; c.fillRect(0, 0, w, h);

      // ── wireframe globe, split front/back ─────────────────────────────
      const wireRing = (theta, phiOff, tilt, r, front) => {
        c.beginPath();
        let started = false;
        for (let i = 0; i <= 72; i++) {
          const a = (i / 72) * TAU;
          let p = theta == null
            ? sph(Math.acos(Math.max(-1, Math.min(1, Math.cos(tilt) * Math.sin(a)))), a + phiOff, r)
            : sph(theta, a + phiOff, r);
          const q = P(p);
          const isFront = q.z <= 0;
          if (isFront !== front) { started = false; continue; }
          if (!started) { c.moveTo(q.x, q.y); started = true; } else c.lineTo(q.x, q.y);
        }
        c.stroke();
      };
      const drawGlobe = (front) => {
        c.lineWidth = 1;
        c.strokeStyle = cfg.wire.replace(/[\d.]+\)$/, (front ? cfg.wireA * 1.9 : cfg.wireA * 0.7) + ')');
        for (let k = 0; k < 6; k++) {
          c.beginPath();
          let started = false;
          const phi = (k / 6) * Math.PI;
          for (let i = 0; i <= 60; i++) {
            const th = (i / 60) * Math.PI;
            const q = P(sph(th, phi, R));
            const isFront = q.z <= 0;
            if (isFront !== front) { started = false; continue; }
            if (!started) { c.moveTo(q.x, q.y); started = true; } else c.lineTo(q.x, q.y);
          }
          c.stroke();
        }
        for (let k = 1; k < 5; k++) wireRing((k / 5) * Math.PI, 0, 0, R, front);
      };

      // armillary rings outside the globe — the reference's gimbal
      const armillary = (front) => {
        const rings = [
          { r: R * 1.30, tilt: 0.10, spin: t * 0.16, a: 0.5 },
          { r: R * 1.18, tilt: 1.15, spin: -t * 0.11, a: 0.38 },
          { r: R * 1.42, tilt: 0.62, spin: t * 0.07, a: 0.24 },
        ];
        for (const rg of rings) {
          c.lineWidth = 1;
          c.strokeStyle = cfg.wire.replace(/[\d.]+\)$/, (rg.a * (front ? 0.85 : 0.28)) + ')');
          c.beginPath();
          let started = false;
          for (let i = 0; i <= 96; i++) {
            const a = (i / 96) * TAU;
            const base = { x: Math.cos(a) * rg.r, y: Math.sin(a) * rg.r * Math.sin(rg.tilt), z: Math.sin(a) * rg.r * Math.cos(rg.tilt) };
            const q = P(rot(base, rg.spin, 0));
            const isFront = q.z <= 0;
            if (isFront !== front) { started = false; continue; }
            if (!started) { c.moveTo(q.x, q.y); started = true; } else c.lineTo(q.x, q.y);
          }
          c.stroke();
        }
      };

      // ── the three appendages ──────────────────────────────────────────
      // Each body is sampled on the sphere: phi winds with u, theta breathes
      // and reaches, so the snake slithers across the coordinate grid.
      const snakePoint = (i, u, tt) => {
        const ph = (i * TAU) / 3;
        const phi = u * cfg.coil + tt * cfg.speed * 1.7 + ph;
        const theta = Math.PI / 2
          + cfg.amp * Math.sin(u * 0.85 + tt * cfg.speed * 2.1 + ph * 1.7)
          + cfg.reach * 0.62 * Math.sin(tt * cfg.speed * 0.85 + ph * 2.1);
        const clamped = Math.max(0.22, Math.min(Math.PI - 0.22, theta));
        return sph(clamped, phi, R * 1.045);
      };
      const N = 52;
      const drawSnakes = (front) => {
        for (let i = 0; i < 3; i++) {
          const head = t * cfg.speed * 2.0;
          for (let k = 0; k < N; k++) {
            const u0 = head - (k / N) * cfg.len;
            const u1 = head - ((k + 1) / N) * cfg.len;
            const a = P(snakePoint(i, u0, t)), b = P(snakePoint(i, u1, t));
            const isFront = ((a.z + b.z) / 2) <= 0;
            if (isFront !== front) continue;
            const taper = Math.pow(1 - k / N, 0.7);
            const depth = front ? 1 : 0.28;
            c.lineCap = 'round';
            c.lineWidth = Math.max(0.6, R * 0.115 * taper * a.s * (front ? 1 : 0.7));
            c.strokeStyle = hexA(cfg.body, (0.30 + 0.65 * taper) * depth);
            c.beginPath(); c.moveTo(a.x, a.y); c.lineTo(b.x, b.y); c.stroke();
            if (front && k < 4) {
              c.lineWidth = Math.max(0.5, R * 0.05 * a.s);
              c.strokeStyle = hexA(cfg.core, 0.9);
              c.beginPath(); c.moveTo(a.x, a.y); c.lineTo(b.x, b.y); c.stroke();
            }
          }
        }
      };

      // ── nucleus ───────────────────────────────────────────────────────
      const beat = Math.sin((t / cfg.pulse) * TAU);
      const nr = R * 0.215 * (1 + 0.20 * beat + (cfg.speed > 0.9 ? 0.06 * Math.sin(t * 14) : 0));
      const jx = cfg.speed > 0.9 ? Math.sin(t * 17) * R * 0.02 : 0;
      const jy = cfg.speed > 0.9 ? Math.cos(t * 13) * R * 0.02 : 0;

      drawSnakes(false);

      const halo = c.createRadialGradient(cx + jx, cy + jy, 0, cx + jx, cy + jy, nr * 4.2);
      halo.addColorStop(0, hexA(cfg.core2, 0.5 * cfg.glow));
      halo.addColorStop(1, hexA(cfg.core2, 0));
      c.fillStyle = halo;
      c.beginPath(); c.arc(cx + jx, cy + jy, nr * 4.2, 0, TAU); c.fill();

      const core = c.createRadialGradient(cx + jx - nr * 0.3, cy + jy - nr * 0.35, 0, cx + jx, cy + jy, nr);
      core.addColorStop(0, cfg.core);
      core.addColorStop(0.55, cfg.core2);
      core.addColorStop(1, hexA(cfg.core2, 0.55));
      c.fillStyle = core;
      c.beginPath(); c.arc(cx + jx, cy + jy, nr, 0, TAU); c.fill();

      // shed ring on the beat
      const shed = ((t / cfg.pulse) % 1);
      if (cfg.glow > 0.3) {
        c.strokeStyle = hexA(cfg.core, 0.42 * (1 - shed));
        c.lineWidth = 1;
        c.beginPath(); c.arc(cx, cy, nr + shed * R * 1.5, 0, TAU); c.stroke();
      }

      drawSnakes(true);
    }
  }

  function hexA(hex, a) {
    const n = hex.replace('#', '');
    const v = n.length === 3 ? n.split('').map((x) => x + x).join('') : n;
    const r = parseInt(v.slice(0, 2), 16), g = parseInt(v.slice(2, 4), 16), b = parseInt(v.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${Math.max(0, Math.min(1, a))})`;
  }

  if (!customElements.get('delphi-sigil')) customElements.define('delphi-sigil', DelphiSigil);
})();
