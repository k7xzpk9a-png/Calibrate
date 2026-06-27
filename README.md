# Curve calibrator

Standalone extract of the NH90 app's `/calibrate` authoring tool. Pick a fig →
tag its blue performance curves (PA / WI / Wind / OAT…) → Save writes
`figs[<fig>].tagged` into `lookup.json`.

```
npm install
npm run dev      # open http://localhost:5173
```

## Data

`static/lookup.json` and `static/svgz/` are **symlinks** into the main project
(`../nh90-svelte/static/...`), so tags you save here land directly in the app —
one source of truth. To make this copy fully independent instead, replace the
symlinks with real copies:

```
rm static/lookup.json static/svgz
cp ../nh90-svelte/static/lookup.json static/
cp -r ../nh90-svelte/static/svgz static/
```

Dev-only: the `/calibrate/save` endpoint writes `static/lookup.json` on disk and
only runs under `vite dev`.
