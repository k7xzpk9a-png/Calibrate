<!-- Curve calibrator (dev-only authoring tool).
     Pick a fig → its svgz is shown → the blue performance curves (stroke
     #303281, the only ink colour the curves use) are isolated as clickable
     candidates → you tag each one's value (PA / WI / Wind / OAT) → Save writes
     figs[<fig>].tagged into static/lookup.json via /calibrate/save.

     Axis calibration is NOT picked by hand: 124 figs already carry a `graph`
     block (pixel-space axis anchors from the lookup.json graph block). We render those anchors
     as on-chart markers so you can eyeball that they land on the printed axes —
     the seed of the eventual "overlay computed perf on the chart" validation. -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { base } from '$app/paths';

  // raster grid the graph-block pixels live on → A4-point viewBox. One uniform
  // scale links them (595.28/2481 ≈ 841.89/3508 ≈ 0.2399).
  const RASTER = { w: 2481, h: 3508 };

  type Tag = { zp: number | null; wi: number | null; oat: number | null; wind: number | null; weight: number | null; drag: number | null; note: string };
  type TagKey = 'zp' | 'wi' | 'oat' | 'wind' | 'weight' | 'drag';
  const VALUE_KEYS: TagKey[] = ['zp', 'wi', 'oat', 'wind', 'weight', 'drag'];
  const LABELS: Record<TagKey, string> = { zp: 'PA', wi: 'Weight idx', oat: 'OAT', wind: 'Wind', weight: 'Weight', drag: 'Drag idx' };
  type Cand = { el: SVGPathElement; d: string; pts: { x: number; y: number }[]; type?: string | null; order?: number };

  // semi-auto pre-fill: which value-set each panel follows (ZP/WIND are the
  // standard NH90 ladders → auto; WI/OAT have no safe convention → you fill).
  const LADDERS: Record<string, number[]> = {
    ZP: [-1, 0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20],
    TRAINING: [-1, 0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20],
    WIND: [0, 10, 20, 30, 40, 50],
  };
  const TYPE_FIELD: Record<string, keyof Tag> = { ZP: 'zp', TRAINING: 'zp', WEIGHTINDEX: 'wi', WIND: 'wind', OAT: 'oat' };
  const TYPE_RANK: Record<string, number> = { ZP: 0, TRAINING: 1, WEIGHTINDEX: 2, WIND: 3, OAT: 0 };

  let lookup = $state<any>(null);
  let figList = $state<{ num: string; family: string; tagged: boolean }[]>([]);
  let filter = $state('');
  let figNum = $state('');
  let status = $state('Loading lookup…');

  let stage: HTMLDivElement;
  let svg: SVGSVGElement | null = null;
  let vb = { x: 0, y: 0, w: 0, h: 0 };
  let vb0 = { x: 0, y: 0, w: 0, h: 0 };

  let candidates = $state<Cand[]>([]);
  let selected = $state<number | null>(null);
  let tags = $state<Record<number, Tag>>({});
  // artifact curves the user has dismissed (legend bits, arrows, partial strokes).
  // Keyed by candidate index for this fig; remembered (by curve `d`) for the
  // current session only — sessionStorage clears when the tab closes.
  let dismissed = $state<Set<number>>(new Set());
  const dismissKey = () => `calibrateDismiss:${figNum}`;
  const loadDismissD = (): Set<string> => {
    try { return new Set(JSON.parse(sessionStorage.getItem(dismissKey()) || '[]')); } catch { return new Set(); }
  };
  const saveDismissD = () => {
    const ds = [...dismissed].map((i) => candidates[i]?.d).filter(Boolean);
    try { sessionStorage.setItem(dismissKey(), JSON.stringify(ds)); } catch { /* quota */ }
  };

  // which tag fields matter per family (others stay hidden to keep the form tight)
  const FIELDS: Record<string, TagKey[]> = {
    flyaway: ['oat'],
    level_flight: ['weight'],
    roc: ['zp', 'wi'],
    cruise: ['drag'],
    hover: ['oat'],
    height_loss: ['zp', 'wi', 'wind'],
    weight_index: ['zp', 'weight'],
  };

  // Manual axis calibration for figs WITHOUT a graph block (e.g. weight_index):
  // pick two points on each labelled axis. The shared intermediate axis needs no
  // calibration (it's a pass-through). Each entry: [valueA, valueB] defaults.
  type AxisDef = { id: string; label: string; defaults: [number, number] };
  const AXES: Record<string, AxisDef[]> = {
    weight_index: [
      { id: 'oat', label: 'OAT (°C)', defaults: [-40, 50] },
      { id: 'wi', label: 'WI ×1000', defaults: [6000, 16000] },
    ],
  };
  let axes = $derived(AXES[family] ?? null);
  // axisId → two endpoints. value is always set (editable); x/y in viewBox coords
  // are null until picked on the chart.
  type CalPt = { value: number; x: number | null; y: number | null };
  let manualCal = $state<Record<string, CalPt[]>>({});
  let pickAxis = $state<{ id: string; i: number } | null>(null); // armed picker

  function initCalibration() {
    pickAxis = null;
    const defs = AXES[family];
    if (!defs) { manualCal = {}; return; }
    const saved = lookup?.figs?.[figNum]?.tagged?.calibration ?? {};
    const m: Record<string, CalPt[]> = {};
    for (const ax of defs) {
      const sv = saved[ax.id] ?? [];
      m[ax.id] = [0, 1].map((i) => ({
        value: sv[i]?.value ?? ax.defaults[i],
        x: sv[i]?.x ?? null,
        y: sv[i]?.y ?? null,
      }));
    }
    manualCal = m;
  }
  function capturePick(clientX: number, clientY: number) {
    if (!svg || !pickAxis) return;
    const pt = svg.createSVGPoint();
    pt.x = clientX; pt.y = clientY;
    const loc = pt.matrixTransform(svg.getScreenCTM()!.inverse());
    const arr = manualCal[pickAxis.id];
    arr[pickAxis.i] = { ...arr[pickAxis.i], x: loc.x, y: loc.y };
    manualCal = { ...manualCal };
    pickAxis = null;
    drawCalMarkers();
  }
  function drawCalMarkers() {
    if (!svg) return;
    svg.querySelector('#calmarks')?.remove();
    if (!axes) return;
    const NS = 'http://www.w3.org/2000/svg';
    const g = document.createElementNS(NS, 'g');
    g.id = 'calmarks'; g.setAttribute('pointer-events', 'none');
    const r = vb0.w * 0.006;
    for (const ax of axes) for (const p of manualCal[ax.id] ?? []) {
      if (p.x == null) continue;
      const c = document.createElementNS(NS, 'circle');
      c.setAttribute('cx', `${p.x}`); c.setAttribute('cy', `${p.y}`); c.setAttribute('r', `${r}`);
      c.setAttribute('fill', '#e91e63');
      g.appendChild(c);
    }
    svg.appendChild(g);
  }
  let family = $derived(lookup?.figs?.[figNum]?.family ?? '');
  let graph = $derived(lookup?.figs?.[figNum]?.graph ?? null);
  let fields = $derived(FIELDS[family] ?? (['zp', 'wi', 'oat', 'wind'] as TagKey[]));
  let shown = $derived(
    figList.filter((f) => !filter || f.num.includes(filter) || f.family.includes(filter)),
  );

  const emptyTag = (): Tag => ({ zp: null, wi: null, oat: null, wind: null, weight: null, drag: null, note: '' });
  const isTagged = (t?: Tag) => !!t && VALUE_KEYS.some((k) => t[k] != null);

  onMount(async () => {
    const res = await fetch(`${base}/lookup.json`);
    lookup = await res.json();
    figList = Object.entries(lookup.figs).map(([num, f]: any) => ({
      num,
      family: f.family ?? '?',
      tagged: !!f.tagged,
    }));
    status = `${figList.length} figs`;
  });

  async function openFig(num: string) {
    figNum = num;
    selected = null;
    tags = {};
    const res = await fetch(`${base}/svgz/${num}.svgz`);
    if (!res.ok) { status = `no svg for ${num}`; return; }
    const buf = new Uint8Array(await res.arrayBuffer());
    const text =
      buf[0] === 0x1f && buf[1] === 0x8b
        ? await new Response(new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip'))).text()
        : new TextDecoder().decode(buf);

    stage.innerHTML = text;
    svg = stage.querySelector('svg');
    if (!svg) { status = 'no <svg> root'; return; }
    svg.removeAttribute('width');
    svg.removeAttribute('height');
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    const a = (svg.getAttribute('viewBox') || '0 0 595.28 841.89').split(/[ ,]+/).map(Number);
    vb0 = { x: a[0], y: a[1], w: a[2], h: a[3] };
    vb = { ...vb0 };
    applyVB();

    // isolate the blue curves; dim everything else so labels stay readable but
    // never steal a click.
    candidates = [];
    for (const el of Array.from(svg.querySelectorAll('path'))) {
      const p = el as SVGPathElement;
      if (p.getAttribute('stroke') === '#303281') {
        p.classList.add('cand');
        p.setAttribute('vector-effect', 'non-scaling-stroke');
        const idx = candidates.length;
        p.addEventListener('click', (e) => { e.stopPropagation(); select(idx); });
        candidates.push({ el: p, d: p.getAttribute('d') || '', pts: samplePath(p) });
      } else {
        p.classList.add('bg');
      }
    }
    // re-apply persisted artifact dismissals (matched by curve `d`)
    const dis = loadDismissD();
    dismissed = new Set();
    candidates.forEach((c, i) => { if (dis.has(c.d)) markDismissed(i); });

    drawMarkers();
    initCalibration();
    drawCalMarkers();
    resumeTags();
    status = `${num} · ${family} · ${candidates.length} curves`;
    prefill(); // classify + order + ZP/WIND ladder; never clobbers resumed tags
  }

  // Drop an artifact curve from the candidate set: dim it on the chart, untag it,
  // exclude it from the list/prefill/save. markDismissed does the DOM/state work;
  // dismiss() also persists and refreshes reactivity.
  function markDismissed(i: number) {
    dismissed.add(i);
    const el = candidates[i].el;
    el.classList.remove('cand', 'tagged', 'sel');
    el.classList.add('bg');
    delete tags[i];
    candidates[i].type = null;
  }
  function dismiss(i: number) {
    if (selected === i) selected = null;
    markDismissed(i);
    dismissed = new Set(dismissed); // reactivity
    saveDismissD();
  }
  function restoreDismissed() {
    for (const i of dismissed) {
      const el = candidates[i].el;
      el.classList.add('cand');
      el.classList.remove('bg');
    }
    dismissed = new Set();
    saveDismissD();
    prefill();
  }

  // Sample a path into screen-independent user-space points for nearest-curve
  // hit-testing. Native getPointAtLength handles any command type, so we never
  // parse path data ourselves.
  function samplePath(p: SVGPathElement, cap = 120) {
    const len = p.getTotalLength();
    const n = Math.max(2, Math.min(cap, Math.round(len)));
    const out: { x: number; y: number }[] = [];
    for (let i = 0; i <= n; i++) { const q = p.getPointAtLength((len * i) / n); out.push({ x: q.x, y: q.y }); }
    return out;
  }

  // Sample a bare `d` string by binding it to a throwaway path, so we can compare
  // a stored curve's shape regardless of how its `d` was formatted on save.
  function sampleD(d: string, cap = 16) {
    if (!svg) return [];
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path') as SVGPathElement;
    p.setAttribute('d', d);
    svg.appendChild(p);
    let pts: { x: number; y: number }[] = [];
    try { pts = samplePath(p, cap); } catch { /* unparseable d */ }
    p.remove();
    return pts;
  }
  // Mean distance from each point of a to its nearest point in b — a cheap,
  // direction-tolerant shape-similarity measure for curve matching.
  function meanNearest(a: { x: number; y: number }[], b: { x: number; y: number }[]) {
    let s = 0;
    for (const p of a) {
      let m = Infinity;
      for (const q of b) { const d2 = (p.x - q.x) ** 2 + (p.y - q.y) ** 2; if (d2 < m) m = d2; }
      s += Math.sqrt(m);
    }
    return a.length ? s / a.length : Infinity;
  }

  function applyVB() { svg?.setAttribute('viewBox', `${vb.x} ${vb.y} ${vb.w} ${vb.h}`); }

  function px(p: number, axis: 'w' | 'h') { return (p * vb0[axis]) / RASTER[axis === 'w' ? 'w' : 'h']; }

  // Axis anchors from the graph block → labelled dots, so you can confirm the
  // stored calibration still lands on the printed axes (graphic validation seed).
  function drawMarkers() {
    if (!svg) return;
    svg.querySelector('#marks')?.remove();
    const g = graph;
    if (!g) return;
    const NS = 'http://www.w3.org/2000/svg';
    const grp = document.createElementNS(NS, 'g');
    grp.id = 'marks';
    grp.setAttribute('pointer-events', 'none');
    const r = vb0.w * 0.005, fs = vb0.w * 0.011;
    const dot = (rx: number, ry: number, label: string, c: string) => {
      const x = px(rx, 'w'), y = px(ry, 'h');
      const c1 = document.createElementNS(NS, 'circle');
      c1.setAttribute('cx', `${x}`); c1.setAttribute('cy', `${y}`); c1.setAttribute('r', `${r}`);
      c1.setAttribute('fill', 'none'); c1.setAttribute('stroke', c); c1.setAttribute('stroke-width', `${r * 0.5}`);
      const tx = document.createElementNS(NS, 'text');
      tx.setAttribute('x', `${x + r * 1.5}`); tx.setAttribute('y', `${y - r * 0.6}`);
      tx.setAttribute('font-size', `${fs}`); tx.setAttribute('fill', c); tx.textContent = label;
      grp.append(c1, tx);
    };
    if (g.graphOriginX != null) { // hover: mass × altitude
      dot(g.graphOriginX, g.graphOriginY, `mass ${g.massMin}`, '#1565c0');
      dot(g.maxXValueX, g.graphOriginY, `mass ${g.massMax}`, '#1565c0');
      dot(g.graphOriginX, g.maxYValueY, `alt ${g.altitudeMax}`, '#c62828');
    }
    if (g.oatOriginX != null) { // roc / height-loss: oat × transfer
      dot(g.oatOriginX, g.transferOriginY, `OAT ${g.oatMin}`, '#1565c0');
      dot(g.oatMaxX, g.transferOriginY, `OAT ${g.oatMax}`, '#1565c0');
      dot(g.oatOriginX, g.transferMaxY, `transfer ${g.transferMax}`, '#c62828');
    }
    if (g.rocOriginX != null) {
      dot(g.rocOriginX, g.transferOriginY, `R/C ${g.rocMin}`, '#2e7d32');
      dot(g.rocMaxX, g.transferOriginY, `R/C ${g.rocMax}`, '#2e7d32');
    }
    if (g.hlOneOriginX != null) {
      dot(g.hlOneOriginX, g.transferOriginY, `WI ${g.hlOneMin}`, '#2e7d32');
      dot(g.hlOneMaxX, g.transferOriginY, `WI ${g.hlOneMax}`, '#2e7d32');
    }
    if (g.heightLossOriginY != null) {
      const bx = g.hlOneOriginX ?? g.oatOriginX;
      dot(bx, g.heightLossOriginY, `hLoss ${g.heightLossMin}`, '#6a1b9a');
      dot(bx, g.heightLossMaxY, `hLoss ${g.heightLossMax}`, '#6a1b9a');
    }
    svg.appendChild(grp);
  }

  // Pre-fill from a previous save by matching stored curves to live ones by
  // SHAPE, not `d` string — a save may have reformatted/simplified the path
  // (the old tool RDP-compacted to absolute coords), so byte-identity fails.
  // Greedy nearest assignment, each live curve claimed once.
  function resumeTags() {
    const prev = lookup?.figs?.[figNum]?.tagged;
    if (!prev?.curves) return;
    const tol = vb0.w * 0.01; // ~6 user-units mean error; true matches sit near 0
    const used = new Set<number>();
    for (const c of prev.curves) {
      const spts = sampleD(c.d);
      if (!spts.length) continue;
      let best = -1, err = Infinity;
      candidates.forEach((cand, i) => {
        if (used.has(i) || dismissed.has(i)) return;
        const e = meanNearest(spts, cand.pts);
        if (e < err) { err = e; best = i; }
      });
      if (best < 0 || err > tol) continue;
      used.add(best);
      tags[best] = { zp: c.zp ?? null, wi: c.wi ?? null, oat: c.oat ?? null, wind: c.wind ?? null, note: c.note ?? '' };
      candidates[best].el.classList.add('tagged');
    }
  }

  // ── semi-auto pre-fill ────────────────────────────────────────────────────────
  // Classify each curve into its panel from the graph-block axis bands, drop the
  // doubled overlapping strokes, order spatially, and fill ZP/WIND from the
  // standard ladders. WI/OAT get type+order (so the list is a clean top-to-bottom
  // run) but no value — you type those. Never overwrites an existing tag.
  function panelBands() {
    const g = graph; if (!g) return null;
    const span = (a: number, b: number): [number, number] => (a < b ? [a, b] : [b, a]);
    const o: any = {};
    if (g.oatOriginX != null) o.oatX = span(px(g.oatOriginX, 'w'), px(g.oatMaxX, 'w'));
    if (g.transferOriginY != null) { o.transferY = span(px(g.transferMaxY, 'h'), px(g.transferOriginY, 'h')); o.transferBotY = px(g.transferOriginY, 'h'); }
    if (g.hlOneOriginX != null) o.wiX = span(px(g.hlOneOriginX, 'w'), px(g.hlOneMaxX, 'w'));
    else if (g.rocOriginX != null) o.wiX = span(px(g.rocOriginX, 'w'), px(g.rocMaxX, 'w'));
    if (g.heightLossOriginY != null) o.windY = span(px(g.heightLossMaxY, 'h'), px(g.heightLossOriginY, 'h'));
    return o;
  }
  const ext = (c: Cand) => {
    const xs = c.pts.map((p) => p.x), ys = c.pts.map((p) => p.y);
    return { cx: (Math.min(...xs) + Math.max(...xs)) / 2, cy: (Math.min(...ys) + Math.max(...ys)) / 2, maxY: Math.max(...ys) };
  };
  function classifyType(c: Cand): string | null {
    if (graph?.graphOriginX != null) return 'OAT'; // hover: every curve is an OAT isoline
    const b = panelBands(); if (!b) return null;
    const { cx, cy, maxY } = ext(c);
    const padX = b.oatX ? (b.oatX[1] - b.oatX[0]) * 0.08 : 0;
    const padY = b.transferY ? (b.transferY[1] - b.transferY[0]) * 0.08 : 0;
    const inB = (v: number, r: [number, number] | undefined, p: number) => !!r && v >= r[0] - p && v <= r[1] + p;
    if (inB(cy, b.windY, padY)) return 'WIND';
    if (inB(cy, b.transferY, padY)) {
      if (inB(cx, b.oatX, padX)) return maxY > b.transferBotY + padY ? 'TRAINING' : 'ZP';
      if (inB(cx, b.wiX, padX)) return 'WEIGHTINDEX';
    }
    return null;
  }
  // drop doubled strokes ONLY — a curve drawn twice. The safe test: BOTH
  // endpoints coincide AND the bodies overlap heavily. Fan curves share just one
  // endpoint (the origin) and diverge, so they fail this and are kept (the
  // "auto-dedup is unsafe" trap: distinct fan lines are near-coincident too).
  function isDup(a: Cand, b: Cand): boolean {
    const ov = (A: typeof a.pts, B: typeof a.pts) => {
      let n = 0;
      for (const p of A) { let m = Infinity; for (const q of B) { const d = (p.x - q.x) ** 2 + (p.y - q.y) ** 2; if (d < m) m = d; } if (m < 0.36) n++; }
      return n / A.length;
    };
    const overlap = Math.min(ov(a.pts, b.pts), ov(b.pts, a.pts));
    // overlap-only test: a doubled stroke covers ~95% of its twin; fan curves
    // converge at one end only (~30-40%), so 0.78 separates them cleanly.
    if (overlap > 0.78) return true;
    // endpoint test catches shorter/clipped doubles that still span the same line.
    const near = (p: { x: number; y: number }, q: { x: number; y: number }) => (p.x - q.x) ** 2 + (p.y - q.y) ** 2 < 9;
    const sa = a.pts[0], ea = a.pts.at(-1)!, sb = b.pts[0], eb = b.pts.at(-1)!;
    const sameSpan = (near(sa, sb) && near(ea, eb)) || (near(sa, eb) && near(ea, sb));
    return sameSpan && overlap > 0.6;
  }
  function dedup(idxs: number[]): number[] {
    const drop = new Set<number>();
    for (let a = 0; a < idxs.length; a++) {
      const i = idxs[a]; if (drop.has(i)) continue;
      for (let b = a + 1; b < idxs.length; b++) {
        const j = idxs[b]; if (drop.has(j)) continue;
        if (isDup(candidates[i], candidates[j])) drop.add(candidates[i].pts.length >= candidates[j].pts.length ? j : i);
      }
    }
    return idxs.filter((i) => !drop.has(i));
  }
  // y of a curve's polyline at x=X (first crossing, else nearest endpoint). The
  // fan curves cross, so centroid-y sorts them wrong; their y at a vertical line
  // through the spread end orders them cleanly (no crossings there).
  function yAtX(c: Cand, X: number): number {
    const p = c.pts;
    let best = p[0]?.y ?? 0, bd = Infinity;
    for (let i = 0; i + 1 < p.length; i++) {
      const a = p[i], b = p[i + 1];
      if ((a.x <= X && X <= b.x) || (b.x <= X && X <= a.x)) {
        const t = b.x === a.x ? 0 : (X - a.x) / (b.x - a.x);
        return a.y + t * (b.y - a.y);
      }
      for (const q of [a, b]) { const d = Math.abs(q.x - X); if (d < bd) { bd = d; best = q.y; } }
    }
    return best;
  }
  function prefill() {
    if (!graph) { status = 'no graph block — manual only'; return; }
    const groups: Record<string, number[]> = {};
    candidates.forEach((c, i) => { if (dismissed.has(i)) { c.type = null; return; } c.type = classifyType(c); if (c.type) (groups[c.type] ||= []).push(i); });
    for (const [type, idxs] of Object.entries(groups)) {
      const field = TYPE_FIELD[type];
      const kept = dedup(idxs);
      const keptSet = new Set(kept);
      for (const i of idxs) if (!keptSet.has(i)) candidates[i].type = 'dup'; // doubled stroke → sort out of the way
      // ZP/TRAINING: order by y at whichever oat-axis end spreads the fan most.
      // WIND: along Y. WI/OAT: along X.
      let key: (i: number) => number;
      if ((type === 'ZP' || type === 'TRAINING') && graph.oatOriginX != null) {
        const refs = [px(graph.oatOriginX, 'w'), px(graph.oatMaxX, 'w')];
        let bestX = refs[0], bestSpread = -1;
        for (const X of refs) {
          const ys = kept.map((i) => yAtX(candidates[i], X));
          const sp = ys.length ? Math.max(...ys) - Math.min(...ys) : 0;
          if (sp > bestSpread) { bestSpread = sp; bestX = X; }
        }
        key = (i) => yAtX(candidates[i], bestX);
      } else if (type === 'WEIGHTINDEX' || type === 'OAT') {
        key = (i) => ext(candidates[i]).cx;
      } else {
        key = (i) => ext(candidates[i]).cy;
      }
      kept.sort((a, b) => key(a) - key(b));
      const ladder = LADDERS[type];
      // only apply the ladder when the deduped count fits it — otherwise doubling
      // wasn't fully resolved and zipping would mis-value, so leave blank to tag.
      const useLadder = ladder && kept.length <= ladder.length;
      kept.forEach((i, k) => {
        candidates[i].order = k;
        tags[i] ??= emptyTag();
        if (useLadder && ladder![k] != null && !isTagged(tags[i])) {
          tags[i][field] = ladder![k];
          candidates[i].el.classList.add('tagged');
        }
      });
    }
    candidates = [...candidates]; // reactivity for badges + list order
    const auto = candidates.filter((_, i) => isTagged(tags[i])).length;
    status = `pre-filled ${auto} (ZP/WIND) · classify ${Object.entries(groups).map(([t, a]) => `${t}:${a.length}`).join(' ')} · verify`;
  }

  function fieldForCand(i: number): keyof Tag {
    const t = candidates[i]?.type;
    return (t && TYPE_FIELD[t]) || fields[0];
  }
  function select(i: number) {
    selected = i;
    tags[i] ??= emptyTag();
    for (const c of candidates) c.el.classList.remove('sel');
    candidates[i].el.classList.add('sel');
    const f = fieldForCand(i);
    queueMicrotask(() => (document.querySelector(`#f_${f}`) as HTMLInputElement)?.select());
  }

  function saveTag() {
    if (selected == null) return;
    const t = tags[selected];
    candidates[selected].el.classList.toggle('tagged', isTagged(t));
    candidates[selected].el.classList.remove('sel');
    // advance to the next untagged curve in VISIBLE order (listOrder already
    // excludes dismissed artifacts), continuing after the current row.
    const order = listOrder;
    const pos = order.indexOf(selected);
    let next = -1;
    for (let k = 1; k <= order.length; k++) {
      const i = order[(pos + k) % order.length];
      if (!isTagged(tags[i])) { next = i; break; }
    }
    selected = null;
    if (next >= 0) select(next);
  }

  function untag() {
    if (selected == null) return;
    delete tags[selected];
    candidates[selected].el.classList.remove('tagged');
  }

  // ── zoom / pan via viewBox; nearest-curve click so thin strokes are easy ──
  function onWheel(e: WheelEvent) {
    if (!svg) return;
    e.preventDefault();
    const r = svg.getBoundingClientRect();
    const mx = vb.x + ((e.clientX - r.left) / r.width) * vb.w;
    const my = vb.y + ((e.clientY - r.top) / r.height) * vb.h;
    const k = e.deltaY < 0 ? 0.85 : 1 / 0.85;
    vb.x = mx - (mx - vb.x) * k; vb.y = my - (my - vb.y) * k; vb.w *= k; vb.h *= k;
    applyVB();
  }
  let pan: { x: number; y: number; vx: number; vy: number } | null = null;
  let down: { x: number; y: number } | null = null;
  function onDown(e: PointerEvent) {
    if (!svg) return;
    if (pickAxis) { capturePick(e.clientX, e.clientY); return; } // record axis point
    if ((e.target as Element).classList?.contains('cand')) return;
    down = { x: e.clientX, y: e.clientY };
    pan = { x: e.clientX, y: e.clientY, vx: vb.x, vy: vb.y };
  }
  function onMove(e: PointerEvent) {
    if (!pan || !svg) return;
    const r = svg.getBoundingClientRect();
    vb.x = pan.vx - ((e.clientX - pan.x) / r.width) * vb.w;
    vb.y = pan.vy - ((e.clientY - pan.y) / r.height) * vb.h;
    applyVB();
  }
  function onUp(e: PointerEvent) {
    const click = down && Math.hypot(e.clientX - down.x, e.clientY - down.y) < 5;
    pan = null; down = null;
    if (!svg || !click || (e.target as Element).closest?.('path.cand')) return;
    nearest(e.clientX, e.clientY);
  }
  function nearest(cx: number, cy: number) {
    if (!svg || !candidates.length) return;
    const pt = svg.createSVGPoint(); pt.x = cx; pt.y = cy;
    const loc = pt.matrixTransform(svg.getScreenCTM()!.inverse());
    const r = svg.getBoundingClientRect();
    const tol = (14 * vb.w) / r.width; // 14 screen px in user units
    let best: { i: number; d2: number } | null = null;
    candidates.forEach((c, i) => {
      if (dismissed.has(i)) return;
      for (const p of c.pts) {
        const d2 = (p.x - loc.x) ** 2 + (p.y - loc.y) ** 2;
        if (!best || d2 < best.d2) best = { i, d2 };
      }
    });
    if (best && best.d2 <= tol * tol) select(best.i);
  }

  async function save() {
    const curves = candidates
      .map((c, i) => ({ c, t: tags[i], i }))
      .filter(({ t }) => isTagged(t))
      .map(({ c, t, i }) => ({
        id: `path-${i}`,
        ...Object.fromEntries(VALUE_KEYS.filter((k) => t[k] != null).map((k) => [k, t[k]])),
        ...(t.note ? { note: t.note } : {}),
        d: c.d, // ponytail: raw d (already root coords, identity transform). RDP-compact if lookup.json size hurts.
      }));
    if (!curves.length) { status = 'nothing tagged'; return; }
    // manual axis calibration (figs without a graph block)
    const calibration = axes
      ? Object.fromEntries(axes.map((ax) => [ax.id, manualCal[ax.id].map((p) => (p.x != null ? { x: p.x, y: p.y, value: p.value } : null))]))
      : undefined;
    const tagged = { source: 'calibrate', fig: figNum, viewBox: vb0, ...(calibration ? { calibration } : {}), curves };
    const res = await fetch(`${base}/calibrate/save`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ fig: figNum, tagged }),
    });
    const out = await res.json().catch(() => ({}));
    if (res.ok) {
      status = `saved ${out.curves} curves → lookup.json`;
      lookup.figs[figNum].tagged = tagged;
      figList = figList.map((f) => (f.num === figNum ? { ...f, tagged: true } : f));
    } else status = `save failed: ${out.message || res.status}`;
  }

  let taggedCount = $derived(candidates.filter((_, i) => isTagged(tags[i])).length);
  // display order: dismissed artifacts hidden; grouped by panel, then spatial order
  let listOrder = $derived(
    candidates
      .map((_, i) => i)
      .filter((i) => !dismissed.has(i))
      .sort((a, b) => {
        const ra = candidates[a].type != null ? TYPE_RANK[candidates[a].type!] ?? 8 : 9;
        const rb = candidates[b].type != null ? TYPE_RANK[candidates[b].type!] ?? 8 : 9;
        return ra - rb || (candidates[a].order ?? 1e9) - (candidates[b].order ?? 1e9) || a - b;
      }),
  );
</script>

<svelte:window onpointermove={onMove} onpointerup={onUp} />

<div class="wrap">
  <div
    class="stage"
    bind:this={stage}
    role="application"
    onwheel={onWheel}
    onpointerdown={onDown}
  ></div>

  <aside>
    <h1>Curve calibrator</h1>
    <p class="status">{status}</p>

    <input class="filter" placeholder="filter figs (number or family)" bind:value={filter} />
    <select size="10" class="figs" onchange={(e) => openFig((e.target as HTMLSelectElement).value)}>
      {#each shown as f (f.num)}
        <option value={f.num} selected={f.num === figNum}>{f.tagged ? '✓ ' : ''}{f.num} · {f.family}</option>
      {/each}
    </select>

    {#if figNum}
      <div class="bar">
        {taggedCount}/{candidates.length - dismissed.size} tagged · {family}
        <button type="button" class="ghost mini" onclick={prefill}>↻ pre-fill</button>
        {#if dismissed.size}
          <button type="button" class="ghost mini" onclick={restoreDismissed} title="Un-dismiss all artifact curves">restore {dismissed.size}✕</button>
        {/if}
      </div>

      {#if axes && manualCal[axes[0].id]}
        <div class="calib">
          <div class="calhdr">Axis calibration <span class="meta">(no graph block — pick 2 points per axis)</span></div>
          {#each axes as ax (ax.id)}
            {#each [0, 1] as i (i)}
              <div class="calrow">
                <span class="callbl">{ax.label} {i === 0 ? 'a' : 'b'}</span>
                <input type="number" step="any" bind:value={manualCal[ax.id][i].value} />
                <button type="button" class="pickbtn" class:armed={pickAxis?.id === ax.id && pickAxis?.i === i}
                  onclick={() => (pickAxis = pickAxis?.id === ax.id && pickAxis?.i === i ? null : { id: ax.id, i })}>
                  {manualCal[ax.id][i].x != null ? '✓' : 'pick'}
                </button>
              </div>
            {/each}
          {/each}
        </div>
      {/if}
      <ul class="list">
        {#each listOrder as i (i)}
          <li class:active={i === selected} class:done={isTagged(tags[i])}>
            <button type="button" class="pick" onclick={() => select(i)}>
              {#if candidates[i].type}<span class="badge t-{candidates[i].type}">{candidates[i].type}</span>{/if}
              #{i + 1}
              {#if isTagged(tags[i])}
                <span class="sum">{fields.map((fld) => `${LABELS[fld]} ${tags[i][fld] ?? '–'}`).join(' · ')}</span>
              {/if}
            </button>
            <button type="button" class="x" title="Dismiss — not a performance curve" onclick={() => dismiss(i)}>✕</button>
          </li>
        {/each}
      </ul>

      {#if selected != null}
        <form class="form" onsubmit={(e) => { e.preventDefault(); saveTag(); }}>
          {#each fields as fld (fld)}
            <label>{LABELS[fld]}
              <input id={`f_${fld}`} type="number" step="any" bind:value={tags[selected][fld]} />
            </label>
          {/each}
          <label>note <input type="text" bind:value={tags[selected].note} /></label>
          <div class="row">
            <button type="submit">Save tag (Enter)</button>
            <button type="button" class="ghost" onclick={untag}>Untag</button>
          </div>
        </form>
      {/if}

      <button class="save" onclick={save}>Save fig → lookup.json</button>
    {/if}
  </aside>
</div>

<style>
  .wrap { display: grid; grid-template-columns: 1fr 340px; height: 100vh; font: 13px/1.4 system-ui, sans-serif; }
  .stage { position: relative; overflow: hidden; background: #fff; touch-action: none; }
  .stage :global(svg) { position: absolute; inset: 0; width: 100%; height: 100%; }
  .stage :global(.bg) { opacity: 0.55; pointer-events: none; }
  .stage :global(.cand) { cursor: pointer; stroke-width: 1.2; }
  .stage :global(.cand:hover) { stroke: #f9a825 !important; stroke-width: 2.4 !important; }
  .stage :global(.tagged) { stroke: #00b341 !important; }
  .stage :global(.sel) { stroke: #e10000 !important; stroke-width: 2.6 !important; }

  aside { background: #252525; color: #e0e0e0; border-left: 1px solid #3a3a3a; display: flex; flex-direction: column; min-height: 0; padding: 10px; gap: 8px; }
  h1 { font-size: 15px; margin: 0; }
  .status { color: #9ad; margin: 0; font-size: 12px; }
  .filter, .figs, input, select { background: #1b1b1b; border: 1px solid #444; color: #eee; border-radius: 4px; padding: 4px 6px; }
  .figs { font-family: ui-monospace, monospace; font-size: 12px; }
  .bar { color: #aaa; display: flex; align-items: center; gap: 8px; }
  button.mini { padding: 2px 7px; font-size: 11px; }
  .badge { font-size: 9px; font-weight: 700; padding: 1px 4px; border-radius: 3px; margin-right: 4px; color: #fff; vertical-align: middle; }
  .t-ZP, .t-OAT { background: #1565c0; } .t-TRAINING { background: #00838f; }
  .t-WEIGHTINDEX { background: #2e7d32; } .t-WIND { background: #6a1b9a; }
  .t-dup { background: #555; opacity: 0.6; }
  .calib { border: 1px solid #3a3a3a; border-radius: 4px; padding: 6px 8px; display: flex; flex-direction: column; gap: 3px; }
  .calhdr { color: #e91e63; font-size: 12px; } .calhdr .meta { color: #888; font-weight: 400; }
  .calrow { display: flex; align-items: center; gap: 6px; }
  .callbl { flex: 0 0 84px; color: #aaa; font-size: 12px; }
  .calrow input { flex: 1; min-width: 0; }
  .pickbtn { padding: 3px 8px; font-size: 11px; background: #444; }
  .pickbtn.armed { background: #e91e63; }
  .list { flex: 1; overflow-y: auto; list-style: none; margin: 0; padding: 0; border: 1px solid #333; border-radius: 4px; }
  .list li { border-bottom: 1px solid #2e2e2e; display: flex; align-items: center; }
  .list li.active { background: #37474f; }
  .list li.done .pick { color: #81c784; }
  .list .pick { flex: 1; text-align: left; background: none; border: 0; color: inherit; padding: 5px 8px; cursor: pointer; }
  .list .x { background: none; border: 0; color: #666; padding: 4px 9px; cursor: pointer; font-size: 12px; }
  .list .x:hover { color: #e57373; }
  .sum { color: #81c784; font-size: 11px; }
  .form { display: flex; flex-direction: column; gap: 5px; background: #1e1e1e; padding: 8px; border-radius: 4px; }
  .form label { display: flex; justify-content: space-between; align-items: center; gap: 8px; color: #aaa; }
  .form input { flex: 1; }
  .row { display: flex; gap: 6px; }
  button { background: #3949ab; color: #fff; border: 0; padding: 6px 10px; border-radius: 4px; cursor: pointer; }
  button.ghost { background: #444; }
  .save { background: #2e7d32; }
</style>
