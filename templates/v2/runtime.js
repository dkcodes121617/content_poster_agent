/* ═══════════════════════════════════════════════════════════════════════════
   The v2 page runtime. Order matters and is the same as v1's, extended:

     1. build      head, main (format builder), foot, background art
     2. engines    Vega (charts), Mermaid (diagrams), Prism (code) - awaited
     3. fonts      document.fonts.ready - measuring earlier measures fallbacks
     4. fit        one --fit multiplier on the whole type scale, shrink or grow
     5. ornament   Rough.js strokes for the sketch look - drawn on final boxes
     6. audit      overflow, clipping, margins, footer, junk text, engine
                   verification; plus text boxes for the pixel-contrast check
                   the Python side runs on the screenshot

   window.__audit then window.__ready = true. A thrown error still sets both,
   with the error in audit.errors, so the renderer never waits out a timeout.
   ═══════════════════════════════════════════════════════════════════════════ */
(async function () {
  const D = window.D || {};
  const c = D.content || {};
  const canvas = document.getElementById('canvas');
  const errors = [], warnings = [], verify = {};
  const W = (D.canvas && D.canvas.w) || 1080, H = (D.canvas && D.canvas.h) || 1350;

  try {
    canvas.style.setProperty('--w', W + 'px');
    canvas.style.setProperty('--h', H + 'px');
    canvas.dataset.look = D.look || 'midnight';
    canvas.dataset.accent = D.accent || 'blue';
    canvas.dataset.format = D.format || 'hook';
    canvas.dataset.layout = D.layout || '';

    const F = window.FORMATS[D.format];
    if (!F) throw new Error(`unknown format ${D.format}`);
    const layout = F.layouts.includes(D.layout) ? D.layout : F.layouts[0];
    canvas.dataset.layout = layout;
    const x = window.makeHelpers(D);

    // ── head ────────────────────────────────────────────────────────────────
    const slide = D.slide || null;
    let head = '';
    if (slide && slide.count > 1) {
      head += '<div class="progress">' + Array.from({ length: slide.count }, (_, i) => `<i class="${i < slide.index ? 'on' : ''}"></i>`).join('') + '</div>';
    }
    const eyebrow = c.eyebrow || D.eyebrow || '';
    const series = D.series && D.series.label ? `<span class="tag">${x.plain(D.series.label)}</span>` : '';
    if (eyebrow || series) head += `<div class="eyebrow">${series}${eyebrow ? `<span>${x.plain(eyebrow)}</span>` : ''}</div>`;
    document.getElementById('head').innerHTML = head;

    // ── main ────────────────────────────────────────────────────────────────
    document.getElementById('main').innerHTML = F.build(c, x, layout);
    errors.push(...x.errors);
    warnings.push(...x.warnings);

    // ── foot ────────────────────────────────────────────────────────────────
    const brand = D.brand || {};
    let right = `<span class="handle">${x.plain(brand.handle || '@wiz_codes')}</span>`;
    if (slide && slide.count > 1) {
      right = slide.index === 1 ? `<span class="swipe">Swipe ${x.icon('arrow-right')}</span>` : `<span class="count">${slide.index} / ${slide.count}</span>`;
    }
    document.getElementById('foot').innerHTML =
      `<span class="wordmark"><span class="w">wiz</span><span class="c">codes</span></span>${right}`;

    // ── art ─────────────────────────────────────────────────────────────────
    const art = D.art || {};
    if (art.kind && art.kind !== 'none' && window.ART[art.kind]) {
      const slot = document.querySelector('[data-art-slot]');
      if (slot) {
        const r = slot.getBoundingClientRect();
        slot.innerHTML = window.ART[art.kind](window.artRng(art.seed || 1), Math.max(200, Math.round(r.width)), Math.max(200, Math.round(r.height)));
        slot.querySelector('svg').style.opacity = 'calc(var(--art-opacity) * 3.2)';
      } else if (figureArt(art.kind)) {
        // drawn after fit, into the slide's largest empty space - see placeInSpace()
      } else {
        const place = art.place || 'bg';
        const dims = { bg: [W, H], corner: [700, 700], band: [W, Math.round(H * 0.42)], side: [Math.round(W * 0.58), Math.round(H * 0.76)] }[place] || [W, H];
        const holder = document.createElement('div');
        holder.innerHTML = window.ART[art.kind](window.artRng(art.seed || 1), dims[0], dims[1]);
        const svgEl = holder.firstElementChild;
        svgEl.classList.add('art-' + place);
        document.getElementById('bg').appendChild(svgEl);
      }
    } else if (art.kind && art.kind !== 'none') {
      warnings.push(`unknown art kind ${art.kind}`);
    }

    // ── fonts, before anything measures text ───────────────────────────────
    // Mermaid sizes every box from text it measures as it lays out, and so
    // does Vega. Measured in a fallback font, the boxes came out the wrong
    // width and the real font then re-wrapped "Build it" inside them.
    await Promise.all([
      document.fonts.load(`700 40px "Google Sans Flex"`), document.fonts.load(`400 40px "Google Sans Code"`),
      document.fonts.load(`400 40px "Instrument Serif"`), document.fonts.load(`800 40px "Bricolage Grotesque"`), document.fonts.load(`600 40px "Caveat"`),
    ]).catch(() => {});
    await document.fonts.ready;

    // ── engines ─────────────────────────────────────────────────────────────
    const css = (name) => getComputedStyle(canvas).getPropertyValue(name).trim();
    for (const job of x.jobs) {
      try {
        if (job.engine === 'vega') await renderChart(job, css, verify, errors);
        else if (job.engine === 'mermaid') await renderTree(job, css, verify, errors);
        else if (job.engine === 'prism') renderCode(job);
      } catch (e) {
        errors.push(`${job.engine} failed: ${String(e && e.message || e).slice(0, 160)}`);
      }
    }

    // ── fit, then finish what depends on the final layout ─────────────────
    const fitResult = fit(D.format);
    if (window.__treeFinish) await window.__treeFinish();

    // ── ornament (sketch) ──────────────────────────────────────────────────
    if ((D.look === 'sketch') && window.rough) sketch(art.seed || 7);

    // ── quadrant labels: placed on final sizes, before anything measures them
    const quadFit = placeQuadLabels();
    if (quadFit) {
      verify.quad = quadFit;
      if (quadFit.overlap) warnings.push('quadrant labels still touch at the smallest label size');
    }

    // ── figure art: into the empty space the final layout left ────────────
    if (figureArt(art.kind) && art.kind !== 'none' && window.ART[art.kind] && !document.querySelector('[data-art-slot]')) {
      verify.art_space = placeInSpace(art);
    }

    // ── art knockout: needs the final text positions, so after fit ─────────
    const artSvg = document.querySelector('#bg > svg:not(.art-space)');
    if (artSvg && !fieldArt(art.kind)) verify.knockout = knockout(artSvg, art.seed || 1);

    window.__audit = audit(fitResult, layout);
  } catch (e) {
    window.__audit = { errors: [`runtime error: ${String(e && e.message || e).slice(0, 200)}`, ...errors], warnings, boxes: [] };
  }
  window.__ready = true;

  // ═══════════════════ engines ═══════════════════
  async function renderChart(jobIn, css, verify, errors) {
    let job = jobIn;
    const slot = document.querySelector('[data-chart]');
    if (!window.vega || !window.vegaLite) throw new Error('vega not loaded');
    const series = (job.chart.series || []).map((s) => ({ label: String(s.label), value: Number(s.value) }));
    if (!series.length || series.some((s) => !isFinite(s.value))) throw new Error('chart series missing or non-numeric');
    const hl = job.chart.highlight || '';
    const unit = job.chart.unit || '';
    const fmt = (v) => (unit && /^[A-Za-z]{2}/.test(unit) ? `${v} ${unit}` : `${v}${unit}`);
    series.forEach((s) => { s.text = fmt(s.value); s.hot = hl ? (s.label === hl) : false; });
    if (!hl) series[series.length - 1].hot = true;
    const r = slot.getBoundingClientRect();
    const w = Math.max(300, Math.round(r.width));
    const fs = Math.round(Math.min(W, H) * 0.036);
    // Bars spread over a tall slot read as three lonely stripes; a horizontal
    // chart gets roughly one band per bar and centres in the space instead.
    let h = Math.max(240, Math.round(r.height));
    if (job.layout === 'bar') h = Math.min(h, Math.round(series.length * fs * 5.2));
    if (job.layout === 'donut') h = Math.min(h, Math.round(w * 0.95));
    const fg = css('--fg'), fg2 = css('--fg-2') || fg, muted = css('--muted'), acc = css('--acc'), soft = css('--line') || muted;
    const maxV = Math.max(...series.map((s) => s.value), 0) || 1;
    // Column labels sit side by side under narrow columns; when the longest
    // would not fit its column the chart is drawn as bars, which give every
    // label the full width. ("Scope boundary" ran into "Exclusions".)
    if (job.layout === 'column') {
      const longest = Math.max(...series.map((s) => s.label.length));
      if (longest * fs * 0.55 > (w / series.length) * 0.92) job = Object.assign({}, job, { layout: 'bar' });
      if (job.layout === 'bar') h = Math.min(Math.max(240, Math.round(r.height)), Math.round(series.length * fs * 5.2));
    }
    const font = getComputedStyle(canvas).fontFamily;
    const base = {
      $schema: 'https://vega.github.io/schema/vega-lite/v6.json', width: w, height: h, background: null, data: { values: series },
      config: { view: { stroke: null }, font, axis: { labelColor: fg, labelFontSize: fs, titleColor: muted, domain: false, ticks: false, grid: false, labelPadding: fs * 0.6, labelLimit: w * 0.42 },
        text: { font, fontSize: Math.round(fs * 1.25), fill: fg, fontWeight: 700 },
        legend: { labelColor: fg, labelFontSize: Math.round(fs * 0.95), titleColor: muted, symbolSize: fs * fs * 0.6, labelLimit: 0, rowPadding: fs * 0.5 } },
    };
    let spec;
    if (job.layout === 'donut') {
      // drawn below, once the HTML legend has taken its share of the slot
    } else if (job.layout === 'bar') {
      // The category sits above its bar and the value at the bar's end: every
      // bar gets the full width, and the numbers - the point of the slide -
      // are the biggest text on it. Headroom in the domain keeps the longest
      // bar's value label inside the drawing.
      const band = h / series.length;
      const barH = Math.round(Math.min(band * 0.4, fs * 2.1));
      const ys = { field: 'label', type: 'nominal', sort: null, title: null, axis: null, scale: { paddingInner: 0, paddingOuter: 0 } };
      const xs = { field: 'value', type: 'quantitative', title: null, axis: null, scale: { domain: [0, maxV * 1.32], nice: false, zero: true } };
      const color = { condition: { test: 'datum.hot', value: acc }, value: soft };
      spec = Object.assign(base, { layer: [
        { mark: { type: 'bar', size: barH, cornerRadiusEnd: Math.round(barH * 0.3) }, encoding: { y: ys, x: xs, color } },
        { mark: { type: 'text', align: 'left', baseline: 'bottom', dy: -Math.round(barH / 2 + fs * 0.35), fontSize: Math.round(fs * 1.02), fontWeight: 600, fill: fg2 },
          encoding: { y: ys, x: { value: 0 }, text: { field: 'label' } } },   // a datum here crashes vega-lite 6.4 (three layers)
        { mark: { type: 'text', align: 'left', baseline: 'middle', dx: Math.round(fs * 0.45), fontSize: Math.round(fs * 1.55), fontWeight: 760, fill: fg },
          encoding: { y: ys, x: xs, text: { field: 'text' } } },
      ] });
    } else {
      const horizontal = job.layout !== 'column';
      const enc = horizontal
        ? { y: { field: 'label', type: 'nominal', sort: null, title: null }, x: { field: 'value', type: 'quantitative', title: null, axis: null } }
        : { x: { field: 'label', type: 'nominal', sort: null, title: null, axis: { labelAngle: 0, labelFontSize: Math.round(fs * 1.02) } },
            y: { field: 'value', type: 'quantitative', title: null, axis: null, scale: { domain: [0, maxV * 1.2], nice: false } } };
      const color = { condition: { test: 'datum.hot', value: acc }, value: soft };
      spec = Object.assign(base, { layer: [
        { mark: { type: 'bar', cornerRadiusEnd: Math.round(fs * 0.4), size: Math.round((horizontal ? h : w) / series.length * 0.56) }, encoding: Object.assign({}, enc, { color }) },
        { mark: horizontal ? { type: 'text', align: 'left', dx: fs * 0.5 } : { type: 'text', baseline: 'bottom', dy: -fs * 0.4, fontSize: Math.round(fs * 1.45), fontWeight: 760 }, encoding: Object.assign({}, enc, { text: { field: 'text' } }) },
      ] });
    }
    let target = slot;
    if (job.layout === 'donut') {
      // The legend is HTML: it scales with the type, wraps like text and the
      // contrast check reads it. Vega's legend was drawn into the same SVG as
      // the ring and shrank with it, to text nobody could read on a phone.
      const shades = [acc, css('--a-soft'), css('--a-mid'), css('--a-alt'), muted];
      const esc = (t) => String(t).replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
      slot.classList.add('donut');
      if (r.height > r.width * 1.3) slot.classList.add('tall');
      slot.innerHTML = '<div class="donut-ring"></div><div class="legend">' + series.map((s, i) =>
        `<div class="lg"><i style="background:${shades[i % shades.length]}"></i><b>${esc(s.text)}</b><span>${esc(s.label)}</span></div>`).join('') + '</div>';
      target = slot.querySelector('.donut-ring');
      const rr = target.getBoundingClientRect();
      const size = Math.max(220, Math.round(Math.min(rr.width, rr.height)));
      spec = Object.assign(base, { width: size, height: size, layer: [
        { mark: { type: 'arc', innerRadius: size * 0.3, outerRadius: size * 0.5, padAngle: 0.02, cornerRadius: 6 },
          encoding: { theta: { field: 'value', type: 'quantitative', stack: true },
            color: { field: 'label', type: 'nominal', sort: null, legend: null,
              scale: { domain: series.map((s) => s.label), range: series.map((_, i) => shades[i % shades.length]) } } } },
      ] });
    }
    const compiled = window.vegaLite.compile(spec).spec;
    const view = new window.vega.View(window.vega.parse(compiled), { renderer: 'none' });
    const svg = await view.toSVG();
    target.innerHTML = svg;
    // verify: bar extents proportional to values, within 2% of the largest
    if (job.layout !== 'donut') {
      const horizontal = job.layout !== 'column';
      const sizes = [...slot.querySelectorAll('g.mark-rect path')].map((p) => {
        const b = p.getBBox();
        return horizontal ? b.width : b.height;
      });
      const maxS = Math.max(...sizes, 0);
      if (sizes.length >= series.length && maxS > 0) {
        const worst = Math.max(...series.map((s, i) => Math.abs(sizes[i] / maxS - s.value / maxV)));
        verify.chart = { bars: sizes.length, worst_error: Math.round(worst * 1000) / 1000 };
        if (worst > 0.02) errors.push(`chart bars are not proportional to the data (worst error ${(worst * 100).toFixed(1)}%)`);
      } else {
        verify.chart = { bars: sizes.length, note: 'could not read bar geometry' };
      }
    }
  }

  async function renderTree(job, css, verify, errors) {
    const slot = document.querySelector('[data-diagram]');
    if (!window.mermaid) throw new Error('mermaid not loaded');
    const lines = [`flowchart ${job.layout === 'lr' ? 'LR' : 'TD'}`];
    let n = 0;
    const clean = (s) => String(s || '').replace(/["`\[\]{}<>|#]/g, "'").replace(/\s+/g, ' ').trim().slice(0, 64);
    // Line breaks are chosen here, per node, instead of by Mermaid's one global
    // wrapping width: four leaves side by side need narrow boxes while the root
    // has the whole width, and a single width either crushed the leaves or
    // stacked the root question one word per line.
    const fsPx = Math.round(Math.min(W, H) * 0.034);
    const meas = document.createElement('canvas').getContext('2d');
    meas.font = `600 ${fsPx}px ${getComputedStyle(canvas).fontFamily}`;
    const charW = meas.measureText('the quick brown fox jumps over the lazy dog').width / 43 || fsPx * 0.55;
    const perRank = [];
    (function count(node, d) {
      perRank[d] = (perRank[d] || 0) + 1;
      if (node && typeof node === 'object' && node.q) { count(node.yes, d + 1); count(node.no, d + 1); }
    })(job.tree, 0);
    const box = slot.getBoundingClientRect();
    const PAD = 14, GAP = 22, RANK = 52;
    const maxChars = (d) => {
      const px = job.layout === 'lr'
        ? (box.width - (perRank.length - 1) * RANK) / perRank.length
        : Math.min(box.width * 0.6, (box.width - ((perRank[d] || 1) - 1) * GAP) / (perRank[d] || 1));
      return Math.max(6, Math.floor((px - 2 * PAD - 10) / charW));
    };
    const breakLines = (text, max) => {
      const words = text.split(' ').filter(Boolean);
      if (text.length <= max || words.length < 2) return text;
      const len = (a) => a.join(' ').length;
      const memo = new Map();
      const solve = (i, m) => {            // words[i:] in m lines, longest line minimal
        const key = i * 8 + m;
        if (memo.has(key)) return memo.get(key);
        let res = null;
        if (m === 1) res = { cost: len(words.slice(i)), lines: [words.slice(i).join(' ')] };
        else {
          for (let j = i + 1; j <= words.length - m + 1; j++) {
            const rest = solve(j, m - 1);
            const cost = Math.max(len(words.slice(i, j)), rest.cost);
            if (!res || cost < res.cost) res = { cost, lines: [words.slice(i, j).join(' '), ...rest.lines] };
          }
        }
        memo.set(key, res);
        return res;
      };
      let best = null;
      for (let m = 2; m <= Math.min(4, words.length); m++) {
        const r = solve(0, m);
        if (!best || r.cost < best.cost) best = r;
        if (r.cost <= max) break;
      }
      return best.lines.join('<br>');
    };
    const label = (s, d) => breakLines(clean(s), maxChars(d));
    function walk(node, d = 0) {
      const id = 'n' + (n++);
      if (node && typeof node === 'object' && node.q) {
        lines.push(`  ${id}("${label(node.q, d)}")`);
        const yes = walk(node.yes, d + 1), no = walk(node.no, d + 1);
        lines.push(`  ${id} -->|"${clean(node.yes_label || 'Yes')}"| ${yes}`);
        lines.push(`  ${id} -->|"${clean(node.no_label || 'No')}"| ${no}`);
      } else {
        lines.push(`  ${id}["${label(node && node.text !== undefined ? node.text : node, d)}"]`);
        lines.push(`  class ${id} leaf`);
      }
      return id;
    }
    walk(job.tree);
    if (n > 9) errors.push(`decision tree has ${n} nodes - more than a slide can hold legibly`);
    const fg = css('--fg'), card = css('--card'), line = css('--line'), acc = css('--acc'), bg = css('--bg');
    // No font-weight here: Mermaid sizes each box from text measured at the
    // normal weight, and a bolder leaf then overflowed its box and re-wrapped.
    lines.push(`  classDef leaf fill:${acc},stroke:${acc},color:${bg}`);
    const init = (rankSpacing) => window.mermaid.initialize({
      startOnLoad: false, securityLevel: 'strict', theme: 'base',
      fontFamily: getComputedStyle(canvas).fontFamily,
      themeVariables: { fontSize: `${fsPx}px`, primaryColor: /color-mix|var\(|rgba/.test(card) ? bg : card,
        primaryTextColor: fg, primaryBorderColor: line.startsWith('rgba') ? fg : line, lineColor: fg, edgeLabelBackground: bg, tertiaryColor: bg },
      // The breaks above decide every line; Mermaid's own wrapping is off.
      flowchart: { curve: 'basis', nodeSpacing: GAP, rankSpacing, padding: PAD, htmlLabels: true, wrappingWidth: 2000 },
    });
    const draw = async (rankSpacing) => {
      init(rankSpacing);
      const { svg } = await window.mermaid.render('tree' + Math.floor(Math.random() * 1e6), lines.join('\n'));
      slot.innerHTML = svg;
      const v = (slot.querySelector('svg').getAttribute('viewBox') || '').trim().split(/[\s,]+/).map(Number);
      return v.length === 4 ? v : null;
    };
    // Scale the drawing to the slot: Mermaid sizes to its content and leaves a
    // small drawing in a big box. Inline styles beat Mermaid's own inline
    // max-width and any stylesheet 'height:auto'.
    const sizing = {};
    const fitSvg = () => {
      const svgEl = slot.querySelector('svg');
      if (!svgEl) return null;
      const vb = (svgEl.getAttribute('viewBox') || '').trim().split(/[\s,]+/).map(Number);
      const sr = slot.getBoundingClientRect();
      sizing.viewBox = vb; sizing.slot = [Math.round(sr.width), Math.round(sr.height)];
      if (vb.length !== 4 || !(vb[2] > 0 && vb[3] > 0 && sr.width > 0 && sr.height > 0)) return null;
      const scale = Math.min(sr.width / vb[2], sr.height / vb[3], 2.4);
      const w = Math.floor(vb[2] * scale), h = Math.floor(vb[3] * scale);
      svgEl.removeAttribute('style');
      svgEl.setAttribute('width', w); svgEl.setAttribute('height', h);
      svgEl.style.cssText = `width:${w}px;height:${h}px;max-width:none;max-height:none`;
      sizing.set = [w, h]; sizing.scale = Math.round(scale * 100) / 100;
      return { vb, sr, scale };
    };
    await draw(RANK);
    fitSvg();
    // The fit pass resizes the slot (a title that grows takes height from
    // it), so the tree is finished against the FINAL slot, after fit. A tree
    // is wide and short and a portrait slot is tall: when the drawing leaves
    // much of the height empty it is drawn again with longer edges between
    // its ranks, then scaled once more. The slot is flex, so none of this
    // moves the rest of the layout.
    window.__treeFinish = async () => {
      let got = fitSvg();
      if (got && perRank.length > 1 && job.layout !== 'lr' && got.vb[3] * got.scale < got.sr.height * 0.72) {
        const extra = (got.sr.height * 0.92 / got.scale - got.vb[3]) / (perRank.length - 1);
        sizing.rank = Math.round(Math.min(RANK + extra, 200));
        await draw(sizing.rank);
        got = fitSvg();
      }
      const nodes = slot.querySelectorAll('g.node').length;
      verify.diagram = { nodes_expected: n, nodes_rendered: nodes, sizing };
      if (nodes !== n) errors.push(`diagram rendered ${nodes} nodes, expected ${n}`);
    };
  }

  function renderCode(job) {
    if (!window.Prism) return;
    const lang = window.Prism.languages[job.language] ? job.language : 'clike';
    document.querySelectorAll('pre[data-code]').forEach((pre) => {
      pre.innerHTML = window.Prism.highlight(pre.textContent, window.Prism.languages[lang], lang);
    });
  }

  // ═══════════════════ fit ═══════════════════
  // Formats whose containers stretch to fill the frame (grid rows of 1fr,
  // flex:1 columns). Their box is always "full", so the grow step measures
  // how full each CARD is instead - otherwise their type never grows and the
  // cards stay half empty, which is what the first lab round showed.
  function fit(format) {
    const STRETCH = ['cheat_sheet', 'flags', 'framework', 'tier_list', 'vs', 'iceberg', 'quadrant', 'decision_tree', 'chart'];
    // Card formats that may give up stretching: their cards can hug the copy.
    const HUGGABLE = ['cheat_sheet', 'flags', 'framework', 'tier_list', 'vs'];
    const main = document.getElementById('main');
    const statement = ['hook', 'hot_take', 'cta', 'quote', 'poll', 'post_card', 'stat'].includes(format);
    // Statement slides keep air around the words; content slides use the space.
    const MIN = 0.6, FILL = statement ? 0.8 : 0.9, CARD_FILL = 0.84, HUG_BELOW = 0.72;
    const MAX = statement ? 1.35 : HUGGABLE.includes(format) ? 1.4 : 1.25;
    const round = (v) => Math.round(v * 100) / 100;
    const ox = (el) => el.scrollWidth > el.clientWidth + 1;
    // One-line elements (a stat's value, a column heading) shrink on their own
    // at every step, down to their floor, instead of capping the whole slide:
    // "Standard process" not fitting at 1.1x held a slide of body copy at 0.85.
    const lineFit = () => {
      for (const el of document.querySelectorAll('[data-fit="line"]')) {
        const floor = Number(el.dataset.fitMin || MIN);
        let v = 1;
        el.style.setProperty('--vfit', v);
        while (ox(el) && v > floor) { v = round(v - 0.04); el.style.setProperty('--vfit', v); }
      }
    };
    const apply = (v) => { canvas.style.setProperty('--fit', v); lineFit(); };
    const tooBig = () => overflowProblems(main).length > 0 || [...main.querySelectorAll('[data-fit]')].some(ox);
    let f = 1;
    apply(f);
    const grow = (stretch) => {
      while (f < MAX) {
        const next = round(f + 0.03);
        apply(next);
        const full = stretch ? cardFill(main) > CARD_FILL : usedHeight(main) > main.clientHeight * FILL;
        if (tooBig() || full) { apply(f); break; }
        f = next;
      }
    };
    let hug = false;
    if (tooBig()) {
      while (tooBig() && f > MIN) { f = round(f - 0.03); apply(f); }
    } else {
      grow(STRETCH.includes(format));
    }
    // Cards still mostly air at the final size - whether growth stopped or the
    // copy had to shrink - only advertise it when stretched. They wrap their
    // copy instead, and the type grows on height if there is room.
    if (HUGGABLE.includes(format) && cardFill(main) < HUG_BELOW) {
      hug = true;
      main.classList.add('hug');
      if (!tooBig()) grow(false);
    }
    // What stopped the growth: one step larger, what breaks? Recorded in the
    // audit so a slide that stays small can be tuned from evidence.
    let limit = f >= MAX ? 'max' : '';
    if (!limit) {
      apply(round(f + 0.03));
      const probs = overflowProblems(main);
      const lines = [...main.querySelectorAll('[data-fit]')].filter(ox).map((el) => `wide: ${(el.textContent || '').trim().slice(0, 30)}`);
      limit = [...probs, ...lines][0] || (hug || !STRETCH.includes(format) ? `fill ${round(usedHeight(main) / main.clientHeight)}` : `cards ${round(cardFill(main))}`);
      apply(f);
    }
    return { fit: f, fill: main.clientHeight ? round(usedHeight(main) / main.clientHeight) : 0, cards: round(cardFill(main)), hug, limit };
  }

  // Everything that means "this does not fit", in any direction.
  function overflowProblems(main) {
    const out = [];
    const mr = main.getBoundingClientRect();
    if (main.scrollHeight > main.clientHeight + 1) out.push('content overflows the canvas vertically');
    if (main.scrollWidth > main.clientWidth + 1) out.push('content overflows the canvas horizontally');
    // Bottom-anchored content that is too tall spills UPWARD, which scroll
    // sizes never report: the first round shipped a hot take with its first
    // line hidden under the eyebrow and an audit that said nothing.
    for (const el of main.querySelectorAll('h1, h2, h3, p, li, .card, .stat-value, .take, .display, .mega, .bub, .opt, .node, .chip')) {
      const r = el.getBoundingClientRect();
      if (r.height > 0 && r.top < mr.top - 2) { out.push(`"${(el.textContent || '').trim().slice(0, 40)}" spills above its box`); break; }
    }
    // Text that may not wrap (column headings, labels) can run out of its box
    // into the next column without moving anything else: "Typical process"
    // ran into "WizCodes" and no scroll size of the page noticed.
    for (const el of main.querySelectorAll('*')) {
      if (el.closest('.diagram, .chart-slot, .shot, .scr, .art-slot, svg, .ticker, .quad, pre')) continue;
      const st = getComputedStyle(el);
      if (st.position === 'absolute' || st.display === 'inline' || el.clientWidth <= 0) continue;
      if (el.scrollWidth > el.clientWidth + 2 && st.whiteSpace === 'nowrap' && !el.dataset.fit) {
        out.push(`"${(el.textContent || '').trim().slice(0, 40)}" runs out of its box`);
        break;
      }
    }
    for (const el of main.querySelectorAll('*')) {
      if (el.closest('.diagram, .chart-slot, .shot, .scr, .art-slot, svg')) continue;
      const st = getComputedStyle(el);
      const hidY = st.overflow === 'hidden' || st.overflowY === 'hidden';
      const hidX = st.overflow === 'hidden' || st.overflowX === 'hidden';
      if (hidY && el.clientHeight > 0 && el.scrollHeight > el.clientHeight + 2) { out.push(`text is clipped inside "${(el.textContent || '').trim().slice(0, 40)}"`); break; }
      if (hidX && el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 2) { out.push(`a line is cut off inside "${(el.textContent || '').trim().slice(0, 40)}"`); break; }
    }
    return out;
  }

  // Height actually occupied by content: the sum of the blocks, not the span
  // from first to last. A short list with a note pinned to the bottom spans
  // the whole frame and was being scored as full.
  // Blocks side by side (a grid of cards) overlap vertically and count once:
  // summing them scored a two-column cheat sheet as 180% full.
  function usedHeight(main) {
    const blocks = [];
    for (const k of main.children) {
      if (k.classList.contains('ticker')) continue;
      const st = getComputedStyle(k);
      if (st.position === 'absolute') continue;
      if (k.classList.contains('grow') || Number(st.flexGrow) > 0) blocks.push(...k.children);
      else blocks.push(k);
    }
    const spans = blocks.map((b) => b.getBoundingClientRect()).filter((r) => r.height > 0)
      .map((r) => [r.top, r.bottom]).sort((a, z) => a[0] - z[0]);
    const merged = [];
    for (const s of spans) {
      const last = merged[merged.length - 1];
      if (last && s[0] <= last[1] + 1) last[1] = Math.max(last[1], s[1]);
      else merged.push([s[0], s[1]]);
    }
    const total = merged.reduce((a, s) => a + (s[1] - s[0]), 0);
    // 'normal' parses to NaN, and a NaN fill silently disabled the grow target.
    const gaps = Math.max(0, merged.length - 1) * (parseFloat(getComputedStyle(main).rowGap) || 0);
    return total + gaps;
  }

  // How full the fullest card is: the extent of what is actually drawn in it
  // (lines of text, icons, chips) over its height. Measuring direct children
  // counted a tier row's stretched cells as content, so a tier list scored
  // 100% full at fit 1 and its chips never grew.
  function cardFill(main) {
    let worst = 0;
    const range = document.createRange();
    for (const card of main.querySelectorAll('.card, .flag-col, .tier, .pillar, .vs-col, .mf-split > div, .zone')) {
      const box = card.getBoundingClientRect();
      if (box.height < 4) continue;
      let top = Infinity, bottom = -Infinity;
      const take = (rr) => { if (rr.height > 0 && rr.width > 0) { top = Math.min(top, rr.top); bottom = Math.max(bottom, rr.bottom); } };
      const walker = document.createTreeWalker(card, NodeFilter.SHOW_TEXT);
      for (let t = walker.nextNode(); t; t = walker.nextNode()) {
        if (!t.textContent.trim()) continue;
        range.selectNodeContents(t);
        for (const rr of range.getClientRects()) take(rr);
      }
      for (const el of card.querySelectorAll('*')) {
        const host = el.closest('svg');
        if (host && host !== el) continue;
        const rr = el.getBoundingClientRect();
        if (rr.height >= box.height * 0.9) continue;          // a stretched cell is not content
        if (el.tagName.toLowerCase() === 'svg' || painted(getComputedStyle(el))) take(rr);
      }
      if (bottom <= top) continue;
      const st = getComputedStyle(card);
      worst = Math.max(worst, (bottom - top + parseFloat(st.paddingTop) + parseFloat(st.paddingBottom)) / box.height);
    }
    return worst;
  }

  // ═══════════════════ quadrant labels ═══════════════════
  // Each label tries four spots around its dot - right, left, above, below -
  // and keeps the first that stays inside the matrix and touches nothing
  // already placed: the axis captions, the zone names, the other labels. A
  // fixed rule (right half grows left) collided two labels on the same row.
  // When labels still touch at full size (long labels in a monospace look),
  // the label type steps down and the placement runs again.
  function placeQuadLabels() {
    const quad = document.querySelector('.quad');
    if (!quad) return null;
    let overlap = 0;
    for (const scale of [1, 0.9, 0.8, 0.72]) {
      quad.style.setProperty('--qfs', scale);
      overlap = placeOnce(quad);
      if (overlap === 0) return { scale, overlap: 0 };
    }
    return { scale: 0.72, overlap: Math.round(overlap) };
  }

  function placeOnce(quad) {
    const qr = quad.getBoundingClientRect();
    const slack = Math.min(W, H) * 0.05;               // the quad's own top/bottom margin
    const range = document.createRange();
    const taken = [];
    for (const el of quad.querySelectorAll('.zone, .lbl')) {
      range.selectNodeContents(el);
      for (const rr of range.getClientRects()) if (rr.width > 0) taken.push(rr);
    }
    // Every other point's dot is an obstacle for this label.
    const dots = new Map([...quad.querySelectorAll('.pt')].map((p) => [p, p.querySelector('i').getBoundingClientRect()]));
    const area = (a, b) => Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) *
      Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
    const grow = (r, p) => ({ left: r.left - p, right: r.right + p, top: r.top - p, bottom: r.bottom + p });
    let total = 0;
    const pts = [...quad.querySelectorAll('.pt')].sort((a, b) => Number(b.classList.contains('us')) - Number(a.classList.contains('us')));
    for (const pt of pts) {
      const tx = pt.querySelector('.tx');
      const obstacles = [...taken, ...[...dots].filter(([p]) => p !== pt).map(([, r]) => r)];
      const h = tx.getBoundingClientRect().height + 4;
      // The side formats.js chose, remembered across re-runs of the placement.
      if (pt.dataset.pref === undefined) pt.dataset.pref = pt.classList.contains('r') ? 'r' : '';
      const first = pt.dataset.pref;
      const sides = [first, first ? '' : 'r'];
      // Beside the dot, then above or below it, then beside it nudged up or
      // down a line at a time: the first spot inside the matrix that touches
      // nothing wins; failing that, the spot with the least overlap.
      const options = [...sides.map((s) => [s, 0]), ['up', 0], ['down', 0]];
      for (const k of [1, -1, 2, -2]) for (const s of sides) options.push([s, k * h]);
      let best = null;
      for (const [cls, dy] of options) {
        pt.classList.remove('r', 'up', 'down');
        if (cls) pt.classList.add(cls);
        pt.style.setProperty('--dy', `${dy}px`);
        const rr = tx.getBoundingClientRect();
        const inside = rr.left >= qr.left - 2 && rr.right <= qr.right + 2 && rr.top >= qr.top - slack && rr.bottom <= qr.bottom + slack;
        if (!inside) continue;
        const overlap = obstacles.reduce((sum, t) => sum + area(grow(rr, 4), t), 0);
        if (!best || overlap < best.overlap) best = { cls, dy, overlap };
        if (overlap === 0) break;
      }
      pt.classList.remove('r', 'up', 'down');
      if (best && best.cls) pt.classList.add(best.cls);
      pt.style.setProperty('--dy', `${best ? best.dy : 0}px`);
      taken.push(tx.getBoundingClientRect());
      total += best ? best.overlap : 1;              // nowhere inside the matrix counts as touching
    }
    return total;
  }

  // ═══════════════════ figure art in empty space ═══════════════════
  // Solid shapes (Bauhaus tiles, UI cards, pixel blocks) are figures, not
  // texture. Behind copy, the knockout carved them into ghosts; a designer
  // would put them where the layout left room. So they are drawn last, into
  // the largest rectangle the content does not touch - and not at all when
  // the slide has no real room.
  function figureArt(kind) { return kind === 'bauhaus' || kind === 'cards' || kind === 'pixels'; }

  function placeInSpace(art) {
    const cell = Math.max(12, Math.round(Math.min(W, H) / 45));
    const cols = Math.ceil(W / cell), rows = Math.ceil(H / cell);
    const grid = Array.from({ length: rows }, () => new Uint8Array(cols));
    const pad = Math.min(W, H) * 0.035;
    for (const [x, y, w, h] of keepOuts()) {
      const c0 = Math.max(0, Math.floor((x - pad) / cell)), c1 = Math.min(cols - 1, Math.floor((x + w + pad) / cell));
      const r0 = Math.max(0, Math.floor((y - pad) / cell)), r1 = Math.min(rows - 1, Math.floor((y + h + pad) / cell));
      for (let r = r0; r <= r1; r++) for (let c = c0; c <= c1; c++) grid[r][c] = 1;
    }
    // Largest empty rectangle: a histogram of free cells per column, swept
    // row by row (the classic maximal-rectangle method).
    const heights = new Array(cols).fill(0);
    let best = { area: 0 };
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) heights[c] = grid[r][c] ? 0 : heights[c] + 1;
      const stack = [];
      for (let c = 0; c <= cols; c++) {
        const hgt = c < cols ? heights[c] : 0;
        let start = c;
        while (stack.length && stack[stack.length - 1][1] >= hgt) {
          const [s, sh] = stack.pop();
          const area = sh * (c - s);
          if (area > best.area) best = { area, c0: s, c1: c - 1, r0: r - sh + 1, r1: r };
          start = s;
        }
        stack.push([start, hgt]);
      }
    }
    if (!best.area) return 'no space';
    const x = best.c0 * cell, y = best.r0 * cell;
    const w = Math.min(W - x, (best.c1 - best.c0 + 1) * cell), h = Math.min(H - y, (best.r1 - best.r0 + 1) * cell);
    if (w < W * 0.24 || h < H * 0.14 || w * h < W * H * 0.07) return `too little space (${Math.round(w)}x${Math.round(h)})`;
    const holder = document.createElement('div');
    holder.innerHTML = window.ART[art.kind](window.artRng(art.seed || 1), Math.round(w), Math.round(h));
    const svgEl = holder.firstElementChild;
    svgEl.classList.add('art-space');
    svgEl.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    svgEl.style.cssText = `left:${x}px;top:${y}px;width:${w}px;height:${h}px`;
    document.getElementById('bg').appendChild(svgEl);
    return `${Math.round(w)}x${Math.round(h)} at ${Math.round(x)},${Math.round(y)}`;
  }

  // ═══════════════════ art knockout ═══════════════════
  // Background art covers the canvas and the layout sits on top of it, so a
  // line of the art could run straight through a line of copy: the neon
  // network crossed card text and the contrast check, which samples colours,
  // still passed it. The mask clears the art under every line of text, every
  // painted panel and every figure, feathered so it fades out around the
  // content rather than stopping at a hard edge.
  // Soft colour fields, not figures: nothing to clear. (A function, not a
  // const: the main block above runs before a const down here exists.)
  function fieldArt(kind) { return kind === 'blobs'; }
  function knockout(svgEl, seed) {
    const vb = svgEl.viewBox && svgEl.viewBox.baseVal;
    if (!vb || !vb.width || !vb.height) return 0;
    const cb = canvas.getBoundingClientRect();
    const r = svgEl.getBoundingClientRect();
    const s = Math.max(r.width / vb.width, r.height / vb.height);   // preserveAspectRatio slice
    if (!s) return 0;
    const ox = r.left - cb.left + (r.width - vb.width * s) / 2;
    const oy = r.top - cb.top + (r.height - vb.height * s) / 2;
    let holes = '', n = 0;
    for (const [x, y, w, h] of keepOuts()) {
      const ax = (x - ox) / s + vb.x, ay = (y - oy) / s + vb.y, aw = w / s, ah = h / s;
      if (ax > vb.x + vb.width || ay > vb.y + vb.height || ax + aw < vb.x || ay + ah < vb.y) continue;
      holes += `<rect x="${ax.toFixed(1)}" y="${ay.toFixed(1)}" width="${aw.toFixed(1)}" height="${ah.toFixed(1)}" rx="${(Math.min(aw, ah) * 0.3).toFixed(1)}"/>`;
      n++;
    }
    if (!n) return 0;
    const id = 'ko' + seed, m = Math.max(vb.width, vb.height) * 0.1;
    const box = `x="${(vb.x - m).toFixed(1)}" y="${(vb.y - m).toFixed(1)}" width="${(vb.width + 2 * m).toFixed(1)}" height="${(vb.height + 2 * m).toFixed(1)}"`;
    const blur = (Math.min(W, H) * 0.014 / s).toFixed(1);
    const tmp = document.createElement('div');
    tmp.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg"><defs>` +
      `<filter id="${id}b" filterUnits="userSpaceOnUse" ${box}><feGaussianBlur stdDeviation="${blur}"/></filter>` +
      `<mask id="${id}" maskUnits="userSpaceOnUse" ${box}><rect ${box} fill="#fff"/><g fill="#000" filter="url(#${id}b)">${holes}</g></mask>` +
      `</defs></svg>`;
    const defs = tmp.querySelector('defs');
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.setAttribute('mask', `url(#${id})`);
    for (const k of [...svgEl.childNodes]) if (!(k.nodeName && k.nodeName.toLowerCase() === 'defs')) g.appendChild(k);
    svgEl.insertBefore(defs, svgEl.firstChild);
    svgEl.appendChild(g);
    return n;
  }

  // Canvas rectangles the art must stay out of: each line of text (padded by
  // a share of its own size), each painted element, each figure. Content in
  // a frosted panel is skipped - the frost already separates it from the art.
  function keepOuts() {
    const cb = canvas.getBoundingClientRect();
    const frame = canvas.querySelector('.frame');
    const unit = Math.min(W, H) / 100;
    const out = [];
    const push = (r, pad) => {
      if (r.width < 1 || r.height < 1) return;
      out.push([r.left - cb.left - pad, r.top - cb.top - pad, r.width + pad * 2, r.height + pad * 2]);
    };
    const all = [...frame.querySelectorAll('*')];
    const frosted = all.filter((el) => { const b = getComputedStyle(el).backdropFilter; return b && b !== 'none'; });
    const inFrost = (el) => frosted.some((f) => f.contains(el));
    const walker = document.createTreeWalker(frame, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    for (let t = walker.nextNode(); t; t = walker.nextNode()) {
      if (!t.textContent.trim()) continue;
      const el = t.parentElement;
      if (!el || el.closest('svg, .ticker') || inFrost(el)) continue;
      const pad = Math.max(unit, parseFloat(getComputedStyle(el).fontSize) * 0.4);
      range.selectNodeContents(t);
      for (const rr of range.getClientRects()) push(rr, pad);
    }
    for (const el of all) {
      if (el.closest('.ticker') || inFrost(el)) continue;
      const tag = el.tagName.toLowerCase();
      const host = el.closest('svg');
      if (host && host !== el) continue;
      const rr = el.getBoundingClientRect();
      if (rr.width * rr.height > W * H * 0.6) continue;
      if (tag === 'svg' || tag === 'img') { push(rr, unit * 0.8); continue; }
      if (painted(getComputedStyle(el))) push(rr, unit * 0.6);
    }
    return out;
  }

  function alpha(col) {
    if (!col || col === 'transparent') return 0;
    const slash = /\/\s*([\d.]+)(%?)\s*\)\s*$/.exec(col);
    if (slash) return parseFloat(slash[1]) / (slash[2] ? 100 : 1);
    const m = /^rgba\(([^)]+)\)$/.exec(col);
    if (m) { const p = m[1].split(','); return p.length === 4 ? parseFloat(p[3]) : 1; }
    return 1;
  }

  function painted(st) {
    if (alpha(st.backgroundColor) > 0.02) return true;
    if (st.backgroundImage && st.backgroundImage !== 'none') return true;
    if (st.boxShadow && st.boxShadow !== 'none') return true;
    for (const side of ['Top', 'Right', 'Bottom', 'Left']) {
      if (parseFloat(st[`border${side}Width`]) > 0 && alpha(st[`border${side}Color`]) > 0.02) return true;
    }
    return false;
  }

  // ═══════════════════ sketch ornament ═══════════════════
  function sketch(seed) {
    const fx = document.getElementById('fx');
    const box = canvas.getBoundingClientRect();
    const svgEl = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svgEl.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svgEl.setAttribute('width', W); svgEl.setAttribute('height', H);
    svgEl.style.left = '0'; svgEl.style.top = '0';
    fx.appendChild(svgEl);
    const rc = window.rough.svg(svgEl);
    const stroke = getComputedStyle(canvas).getPropertyValue('--fg').trim() || '#1B2433';
    const accent = getComputedStyle(canvas).getPropertyValue('--acc').trim() || '#1E7AAB';
    let k = 0;
    for (const el of document.querySelectorAll('#main .card, #main .flag-col, #main .opt, #main .win, #main .mf-split > div, #main .tier, #main .mock-browser')) {
      const r = el.getBoundingClientRect();
      svgEl.appendChild(rc.rectangle(r.left - box.left, r.top - box.top, r.width, r.height,
        { roughness: 1.5, bowing: 1.2, stroke, strokeWidth: 2.4, seed: seed + (k++) }));
    }
    let u = 0;
    for (const el of document.querySelectorAll('#main .display .grad, #main .h1 .grad, #main .mega .grad, #main .h2 .grad')) {
      if (u++ > 2) break;
      for (const r of el.getClientRects()) {
        const y = r.bottom - box.top + 4;
        svgEl.appendChild(rc.line(r.left - box.left, y, r.right - box.left, y + 2, { roughness: 2.2, stroke: accent, strokeWidth: 5, seed: seed + 50 + u }));
      }
    }
    const sv = document.querySelector('#main .stat-value');
    if (sv) {
      const r = sv.getBoundingClientRect();
      svgEl.appendChild(rc.ellipse(r.left - box.left + r.width / 2, r.top - box.top + r.height / 2, r.width * 1.15, r.height * 1.25,
        { roughness: 2, stroke: accent, strokeWidth: 4, seed: seed + 99 }));
    }
  }

  // ═══════════════════ audit ═══════════════════
  function audit(fitResult, layout) {
    const main = document.getElementById('main');
    const foot = document.getElementById('foot');
    const frame = canvas.querySelector('.frame');
    const pad = parseFloat(getComputedStyle(frame).paddingLeft);
    const box = canvas.getBoundingClientRect();

    if (!main.textContent.trim() && !main.querySelector('svg, img')) errors.push('the format drew nothing');
    errors.push(...overflowProblems(main));
    const headBottom = document.getElementById('head').getBoundingClientRect().bottom;
    for (const el of main.querySelectorAll('h1, h2, h3, p, .display, .mega, .take')) {
      const r = el.getBoundingClientRect();
      if (r.height > 0 && document.getElementById('head').textContent.trim() && r.top < headBottom - 2) {
        errors.push(`"${el.textContent.trim().slice(0, 40)}" overlaps the header`);
        break;
      }
    }
    const junk = main.textContent.match(/\b(undefined|null|NaN|\[object Object\])\b/);
    if (junk) errors.push(`the word "${junk[1]}" is on the canvas - a field was missing`);

    const footTop = foot.getBoundingClientRect().top;
    const boxes = [];
    const leaves = [...canvas.querySelectorAll('#head *, #main *, #foot *')].filter((el) =>
      [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()) && !el.closest('.diagram, .chart-slot, .ticker, svg, .shot, .scr'));
    for (const el of leaves) {
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) continue;
      const inFoot = !!el.closest('#foot');
      if (r.left < box.left + pad - 3 || r.right > box.right - pad + 3)
        errors.push(`"${el.textContent.trim().slice(0, 40)}" sits outside the margin`);
      if (!inFoot && r.bottom > footTop + 2)
        errors.push(`"${el.textContent.trim().slice(0, 40)}" runs under the footer`);
      const s = getComputedStyle(el);
      if (boxes.length < 80) {
        boxes.push({ x: r.left - box.left, y: r.top - box.top, w: r.width, h: r.height, color: s.color,
          size: parseFloat(s.fontSize), weight: Number(s.fontWeight) || 400,
          clip: (s.webkitBackgroundClip === 'text' || s.backgroundClip === 'text'), text: el.textContent.trim().slice(0, 40) });
      }
    }
    if (fitResult.fit <= 0.6) errors.push('could not fit even at 0.6x - the copy is far too long');
    else if (fitResult.fit < 0.8) warnings.push(`type scaled to ${fitResult.fit}x to fit`);
    const contentFormats = ['checklist', 'cheat_sheet', 'flags', 'vs', 'steps', 'framework', 'tier_list', 'timeline', 'recap', 'chat'];
    if (contentFormats.includes(D.format) && fitResult.fill && fitResult.fill < 0.42)
      warnings.push(`content fills only ${Math.round(fitResult.fill * 100)}% of the space`);

    const uniq = (a) => [...new Set(a)];
    return {
      format: D.format, layout, look: D.look, accent: D.accent, art: (D.art || {}).kind || 'none',
      fit: fitResult.fit, fill: fitResult.fill, hug: !!fitResult.hug, limit: fitResult.limit || '', errors: uniq(errors).slice(0, 12), warnings: uniq(warnings).slice(0, 12), verify,
      boxes, text: main.textContent.replace(/\s+/g, ' ').trim().slice(0, 1200),
    };
  }
})();
