#!/usr/bin/env python3
"""One-shot patch for /opt/spark/portal/index.html container rows."""
from pathlib import Path

path = Path("/opt/spark/portal/index.html")
text = path.read_text()

css_old = """    .svc-item { display: flex; flex-wrap: wrap; gap: .35rem .75rem; justify-content: space-between; font-size: .8rem; font-family: ui-monospace, monospace; color: #c5cdd8; padding: .45rem .55rem; background: #12151c; border-radius: 8px; border: 1px solid var(--border); }
    .svc-item .name { color: var(--text); font-weight: 600; }
    .svc-item .ports { color: var(--accent); }"""

css_new = """    .svc-item { display: flex; flex-direction: column; gap: .35rem; font-size: .8rem; font-family: ui-monospace, monospace; color: #c5cdd8; padding: .45rem .55rem; background: #12151c; border-radius: 8px; border: 1px solid var(--border); }
    .svc-row { display: flex; flex-wrap: wrap; gap: .35rem .75rem; justify-content: space-between; align-items: baseline; width: 100%; }
    .svc-item .name { color: var(--text); font-weight: 600; }
    .svc-meta { color: var(--muted); font-size: .74rem; }
    .svc-eps { display: flex; flex-wrap: wrap; gap: .35rem .5rem; width: 100%; }
    .svc-ep { color: var(--accent); text-decoration: none; font-size: .76rem; padding: .12rem .4rem; border-radius: 6px; border: 1px solid #243040; background: #0e1218; }
    .svc-ep:hover { border-color: #3a5070; background: #121820; }
    .svc-ep.up { border-color: #2a4a2a; color: var(--ok); }
    .svc-ep.down { border-color: #4a2a2a; color: var(--down); opacity: .85; }
    .svc-item .ports { color: var(--accent); }"""

if ".svc-row" not in text:
    text = text.replace(css_old, css_new, 1)

fn_old = """      function renderContainers(list) {
        if (!list.length) {
          $('containers').innerHTML = '<div class="svc-item"><span class="name">No running containers</span></div>';
          return;
        }
        $('containers').innerHTML = list.map((c) =>
          '<div class="svc-item"><span class="name">' + c.name + '</span>'
          + '<span>' + c.status + '</span>'
          + (c.ports ? '<span class="ports">' + c.ports + '</span>' : '')
          + '</div>'
        ).join('');
      }"""

fn_new = """      function escAttr(text) {
        return String(text == null ? '' : text)
          .replace(/&/g, '&amp;')
          .replace(/"/g, '&quot;')
          .replace(/</g, '&lt;');
      }

      function fmtSvcEndpoint(ep) {
        if (!ep) return '';
        const port = ep.port != null ? ':' + ep.port : '';
        const path = ep.path || '';
        let tail = '';
        if (ep.model) tail = ' · ' + ep.model;
        else if (ep.kind === 'gateway') tail = ' · stable front door';
        const cls = 'svc-ep' + (ep.up === false ? ' down' : ep.up ? ' up' : '');
        const href = ep.url || ep.local_url || '#';
        const label = ep.label ? ep.label + ' ' : '';
        return '<a class="' + cls + '" href="' + escAttr(href) + '" target="_blank" rel="noopener">'
          + escHtml((label + port + path + tail).trim()) + '</a>';
      }

      function renderContainers(list) {
        if (!list.length) {
          $('containers').innerHTML = '<div class="svc-item"><span class="name">No running containers</span></div>';
          return;
        }
        $('containers').innerHTML = list.map((c) => {
          const net = c.network && c.network !== 'default' && c.network !== 'bridge'
            ? ' · ' + c.network : '';
          const eps = (c.endpoints || []).map(fmtSvcEndpoint).join('');
          const legacyPorts = !eps.length && c.ports
            ? '<span class="ports">' + escHtml(c.ports) + '</span>' : '';
          return '<div class="svc-item">'
            + '<div class="svc-row">'
            + '<span class="name">' + escHtml(c.name) + '</span>'
            + '<span class="svc-meta">' + escHtml(c.status + net) + '</span>'
            + '</div>'
            + (eps ? '<div class="svc-eps">' + eps + '</div>' : legacyPorts)
            + '</div>';
        }).join('');
      }"""

if "function fmtSvcEndpoint" not in text:
    text = text.replace(fn_old, fn_new, 1)

path.write_text(text)
print("patched portal/index.html")
