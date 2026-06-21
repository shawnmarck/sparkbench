/* Nebula tuning panel — live sliders with numeric readouts. Persists to localStorage. */
(function (global) {
  'use strict';

  const STORAGE_KEY = 'sparky-nebula-tune';
  const PANEL_KEY = 'sparky-nebula-tune-panel';

  const SPECS = [
    { key: 'speed', label: 'Speed', min: 0.1, max: 2, step: 0.05, def: 0.1 },
    { key: 'brightness', label: 'Brightness', min: 0.4, max: 2.5, step: 0.05, def: 2 },
    { key: 'contrast', label: 'Contrast', min: 0.5, max: 2, step: 0.05, def: 0.95 },
    { key: 'sphereSize', label: 'Sphere size', min: 40, max: 180, step: 5, def: 135 },
    { key: 'yFrac', label: 'Y position', min: 0.15, max: 0.65, step: 0.01, def: 0.42, pct: true },
    { key: 'lineAlpha', label: 'Line alpha', min: 0, max: 0.45, step: 0.01, def: 0.35 },
    { key: 'scrimDark', label: 'Scrim edge', min: 0, max: 0.95, step: 0.01, def: 0.44 },
    { key: 'scrimCenter', label: 'Scrim center', min: 0, max: 0.5, step: 0.01, def: 0.13 },
    { key: 'particleAlpha', label: 'White alpha', min: 0.1, max: 0.9, step: 0.01, def: 0.22 },
    { key: 'goldBrightness', label: 'Gold alpha', min: 0.3, max: 1, step: 0.01, def: 1 },
  ];

  function defaults(overrides) {
    const out = {};
    SPECS.forEach((s) => { out[s.key] = s.def; });
    return Object.assign(out, overrides || {});
  }

  function loadSaved(base) {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return base;
      return Object.assign({}, base, JSON.parse(raw));
    } catch (_) {
      return base;
    }
  }

  function save(values) {
    const payload = {};
    SPECS.forEach((s) => {
      if (values[s.key] != null) payload[s.key] = values[s.key];
    });
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  }

  function fmt(spec, value) {
    if (spec.pct) return Math.round(value * 100) + '%';
    const step = spec.step || 0.01;
    const dec = String(step).includes('.') ? String(step).split('.')[1].length : 0;
    return Number(value).toFixed(dec);
  }

  function exportJson(values) {
    const out = {};
    SPECS.forEach((s) => { out[s.key] = values[s.key]; });
    return JSON.stringify(out, null, 2);
  }

  function mount(nebula, baseOpts) {
    if (!nebula || document.getElementById('nebula-tune-panel')) return;

    const values = loadSaved(defaults(baseOpts));
    nebula.setOptions(values);

    const wrap = document.createElement('div');
    wrap.className = 'nebula-tune-wrap';
    wrap.innerHTML =
      '<button type="button" class="nebula-tune-gear" id="nebula-tune-gear" title="Nebula tuning" aria-label="Nebula tuning" aria-expanded="false">'
      + '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4Z" stroke="currentColor" stroke-width="1.4"/>'
      + '<path d="M19.4 13.2a7.4 7.4 0 0 0 .1-2.4l2-1.2-2-3.4-2.3 1a7.5 7.5 0 0 0-2.1-1.2L14.8 2h-5.6l-.3 4.2a7.5 7.5 0 0 0-2.1 1.2l-2.3-1-2 3.4 2 1.2a7.4 7.4 0 0 0 0 2.4l-2 1.2 2 3.4 2.3-1a7.5 7.5 0 0 0 2.1 1.2l.3 4.2h5.6l.3-4.2a7.5 7.5 0 0 0 2.1-1.2l2.3 1 2-3.4-2-1.2Z" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round" opacity=".85"/></svg>'
      + '</button>'
      + '<div class="nebula-tune-panel" id="nebula-tune-panel" hidden>'
      + '<div class="nebula-tune-head"><strong>Nebula tune</strong><span class="nebula-tune-hint">Dial in, then copy values</span></div>'
      + '<div class="nebula-tune-fields"></div>'
      + '<pre class="nebula-tune-json" id="nebula-tune-json"></pre>'
      + '<div class="nebula-tune-actions">'
      + '<button type="button" class="nebula-tune-btn" id="nebula-tune-copy">Copy JSON</button>'
      + '<button type="button" class="nebula-tune-btn" id="nebula-tune-reset">Reset defaults</button>'
      + '</div></div>';

    document.body.appendChild(wrap);

    const panel = wrap.querySelector('#nebula-tune-panel');
    const gear = wrap.querySelector('#nebula-tune-gear');
    const fields = wrap.querySelector('.nebula-tune-fields');
    const jsonOut = wrap.querySelector('#nebula-tune-json');

    function refreshJson() {
      jsonOut.textContent = exportJson(values);
    }

    function apply() {
      nebula.setOptions(values);
      save(values);
      refreshJson();
    }

    SPECS.forEach((spec) => {
      if (values[spec.key] == null) values[spec.key] = spec.def;
      const row = document.createElement('label');
      row.className = 'nebula-tune-row';
      row.innerHTML =
        '<span class="nebula-tune-label">' + spec.label + '</span>'
        + '<input type="range" min="' + spec.min + '" max="' + spec.max + '" step="' + spec.step + '" value="' + values[spec.key] + '">'
        + '<output class="nebula-tune-val">' + fmt(spec, values[spec.key]) + '</output>';
      const input = row.querySelector('input');
      const out = row.querySelector('output');
      input.addEventListener('input', () => {
        values[spec.key] = Number(input.value);
        out.textContent = fmt(spec, values[spec.key]);
        apply();
      });
      fields.appendChild(row);
    });

    function setOpen(open) {
      panel.hidden = !open;
      gear.setAttribute('aria-expanded', open ? 'true' : 'false');
      localStorage.setItem(PANEL_KEY, open ? 'open' : 'closed');
    }

    gear.addEventListener('click', () => setOpen(panel.hidden));
    wrap.querySelector('#nebula-tune-copy').addEventListener('click', () => {
      const text = exportJson(values);
      navigator.clipboard.writeText(text).then(() => {
        const btn = wrap.querySelector('#nebula-tune-copy');
        const prev = btn.textContent;
        btn.textContent = 'Copied!';
        setTimeout(() => { btn.textContent = prev; }, 1400);
      }).catch(() => {
        window.prompt('Copy nebula settings:', text);
      });
    });
    wrap.querySelector('#nebula-tune-reset').addEventListener('click', () => {
      Object.assign(values, defaults(baseOpts));
      fields.querySelectorAll('.nebula-tune-row').forEach((row, i) => {
        const spec = SPECS[i];
        const input = row.querySelector('input');
        const out = row.querySelector('output');
        input.value = values[spec.key];
        out.textContent = fmt(spec, values[spec.key]);
      });
      localStorage.removeItem(STORAGE_KEY);
      apply();
    });

    if (localStorage.getItem(PANEL_KEY) === 'open') setOpen(true);
    refreshJson();
  }

  global.SparkyNebulaTune = { mount, defaults, loadSaved, SPECS, STORAGE_KEY };
})(window);