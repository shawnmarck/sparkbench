/**
 * spark-inventory-grid.js — Reusable UX primitives for Sparky portal inventory pages.
 *
 * Exposes: window.SparkInventoryGrid
 *
 * Integration guide (TASK-002 Models / TASK-005 Inference / TASK-004 Explore):
 *
 *   <script src="/assets/spark-inventory-grid.js" defer></script>
 *
 *   // Summary line ("Showing A of B suffix"):
 *   SparkInventoryGrid.renderSummary(el, { filtered: 5, total: 12, suffix: '· 8 switchable' });
 *
 *   // Sort comparator, nulls last:
 *   rows.sort((a, b) => SparkInventoryGrid.compareValues(a, b, 'size_gb', 'asc'));
 *
 *   // Filter chips (chips: string[] | {key, label}[]):
 *   SparkInventoryGrid.renderChips(container, chips, activeSet, (key) => toggleChip(key));
 *
 *   // Sortable table:
 *   SparkInventoryGrid.renderTable(container, {
 *     columns: [{ key: 'name', label: 'Name' }, { key: 'size', label: 'Size' }],
 *     rows: filteredRows,
 *     sort: { col: 'name', dir: 'asc' },
 *     onSort: ({ col, dir }) => { sortState = { col, dir }; rerender(); },
 *   });
 *
 *   // Flat / grouped toggle (button must have data-sig-group-toggle attr):
 *   SparkInventoryGrid.toggleGrouped(wrapEl, flatRenderFn, groupedRenderFn, onRender);
 */
(function () {
  'use strict';

  function escHtml(text) {
    return String(text == null ? '' : text).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function escAttr(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/</g, '&lt;');
  }

  /**
   * renderSummary(el, { filtered, total, suffix })
   * Writes "Showing <filtered> of <total> <suffix>" into el.textContent.
   */
  function renderSummary(el, opts) {
    if (!el) return;
    var filtered = opts && opts.filtered;
    var total = opts && opts.total;
    var suffix = opts && opts.suffix;
    if (filtered == null || total == null) { el.textContent = ''; return; }
    el.textContent = 'Showing ' + filtered + ' of ' + total + (suffix ? ' ' + suffix : '');
  }

  /**
   * compareValues(a, b, col, dir)
   * General-purpose sort comparator. Nulls sort last regardless of direction.
   * Strings compare via locale-aware (effectively case-insensitive) ordering,
   * matching portal's human-facing display needs (model ids, names, etc.).
   */
  function compareValues(a, b, col, dir) {
    var av = a[col];
    var bv = b[col];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    var r;
    if (typeof av === 'string' && typeof bv === 'string') {
      r = av.localeCompare(bv);
      if (r < 0) r = -1; else if (r > 0) r = 1;
    } else {
      r = av < bv ? -1 : av > bv ? 1 : 0;
    }
    return dir === 'desc' ? -r : r;
  }

  /**
   * renderTable(container, { columns, rows, sort, onSort })
   * Renders a sortable <table> into container.
   * columns: { key, label, sortable? }[]
   * sort: { col, dir } | null
   * onSort: ({ col, dir }) => void
   */
  function renderTable(container, opts) {
    if (!container) return;
    var columns = (opts && opts.columns) || [];
    var rows = (opts && opts.rows) || [];
    var sort = opts && opts.sort;
    var onSort = opts && opts.onSort;

    var headCells = columns.map(function (col) {
      var isSorted = sort && sort.col === col.key;
      var dir = isSorted ? sort.dir : '';
      var indicator = isSorted ? (dir === 'desc' ? ' ↓' : ' ↑') : '';
      var ariaSortAttr = isSorted
        ? ' aria-sort="' + (dir === 'desc' ? 'descending' : 'ascending') + '"' : '';
      var sortCls = col.sortable !== false ? ' sig-th-sort' : '';
      return '<th class="sig-th' + sortCls + '" data-col="' + escAttr(col.key) + '"'
        + ariaSortAttr + '>'
        + escHtml(col.label) + escHtml(indicator) + '</th>';
    }).join('');

    var bodyCells = rows.map(function (row) {
      var cells = columns.map(function (col) {
        var val = row[col.key];
        return '<td>' + escHtml(val == null ? '' : String(val)) + '</td>';
      }).join('');
      return '<tr>' + cells + '</tr>';
    }).join('');

    if (!bodyCells) {
      bodyCells = '<tr><td colspan="' + columns.length + '" class="sig-empty">—</td></tr>';
    }

    container.innerHTML = '<table class="sig-table">'
      + '<thead><tr>' + headCells + '</tr></thead>'
      + '<tbody>' + bodyCells + '</tbody>'
      + '</table>';

    if (onSort) {
      container.querySelectorAll('.sig-th.sig-th-sort').forEach(function (th) {
        th.addEventListener('click', function () {
          var col = th.dataset.col;
          var dir = (sort && sort.col === col)
            ? (sort.dir === 'asc' ? 'desc' : 'asc')
            : 'asc';
          onSort({ col: col, dir: dir });
        });
      });
    }
  }

  /**
   * renderChips(container, chips, active, onToggle)
   * Renders filter chip buttons. active: string | string[] | Set<string>
   * chips: string[] | { key, label }[]
   */
  function renderChips(container, chips, active, onToggle) {
    if (!container) return;
    var activeArr = active instanceof Set
      ? Array.from(active)
      : Array.isArray(active) ? active : (active ? [active] : []);
    var activeSet = new Set(activeArr);

    container.innerHTML = (chips || []).map(function (chip) {
      var key = typeof chip === 'string' ? chip : chip.key;
      var label = typeof chip === 'string' ? chip : (chip.label || chip.key);
      return '<button type="button" class="sig-chip' + (activeSet.has(key) ? ' active' : '') + '"'
        + ' data-chip="' + escAttr(key) + '">' + escHtml(label) + '</button>';
    }).join('');

    if (onToggle) {
      container.querySelectorAll('.sig-chip').forEach(function (btn) {
        btn.addEventListener('click', function () { onToggle(btn.dataset.chip); });
      });
    }
  }

  /**
   * toggleGrouped(wrapEl, flatRender, groupedRender, onRender)
   * Wires a [data-sig-group-toggle] button to swap between flat and grouped render callbacks.
   */
  function toggleGrouped(wrapEl, flatRender, groupedRender, onRender) {
    if (!wrapEl) return;
    var btn = wrapEl.querySelector('[data-sig-group-toggle]');
    if (!btn) return;
    var grouped = btn.dataset.sigGroupToggle !== 'flat';
    btn.addEventListener('click', function () {
      grouped = !grouped;
      btn.dataset.sigGroupToggle = grouped ? 'grouped' : 'flat';
      btn.textContent = grouped ? 'Flat' : 'Grouped';
      if (onRender) onRender(grouped ? groupedRender : flatRender);
    });
  }

  window.SparkInventoryGrid = {
    renderSummary: renderSummary,
    compareValues: compareValues,
    renderTable: renderTable,
    renderChips: renderChips,
    toggleGrouped: toggleGrouped,
  };
})();
