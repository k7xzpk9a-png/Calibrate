import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

// Dev-only authoring tool: runs under `vite dev`. base stays empty so the page's
// `${base}/lookup.json`, `${base}/svgz/...`, `${base}/calibrate/save` resolve at /.
/** @type {import('@sveltejs/kit').Config} */
export default {
  preprocess: vitePreprocess(),
  kit: { adapter: adapter({ fallback: 'index.html', strict: false }) },
};
