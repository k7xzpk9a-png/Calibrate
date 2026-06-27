import { json, error } from '@sveltejs/kit';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Dev-only authoring endpoint: writes validated curve tags straight into
// static/lookup.json on disk, so the calibrator has no download/merge step.
// The app ships via adapter-static (no server at runtime) — this only ever
// runs under `vite dev`, which is exactly when you'd be calibrating.
export const prerender = false;

export async function POST({ request }) {
  const { fig, tagged } = await request.json();
  if (!fig || !tagged) throw error(400, 'fig and tagged required');

  const path = resolve('static/lookup.json');
  const data = JSON.parse(readFileSync(path, 'utf8'));
  if (!data.figs?.[fig]) throw error(404, `fig ${fig} not in lookup`);

  data.figs[fig].tagged = tagged; // preserves family/name/graph alongside
  writeFileSync(path, JSON.stringify(data, null, 2) + '\n');
  return json({ ok: true, curves: tagged.curves.length });
}
