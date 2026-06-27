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
    python3 extract_curves.py [PDF]               # all (parse + SVGZ, svgo)
    python3 extract_curves.py [PDF] --list-only   # only chart catalog
    python3 extract_curves.py [PDF] --precision 3 # 3 decimal coords
    python3 extract_curves.py [PDF] --no-svgo     # disable svgo 
    python3 extract_curves.py [PDF] --svg         # plain SVG (no gzip)

**Todo : add the RDP algorithm, reduces definition by 98%, most curves are almost linear**
