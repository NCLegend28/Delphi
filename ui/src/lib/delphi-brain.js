// <delphi-brain fill="0.78" zone="0"> — the holographic knowledge graph.
// Each discipline is a dendritic tree grown outward from a common core: branches
// fork, curve, and taper to terminal beads. The tree's reach is bounded by the
// bitspace enclosure — a translucent volume whose radius IS the fill fraction.
// The active zone's pathways draw as solid bright lines carrying pulses of
// information, so you can see where the thinking is happening.
// Drag to spin; it returns to its own drift.
(() => {
  const TAU = Math.PI * 2;
  const ACC = '#9184d9', HOT = '#d2cefd', NEU = '#9397ab';

  // One value per zone, each a declared token: accent-2-300, section-ghost,
  // accent-2-500, neutral-400, accent.
  const ZONES = [
    { name: 'CODE & MODELS', dir: [-0.66, 0.40, 0.26], color: '#d2cefd', trunks: 4, depth: 5 },
    { name: 'TRADING', dir: [0.70, 0.38, -0.20], color: '#4c5397', trunks: 4, depth: 4 },
    { name: 'LANGUAGE', dir: [0.56, -0.54, 0.24], color: '#9690c9', trunks: 3, depth: 4 },
    { name: 'INFRA & DEPLOY', dir: [-0.54, -0.56, -0.26], color: '#b2b6ca', trunks: 3, depth: 4 },
    { name: 'DELPHI HERSELF', dir: [0.04, 0.10, 0.74], color: '#9184d9', trunks: 3, depth: 3 },
  ];

  // Every terminal bead is a real thing she knows — a note, a file, a project or
  // an entity. Names are per-zone so a bead's label tells you which discipline
  // it belongs to before you read it.
  const NAMES = [
    [['judge-rubric.md','note'],['judge.py','file'],['nursery/curriculum','project'],['roster hot-reload','note'],['promotion threshold','note'],['qwen3-coder:480b','entity'],['gpt-oss:120b','entity'],['classifier prompt','file'],['0–4 rubric axes','note'],['candidate 2.4→2.9','note'],['eval harness','project'],['scoring drift log','note'],['pinning policy','note'],['nursery/judge','file'],['refusal calibration','note']],
    [['alpaca paper keys','note'],['squeeze detector','project'],['FinBERT sentiment','entity'],['options flow feed','file'],['backtest harness','project'],['Financio','project'],['position sizing','note'],['webull bridge','file'],['risk ceiling','note'],['signal pipeline','project'],['paper→live gate','note'],['market data cache','file']],
    [['GRE set 12','project'],['obviate','entity'],['truculent','entity'],['laconic','entity'],['SRS intervals','note'],['verbal section 14/27','note'],['mnemonic drafts','file'],['missed-twice queue','note'],['vocab source list','file'],['review streak','note']],
    [['caddy bearer inject','note'],['tailnet boundary','note'],['.env.docker','file'],['worker :9100','entity'],['redis arq','entity'],['fail-open offload','note'],['compose stack','file'],['readyz probe','note'],['TLS at the edge','note']],
    [['soul.py','file'],['directive grammar','note'],['mode → colour map','note'],['what I am','note'],['memory pipeline','project'],['bitspace budget','note'],['speech playback','file'],['first-person voice','note']],
  ];

  const mul = (s) => () => { s |= 0; s = (s + 0x6D2B79F5) | 0; let t = Math.imul(s ^ (s >>> 15), 1 | s); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };

  function hexA(hex, a) {
    const n = hex.replace('#', '');
    const r = parseInt(n.slice(0, 2), 16), g = parseInt(n.slice(2, 4), 16), b = parseInt(n.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${Math.max(0, Math.min(1, a))})`;
  }
  const rot = (p, yaw, pitch) => {
    const cy = Math.cos(yaw), sy = Math.sin(yaw);
    const x1 = p[0] * cy + p[2] * sy, z1 = -p[0] * sy + p[2] * cy;
    const cp = Math.cos(pitch), sp = Math.sin(pitch);
    return [x1, p[1] * cp - z1 * sp, p[1] * sp + z1 * cp];
  };
  const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
  const scale = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
  const norm = (a) => { const l = Math.hypot(...a) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
  const bez = (a, c, b, u) => {
    const m = 1 - u;
    return [m * m * a[0] + 2 * m * u * c[0] + u * u * b[0],
            m * m * a[1] + 2 * m * u * c[1] + u * u * b[1],
            m * m * a[2] + 2 * m * u * c[2] + u * u * b[2]];
  };

  class DelphiBrain extends HTMLElement {
    static get observedAttributes() { return ['fill', 'zone', 'query', 'highlight', 'data-nodes']; }

    connectedCallback() {
      if (this._built) return;
      this._built = true;
      this.style.cssText += ';display:block;position:relative;width:100%;height:100%;cursor:grab';
      this.canvas = document.createElement('canvas');
      this.canvas.style.cssText = 'display:block;position:absolute;inset:0;width:100%;height:100%';
      this.appendChild(this.canvas);
      this.ctx = this.canvas.getContext('2d');
      this._build();
      this._ro = new ResizeObserver(() => this._resize());
      this._ro.observe(this);
      this._resize();
      this._yaw = this._homeYaw ?? 0.4; this._pitch = this._homePitch ?? -0.20;
      this._drag = null; this._spin = 0.05;
      this.addEventListener('pointerdown', (e) => {
        this._down = { x: e.clientX, y: e.clientY, yaw: this._yaw, pitch: this._pitch, node: this._hover };
        // On a node, hold the pointer for a click; never start a drag from it.
        if (!this._hover) this.style.cursor = 'grabbing';
        this.setPointerCapture(e.pointerId);
      });
      this.addEventListener('pointermove', (e) => {
        const d = this._down;
        if (!d) return;
        const dx = e.clientX - d.x, dy = e.clientY - d.y;
        if (!this._drag) {
          if (Math.hypot(dx, dy) < 4) return;              // deadzone: a click never rotates
          this._drag = d; this._touched = true;
        }
        const k = 2.6 / Math.max(240, this.w || 400);
        this._yaw = d.yaw - dx * k;
        this._pitch = Math.max(-1.15, Math.min(1.15, d.pitch + dy * k * 0.85));
      });
      const up = () => {
        const d = this._down, dragged = !!this._drag;
        this._down = null; this._drag = null;
        this.style.cursor = this._hover ? 'pointer' : 'grab';
        if (dragged || !d) return;
        if (d.node) this._select(d.node);
        else if (this.selected) {           // a click in empty space lets it go
          this.selected = null;
          this.dispatchEvent(new CustomEvent('node-clear', { bubbles: true, composed: true }));
        }
      };
      this.addEventListener('pointerup', up);
      this.addEventListener('pointercancel', () => { this._down = null; this._drag = null; });
      this.addEventListener('pointermove', (e) => {
        const r = this.getBoundingClientRect();
        this._mx = e.clientX - r.left; this._my = e.clientY - r.top;
      });
      this.addEventListener('pointerleave', () => { this._mx = null; this._my = null; this._hover = null; });
      this._t0 = performance.now();
      this._still = matchMedia('(prefers-reduced-motion: reduce)').matches;
      this._loop();
    }
    disconnectedCallback() { cancelAnimationFrame(this._raf); this._ro?.disconnect(); }

    // Selecting a bead is how you get to the thing it stands for. The host
    // listens for this and opens the note, file, project or entity.
    _select(n) {
      this.selected = n;
      this.dispatchEvent(new CustomEvent('node-select', {
        bubbles: true, composed: true,
        detail: { name: n.name, kind: n.kind, zone: ZONES[n.zone].name, zoneIndex: n.zone },
      }));
    }
    get nodes() { return this.tips; }
    find(q) {
      const s = (q || '').trim().toLowerCase();
      if (!s) return [];
      return this.tips.filter((n) => n.name && n.name.toLowerCase().includes(s));
    }
    focusNode(name) {
      const n = this.tips.find((t) => t.name === name);
      if (!n) return;
      const d = norm(n.p);
      this._touched = true;
      this._yaw = Math.atan2(d[0], -d[2]);
      this._pitch = Math.max(-1.1, Math.min(1.1, -Math.asin(d[1]) * 0.9));
      this._select(n);
    }
    attributeChangedCallback(name) {
      if (!this._built) return;
      if (name === 'query') return;
      if (name === 'highlight') { this._aimAtHighlight(); return; }
      this._build();
    }

    // Bring a zone round to face the viewer — a soft ease, not a jump.
    _aimAtHighlight() {
      const i = parseInt(this.getAttribute('highlight') ?? '-1', 10);
      if (!Number.isInteger(i) || i < 0 || !ZONES[i]) { this._aim = null; return; }
      const d = norm(ZONES[i].dir);
      let yaw = Math.atan2(d[0], -d[2]);
      // take the short way round
      while (yaw - this._yaw > Math.PI) yaw -= TAU;
      while (yaw - this._yaw < -Math.PI) yaw += TAU;
      this._aim = { yaw, pitch: Math.max(-0.8, Math.min(0.8, -Math.asin(d[1]) * 0.8)) };
      this._touched = true;
    }

    _namesFromAttribute() {
      const raw = this.getAttribute('data-nodes');
      if (!raw) return null;
      const grouped = ZONES.map(() => []);
      try {
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return grouped;
        for (const node of parsed) {
          if (!node || typeof node !== 'object') continue;
          const zi = Number.isInteger(node.zone_index) ? node.zone_index : ZONES.findIndex((z) => z.name === String(node.zone || '').toUpperCase());
          if (!ZONES[zi]) continue;
          const name = String(node.name || node.path || '').trim();
          if (!name) continue;
          grouped[zi].push([name, String(node.kind || 'note'), String(node.path || name)]);
        }
      } catch {
        return grouped;
      }
      return grouped;
    }

    _build() {
      const fill = Math.max(0.05, Math.min(1, parseFloat(this.getAttribute('fill') || '0.78')));
      this.fill = fill;
      this.used = Math.cbrt(fill);
      this.active = parseInt(this.getAttribute('zone') || '0', 10) || 0;
      const rnd = mul(20260727);
      const jitter = (k) => [(rnd() - 0.5) * k, (rnd() - 0.5) * k, (rnd() - 0.5) * k];
      const sourceNames = this._namesFromAttribute();
      const used = ZONES.map(() => 0);
      const pick = (zi) => {
        const list = sourceNames
          ? (sourceNames[zi]?.length ? sourceNames[zi] : [[ZONES[zi].name.toLowerCase(), 'zone', ZONES[zi].name]])
          : NAMES[zi];
        const i = used[zi]++;
        const e = list[i % list.length];
        const lap = Math.floor(i / list.length);
        // Past one lap the titles repeat, so number them — every bead stays a
        // distinct thing, and find()/focusNode() can reach each one.
        return { name: lap === 0 ? e[0] : e[0] + ' · ' + (lap + 1), kind: e[1], path: e[2] };
      };

      // branches: {a, c, b, zone, gen, main} quadratic segments; tips: terminal beads
      this.branches = []; this.tips = []; this.paths = [];
      const RMAX = this.used * 0.95;

      ZONES.forEach((z, zi) => {
        const axis = norm(z.dir);
        const root = scale(axis, RMAX * 0.10);
        // an initial spread of trunks fanning along the zone axis
        for (let tr = 0; tr < z.trunks; tr++) {
          const spread = 0.55;
          const dir0 = norm(add(axis, jitter(spread)));
          const chain = [];
          const grow = (from, dir, gen, reach, main) => {
            const len = reach * (gen === 0 ? 0.34 : 0.30 + rnd() * 0.16);
            const nd = norm(add(dir, jitter(gen === 0 ? 0.22 : 0.75)));
            let to = add(from, scale(nd, len));
            const d = Math.hypot(...to);
            if (d > RMAX) to = scale(to, RMAX / d);
            // control point bows the segment — dendrites curve, never straight
            const mid = scale(add(from, to), 0.5);
            const ctrl = add(mid, jitter(len * 0.55));
            const seg = { a: from, c: ctrl, b: to, zone: zi, gen, main };
            this.branches.push(seg);
            if (main) chain.push(seg);
            if (gen >= z.depth - 1 || Math.hypot(...to) > RMAX * 0.985) {
              this.tips.push({ p: to, zone: zi, r: 1.9 + rnd() * 2.2, seed: rnd(), ...pick(zi) });
              return;
            }
            const forks = gen < 2 ? 2 : (rnd() < 0.62 ? 2 : 1);
            for (let k = 0; k < forks; k++) grow(to, nd, gen + 1, reach * 0.86, main && k === 0);
            if (rnd() < 0.5) this.tips.push({ p: to, zone: zi, r: 1.4 + rnd() * 1.2, seed: rnd(), ...pick(zi) });
          };
          grow(root, dir0, 0, RMAX * 0.95, tr < 3);
          if (chain.length) this.paths.push({ zone: zi, chain });
        }
        this.tips.push({ p: root, zone: zi, r: 3.6, seed: 0.5, hub: true, name: z.name.toLowerCase(), kind: 'zone' });
      });

      // cross-discipline arcs — long sweeping links tip-to-tip between zones
      const tipsOf = (zi) => this.tips.filter((t) => t.zone === zi && !t.hub);
      const link = (za, zb, strong) => {
        const A = tipsOf(za), B = tipsOf(zb);
        if (!A.length || !B.length) return;
        const a = A[Math.floor(rnd() * A.length)].p, b = B[Math.floor(rnd() * B.length)].p;
        const mid = scale(add(a, b), 0.5);
        const ctrl = add(mid, scale(norm(mid), RMAX * (0.18 + rnd() * 0.2)));
        this.arcs.push({ a, c: ctrl, b, strong });
      };
      this.arcs = [];
      [[0, 4, 1], [0, 4, 1], [0, 1, 0], [1, 4, 0], [2, 4, 0], [3, 0, 0], [3, 2, 0], [1, 2, 0], [3, 4, 0], [2, 0, 0]]
        .forEach(([a, b, s]) => link(a, b, s));

      this.activePaths = this.paths.filter((p) => p.zone === this.active);
      this.hotArcs = this.arcs.filter((a) => a.strong);

      // Face the active zone: solve for the yaw/pitch that bring its axis toward
      // the viewer (-z), so its label, annotation and lit routes all read on load.
      const d = norm(ZONES[this.active].dir);
      this._homeYaw = Math.atan2(d[0], -d[2]);
      this._homePitch = Math.max(-0.7, Math.min(0.7, -Math.asin(d[1]) * 0.8));
      if (!this._touched) { this._yaw = this._homeYaw; this._pitch = this._homePitch; }
    }

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
      const t = this._still ? 4 : (performance.now() - this._t0) / 1000;
      const dt = t - (this._lt ?? t);
      if (this._aim && !this._drag) {
        const k = Math.min(1, dt * 3.2);
        this._yaw += (this._aim.yaw - this._yaw) * k;
        this._pitch += (this._aim.pitch - this._pitch) * k;
        if (Math.abs(this._aim.yaw - this._yaw) < 0.004) this._aim = null;
      } else if (!this._drag && !this._still) this._yaw += this._spin * dt;
      this._lt = t;
      this._draw(t);
    }

    _draw(t) {
      const c = this.ctx, w = this.w, h = this.h;
      if (!c || !w) return;
      const cx = w / 2, cy = h * 0.5;
      const R = Math.min(w * 0.42, h * 0.45);
      const f = R * 3.8;
      const idle = this._drag ? 0 : 1;
      const yaw = this._yaw + Math.sin(t * 0.11) * 0.05 * idle;
      const pitch = this._pitch + Math.sin(t * 0.07) * 0.05 * idle;
      const P = (p) => { const q = rot(p, yaw, pitch); const s = f / (f + q[2] * R); return { x: cx + q[0] * R * s, y: cy + q[1] * R * s, z: q[2], s }; };

      c.clearRect(0, 0, w, h);
      const bloom = c.createRadialGradient(cx, cy, 0, cx, cy, R * 1.9);
      bloom.addColorStop(0, 'rgba(145,132,217,0.13)');
      bloom.addColorStop(0.62, 'rgba(93,82,148,0.06)');
      bloom.addColorStop(1, 'rgba(93,82,148,0)');
      c.fillStyle = bloom; c.fillRect(0, 0, w, h);

      const near = this.fill > 0.75;
      const alertPulse = 0.5 + 0.5 * Math.sin(t * 2.2);
      const usedPx = R * this.used;

      const headroom = () => {
        const g = c.createRadialGradient(cx, cy, usedPx, cx, cy, R);
        g.addColorStop(0, hexA(NEU, 0.05));
        g.addColorStop(0.92, hexA(NEU, 0.018));
        g.addColorStop(1, hexA(near ? HOT : NEU, 0));
        c.fillStyle = g;
        c.beginPath(); c.arc(cx, cy, R, 0, TAU); c.fill();
        c.strokeStyle = hexA(near ? HOT : NEU, near ? 0.16 + 0.10 * alertPulse : 0.10);
        c.lineWidth = 1;
        c.beginPath(); c.arc(cx, cy, R, 0, TAU); c.stroke();
      };
      const enclosure = (front) => {
        const g = c.createRadialGradient(cx, cy, usedPx * 0.55, cx, cy, usedPx);
        g.addColorStop(0, hexA(ACC, 0));
        g.addColorStop(0.82, hexA(ACC, front ? 0.045 : 0.02));
        g.addColorStop(0.97, hexA(near ? HOT : ACC, front ? (near ? 0.18 + 0.09 * alertPulse : 0.14) : 0.05));
        g.addColorStop(1, hexA(ACC, 0));
        c.fillStyle = g;
        c.beginPath(); c.arc(cx, cy, usedPx, 0, TAU); c.fill();
        if (front) {
          c.strokeStyle = hexA(near ? HOT : ACC, near ? 0.28 + 0.16 * alertPulse : 0.22);
          c.lineWidth = 1.2;
          c.beginPath(); c.arc(cx, cy, usedPx, 0, TAU); c.stroke();
        }
      };

      // draw one quadratic segment, sampled so perspective bends it correctly
      const curve = (a, cp, b, steps) => {
        c.beginPath();
        for (let i = 0; i <= steps; i++) {
          const q = P(bez(a, cp, b, i / steps));
          if (i === 0) c.moveTo(q.x, q.y); else c.lineTo(q.x, q.y);
        }
        c.stroke();
      };
      const depthOf = (seg) => P(bez(seg.a, seg.c, seg.b, 0.5)).z;

      const dendrites = (front) => {
        c.lineCap = 'round';
        for (const s of this.branches) {
          const isF = depthOf(s) <= 0;
          if (isF !== front) continue;
          const zone = ZONES[s.zone];
          const activeZone = s.zone === this.active;
          const taper = Math.max(0.32, 1 - s.gen * 0.17);
          const depth = front ? 1 : 0.30;
          const lift = s.zone === hl ? 1.5 : 1;
          c.lineWidth = (activeZone ? 1.4 : 1.15) * taper * (s.zone === hl ? 1.15 : 1);
          c.strokeStyle = hexA(activeZone ? HOT : zone.color, (activeZone ? 0.55 : 0.46) * taper * depth * lift);
          curve(s.a, s.c, s.b, 10);
        }
      };

      const crossArcs = (front) => {
        for (const a of this.arcs) {
          const isF = P(bez(a.a, a.c, a.b, 0.5)).z <= 0;
          if (isF !== front) continue;
          const depth = front ? 1 : 0.32;
          if (a.strong) { c.strokeStyle = hexA(HOT, 0.55 * depth); c.lineWidth = 1.1; }
          else { c.strokeStyle = hexA(NEU, 0.22 * depth); c.lineWidth = 0.9; c.setLineDash([4, 8]); }
          curve(a.a, a.c, a.b, 22);
          c.setLineDash([]);
        }
      };

      const hlAttr = parseInt(this.getAttribute('highlight') ?? '-1', 10);
      const hl = Number.isInteger(hlAttr) && ZONES[hlAttr] ? hlAttr : -1;
      const hlBreath = 0.6 + 0.4 * Math.sin(t * 1.9);
      const query = (this.getAttribute('query') || '').trim().toLowerCase();
      const matches = query ? this.tips.filter((n) => n.name && n.name.toLowerCase().includes(query)) : null;
      const isMatch = (n) => !matches || matches.includes(n);

      // hit-test on the front-most bead under the cursor
      let hover = null, hoverPt = null, hoverBest = 1e9;
      if (this._mx != null && !this._drag && !(this._down && !this._down.node)) {
        for (const n of this.tips) {
          const q = P(n.p);
          if (q.z > 0.06) continue;
          if (!isMatch(n)) continue;
          const d = Math.hypot(q.x - this._mx, q.y - this._my);
          const grab = Math.max(9, n.r * q.s + 7);
          if (d < grab && d < hoverBest) { hoverBest = d; hover = n; hoverPt = q; }
        }
      }
      this._hover = hover;
      const wantCursor = this._drag ? 'grabbing' : (hover ? 'pointer' : 'grab');
      if (this.style.cursor !== wantCursor) this.style.cursor = wantCursor;

      const beads = (front) => {
        for (const n of this.tips) {
          const q = P(n.p);
          if ((q.z <= 0) !== front) continue;
          const zone = ZONES[n.zone];
          const activeZone = n.zone === this.active;
          const match = isMatch(n);
          const twinkle = activeZone ? 0.6 + 0.4 * Math.sin(t * 2.6 + n.seed * 14) : 1;
          const sel = this.selected === n;
          const hov = hover === n;
          const r = n.r * q.s * (front ? 1 : 0.7) * (hov || sel ? 1.5 : 1);
          const dim = match ? 1 : 0.16;
          c.fillStyle = hexA(hov || sel ? '#ffffff' : (activeZone ? HOT : zone.color), (front ? 0.95 : 0.3) * twinkle * dim);
          c.beginPath(); c.arc(q.x, q.y, r, 0, TAU); c.fill();
          if (front && (n.hub || activeZone || hov || sel || (matches && match))) {
            const g = c.createRadialGradient(q.x, q.y, 0, q.x, q.y, r * 5.5);
            g.addColorStop(0, hexA(hov || sel ? '#ffffff' : (activeZone ? HOT : zone.color), (hov || sel ? 0.5 : 0.26) * twinkle * dim));
            g.addColorStop(1, hexA(zone.color, 0));
            c.fillStyle = g; c.beginPath(); c.arc(q.x, q.y, r * 5.5, 0, TAU); c.fill();
          }
          if (front && n.zone === hl && !sel && !hov) {
            c.strokeStyle = hexA(zone.color, 0.34 * hlBreath);
            c.lineWidth = 1;
            c.beginPath(); c.arc(q.x, q.y, r + 4, 0, TAU); c.stroke();
          }
          if (front && (sel || (matches && match && !hov))) {
            c.strokeStyle = hexA(sel ? '#ffffff' : HOT, sel ? 0.9 : 0.55);
            c.lineWidth = 1.2;
            c.beginPath(); c.arc(q.x, q.y, r + 5, 0, TAU); c.stroke();
          }
        }
      };

      // hover label — the bead's name, so every node is legible on approach
      const hoverLabel = () => {
        if (!hover || !hoverPt) return;
        const pad = 7, gap = 12;
        c.font = '500 12px Inter, system-ui, sans-serif';
        const tw = c.measureText(hover.name).width;
        c.font = '400 11px Inter, system-ui, sans-serif';
        const kw = c.measureText(hover.kind).width;
        const bw = Math.max(tw, kw) + pad * 2, bh = 34;
        let bx = hoverPt.x + gap, by = hoverPt.y - bh / 2;
        if (bx + bw > w - 8) bx = hoverPt.x - gap - bw;
        by = Math.max(6, Math.min(h - bh - 6, by));
        c.fillStyle = 'rgba(18,19,31,0.92)';
        c.strokeStyle = hexA(HOT, 0.34); c.lineWidth = 1;
        c.beginPath(); c.roundRect(bx, by, bw, bh, 7); c.fill(); c.stroke();
        c.textBaseline = 'alphabetic';
        c.font = '500 12px Inter, system-ui, sans-serif';
        c.fillStyle = '#e9e9ed'; c.fillText(hover.name, bx + pad, by + 15);
        c.font = '400 11px Inter, system-ui, sans-serif';
        c.fillStyle = hexA(NEU, 0.95); c.fillText(hover.kind, bx + pad, by + 28);
        c.textBaseline = 'middle';
      };

      // ── the lit pathways ──────────────────────────────────────────────
      // A whole route through the active zone draws as one solid bright line;
      // pulses of information run along it as travelling brightenings.
      const pathways = (front) => {
        const routes = [];
        for (const p of this.activePaths) routes.push(p.chain);
        for (const a of this.hotArcs) routes.push([{ a: a.a, c: a.c, b: a.b }]);
        routes.forEach((chain, ri) => {
          const mid = chain[Math.floor(chain.length / 2)];
          const isF = P(bez(mid.a, mid.c, mid.b, 0.5)).z <= 0;
          if (isF !== front) return;
          const dep = front ? 1 : 0.30;
          // the lit line itself
          c.lineCap = 'round';
          c.lineWidth = 1.3 * (front ? 1 : 0.8);
          c.strokeStyle = hexA(HOT, 0.62 * dep);
          for (const s of chain) curve(s.a, s.c, s.b, 16);
          c.lineWidth = 3.2;
          c.strokeStyle = hexA(HOT, 0.10 * dep);
          for (const s of chain) curve(s.a, s.c, s.b, 16);

          // pulses — two per route, offset, travelling root→tip
          for (let k = 0; k < 2; k++) {
            const u = ((t * 0.34 + ri * 0.21 + k * 0.5) % 1);
            const pos = u * chain.length;
            const si = Math.min(chain.length - 1, Math.floor(pos));
            const s = chain[si], su = pos - si;
            const TAIL = 7;
            for (let j = 0; j < TAIL; j++) {
              const uu = Math.max(0, su - j * 0.075);
              const p0 = P(bez(s.a, s.c, s.b, uu));
              const p1 = P(bez(s.a, s.c, s.b, Math.max(0, uu - 0.075)));
              c.lineWidth = 2.4 * (1 - j / TAIL) * p0.s * (front ? 1 : 0.7);
              c.strokeStyle = hexA(j < 2 && front ? '#ffffff' : HOT, 0.85 * (1 - j / TAIL) * dep);
              c.beginPath(); c.moveTo(p0.x, p0.y); c.lineTo(p1.x, p1.y); c.stroke();
            }
            const head = P(bez(s.a, s.c, s.b, su));
            const hr = 9 * head.s * (front ? 1 : 0.65);
            const g = c.createRadialGradient(head.x, head.y, 0, head.x, head.y, hr);
            g.addColorStop(0, hexA('#ffffff', 0.8 * dep));
            g.addColorStop(0.4, hexA(HOT, 0.4 * dep));
            g.addColorStop(1, hexA(HOT, 0));
            c.fillStyle = g; c.beginPath(); c.arc(head.x, head.y, hr, 0, TAU); c.fill();
          }
        });
      };

      headroom();
      enclosure(false);
      dendrites(false); crossArcs(false); pathways(false); beads(false);

      const az = ZONES[this.active];
      const ac = P(scale(norm(az.dir), this.used * 0.5));
      const halo = c.createRadialGradient(ac.x, ac.y, 0, ac.x, ac.y, R * 0.5);
      halo.addColorStop(0, hexA(HOT, 0.16 + 0.07 * alertPulse));
      halo.addColorStop(1, hexA(HOT, 0));
      c.fillStyle = halo; c.beginPath(); c.arc(ac.x, ac.y, R * 0.5, 0, TAU); c.fill();

      if (hl >= 0 && hl !== this.active) {
        const hc = P(scale(norm(ZONES[hl].dir), this.used * 0.5));
        const g = c.createRadialGradient(hc.x, hc.y, 0, hc.x, hc.y, R * 0.46);
        g.addColorStop(0, hexA(ZONES[hl].color, 0.13 * hlBreath));
        g.addColorStop(1, hexA(ZONES[hl].color, 0));
        c.fillStyle = g; c.beginPath(); c.arc(hc.x, hc.y, R * 0.46, 0, TAU); c.fill();
      }

      dendrites(true); crossArcs(true); pathways(true); beads(true);
      enclosure(true);
      hoverLabel();

      const sy = ((t * 0.14) % 1) * h;
      const sweep = c.createLinearGradient(0, sy - 40, 0, sy + 40);
      sweep.addColorStop(0, 'rgba(181,171,252,0)');
      sweep.addColorStop(0.5, 'rgba(181,171,252,0.05)');
      sweep.addColorStop(1, 'rgba(181,171,252,0)');
      c.fillStyle = sweep; c.fillRect(0, sy - 40, w, 80);

      if (matches) {
        c.font = '400 12px Inter, system-ui, sans-serif';
        c.textBaseline = 'alphabetic';
        c.fillStyle = hexA(matches.length ? HOT : NEU, 0.9);
        c.fillText(matches.length ? matches.length + (matches.length === 1 ? ' match' : ' matches') : 'nothing by that name', 24, 30);
      }
      c.font = '500 11px Inter, system-ui, sans-serif';
      c.textBaseline = 'middle';
      ZONES.forEach((z, i) => {
        const q = P(scale(norm(z.dir), this.used * 0.99));
        const isH = i === hl;
        if (q.z > 0.25 && !isH) return;
        const isA = i === this.active;
        c.fillStyle = hexA(isA ? HOT : (isH ? z.color : NEU), q.z > 0 ? (isH ? 0.6 : 0.35) : (isH ? 1 : 0.9));
        const tx = q.x + (q.x > cx ? 10 : -10 - c.measureText(z.name).width);
        c.fillText(z.name, tx, q.y);
        c.strokeStyle = hexA(isA ? HOT : (isH ? z.color : NEU), isH ? 0.5 : 0.28);
        c.lineWidth = 1;
        c.beginPath(); c.moveTo(q.x, q.y); c.lineTo(q.x + (q.x > cx ? 7 : -7), q.y); c.stroke();
        if (isA) {
          c.font = '400 11px Inter, system-ui, sans-serif';
          c.fillStyle = hexA(HOT, 0.75);
          c.fillText('thinking here', tx, q.y + 15);
          c.font = '500 11px Inter, system-ui, sans-serif';
        }
      });
    }
  }

  if (!customElements.get('delphi-brain')) customElements.define('delphi-brain', DelphiBrain);
})();
