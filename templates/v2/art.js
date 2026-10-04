/* ═══════════════════════════════════════════════════════════════════════════
   Generative vector art. Every piece is drawn from a seed, so the same post
   always re-renders identically (determinism, for retries and tests) while two
   posts never share a picture. Colours are CSS custom properties, never
   literals, so the art takes on whatever look and accent the slide wears.

   ART[kind](rng, W, H) -> SVG markup with viewBox "0 0 W H".
   ═══════════════════════════════════════════════════════════════════════════ */
(function () {
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const rnd = (rng, a, b) => a + (b - a) * rng();
  const pick = (rng, arr) => arr[Math.floor(rng() * arr.length) % arr.length];
  const f = (n) => Math.round(n * 10) / 10;
  const C = { acc: 'var(--acc)', soft: 'var(--a-soft)', mid: 'var(--a-mid)', alt: 'var(--a-alt)', fg: 'var(--fg)', line: 'var(--line)', glow: 'var(--a-glow)', alt2: 'var(--a-alt-glow)' };
  const svg = (W, H, body, defs = '') =>
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid slice">${defs ? `<defs>${defs}</defs>` : ''}${body}</svg>`;

  // A smooth closed blob through n points around a centre (Catmull-Rom -> Bezier).
  function blobPath(rng, cx, cy, r, n = 7, wob = 0.28) {
    const pts = [];
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2;
      const rr = r * (1 - wob + rng() * wob * 2);
      pts.push([cx + Math.cos(a) * rr, cy + Math.sin(a) * rr]);
    }
    let d = `M${f(pts[0][0])},${f(pts[0][1])}`;
    for (let i = 0; i < n; i++) {
      const p0 = pts[(i - 1 + n) % n], p1 = pts[i], p2 = pts[(i + 1) % n], p3 = pts[(i + 2) % n];
      const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
      const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
      d += ` C${f(c1[0])},${f(c1[1])} ${f(c2[0])},${f(c2[1])} ${f(p2[0])},${f(p2[1])}`;
    }
    return d + 'Z';
  }

  const ART = {
    orbits(rng, W, H) {
      const cx = W * rnd(rng, 0.55, 0.8), cy = H * rnd(rng, 0.2, 0.45), R = Math.max(W, H) * 0.7;
      let b = '';
      const rings = 7 + Math.floor(rng() * 4);
      for (let i = 1; i <= rings; i++) {
        const r = (R / rings) * i;
        const dash = rng() < 0.35 ? ` stroke-dasharray="${f(rnd(rng, 4, 18))} ${f(rnd(rng, 8, 30))}"` : '';
        b += `<circle cx="${f(cx)}" cy="${f(cy)}" r="${f(r)}" fill="none" style="stroke:${i % 3 === 0 ? C.acc : C.line}" stroke-width="${i % 3 === 0 ? 2.2 : 1.3}"${dash}/>`;
        const dots = 1 + Math.floor(rng() * 2);
        for (let k = 0; k < dots; k++) {
          const a = rng() * Math.PI * 2;
          b += `<circle cx="${f(cx + Math.cos(a) * r)}" cy="${f(cy + Math.sin(a) * r)}" r="${f(rnd(rng, 4, 11))}" style="fill:${rng() < 0.5 ? C.acc : C.soft}"/>`;
        }
      }
      b += `<circle cx="${f(cx)}" cy="${f(cy)}" r="${f(R / rings * 0.55)}" style="fill:${C.acc}" opacity="0.9"/>`;
      return svg(W, H, b);
    },

    blobs(rng, W, H) {
      const id = 'bl' + Math.floor(rng() * 1e6);
      const defs = `<filter id="${id}" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="${f(Math.min(W, H) * 0.035)}"/></filter>`;
      let b = '';
      const cols = [C.mid, C.soft, C.alt, C.acc];
      const n = 4 + Math.floor(rng() * 2);
      for (let i = 0; i < n; i++) {
        const r = Math.min(W, H) * rnd(rng, 0.16, 0.32);
        b += `<path d="${blobPath(rng, W * rnd(rng, 0.1, 0.95), H * rnd(rng, 0.05, 0.95), r, 7 + (i % 3))}" style="fill:${cols[i % cols.length]}" opacity="${f(rnd(rng, 0.45, 0.85))}" filter="url(#${id})"/>`;
      }
      return svg(W, H, b, defs);
    },

    iso(rng, W, H) {
      const s = Math.min(W, H) * rnd(rng, 0.055, 0.075);
      const h = s * Math.sqrt(3) / 2;
      let b = '';
      const cube = (x, y, hot) => {
        const top = `M${f(x)},${f(y - s)} L${f(x + h)},${f(y - s / 2)} L${f(x)},${f(y)} L${f(x - h)},${f(y - s / 2)}Z`;
        const left = `M${f(x - h)},${f(y - s / 2)} L${f(x)},${f(y)} L${f(x)},${f(y + s)} L${f(x - h)},${f(y + s / 2)}Z`;
        const right = `M${f(x + h)},${f(y - s / 2)} L${f(x)},${f(y)} L${f(x)},${f(y + s)} L${f(x + h)},${f(y + s / 2)}Z`;
        if (hot) return `<path d="${top}" style="fill:${C.soft}"/><path d="${left}" style="fill:${C.mid}"/><path d="${right}" style="fill:${C.acc}"/>`;
        return `<path d="${top}${left}${right}" fill="none" style="stroke:${C.line}" stroke-width="1.2"/>`;
      };
      for (let row = -1; row < H / s + 2; row++) {
        for (let col = -1; col < W / (2 * h) + 2; col++) {
          const x = col * 2 * h + (row % 2 ? h : 0), y = row * s * 1.5;
          b += cube(x, y, rng() < 0.07);
        }
      }
      return svg(W, H, b);
    },

    waves(rng, W, H) {
      let b = '';
      const n = 9 + Math.floor(rng() * 6);
      const base = H * rnd(rng, 0.45, 0.7);
      for (let i = 0; i < n; i++) {
        const amp = H * rnd(rng, 0.03, 0.12), ph = rng() * Math.PI * 2, k = rnd(rng, 1.2, 2.6);
        let d = '';
        for (let x = -20; x <= W + 20; x += W / 48) {
          const y = base + i * (H * 0.035) + Math.sin((x / W) * Math.PI * k + ph) * amp;
          d += (d ? ' L' : 'M') + `${f(x)},${f(y)}`;
        }
        b += `<path d="${d}" fill="none" style="stroke:${i % 4 === 0 ? C.acc : C.line}" stroke-width="${i % 4 === 0 ? 2.6 : 1.4}" opacity="${f(1 - i / (n * 1.4))}"/>`;
      }
      return svg(W, H, b);
    },

    topo(rng, W, H) {
      let b = '';
      const centres = 2 + Math.floor(rng() * 2);
      for (let c = 0; c < centres; c++) {
        const cx = W * rnd(rng, 0.1, 0.9), cy = H * rnd(rng, 0.1, 0.9);
        const rings = 8 + Math.floor(rng() * 5);
        for (let i = 1; i <= rings; i++) {
          const r = Math.min(W, H) * 0.045 * i;
          b += `<path d="${blobPath(rng, cx, cy, r, 9, 0.12)}" fill="none" style="stroke:${i === rings - 2 ? C.acc : C.line}" stroke-width="${i === rings - 2 ? 2.4 : 1.2}"/>`;
        }
      }
      return svg(W, H, b);
    },

    bauhaus(rng, W, H) {
      const cols = 4 + Math.floor(rng() * 2), size = W / cols, rows = Math.ceil(H / size);
      let b = '';
      const fills = [C.acc, C.soft, C.mid, C.alt, 'var(--fg)'];
      for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
        if (rng() < 0.42) continue;
        const x = c * size, y = r * size, fill = pick(rng, fills), t = Math.floor(rng() * 5), op = f(rnd(rng, 0.55, 0.95));
        if (t === 0) b += `<circle cx="${f(x + size / 2)}" cy="${f(y + size / 2)}" r="${f(size * 0.42)}" style="fill:${fill}" opacity="${op}"/>`;
        else if (t === 1) b += `<path d="M${f(x)},${f(y + size)} A${f(size)},${f(size)} 0 0 1 ${f(x + size)},${f(y)} L${f(x + size)},${f(y + size)}Z" style="fill:${fill}" opacity="${op}"/>`;
        else if (t === 2) b += `<path d="M${f(x)},${f(y + size)} L${f(x + size / 2)},${f(y)} L${f(x + size)},${f(y + size)}Z" style="fill:${fill}" opacity="${op}"/>`;
        else if (t === 3) b += `<rect x="${f(x + size * 0.12)}" y="${f(y + size * 0.12)}" width="${f(size * 0.76)}" height="${f(size * 0.76)}" rx="${f(size * 0.12)}" style="fill:${fill}" opacity="${op}"/>`;
        else b += `<path d="M${f(x)},${f(y)} h${f(size)} v${f(size / 2)} A${f(size / 2)},${f(size / 2)} 0 0 1 ${f(x)},${f(y + size / 2)}Z" style="fill:${fill}" opacity="${op}"/>`;
      }
      return svg(W, H, b);
    },

    network(rng, W, H) {
      const n = 26 + Math.floor(rng() * 14), pts = [];
      for (let i = 0; i < n; i++) pts.push([rnd(rng, 0, W), rnd(rng, 0, H)]);
      let b = '';
      for (let i = 0; i < n; i++) {
        const near = pts.map((p, j) => [j, Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1])]).sort((a, z) => a[1] - z[1]).slice(1, 3);
        for (const [j] of near) b += `<line x1="${f(pts[i][0])}" y1="${f(pts[i][1])}" x2="${f(pts[j][0])}" y2="${f(pts[j][1])}" style="stroke:${C.line}" stroke-width="1.3"/>`;
      }
      pts.forEach((p, i) => {
        const hot = i % 7 === 0;
        b += `<circle cx="${f(p[0])}" cy="${f(p[1])}" r="${hot ? 9 : 4.5}" style="fill:${hot ? C.acc : C.soft}"/>`;
        if (hot) b += `<circle cx="${f(p[0])}" cy="${f(p[1])}" r="20" fill="none" style="stroke:${C.acc}" stroke-width="1.5" opacity="0.6"/>`;
      });
      return svg(W, H, b);
    },

    cards(rng, W, H) {
      let b = '';
      const n = 3 + Math.floor(rng() * 2), cw = W * 0.5, ch = H * 0.26;
      for (let i = 0; i < n; i++) {
        const x = W * 0.42 + i * W * 0.05, y = H * 0.16 + i * H * 0.12, rot = f(rnd(rng, -6, 6));
        b += `<g transform="rotate(${rot} ${f(x + cw / 2)} ${f(y + ch / 2)})">` +
          `<rect x="${f(x)}" y="${f(y)}" width="${f(cw)}" height="${f(ch)}" rx="${f(W * 0.025)}" style="fill:var(--card);stroke:var(--card-line)" stroke-width="2"/>` +
          `<circle cx="${f(x + W * 0.05)}" cy="${f(y + H * 0.05)}" r="${f(W * 0.022)}" style="fill:${i === n - 1 ? C.acc : C.soft}"/>` +
          `<rect x="${f(x + W * 0.09)}" y="${f(y + H * 0.035)}" width="${f(cw * 0.5)}" height="${f(H * 0.014)}" rx="6" style="fill:var(--fg)" opacity="0.5"/>` +
          `<rect x="${f(x + W * 0.03)}" y="${f(y + H * 0.11)}" width="${f(cw * 0.86)}" height="${f(H * 0.012)}" rx="6" style="fill:var(--fg)" opacity="0.18"/>` +
          `<rect x="${f(x + W * 0.03)}" y="${f(y + H * 0.145)}" width="${f(cw * 0.66)}" height="${f(H * 0.012)}" rx="6" style="fill:var(--fg)" opacity="0.18"/>` +
          `<rect x="${f(x + W * 0.03)}" y="${f(y + H * 0.19)}" width="${f(cw * 0.32)}" height="${f(H * 0.035)}" rx="${f(H * 0.017)}" style="fill:${C.acc}" opacity="${i === n - 1 ? 1 : 0.35}"/></g>`;
      }
      return svg(W, H, b);
    },

    chevrons(rng, W, H) {
      let b = '';
      const s = Math.min(W, H) * rnd(rng, 0.07, 0.1), rows = Math.ceil(H / s) + 2, colsN = Math.ceil(W / s) + 2;
      for (let r = 0; r < rows; r++) for (let c = 0; c < colsN; c++) {
        const x = c * s, y = r * s * 0.9, op = f(Math.max(0, Math.sin((c / colsN) * Math.PI) * (0.25 + rng() * 0.75)));
        if (op < 0.08) continue;
        b += `<path d="M${f(x)},${f(y)} l${f(s * 0.45)},${f(s * 0.35)} l-${f(s * 0.45)},${f(s * 0.35)}" fill="none" style="stroke:${(r + c) % 9 === 0 ? C.acc : C.line}" stroke-width="${f(s * 0.08)}" stroke-linecap="round" opacity="${op}"/>`;
      }
      return svg(W, H, b);
    },

    streaks(rng, W, H) {
      const id = 'st' + Math.floor(rng() * 1e6);
      const defs = `<linearGradient id="${id}" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset="0.7" style="stop-color:${C.glow}" stop-opacity="0.9"/><stop offset="1" stop-color="#fff" stop-opacity="1"/></linearGradient>` +
        `<filter id="${id}g" x="-20%" y="-50%" width="140%" height="200%"><feGaussianBlur stdDeviation="3"/></filter>`;
      let b = '';
      const n = 22 + Math.floor(rng() * 16), ang = rnd(rng, -24, -12);
      b += `<g transform="rotate(${f(ang)} ${W / 2} ${H / 2})">`;
      for (let i = 0; i < n; i++) {
        const y = rnd(rng, -H * 0.2, H * 1.2), x = rnd(rng, -W * 0.4, W * 0.8), len = rnd(rng, W * 0.2, W * 0.9), th = rnd(rng, 1.5, 6);
        b += `<rect x="${f(x)}" y="${f(y)}" width="${f(len)}" height="${f(th)}" rx="${f(th / 2)}" fill="url(#${id})" opacity="${f(rnd(rng, 0.35, 1))}"${rng() < 0.4 ? ` filter="url(#${id}g)"` : ''}/>`;
      }
      return svg(W, H, b + '</g>', defs);
    },

    pixels(rng, W, H) {
      const s = Math.min(W, H) * 0.045, cols = Math.ceil(W / s), rows = Math.ceil(H / s);
      let b = '';
      const cols2 = [C.acc, C.soft, C.mid, C.alt];
      for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
        const p = (c / cols) * 0.7 + (1 - r / rows) * 0.3;
        if (rng() > p * p * 0.9) continue;
        b += `<rect x="${f(c * s + 1)}" y="${f(r * s + 1)}" width="${f(s - 2)}" height="${f(s - 2)}" rx="${f(s * 0.18)}" style="fill:${pick(rng, cols2)}" opacity="${f(rnd(rng, 0.35, 1))}"/>`;
      }
      return svg(W, H, b);
    },

    rays(rng, W, H) {
      const cx = W * rnd(rng, 0.6, 1.0), cy = H * rnd(rng, -0.1, 0.25), n = 18 + Math.floor(rng() * 10), R = Math.hypot(W, H) * 1.2;
      let b = '';
      for (let i = 0; i < n; i++) {
        const a0 = Math.PI * 0.5 + (i / n) * Math.PI * 0.9, a1 = a0 + rnd(rng, 0.015, 0.05);
        b += `<path d="M${f(cx)},${f(cy)} L${f(cx + Math.cos(a0) * R)},${f(cy + Math.sin(a0) * R)} L${f(cx + Math.cos(a1) * R)},${f(cy + Math.sin(a1) * R)}Z" style="fill:${i % 4 === 0 ? C.acc : C.soft}" opacity="${f(rnd(rng, 0.12, 0.4))}"/>`;
      }
      b += `<circle cx="${f(cx)}" cy="${f(cy)}" r="${f(Math.min(W, H) * 0.08)}" style="fill:${C.acc}"/>`;
      return svg(W, H, b);
    },
  };

  window.ART = ART;
  window.artRng = mulberry32;
  window.ART_KINDS = Object.keys(ART);
})();
