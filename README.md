# Curve calibrator

Standalone extract of the NH90 app's `/calibrate` authoring tool. Pick a fig →
tag its blue performance curves (PA / WI / Wind / OAT…) → Save writes
`figs[<fig>].tagged` into `lookup.json`.

```
npm install
npm run dev      # open http://localhost:5173
```

## Data


```
rm static/lookup.json static/svgz
cp ../nh90-svelte/static/lookup.json static/
cp -r ../nh90-svelte/static/svgz static/
```

Dev-only: the `/calibrate/save` endpoint writes `static/lookup.json` on disk and
only runs under `vite dev`.


## Scripts

Use extract_curves to pull all performance chart from FM.
Usage :
```
    python3 extract_curves.py [PDF]               # all (parse + SVGZ, svgo)
    python3 extract_curves.py [PDF] --list-only   # only chart catalog
    python3 extract_curves.py [PDF] --precision 3 # 3 decimal coords
    python3 extract_curves.py [PDF] --no-svgo     # disable svgo 
    python3 extract_curves.py [PDF] --svg         # plain SVG (no gzip)
```

Optimize lookup.json: RDP-simplify every tagged-curve `d` path AND strip the
authoring-only tags the runtime never reads, then minify.
```
  python3 optimize.py [epsilon] [decimals]
```

Reads `static/lookup.json`, writes `lookup.optimized.json` (minified). epsilon is
in viewBox units (default 0.05 = very small; curves are within a 595x842 page).
Idempotent — re-running on an already-optimized file is a no-op for paths.

Dropped tags (unused by nh90-svelte/lookupTable.ts): `curve.id`, `tagged.source`,
`tagged.fig`, `tagged.viewBox`. Everything else — incl. `tagged.calibration` and
any unknown keys — is copied verbatim. Promote with
`cp lookup.optimized.json static/lookup.json`.
