/* Shared nebula theme: toggle, persistence, canvas boot, iframe sync. */
(function (global) {
  'use strict';

  const STORAGE_KEY = 'sparky-theme';
  const MSG_TYPE = 'sparky-theme';
  const NEBULA_DEFAULTS = {
    speed: 0.1,
    brightness: 2,
    contrast: 0.95,
    sphereSize: 135,
    yFrac: 0.42,
    lineAlpha: 0.35,
    scrimDark: 0.44,
    scrimCenter: 0.13,
    particleAlpha: 0.22,
    goldBrightness: 1,
  };
  let nebulaInstance = null;
  let initOptions = {};
  let toggleBtn = null;

  function activeTheme() {
    return document.documentElement.classList.contains('theme-b') ? 'b' : 'a';
  }

  function updateToggleButton() {
    if (!toggleBtn) return;
    const isB = activeTheme() === 'b';
    toggleBtn.classList.toggle('is-nebula', isB);
    const label = isB ? 'Switch to default background' : 'Nebula background';
    toggleBtn.title = label;
    toggleBtn.setAttribute('aria-label', label);
  }

  function syncUrl(theme) {
    const url = new URL(location.href);
    if (theme === 'b') url.searchParams.set('theme', 'b');
    else url.searchParams.delete('theme');
    const next = url.pathname + url.search + url.hash;
    if (location.pathname + location.search + location.hash !== next) {
      history.replaceState(null, '', next);
    }
  }

  function applyThemeDom(theme) {
    const isB = theme === 'b';
    document.documentElement.classList.toggle('theme-b', isB);
    const sheet = document.getElementById('theme-b-stylesheet');
    if (sheet) sheet.media = isB ? 'all' : 'not all';
    updateToggleButton();
  }

  function stopNebula() {
    if (nebulaInstance) {
      nebulaInstance.stop();
      nebulaInstance = null;
    }
    const canvas = document.getElementById(initOptions.canvasId || 'theme-b-nebula-canvas');
    if (canvas) {
      const ctx = canvas.getContext('2d');
      if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
  }

  function restorePortalView() {
    const dashboard = document.getElementById('dashboard');
    const framePanel = document.getElementById('frame-panel');
    if (!dashboard || !framePanel) return;
    if (!framePanel.classList.contains('open')) dashboard.style.display = '';
  }

  function themedUrl(src, theme) {
    const t = theme != null ? theme : activeTheme();
    if (!src || t !== 'b') return src;
    try {
      const url = new URL(src, location.href);
      if (url.origin !== location.origin) return src;
      url.searchParams.set('theme', 'b');
      return url.pathname + url.search + url.hash;
    } catch (_) {
      return src;
    }
  }

  function mergeNebulaOpts(options) {
    const base = Object.assign({}, NEBULA_DEFAULTS, options || {});
    if (global.SparkyNebulaTune) {
      return global.SparkyNebulaTune.loadSaved(base);
    }
    try {
      const raw = localStorage.getItem('sparky-nebula-tune');
      if (raw) return Object.assign(base, JSON.parse(raw));
    } catch (_) {}
    return base;
  }

  function mountTunePanel(baseOpts) {
    if (!nebulaInstance || optionsDisabled()) return;
    const start = () => {
      if (global.SparkyNebulaTune) global.SparkyNebulaTune.mount(nebulaInstance, baseOpts);
    };
    if (global.SparkyNebulaTune) start();
    else {
      const s = document.createElement('script');
      s.src = '/assets/nebula-tune.js';
      s.onload = start;
      document.head.appendChild(s);
    }
  }

  function optionsDisabled() {
    return new URLSearchParams(location.search).get('nebula-tune') === '0';
  }

  function bootNebula(canvasId, options) {
    if (activeTheme() !== 'b') return;
    const canvas = document.getElementById(canvasId || initOptions.canvasId || 'theme-b-nebula-canvas');
    if (!canvas) return;
    stopNebula();
    const baseOpts = Object.assign({}, NEBULA_DEFAULTS, initOptions.nebula || {}, options || {});
    const opts = mergeNebulaOpts(baseOpts);
    const start = () => {
      if (!global.SparkyNebula) return;
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          nebulaInstance = new global.SparkyNebula(canvas, opts);
          nebulaInstance.start();
          mountTunePanel(baseOpts);
        });
      });
    };
    if (global.SparkyNebula) start();
    else {
      const s = document.createElement('script');
      s.src = '/assets/oobe-nebula.js';
      s.onload = start;
      document.head.appendChild(s);
    }
  }

  function postTheme(target, theme) {
    if (!target || target === window) return;
    try {
      target.postMessage({ type: MSG_TYPE, theme: theme }, location.origin);
    } catch (_) {}
  }

  function updatePortalLinks(theme) {
    const popout = document.getElementById('frame-popout');
    if (!popout) return;
    const href = popout.getAttribute('href');
    if (!href || href === '#') return;
    popout.href = themedUrl(href, theme);
  }

  function broadcastTheme(theme, source) {
    localStorage.setItem(STORAGE_KEY, theme);
    syncUrl(theme);
    updatePortalLinks(theme);
    if (source !== 'parent' && window.parent !== window) {
      postTheme(window.parent, theme);
    }
    if (source !== 'child') {
      const frame = document.getElementById('content-frame');
      if (frame && frame.contentWindow) postTheme(frame.contentWindow, theme);
    }
  }

  function setTheme(theme, opts) {
    opts = opts || {};
    if (theme !== 'a' && theme !== 'b') theme = 'a';
    applyThemeDom(theme);
    if (theme === 'b') bootNebula(opts.canvasId, opts.nebula);
    else {
      stopNebula();
      restorePortalView();
    }
    if (!opts.silent) broadcastTheme(theme, opts.source);
    else {
      syncUrl(theme);
      updatePortalLinks(theme);
    }
  }

  function toggle() {
    const next = activeTheme() === 'b' ? 'a' : 'b';
    setTheme(next);
  }

  function bindToggle(btn) {
    if (!btn) return;
    toggleBtn = btn;
    updateToggleButton();
    btn.addEventListener('click', toggle);
  }

  function onMessage(event) {
    if (event.origin !== location.origin) return;
    if (!event.data || event.data.type !== MSG_TYPE) return;
    const theme = event.data.theme === 'b' ? 'b' : 'a';
    if (theme === activeTheme()) return;
    setTheme(theme, { silent: true, source: event.source === window.parent ? 'parent' : 'child' });
    localStorage.setItem(STORAGE_KEY, theme);
  }

  function init(options) {
    options = options || {};
    initOptions = options;
    bindToggle(document.getElementById(options.toggleId || 'theme-toggle'));
    if (activeTheme() === 'b') bootNebula(options.canvasId, options.nebula);
    window.addEventListener('message', onMessage);
    window.addEventListener('storage', (e) => {
      if (e.key !== STORAGE_KEY || e.newValue == null) return;
      const theme = e.newValue === 'b' ? 'b' : 'a';
      if (theme === activeTheme()) return;
      setTheme(theme, { silent: true });
    });
  }

  global.SparkyTheme = {
    init,
    toggle,
    setTheme,
    bootNebula,
    activeTheme,
    themedUrl,
    NEBULA_DEFAULTS,
    get nebula() { return nebulaInstance; },
  };
})(window);