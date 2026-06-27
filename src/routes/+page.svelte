<script lang="ts">
  import { onMount } from 'svelte';
  // The tool lives at /calibrate (verbatim route from the main app); bounce there.
  onMount(() => location.replace('/calibrate'));
</script>

<a href="/calibrate">Curve calibrator →</a>
