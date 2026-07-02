/* Benchmaster portal tab — live queue, controls, run history */
(function () {
  'use strict';

  const API = '/api/benchmaster';
  const FETCH_TIMEOUT_MS = 8000;
  const POLL_MS = 10000;
  const STALE_MS = 45000;
  const DEBOUNCE_MS = 800;

  let pollTimer = null;
  let watchdogTimer = null;
  let eventSource = null;
  let onBenchmaster = false;
  let lastRefreshOk = 0;
  let refreshGen = 0;
  let refreshInFlight = false;
  let refreshDebounce = null;
  let hasRenderedOnce = false;

  function $(id) {
    return document.getElementById(id);
  }

  function esc(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function fmtTs(ts) {
    if (!ts) return '—';
    try {
      return new Date(ts).toLocaleString();
    } catch (_e) {
      return ts;
    }
  }

  function setMsg(text, kind) {
    const el = $('bm-msg');
    if (!el) return;
    el.textContent = text || '';
    el.className = 'bm-msg' + (kind ? ' ' + kind : '');
    el.hidden = !text;
  }

  function renderPending(label) {
    const text = label || 'Connecting…';
    const head = $('bm-head-meta');
    if (head) head.innerHTML = '<span class="bm-badge warn">' + esc(text) + '</span>';
    const cur = $('bm-current');
    if (cur) cur.innerHTML = '<div class="bm-empty bm-pending">' + esc(text) + '</div>';
  }

  function renderOffline(reason) {
    const msg = reason || 'Benchmaster API unreachable';
    const head = $('bm-head-meta');
    if (head) head.innerHTML = '<span class="bm-badge err">offline</span>';
    const cur = $('bm-current');
    if (cur) cur.innerHTML = '<div class="bm-empty">' + esc(msg) + '</div>';
    const q = $('bm-queue');
    if (q) q.innerHTML = '<div class="bm-empty">—</div>';
    const runs = $('bm-runs');
    if (runs) runs.innerHTML = '<div class="bm-empty">—</div>';
    setMsg(msg + ' — tap Refresh or wait for retry', 'err');
    hasRenderedOnce = true;
  }

  function fetchJson(path, timeoutMs) {
    timeoutMs = timeoutMs || FETCH_TIMEOUT_MS;
    const ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    let timer = null;
    if (ctrl) {
      timer = setTimeout(function () {
        try { ctrl.abort(); } catch (_e) { /* ignore */ }
      }, timeoutMs);
    }
    return fetch(API + path, {
      cache: 'no-store',
      signal: ctrl ? ctrl.signal : undefined,
      headers: { Accept: 'application/json' },
    })
      .then(function (res) {
        if (timer) clearTimeout(timer);
        return res.json().catch(function () { return {}; }).then(function (data) {
          if (!res.ok) throw new Error(data.error || res.statusText || ('HTTP ' + res.status));
          return data;
        });
      })
      .catch(function (err) {
        if (timer) clearTimeout(timer);
        if (err && err.name === 'AbortError') throw new Error('request timed out');
        throw err;
      });
  }

  async function apiPost(path, body) {
    const ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    const timer = ctrl ? setTimeout(function () { ctrl.abort(); }, FETCH_TIMEOUT_MS) : null;
    try {
      const res = await fetch(API + path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(body || {}),
        cache: 'no-store',
        signal: ctrl ? ctrl.signal : undefined,
      });
      if (timer) clearTimeout(timer);
      const data = await res.json().catch(function () { return {}; });
      if (!res.ok) throw new Error(data.error || res.statusText);
      return data;
    } catch (err) {
      if (timer) clearTimeout(timer);
      throw err;
    }
  }

  function controlBadge(ctrl) {
    const mode = (ctrl && ctrl.mode) || 'paused';
    const cls = mode === 'running' ? 'ok' : mode === 'stopped' ? 'err' : 'warn';
    let extra = '';
    if (ctrl && ctrl.stop_after_current) extra = ' · stop after current';
    if (ctrl && ctrl.abort_requested) extra = ' · aborting…';
    return '<span class="bm-badge ' + cls + '">' + esc(mode) + extra + '</span>';
  }

  function phaseIcon(state) {
    if (state === 'done') return '✓';
    if (state === 'running') return '●';
    if (state === 'failed') return '✗';
    return '○';
  }

  function renderSubsteps(substeps) {
    if (!substeps || !substeps.length) return '';
    return '<ul class="bm-substeps">'
      + substeps.map(function (ss) {
        const st = ss.state || 'pending';
        return '<li class="bm-substep bm-substep-' + esc(st) + '">'
          + '<span class="bm-phase-icon" aria-hidden="true">' + phaseIcon(st) + '</span>'
          + '<span>' + esc(ss.label || ss.id) + '</span>'
          + (ss.detail ? '<span class="bm-phase-detail">' + esc(ss.detail) + '</span>' : '')
          + '</li>';
      }).join('')
      + '</ul>';
  }

  function renderPhaseList(job) {
    const phases = job.live_phases;
    if (!phases || !phases.length) return '';
    return '<ul class="bm-phases">'
      + phases.map(function (ph) {
        const st = ph.state || 'pending';
        let detail = ph.detail ? '<span class="bm-phase-detail">' + esc(ph.detail) + '</span>' : '';
        let hint = ph.hint && st === 'pending' ? '<span class="bm-phase-hint">' + esc(ph.hint) + '</span>' : '';
        return '<li class="bm-phase bm-phase-' + esc(st) + '">'
          + '<span class="bm-phase-icon" aria-hidden="true">' + phaseIcon(st) + '</span>'
          + '<span class="bm-phase-label">' + esc(ph.label || ph.id) + '</span>'
          + detail + hint
          + renderSubsteps(ph.substeps)
          + '</li>';
      }).join('')
      + '</ul>';
  }

  function renderCurrent(st) {
    const el = $('bm-current');
    if (!el) return;
    const job = st.current_job;
    if (!job) {
      el.innerHTML = '<div class="bm-empty">No active job</div>';
      return;
    }
    const p = job.progress || {};
    const step = p.step || 0;
    const total = p.total_steps || '?';
    el.innerHTML =
      '<div class="bm-current-row"><strong>' + esc(job.profile_id) + '</strong>'
      + ' <span class="bm-muted">' + esc(job.type) + '</span></div>'
      + renderPhaseList(job)
      + '<div class="bm-progress" aria-hidden="true"><i style="width:' + (total && step ? Math.min(100, (step / total) * 100) : 10) + '%"></i></div>'
      + '<div class="bm-muted">step ' + esc(step) + '/' + esc(total) + ' · ' + esc(job.id) + '</div>';
  }

  function renderQueue(items) {
    const el = $('bm-queue');
    if (!el) return;
    const rows = (items || []).filter(function (j) {
      return j.state === 'queued' || j.state === 'running' || j.state === 'failed';
    });
    if (!rows.length) {
      el.innerHTML = '<div class="bm-empty">Queue empty</div>';
      return;
    }
    el.innerHTML = rows.map(function (job, idx) {
      const st = job.state || 'queued';
      const cls = st === 'running' ? 'running' : st === 'failed' ? 'failed' : '';
      return '<div class="bm-queue-row ' + cls + '" data-job-id="' + esc(job.id) + '">'
        + '<span class="bm-q-idx">' + (idx + 1) + '</span>'
        + '<span class="bm-q-profile">' + esc(job.profile_id) + '</span>'
        + '<span class="bm-q-type">' + esc(job.type) + '</span>'
        + '<span class="bm-q-state">' + esc(st) + '</span>'
        + (job.claimed_by ? '<span class="bm-muted">' + esc(job.claimed_by) + '</span>' : '')
        + (st !== 'running'
          ? '<button type="button" class="bm-btn tiny" data-bm-remove="' + esc(job.id) + '">remove</button>'
          : '')
        + '</div>';
    }).join('');
  }

  function renderRuns(runs) {
    const el = $('bm-runs');
    if (!el) return;
    const rows = runs || [];
    if (!rows.length) {
      el.innerHTML = '<div class="bm-empty">No completed runs yet</div>';
      return;
    }
    el.innerHTML = rows.slice(0, 20).map(function (r) {
      const ok = r.ok ? 'ok' : r.aborted ? 'warn' : 'err';
      const label = r.aborted ? 'aborted' : r.ok ? 'done' : 'failed';
      return '<div class="bm-run-row ' + ok + '">'
        + '<span>' + esc(r.profile_id) + '</span>'
        + '<span class="bm-muted">' + esc(r.type) + '</span>'
        + '<span>' + esc(label) + '</span>'
        + '<span class="bm-muted">' + fmtTs(r.finished_at || r.started_at) + '</span>'
        + '</div>';
    }).join('');
  }

  function renderStatus(st) {
    const head = $('bm-head-meta');
    if (head) {
      head.innerHTML = controlBadge(st.control)
        + ' · queued ' + ((st.counts && st.counts.queued) || 0)
        + ' · worker ' + (st.worker_alive ? 'up' : 'down')
        + (st.schedule_open === false ? ' · outside schedule' : '');
    }
    renderCurrent(st);
  }

  function applyStatusFromStream(raw) {
    try {
      const st = typeof raw === 'string' ? JSON.parse(raw) : raw;
      if (!st || !st.ok) return;
      renderStatus(st);
      lastRefreshOk = Date.now();
      hasRenderedOnce = true;
    } catch (_e) {
      /* ignore malformed SSE payload */
    }
  }

  function scheduleRefresh(immediate) {
    if (!onBenchmaster) return;
    if (immediate) {
      if (refreshDebounce) {
        clearTimeout(refreshDebounce);
        refreshDebounce = null;
      }
      doRefresh(true);
      return;
    }
    if (refreshDebounce) return;
    refreshDebounce = setTimeout(function () {
      refreshDebounce = null;
      doRefresh(false);
    }, DEBOUNCE_MS);
  }

  async function doRefresh(force) {
    if (!onBenchmaster && !force) return;
    if (refreshInFlight) {
      if (!force) return;
      refreshGen += 1;
    }
    const gen = ++refreshGen;
    refreshInFlight = true;

    if (!hasRenderedOnce) {
      renderPending('Connecting…');
    }

    try {
      let st = null;
      try {
        st = await fetchJson('/status');
        if (gen !== refreshGen) return;
        renderStatus(st);
      } catch (err) {
        if (gen !== refreshGen) return;
        renderOffline(err && err.message ? err.message : 'status failed');
        return;
      }

      const tail = await Promise.allSettled([
        fetchJson('/queue'),
        fetchJson('/runs'),
      ]);
      if (gen !== refreshGen) return;

      const q = tail[0].status === 'fulfilled' ? tail[0].value : null;
      const runs = tail[1].status === 'fulfilled' ? tail[1].value : null;
      renderQueue((q && q.items) || []);
      renderRuns((runs && runs.runs) || []);

      if (!q || !runs) {
        setMsg('Partial refresh — queue or runs failed', 'warn');
      } else {
        setMsg('', '');
      }
      lastRefreshOk = Date.now();
      hasRenderedOnce = true;
    } catch (e) {
      if (gen !== refreshGen) return;
      renderOffline(String(e.message || e));
    } finally {
      if (gen === refreshGen) refreshInFlight = false;
    }
  }

  async function refresh(force) {
    scheduleRefresh(!!force);
  }

  async function control(action) {
    if (action === 'refresh') {
      await doRefresh(true);
      return;
    }
    try {
      await apiPost('/control', { action: action });
      setMsg('Control: ' + action, 'ok');
      await doRefresh(true);
    } catch (e) {
      setMsg(String(e.message || e), 'err');
    }
  }

  async function addJob() {
    const profile = ($('bm-add-profile') && $('bm-add-profile').value || '').trim();
    const inv = ($('bm-add-inv') && $('bm-add-inv').value || '').trim();
    const jtype = ($('bm-add-type') && $('bm-add-type').value) || 'perf_sweep';
    if (!profile) {
      setMsg('Profile id required', 'err');
      return;
    }
    try {
      await apiPost('/queue/add', {
        type: jtype,
        profile_id: profile,
        inventory_path: inv || undefined,
      });
      setMsg('Queued ' + profile, 'ok');
      if ($('bm-add-profile')) $('bm-add-profile').value = '';
      await doRefresh(true);
    } catch (e) {
      setMsg(String(e.message || e), 'err');
    }
  }

  async function removeJob(jobId) {
    try {
      await apiPost('/queue/remove', { job_id: jobId });
      await doRefresh(true);
    } catch (e) {
      setMsg(String(e.message || e), 'err');
    }
  }

  function bindControls() {
    const card = $('benchmaster-card');
    if (!card || card.dataset.bound === '1') return;
    card.dataset.bound = '1';

    card.addEventListener('click', function (ev) {
      const t = ev.target;
      if (!(t instanceof HTMLElement)) return;
      const act = t.getAttribute('data-bm-action');
      if (act) {
        ev.preventDefault();
        control(act);
        return;
      }
      const rm = t.getAttribute('data-bm-remove');
      if (rm) {
        ev.preventDefault();
        removeJob(rm);
      }
    });

    const addBtn = $('bm-add-btn');
    if (addBtn) addBtn.addEventListener('click', addJob);
  }

  function connectStream() {
    if (typeof EventSource === 'undefined') return;
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    try {
      eventSource = new EventSource(API + '/stream');
      // SSE status heartbeat every 2s — update header/current only (no full refetch flicker)
      eventSource.addEventListener('status', function (ev) {
        if (onBenchmaster) applyStatusFromStream(ev.data);
      });
      // Real queue events — debounced full refresh for queue + runs
      eventSource.addEventListener('benchmaster', function () {
        if (onBenchmaster) scheduleRefresh(false);
      });
      eventSource.onerror = function () {
        if (eventSource) {
          eventSource.close();
          eventSource = null;
        }
        if (onBenchmaster) {
          setTimeout(connectStream, 5000);
        }
      };
    } catch (_e) {
      /* polling fallback */
    }
  }

  function startPoll() {
    stopPoll();
    doRefresh(true);
    pollTimer = setInterval(function () {
      if (onBenchmaster) scheduleRefresh(false);
    }, POLL_MS);
    watchdogTimer = setInterval(function () {
      if (!onBenchmaster) return;
      if (!lastRefreshOk || Date.now() - lastRefreshOk > STALE_MS) {
        connectStream();
        doRefresh(true);
      }
    }, STALE_MS);
    connectStream();
  }

  function stopPoll() {
    refreshGen += 1;
    refreshInFlight = false;
    if (refreshDebounce) {
      clearTimeout(refreshDebounce);
      refreshDebounce = null;
    }
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    if (watchdogTimer) {
      clearInterval(watchdogTimer);
      watchdogTimer = null;
    }
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  }

  function wakeReconnect() {
    if (!onBenchmaster) return;
    connectStream();
    doRefresh(true);
  }

  function show() {
    if (onBenchmaster) {
      doRefresh(true);
      return;
    }
    onBenchmaster = true;
    bindControls();
    startPoll();
  }

  window.SparkBenchmaster = {
    show: show,
    hide: function () {
      onBenchmaster = false;
      stopPoll();
    },
    refresh: function () { return doRefresh(true); },
  };

  /* Hard refresh with #benchmaster: inline portal script runs before this defer script. */
  function bootIfRoutedHere() {
    if ((location.hash || '').replace(/^#/, '') !== 'benchmaster') return;
    var card = document.getElementById('benchmaster-card');
    if (card && card.hidden) return;
    show();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootIfRoutedHere);
  } else {
    bootIfRoutedHere();
  }

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState !== 'visible') return;
    if (onBenchmaster) wakeReconnect();
    else bootIfRoutedHere();
  });

  window.addEventListener('pageshow', function (ev) {
    if (ev.persisted) wakeReconnect();
  });

  window.addEventListener('online', wakeReconnect);

  window.addEventListener('focus', function () {
    if (onBenchmaster) wakeReconnect();
  });
})();
