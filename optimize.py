#!/usr/bin/env python3
"""Optimize lookup.json: RDP-simplify every tagged-curve `d` path AND strip the
authoring-only tags the runtime app never reads, then minify.

  python3 optimize.py [epsilon] [decimals]

Reads static/lookup.json, writes lookup.optimized.json (minified). epsilon is in
viewBox units (default 0.05 = very small; curves are within a 595x842 page).

Dropped tags (verified unused by the consumer in nh90-svelte/lookupTable.ts,
which reads only `curve.<value>` + `curve.d`, plus `tagged.calibration`):
  • curve.id           — source SVG path index, dead after tagging
  • tagged.source      — provenance (calibrate/auto)
  • tagged.fig         — duplicates the figs[<fig>] key
  • tagged.viewBox     — constant 595.28x841.89, not read at runtime
Everything else (version/normalise/index, family/name/graph, tagged.curves,
tagged.calibration, any unknown keys) is copied verbatim.
"""
import json, re, sys

EPS = float(sys.argv[1]) if len(sys.argv) > 1 else 0.05
DP  = int(sys.argv[2]) if len(sys.argv) > 2 else 2

CURVE_DROP  = {'id'}
TAGGED_DROP = {'source', 'fig', 'viewBox'}

# --- SVG path (M m L l H h V v) -> list of absolute (x,y) points ---
def parse(d):
    t = re.findall(r'[MmLlHhVv]|-?\d*\.?\d+', d)
    i = x = y = 0; cmd = None; pts = []
    def num():
        nonlocal i; v = float(t[i]); i += 1; return v
    x = y = 0.0
    while i < len(t):
        if t[i].isalpha(): cmd = t[i]; i += 1
        if   cmd == 'M': x = num();  y = num();  pts.append((x, y)); cmd = 'L'
        elif cmd == 'm': x += num(); y += num(); pts.append((x, y)); cmd = 'l'
        elif cmd == 'L': x = num();  y = num();  pts.append((x, y))
        elif cmd == 'l': x += num(); y += num(); pts.append((x, y))
        elif cmd == 'H': x = num();  pts.append((x, y))
        elif cmd == 'h': x += num(); pts.append((x, y))
        elif cmd == 'V': y = num();  pts.append((x, y))
        elif cmd == 'v': y += num(); pts.append((x, y))
        else: i += 1
    return pts

# --- iterative Ramer-Douglas-Peucker (recursion blows the stack at 1400 pts) ---
def rdp(P, eps):
    n = len(P)
    if n < 3: return P[:]
    keep = [False]*n; keep[0] = keep[-1] = True
    stack = [(0, n-1)]
    while stack:
        a, b = stack.pop()
        ax, ay = P[a]; bx, by = P[b]
        dx, dy = bx-ax, by-ay; L = (dx*dx+dy*dy)**.5 or 1e-9
        dmax = 0.0; idx = -1
        for k in range(a+1, b):
            d = abs(dy*(P[k][0]-ax) - dx*(P[k][1]-ay)) / L
            if d > dmax: dmax = d; idx = k
        if dmax > eps:
            keep[idx] = True
            stack.append((a, idx)); stack.append((idx, b))
    return [P[k] for k in range(n) if keep[k]]

# --- compact relative path emitter (".5", "-.5", no space before -/. ) ---
def fmt(v):
    v = round(v, DP)
    if v == 0: return '0'
    s = f'{v:.{DP}f}'.rstrip('0').rstrip('.')
    return re.sub(r'^(-?)0\.', r'\1.', s)

class Path:
    def __init__(self): self.s = ''; self.numprev = False; self.prevdot = False
    def cmd(self, c): self.s += c; self.numprev = False
    def num(self, v):
        t = fmt(v)
        # may omit separator only before '-', or before '.' when prev had a dot
        # (else "2"+".3" would fuse into the single number 2.3)
        if self.numprev and not (t[0] == '-' or (t[0] == '.' and self.prevdot)):
            self.s += ' '
        self.s += t; self.numprev = True; self.prevdot = '.' in t

def emit(pts):
    p = Path(); px = py = 0.0
    p.cmd('m'); p.num(pts[0][0]); p.num(pts[0][1]); px, py = pts[0]
    if len(pts) > 1:
        p.cmd('l')
        for x, y in pts[1:]:
            p.num(x-px); p.num(y-py); px, py = x, y
    return p.s

def main():
    src = 'static/lookup.json'; out = 'lookup.optimized.json'
    raw_before = len(open(src, 'rb').read())
    data = json.load(open(src))
    before = after = pts_before = pts_after = dropped = 0
    for f in data['figs'].values():
        t = f.get('tagged')
        if not t: continue
        for k in TAGGED_DROP:
            if k in t: del t[k]; dropped += 1
        for c in t.get('curves', []):
            for k in CURVE_DROP:
                if k in c: del c[k]; dropped += 1
            P = parse(c['d']); S = rdp(P, EPS)
            before += len(c['d']); pts_before += len(P); pts_after += len(S)
            c['d'] = emit(S)
            after += len(c['d'])
    json.dump(data, open(out, 'w'), separators=(',', ':'))
    raw_after = len(open(out, 'rb').read())
    print(f'eps={EPS}  decimals={DP}  ->  {out}')
    print(f'points : {pts_before:,} -> {pts_after:,} ({100*pts_after/pts_before:.1f}%)')
    print(f'd bytes: {before:,} -> {after:,} ({100*after/before:.1f}%)')
    print(f'tags dropped: {dropped:,}')
    print(f'FILE   : {raw_before:,} -> {raw_after:,} bytes ({100*raw_after/raw_before:.1f}%)')

if __name__ == '__main__':
    main()
