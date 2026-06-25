# Portal UI — Performance & Reliability Improvements (Opus review)

Review of `portal/index.html`, `portal/models.html`, and `portal/assets/oobe-nebula.js`. Ordered by ROI: biggest reliability/perf wins first.

## Reliability — biggest wins

### 1. Polls fire without in-flight guard or visibility check

`portal/index.html:2993-2994`

```js
pollTimer    = setInterval(gpuPoll, 1000);
infPollTimer = setInterval(() => { infTick(); expTick(); }, 2000);
```

- If `/api/gpu` ever takes >1 s (eugr loading, sparky busy), requests pile up. Same for inf/exp.
- No `document.hidden` check — keeps hammering when the tab is backgrounded. `portal/models.html:1806` already does this well; copy the pattern.

**Fix:** wrap each tick in an in-flight flag and skip when `document.visibilityState !== 'visible'`. ~6 lines.

### 2. Double log fetch when overlay is open

`portal/index.html:1990` (in `gpuPoll`) and `portal/index.html:1749` (in `infTick`).

`fetchInfLogs()` runs from both `gpuPoll` (1 s) and `infTick` (2 s) when the inference log overlay is open AND user is on Inference. Effectively two overlapping log fetches per second.

**Fix:** drop the `fetchInfLogs()` from `gpuPoll` — `infTick` already covers it whenever the overlay is open and visible.

### 3. No `AbortController` on view switches

Switching from Inference → System with a slow `/api/inference/status` still in flight will land that response after navigation, clobbering nav state via `renderNavInference`. The clobber is mild today but real.

**Fix:** keep an `AbortController` per tick; abort on view change. Or at minimum guard the assign with `if (!onInference) return`.

### 4. No backoff on error

On a failed `/api/gpu`, the next attempt is still in 1 s, indefinitely. If the backend is unhealthy (or sparky paused), the dashboard fires ~3600 failed reqs/hr.

**Fix:** doubled delay (cap 30 s), reset on success.

### 5. Race in `lastInfNavStatus` cache

`portal/index.html:1968-1975`

The 5 s gate (`INF_NAV_POLL_MS`) skips the network call, but the previous in-flight promise's `.then` writes `lastInfNavFetchAt = Date.now()` even if `d` is `null` (failed). A failure resets the clock and prevents the next retry for 5 s instead of triggering an immediate one.

**Fix:** only stamp `lastInfNavFetchAt` when `d` is truthy.

## Performance — small but free

### 6. Nebula link drawing is O(N²) with a `sqrt` per pair

`portal/assets/oobe-nebula.js:113`

250 particles → ~31 k `Math.sqrt(dx*dx + dy*dy)` per frame at 60 fps ≈ 1.9 M/s.

```js
if (Math.sqrt(dx*dx + dy*dy) < maxDist) {
```

**Fix:** compare squares — `const m2 = maxDist*maxDist; if (dx*dx + dy*dy < m2)`. Free 20–30 % off this loop.

### 7. Per-tick `innerHTML` rebuilds with no diff

Multiple `render*` in `portal/index.html`. `renderInfProfiles` is dirty-checked via `lastInfProfilesSnapshot` (good). `renderStorage`, `renderContainers`, `renderNavHermes`, `renderNavInference` are not — they rebuild HTML every second even when nothing changed, which thrashes layout and discards focus on any interactive child.

**Fix:** apply the same JSON-snapshot guard pattern to those four. Cheap and they're the noisiest.

### 8. `<style>` block is ~820 inline lines, blocking parse

`portal/index.html:21-843`

Same content on every page load; not cached.

**Fix:** move into `/themes/portal.css` with a real `Cache-Control`. Saves bytes on repeat loads, lets the browser cache it.

### 9. Render-blocking script tag

`portal/index.html:845`

```html
<script src="/assets/sparky-theme.js"></script>
```

**Fix:** add `defer`. Same for `portal/models.html`.

### 10. Animating `width` triggers layout

`portal/index.html:49` and similar:

```css
.nav-metric-bar > i { transition: width .35s ease; }
```

Animates `width` (layout property). Switch to `transform: scaleX()` to keep it on the compositor; same visual, no layout pass per poll. Same for `.metric-bar > i` and `.temp-bar > i`.

## Notes worth glancing at

- `portal/models.html:1547-1548` — `loadData(true)` then `setTimeout(loadData, 2000)`. Two full `models.json` fetches per recipe action; the second usually duplicates the first.
- `portal/models.html:1804` — refresh poll keeps firing when hidden (only `visibilitychange` triggers an extra fetch on focus). Cheap (30 s) but inconsistent with the focus handler.
- `portal/index.html:2358` uses `CSS.escape` (good) but other queries (`[data-variant-id="…"]`) don't — fine today since IDs are sanitized, just be consistent.

## Suggested order

1. (#1) visibility + in-flight guard
2. (#2) kill duplicate log fetch
3. (#7) snapshot-diff the four noisy renders
4. (#6) sqrt → squared distance
5. (#4) error backoff
6. (#9 + #8) defer + extract CSS

#1 + #2 + #6 together is ~30 lines and gives most of the win.
