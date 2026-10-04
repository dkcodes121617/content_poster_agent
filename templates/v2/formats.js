/* ═══════════════════════════════════════════════════════════════════════════
   Format builders. FORMATS[name].build(c, x, layout) returns the markup for
   #main; `c` is the format's content (validated in Python against
   design/registry.py before it ever reaches a page), `x` the shared helpers.

   Text from the writer is escaped, always. Two marks are honoured:
     *accent*    -> the look's emphasis (gradient, colour or italic serif)
     ==marker==  -> a highlighter stroke behind the words
   Anything else that looks like markup is shown as the characters it is.

   Engine-backed formats (chart, decision_tree, code) leave a slot and push a
   job onto x.jobs; runtime.js awaits the jobs before measuring anything.
   ═══════════════════════════════════════════════════════════════════════════ */
(function () {
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
  const has = (v) => v !== undefined && v !== null && v !== '' && !(Array.isArray(v) && !v.length);
  // "Off-the-shelf" broke after its first hyphen in a column heading; a
  // compound is one word to a reader, so it wraps as one. A WORD JOINER after
  // each hyphen forbids the break without adding an element: a <span> inside
  // a flex row becomes its own flex item, which split "One-command deploy
  // from the repo" into two side-by-side columns of text.
  const nw = (h) => h.replace(/([A-Za-z0-9])-(?=[A-Za-z0-9])/g, '$1-\u2060');
  const rich = (s) => nw(esc(s))
    .replace(/==(.+?)==/g, '<span class="mark">$1</span>')
    .replace(/\*(.+?)\*/g, '<span class="grad">$1</span>')
    .replace(/\*/g, '').replace(/==/g, '')
    .replace(/\n/g, '<br>');
  const plain = (s) => nw(esc(s)).replace(/\*+/g, '').replace(/==/g, '').replace(/\n/g, '<br>');
  const arr = (v) => (Array.isArray(v) ? v : []);
  const txt = (it) => (typeof it === 'string' ? it : (it && (it.text || it.head || it.label)) || '');

  function makeHelpers(D) {
    const icons = D.icons || {};
    const icon = (name, cls = 'ico') => {
      const markup = icons[name] || icons['check'] || '';
      return markup ? `<span class="${cls}">${markup}</span>` : '';
    };
    return { esc, has, rich, plain, arr, txt, icon, jobs: [], errors: [], warnings: [], D };
  }

  const title = (t, cls = 'h1') => (has(t) ? `<h2 class="${cls}" data-fit="block">${rich(t)}</h2>` : '');
  const tick = (x, bad) => `<span class="ic${bad ? ' bad' : ''}">${x.icon(bad ? 'x' : 'check')}</span>`;

  const FORMATS = {

    // ── openers & statements ────────────────────────────────────────────────
    hook: {
      layouts: ['stack', 'split', 'center', 'ticker'],
      build(c, x, layout) {
        const text = `<div class="hook-wrap"><p class="display" data-fit="block">${rich(c.hook)}</p>` +
          (has(c.sub) ? `<p class="hook-sub">${plain(c.sub)}</p>` : '') + '</div>';
        if (layout === 'split') return `<div class="split"><div class="grow end">${text}</div><div class="art-slot" data-art-slot></div></div>`;
        if (layout === 'center') return `<div class="grow center">${text}</div>`;
        if (layout === 'ticker') {
          const word = esc(String(c.ticker || txt(c.hook).replace(/[*=]/g, '').split(/\s+/).slice(-1)[0] || 'WizCodes').toUpperCase());
          return `<div class="ticker" style="top:30%">${(word + ' · ').repeat(6)}</div><div class="grow end">${text}</div>`;
        }
        return `<div class="grow end">${text}</div>`;
      },
    },

    hot_take: {
      layouts: ['big', 'quote', 'underline'],
      build(c, x, layout) {
        const support = has(c.support) ? `<p class="body">${plain(c.support)}</p>` : '';
        const by = `<div class="byline"><span class="av">W</span><div><div class="small" style="color:var(--fg);font-weight:600">${plain(c.byline || 'WizCodes')}</div>` +
          `<div class="micro">${plain(c.byline_role || 'founder-run software studio')}</div></div></div>`;
        if (layout === 'quote') return `<div class="grow center gap-m"><div class="take-quote">&ldquo;</div><p class="take display" data-fit="block">${rich(c.take)}</p>${support}${by}</div>`;
        if (layout === 'underline') {
          const t = esc(c.take).replace(/\*(.+?)\*/g, '<span class="u">$1</span>').replace(/==(.+?)==/g, '<span class="mark">$1</span>').replace(/[*]|==/g, '').replace(/\n/g, '<br>');
          return `<div class="grow center gap-l take-underline"><p class="take mega" data-fit="block">${t}</p>${support}</div>`;
        }
        return `<div class="grow end gap-m"><p class="take mega" data-fit="block">${rich(c.take)}</p>${support}</div>`;
      },
    },

    // ── numbers ─────────────────────────────────────────────────────────────
    stat: {
      layouts: ['hero', 'ring', 'bento'],
      build(c, x, layout) {
        const src = has(c.source) ? `<p class="source">Source: ${plain(c.source)}</p>` : '';
        const ctx = has(c.context) ? `<p class="body">${plain(c.context)}</p>` : '';
        const pct = /^\s*(\d+(?:\.\d+)?)\s*%\s*$/.exec(String(c.value || ''));
        if (layout === 'ring' && pct) {
          const v = Math.max(0, Math.min(100, Number(pct[1]))), r = 44, C = 2 * Math.PI * r;
          return `<div class="grow center gap-l" style="align-items:flex-start">` +
            `<div class="ring"><svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="${r}" fill="none" style="stroke:var(--line)" stroke-width="9"/>` +
            `<circle cx="50" cy="50" r="${r}" fill="none" style="stroke:var(--acc)" stroke-width="9" stroke-linecap="round" stroke-dasharray="${(v / 100 * C).toFixed(2)} ${C.toFixed(2)}" data-verify-arc="${v}"/></svg>` +
            `<div class="rv grad" data-fit="line">${plain(c.value)}</div></div>` +
            `<p class="stat-label" data-fit="block">${rich(c.label)}</p>${ctx}${src}</div>`;
        }
        if (layout === 'bento') {
          const tiles = arr(c.tiles).slice(0, 3);
          const minis = tiles.map((t) => `<div class="card mini"><div class="big">${plain(t.value)}</div><div class="small">${plain(t.label)}</div></div>`).join('');
          const style = tiles.length ? `grid-template-columns:repeat(${tiles.length},minmax(0,1fr))` : 'grid-template-columns:1fr;grid-template-rows:1fr';
          return `<div class="bento stat-bento" style="${style}"><div class="card hero">` +
            `<div class="stat-value grad" data-fit="line" style="font-size:calc(24cqmin*var(--fit)*var(--vfit,1))">${plain(c.value)}</div>` +
            `<p class="stat-label">${rich(c.label)}</p>${src}</div>${minis}</div>`;
        }
        return `<div class="grow end gap-m"><div class="stat-value grad" data-fit="line">${plain(c.value)}</div>` +
          `<p class="stat-label" data-fit="block">${rich(c.label)}</p>${ctx}${src}</div>`;
      },
    },

    chart: {
      layouts: ['bar', 'column', 'donut'],
      build(c, x, layout) {
        x.jobs.push({ engine: 'vega', layout, chart: c });
        const src = has(c.source) ? `<p class="source">Source: ${plain(c.source)}</p>` : '';
        return `${title(c.title, 'h2')}<div class="chart-slot" data-chart></div>${src}`;
      },
    },

    // ── words ───────────────────────────────────────────────────────────────
    quote: {
      layouts: ['classic', 'card'],
      build(c, x, layout) {
        const who = `<div class="byline"><span class="av">${esc(String(c.name || 'W').trim().charAt(0).toUpperCase())}</span><div>` +
          `<div class="small" style="color:var(--fg);font-weight:600">${plain(c.name)}</div>${has(c.role) ? `<div class="micro">${plain(c.role)}</div>` : ''}</div></div>`;
        const q = `<p class="quote-text h1" data-fit="block">${rich(c.quote)}</p>`;
        if (layout === 'card') return `<div class="grow center"><div class="card gap-m" style="display:flex;flex-direction:column;padding:5cqmin"><div class="quote-mark">&ldquo;</div>${q}${who}</div></div>`;
        return `<div class="grow center gap-m"><div class="quote-mark">&ldquo;</div>${q}${who}</div>`;
      },
    },

    myth_fact: {
      layouts: ['stacked', 'split'],
      build(c, x, layout) {
        if (layout === 'split') {
          return `${title(c.title, 'h2')}<div class="grow center"><div class="mf-split"><div class="m"><span class="tagline bad">${x.icon('x')} Myth</span><p class="h3">${plain(c.myth)}</p></div>` +
            `<div class="f"><span class="tagline ok">${x.icon('check')} Reality</span><p class="h3">${rich(c.fact)}</p></div></div></div>`;
        }
        return `<div class="mf"><div class="mf-myth"><span class="tagline bad">${x.icon('x')} Myth</span><p class="h2" data-fit="block">${plain(c.myth)}</p></div>` +
          `<div class="rule"></div><div><span class="tagline ok">${x.icon('check')} Reality</span><p class="h1" data-fit="block">${rich(c.fact)}</p></div></div>`;
      },
    },

    post_card: {
      layouts: ['card'],
      build(c, x) {
        return `<div class="grow center"><div class="post"><div class="who"><span class="av">W</span><div><div class="nm">${plain(c.name || 'WizCodes')} ${x.icon('badge-check')}</div>` +
          `<div class="hd">${plain(c.handle || '@wiz_codes')}</div></div></div><p class="tx" data-fit="block">${rich(c.text)}</p></div></div>`;
      },
    },

    notes: {
      layouts: ['ios'],
      build(c, x) {
        const items = arr(c.items).map((it) => `<li class="${it && it.done ? 'done' : ''}"><span class="box"></span><span>${plain(txt(it))}</span></li>`).join('');
        return `<div class="grow center"><div class="notes"><div class="bar"><span>‹ Notes</span><span>Done</span></div><div class="d">${plain(c.date || '')}</div>` +
          `<div class="t" data-fit="block">${plain(c.title)}</div><ul>${items}</ul></div></div>`;
      },
    },

    chat: {
      layouts: ['bubbles'],
      build(c, x) {
        const L = Object.assign({ them: 'Founder', us: 'WizCodes' }, c.labels || {});
        let last = '';
        const msgs = arr(c.messages).map((m) => {
          const side = m.from === 'us' ? 'us' : 'them';
          const label = side !== last ? `<div class="bub-who ${side}">${plain(L[side])}</div>` : '';
          last = side;
          return `${label}<div class="bub ${side}">${plain(m.text)}</div>`;
        }).join('');
        return `${title(c.title, 'h2')}<div class="chat">${msgs}</div>`;
      },
    },

    // ── lists & frameworks ──────────────────────────────────────────────────
    checklist: {
      layouts: ['list', 'cards', 'bento'],
      build(c, x, layout) {
        const bad = c.kind === 'dont';
        const items = arr(c.items);
        if (layout === 'cards') {
          return `${title(c.title)}<div class="grow center"><div class="cards">` + items.map((it, i) =>
            `<div class="card"><span class="n-badge">${String(i + 1).padStart(2, '0')}</span><div><div class="h3">${plain(txt(it))}</div>` +
            `${it && it.sub ? `<div class="small">${plain(it.sub)}</div>` : ''}</div></div>`).join('') + '</div></div>';
        }
        if (layout === 'bento') {
          const cols = items.length > 4 ? 3 : 2;
          return `${title(c.title, 'h2')}<div class="bento" style="grid-template-columns:repeat(${cols},1fr)">` + items.map((it, i) =>
            `<div class="card" style="${i === 0 && items.length % cols ? `grid-column:span ${cols - (items.length - 1) % cols}` : ''}">` +
            `${x.icon((it && it.icon) || (bad ? 'circle-x' : 'circle-check'))}<div class="h3" style="font-size:calc(4.8cqmin*var(--fit))">${plain(txt(it))}</div></div>`).join('') + '</div>';
        }
        return `${title(c.title)}<div class="grow center"><ul class="list">` + items.map((it) =>
          `<li class="li">${tick(x, bad)}<span>${plain(txt(it))}${it && it.sub ? `<span class="sub">${plain(it.sub)}</span>` : ''}</span></li>`).join('') +
          `</ul></div>${has(c.note) ? `<p class="small">${plain(c.note)}</p>` : ''}`;
      },
    },

    cheat_sheet: {
      layouts: ['grid', 'bento', 'numbered'],
      build(c, x, layout) {
        const cells = arr(c.cells);
        const cols = cells.length > 4 ? 2 : (cells.length === 3 ? 1 : 2);
        if (layout === 'bento' && cells.length >= 4) {
          // A full-width hero and footer around pairs: asymmetric enough to read
          // as a bento, never so narrow that body copy breaks every two words.
          const spans = { 4: [6, 3, 3, 6], 5: [6, 3, 3, 3, 3], 6: [6, 3, 3, 3, 3, 6] }[cells.length] || cells.map(() => 3);
          return `${title(c.title, 'h2')}<div class="cheat" style="grid-template-columns:repeat(6,minmax(0,1fr))">` + cells.map((cl, i) =>
            // Icons only on the wide cells: the hero carries the picture, the
            // pairs carry the words - and each pair row is an icon-row shorter.
            `<div class="card${spans[i] === 6 ? ' wide' : ''}" style="grid-column:span ${spans[i]}">${spans[i] === 6 ? x.icon(cl.icon || 'sparkles') : ''}<div class="h3">${plain(cl.head)}</div><div class="small">${plain(cl.body)}</div></div>`).join('') + '</div>';
        }
        if (layout === 'numbered') {
          return `${title(c.title, 'h2')}<div class="cheat" style="grid-template-columns:repeat(${cols},1fr)">` + cells.map((cl, i) =>
            `<div class="card"><span class="n-badge">${String(i + 1).padStart(2, '0')}</span><div class="h3">${plain(cl.head)}</div><div class="small">${plain(cl.body)}</div></div>`).join('') + '</div>';
        }
        return `${title(c.title, 'h2')}<div class="cheat" style="grid-template-columns:repeat(${cols},1fr)">` + cells.map((cl) =>
          `<div class="card">${x.icon(cl.icon || 'sparkles')}<div class="h3">${plain(cl.head)}</div><div class="small">${plain(cl.body)}</div></div>`).join('') + '</div>';
      },
    },

    flags: {
      layouts: ['columns'],
      build(c, x) {
        const col = (cls, label, items, ic) => `<div class="flag-col ${cls}"><p class="h3" data-fit="line" data-fit-min="0.78">${x.icon(ic)} ${plain(label)}</p>` +
          arr(items).map((t) => `<p class="small">${plain(txt(t))}</p>`).join('') + '</div>';
        return `${title(c.title, 'h2')}<div class="flags">${col('red', c.red_label || 'Red flags', c.red, 'flag')}${col('green', c.green_label || 'Green flags', c.green, 'circle-check')}</div>`;
      },
    },

    vs: {
      layouts: ['columns', 'table'],
      build(c, x, layout) {
        const L = c.left || {}, R = c.right || {};
        if (layout === 'table' && arr(c.rows).length) {
          const win = c.winner;
          return `${title(c.title, 'h2')}<div class="grow center"><table class="vs-table"><thead><tr><th></th><th>${plain(L.label)}</th><th>${plain(R.label)}</th></tr></thead><tbody>` +
            arr(c.rows).map((r) => `<tr><td>${plain(r.aspect)}</td><td class="${win === 'left' ? 'is-win' : ''}">${plain(r.left)}</td><td class="${win === 'right' ? 'is-win' : ''}">${plain(r.right)}</td></tr>`).join('') +
            `</tbody></table>${has(c.verdict) ? `<p class="verdict">${rich(c.verdict)}</p>` : ''}</div>`;
        }
        const col = (side, d) => `<div class="vs-col${c.winner === side ? ' is-win' : ''}"><p class="h3">${plain(d.label)}</p>` +
          arr(d.points).map((p) => `<p class="small">${plain(txt(p))}</p>`).join('') + '</div>';
        return `${title(c.title, 'h2')}<div class="vs">${col('left', L)}<div class="vs-mid">vs</div>${col('right', R)}</div>` +
          (has(c.verdict) ? `<p class="verdict">${rich(c.verdict)}</p>` : '');
      },
    },

    steps: {
      layouts: ['rail', 'cards'],
      build(c, x, layout) {
        const steps = arr(c.steps);
        if (layout === 'cards') {
          return `${title(c.title)}<div class="grow center"><div class="cards">` + steps.map((s, i) =>
            `<div class="card"><span class="n-badge">${String(i + 1).padStart(2, '0')}</span><div><div class="h3">${plain(s.head)}</div>${s.body ? `<div class="small">${plain(s.body)}</div>` : ''}</div></div>`).join('') + '</div></div>';
        }
        return `${title(c.title)}<div class="grow center"><ol class="rail">` + steps.map((s) =>
          `<li><div><div class="h3">${plain(s.head)}</div>${s.body ? `<div class="small">${plain(s.body)}</div>` : ''}</div></li>`).join('') + '</ol></div>';
      },
    },

    framework: {
      layouts: ['pillars', 'acronym'],
      build(c, x, layout) {
        const ps = arr(c.pillars);
        const head = `${has(c.name) ? `<p class="eyebrow"><span class="tag">${plain(c.name)}</span></p>` : ''}${title(c.title, 'h2')}`;
        return `${head}<div class="pillars">` + ps.map((p, i) => {
          const L = layout === 'acronym' ? esc(String(p.letter || p.head || '?').trim().charAt(0).toUpperCase()) : String(i + 1).padStart(2, '0');
          return `<div class="pillar"><div class="L grad"${layout === 'acronym' ? '' : ' style="font-size:calc(9cqmin*var(--fit))"'}>${L}</div>` +
            `<div><div class="h3">${plain(p.head)}</div>${p.body ? `<div class="small">${plain(p.body)}</div>` : ''}</div></div>`;
        }).join('') + '</div>';
      },
    },

    tier_list: {
      layouts: ['tiers'],
      build(c, x) {
        return `${title(c.title, 'h2')}<div class="tiers">` + arr(c.tiers).map((t) =>
          `<div class="tier ${esc(String(t.tier || 'c').toLowerCase().charAt(0))}"><div class="t">${esc(String(t.tier || '?').toUpperCase().slice(0, 1))}</div>` +
          `<div class="items">${arr(t.items).map((i) => `<span>${plain(txt(i))}</span>`).join('')}</div></div>`).join('') + '</div>';
      },
    },

    iceberg: {
      layouts: ['iceberg'],
      build(c, x) {
        const chips = (items) => arr(items).map((t) => `<span class="chip">${plain(txt(t))}</span>`).join('');
        return `${title(c.title, 'h2')}<div class="berg"><div class="water"></div>` +
          `<svg class="ice" viewBox="0 0 300 400" aria-hidden="true"><path d="M150 14 L186 70 L176 84 L206 120 L94 120 L118 82 L110 64 Z" style="fill:var(--card);stroke:var(--fg)" stroke-width="2" stroke-linejoin="round"/>` +
          `<path d="M94 120 L206 120 L246 176 L272 262 L236 352 L168 392 L92 378 L36 300 L44 214 Z" style="fill:var(--card);stroke:var(--fg)" stroke-width="2" stroke-linejoin="round" opacity="0.55"/></svg>` +
          `<div class="sky"><span class="cap">${plain(c.above_label || 'What people see')}</span>${chips(c.above)}</div>` +
          `<div class="deep"><span class="cap">${plain(c.below_label || 'What it takes')}</span>${chips(c.below)}</div></div>`;
      },
    },

    poll: {
      layouts: ['options'],
      build(c, x) {
        return `<div class="grow center gap-l"><p class="h1" data-fit="block">${rich(c.question)}</p><div class="opts">` +
          arr(c.options).map((o, i) => `<div class="opt"><span class="k">${'ABCD'[i] || i + 1}</span><span>${plain(txt(o))}</span></div>`).join('') +
          `</div><p class="micro">${plain(c.ask || 'Answer in the comments.')}</p></div>`;
      },
    },

    // ── diagrams ────────────────────────────────────────────────────────────
    decision_tree: {
      layouts: ['td', 'lr'],
      build(c, x, layout) {
        x.jobs.push({ engine: 'mermaid', kind: 'tree', layout, tree: c.tree });
        return `${title(c.title, 'h2')}<div class="diagram" data-diagram></div>`;
      },
    },

    timeline: {
      layouts: ['vertical', 'horizontal'],
      build(c, x, layout) {
        const ev = arr(c.events);
        const wide = x.D.canvas && x.D.canvas.w > x.D.canvas.h;
        if (layout === 'horizontal' && (wide ? ev.length <= 5 : ev.length <= 3)) {
          return `${title(c.title)}<div class="grow center"><div class="tl-h">` + ev.map((e) =>
            `<div><div class="when mono" style="font-size:calc(2.5cqmin*var(--fit));color:var(--acc-text);letter-spacing:.08em;text-transform:uppercase">${plain(e.when)}</div>` +
            `<div class="h3" style="margin-top:1cqmin;font-size:calc(3.8cqmin*var(--fit))">${plain(e.what)}</div></div>`).join('') + '</div></div>';
        }
        return `${title(c.title)}<div class="grow center"><ul class="tl">` + ev.map((e) =>
          `<li><div class="when">${plain(e.when)}</div><div class="what">${plain(e.what)}</div></li>`).join('') + '</ul></div>';
      },
    },

    quadrant: {
      layouts: ['matrix'],
      build(c, x) {
        const X = c.x || {}, Y = c.y || {}, z = c.zones || {}, win = c.win || 'tr';
        const zone = (k) => `<div class="zone ${k}${win === k ? ' win' : ''}">${plain(z[k] || '')}</div>`;
        const pts = arr(c.points).map((p) => {
          const px = Math.max(4, Math.min(96, Number(p.x) * 100)), py = Math.max(4, Math.min(96, (1 - Number(p.y)) * 100));
          // The dot marks the data point exactly; its label runs right, or left
          // on the right-hand side, so a long label never leaves the frame.
          return `<div class="pt${p.us ? ' us' : ''}${px > 62 ? ' r' : ''}" style="left:${px}%;top:${py}%"><i></i><span class="tx">${plain(p.label)}</span></div>`;
        }).join('');
        return `${title(c.title, 'h2')}<div class="quad">${zone('tl')}${zone('tr')}${zone('bl')}${zone('br')}<div class="axis-x"></div><div class="axis-y"></div>${pts}` +
          `<span class="lbl x1">${plain(X.high)} &rarr;</span><span class="lbl y1">&uarr; ${plain(Y.high)}</span></div>`;
      },
    },

    // ── code ────────────────────────────────────────────────────────────────
    code: {
      layouts: ['editor'],
      build(c, x) {
        x.jobs.push({ engine: 'prism', language: c.language || 'python' });
        return `${title(c.title, 'h2')}<div class="grow center"><div class="win"><div class="bar"><i style="background:#FF5F57"></i><i style="background:#FEBC2E"></i><i style="background:#28C840"></i>` +
          `<span class="fn">${plain(c.filename || 'example')}</span></div><pre data-code class="language-${esc(c.language || 'python')}">${esc(c.code)}</pre></div></div>` +
          (has(c.caption) ? `<p class="body">${plain(c.caption)}</p>` : '');
      },
    },

    terminal: {
      layouts: ['session'],
      build(c, x) {
        const lines = arr(c.lines).map((l) => (l.cmd ? `<div class="term-line"><span class="p">$</span> ${esc(l.cmd)}</div>` : '') +
          (l.out ? `<div class="term-out">${esc(l.out)}</div>` : '')).join('');
        return `${title(c.title, 'h2')}<div class="grow center"><div class="win"><div class="bar"><i style="background:#FF5F57"></i><i style="background:#FEBC2E"></i><i style="background:#28C840"></i>` +
          `<span class="fn">${plain(c.filename || 'zsh')}</span></div><pre>${lines}</pre></div></div>`;
      },
    },

    // ── proof ───────────────────────────────────────────────────────────────
    mockup: {
      layouts: ['browser', 'phone'],
      build(c, x, layout) {
        let art = x.D.svg ? `${String(x.D.svg).replace(/<script[\s\S]*?<\/script>/gi, '').replace(/\son\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, '')}` : '';
        if (art) art = art.replace(/<svg\b(?![^>]*preserveAspectRatio)/, '<svg preserveAspectRatio="xMidYMid meet"');
        if (!art && layout !== 'phone') x.errors.push('mockup has no artwork');
        const cap = has(c.caption) ? `<p class="body">${plain(c.caption)}</p>` : '';
        if (layout === 'phone') {
          // Project artwork is a wide banner; squeezed into a phone it becomes a
          // sliver. The phone shows the app's identity instead, drawn here.
          const app = c.app || {};
          const initials = esc(String(app.initials || app.name || 'App').slice(0, 2));
          const screen = `<div class="app-screen"><div class="icon">${initials}</div><div class="nm">${plain(app.name || '')}</div>` +
            `${app.category ? `<div class="cat">${plain(app.category)}</div>` : ''}` +
            `<div class="tech">${arr(app.tech).slice(0, 3).map((t) => `<span>${plain(t)}</span>`).join('')}</div>` +
            `<div class="skel"><i></i><i></i><i></i></div></div>`;
          return `<div class="split" style="display:grid;grid-template-columns:1fr 1fr;gap:4cqmin;align-items:center;flex:1;min-height:0">` +
            `<div class="grow center gap-m">${title(c.title, 'h2')}${cap}</div><div class="mock-phone"><div class="notch"></div><div class="scr">${screen}</div></div></div>`;
        }
        return `${title(c.title, 'h2')}<div class="mock-browser"><div class="bar"><i style="background:#FF5F57"></i><i style="background:#FEBC2E"></i><i style="background:#28C840"></i>` +
          `<span class="url">${plain(c.url || 'wizcodes.site/work')}</span></div><div class="shot">${art}</div></div>${cap}`;
      },
    },

    // ── closers ─────────────────────────────────────────────────────────────
    cta: {
      layouts: ['save', 'follow', 'comment'],
      build(c, x, layout) {
        const acts = {
          save: `<span class="btn">${x.icon('bookmark')} Save</span><span class="btn ghost">${x.icon('send')} Send to a co-founder</span>`,
          follow: `<span class="btn">${x.icon('user-plus')} Follow for more</span><span class="btn ghost">${x.icon('bookmark')} Save</span>`,
          comment: `<span class="btn">${x.icon('message-circle')} Tell us below</span><span class="btn ghost">${x.icon('bookmark')} Save</span>`,
        }[layout] || '';
        return `<div class="grow center gap-l"><p class="mega" data-fit="block">${rich(c.headline)}</p>${has(c.sub) ? `<p class="body" style="color:var(--fg)">${plain(c.sub)}</p>` : ''}` +
          `<div class="cta-actions">${acts}</div>${has(c.ask) ? `<p class="small">${plain(c.ask)}</p>` : ''}</div>`;
      },
    },

    recap: {
      layouts: ['checklist'],
      build(c, x) {
        return `${title(c.title, 'h2')}<div class="grow center"><ul class="list recap">` +
          arr(c.items).map((it) => `<li class="li">${tick(x, false)}<span>${plain(txt(it))}</span></li>`).join('') + '</ul></div>' +
          `<p class="micro">${plain(c.note || 'Save this for your next build.')}</p>`;
      },
    },
  };

  window.FORMATS = FORMATS;
  window.makeHelpers = makeHelpers;
})();
