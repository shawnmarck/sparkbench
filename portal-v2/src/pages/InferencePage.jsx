import { useEffect, useMemo, useRef, useState } from 'react'
import { EngineLogDock } from '../components/EngineLog.jsx'
import { Leaderboard } from '../components/Leaderboard.jsx'
import { LoadMeter } from '../components/LoadMeter.jsx'
import { getInferenceContext, setRecipeLifecycle } from '../lib/api.js'
import {
  benchMethodLabel,
  engineLabel,
  fmtCtx,
  fmtEtaS,
  fmtTokS,
  modalitiesLabel,
  shortName,
  stackLabel,
  visionCapLabel,
} from '../lib/fmt.js'

const FILTER_STORE = 'spark-v2-inference-filters-v2'
const MODES = ['text', 'vision', 'video']
const LIFE_ORDER = ['production', 'works', 'testing', 'draft', 'failed']
const GROUP_BYS = [
  ['model', 'Model'],
  ['family', 'Family'],
  ['engine', 'Engine'],
  ['life', 'Lifecycle'],
  ['flat', 'Flat'],
]
const VIEWS = [
  ['picker', 'Picker'],
  ['leaderboard', 'Leaderboard'],
]
const LIFE_RANK = { works: 0, production: 0, testing: 1, failed: 2, draft: 3 }
const MODE_RANK = { text: 0, vision: 1, video: 2 }

const KV_LABELS = {
  auto: 'auto',
  fp8: 'fp8 (vLLM)',
  q8_0: 'q8_0 (llama.cpp)',
  q4_0: 'q4_0 (llama.cpp)',
  f16: 'f16',
}

const COLS = [
  { key: 'recipe', label: 'Lab' },
  { key: 'modes', label: 'Modes' },
  { key: 'active', label: 'Active', num: true },
  { key: 'total', label: 'Total', num: true },
  { key: 'engine', label: 'Engine' },
  { key: 'life', label: 'Life' },
  { key: 'bench', label: 'Bench', num: true },
  { key: 'ctx', label: 'Context', num: true },
  { key: 'fits', label: 'Size', num: true },
]

function readFilters() {
  const empty = {
    q: '',
    life: 'all',
    engines: [],
    switchable: true,
    modes: [],
    sort: { key: 'life', dir: 'asc' },
    groupBy: 'model',
    open: null,
    view: 'picker',
  }
  try {
    const raw = JSON.parse(window.localStorage.getItem(FILTER_STORE) || '{}')
    return {
      q: typeof raw.q === 'string' ? raw.q : '',
      life: typeof raw.life === 'string' ? raw.life : 'all',
      engines: Array.isArray(raw.engines) ? raw.engines.filter((e) => typeof e === 'string') : [],
      switchable: raw.switchable !== false,
      modes: Array.isArray(raw.modes) ? raw.modes.filter((m) => MODES.includes(m)) : [],
      sort: raw.sort && typeof raw.sort.key === 'string'
        ? { key: raw.sort.key, dir: raw.sort.dir === 'desc' ? 'desc' : 'asc' }
        : empty.sort,
      groupBy: GROUP_BYS.some(([k]) => k === raw.groupBy) ? raw.groupBy : 'model',
      open: Array.isArray(raw.open) ? new Set(raw.open.filter((k) => typeof k === 'string')) : null,
      view: raw.view === 'leaderboard' ? 'leaderboard' : 'picker',
    }
  } catch {
    return empty
  }
}

function kvOptionsForEngine(engine) {
  if (engine === 'eugr') return ['auto', 'fp8']
  if (engine === 'llamacpp') return ['auto', 'q8_0', 'q4_0', 'f16']
  if (engine === 'ds4' || engine === 'sparkinfer') return ['auto']
  if (engine === 'sglang' || engine === 'flashnext' || engine === 'tensorfold') return ['auto', 'fp8']
  return ['auto', 'fp8', 'q8_0', 'q4_0']
}

function ident(r) {
  const idn = r.identity || {}
  const inv = String(r.inventory_path || r.catalog_id || '')
  const slash = inv.indexOf('/')
  const labFallback = slash >= 0 ? inv.slice(0, slash) : 'other'
  const slugFallback = slash >= 0 ? inv.slice(slash + 1) : inv
  return {
    family: idn.family || 'Other',
    lab: idn.lab || labFallback || 'other',
    version: idn.version || '—',
    variant: idn.variant || slugFallback || 'Base',
    quant: idn.quant || '—',
    param_b: idn.param_b,
    param_active_b: idn.param_active_b,
  }
}

function fmtParam(n) {
  const v = Number(n)
  if (!Number.isFinite(v)) return '—'
  if (v >= 10) return `${Math.round(v)}B`
  return `${String(v.toFixed(1)).replace(/\.0$/, '')}B`
}

function specMarks(r) {
  const tags = new Set((r.tags || []).map((t) => String(t).toLowerCase()))
  const marks = []
  if (r.speculative?.method === 'dflash' || tags.has('dflash')) marks.push('dflash')
  if (r.mtp || r.speculative?.method === 'mtp' || tags.has('mtp')) marks.push('mtp')
  return marks
}

function sortVal(r, key) {
  const idn = ident(r)
  if (key === 'modes') {
    const modes = r.input_modes || ['text']
    return Math.max(...modes.map((m) => MODE_RANK[m] ?? 0))
  }
  if (key === 'active') {
    const n = Number(idn.param_active_b)
    return Number.isFinite(n) ? n : null
  }
  if (key === 'total') {
    const n = Number(idn.param_b)
    return Number.isFinite(n) ? n : null
  }
  if (key === 'engine') return String(r.engine || '')
  if (key === 'life') return LIFE_RANK[r.lifecycle || 'works'] ?? 9
  if (key === 'bench') {
    const n = Number(r.tok_s)
    return Number.isFinite(n) ? n : null
  }
  if (key === 'ctx') {
    const n = Number(r.context?.default)
    return Number.isFinite(n) ? n : null
  }
  if (key === 'fits') {
    const n = Number(r.context?.weight_gb)
    return Number.isFinite(n) ? n : null
  }
  return String(idn.lab || r.name || r.id || '').toLowerCase()
}

function missing(v) {
  return v == null || (typeof v === 'number' && !Number.isFinite(v))
}

function cmpRows(a, b, sort) {
  const av = sortVal(a, sort.key)
  const bv = sortVal(b, sort.key)
  if (missing(av) && missing(bv)) return String(a.id || '').localeCompare(String(b.id || ''))
  if (missing(av)) return 1
  if (missing(bv)) return -1
  let n = 0
  if (typeof av === 'number' && typeof bv === 'number') n = av - bv
  else n = String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: 'base' })
  if (n === 0) {
    const ab = Number(a.tok_s)
    const bb = Number(b.tok_s)
    n = (Number.isFinite(ab) ? ab : -1) - (Number.isFinite(bb) ? bb : -1)
  }
  if (n === 0) n = String(a.name || a.id || '').localeCompare(String(b.name || b.id || ''))
  return sort.dir === 'desc' ? -n : n
}

function modelLabel(r) {
  const idn = ident(r)
  const fam = idn.family || ''
  const ver = idn.version && idn.version !== '—' ? idn.version : fam
  const head = fam && !ver.toLowerCase().startsWith(fam.toLowerCase()) ? `${fam} ${ver}` : ver
  return `${head || 'Other'} · ${idn.variant || 'Base'}`
}

function groupLabels(r, groupBy) {
  if (groupBy === 'engine') return [engineLabel(r.engine) || 'other']
  if (groupBy === 'life') return [r.lifecycle || 'works']
  if (groupBy === 'flat') return []
  const idn = ident(r)
  return [idn.family, idn.version, idn.variant, idn.quant]
}

function buildTree(rows, groupBy = 'family') {
  const root = new Map()
  const paths = new Map()
  if (groupBy === 'model') {
    const byModel = new Map()
    for (const r of rows) {
      const label = modelLabel(r)
      if (!byModel.has(label)) byModel.set(label, [])
      byModel.get(label).push(r)
    }
    for (const [label, group] of byModel) {
      const node = { key: label, label, depth: 0, kids: new Map(), recipes: [] }
      const byQuant = new Map()
      for (const r of group) {
        const q = ident(r).quant || '—'
        if (!byQuant.has(q)) byQuant.set(q, [])
        byQuant.get(q).push(r)
      }
      if (byQuant.size > 1) {
        for (const [q, grp] of byQuant) {
          const qkey = `${label}\0${q}`
          node.kids.set(q, { key: qkey, label: q, depth: 1, kids: new Map(), recipes: grp })
          for (const r of grp) paths.set(r.id, [label, qkey])
        }
      } else {
        node.recipes = group
        for (const r of group) paths.set(r.id, [label])
      }
      root.set(label, node)
    }
    return { tree: root, paths }
  }
  for (const r of rows) {
    const labels = groupLabels(r, groupBy)
    if (!labels.length) continue
    let level = root
    let key = ''
    const path = []
    labels.forEach((label, depth) => {
      key = key ? `${key}\0${label}` : label
      path.push(key)
      if (!level.has(label)) {
        level.set(label, { key, label, depth, kids: new Map(), recipes: [] })
      }
      const node = level.get(label)
      if (depth === labels.length - 1) node.recipes.push(r)
      level = node.kids
    })
    paths.set(r.id, path)
  }
  return { tree: root, paths }
}

function collect(node) {
  const out = [...node.recipes]
  for (const kid of node.kids.values()) out.push(...collect(kid))
  return out
}

function extreme(recipes, sort) {
  const vals = recipes.map((r) => sortVal(r, sort.key)).filter((v) => !missing(v))
  if (!vals.length) return null
  if (typeof vals[0] === 'number') {
    return sort.dir === 'desc' ? Math.max(...vals) : Math.min(...vals)
  }
  const sorted = [...vals].sort((a, b) => String(a).localeCompare(String(b), undefined, { numeric: true }))
  return sort.dir === 'desc' ? sorted[sorted.length - 1] : sorted[0]
}

function cmpNodes(a, b, sort) {
  const byLabel = a.label.localeCompare(b.label, undefined, { numeric: true, sensitivity: 'base' })
  if (sort.key === 'recipe') return sort.dir === 'desc' ? -byLabel : byLabel
  const av = extreme(collect(a), sort)
  const bv = extreme(collect(b), sort)
  if (missing(av) && missing(bv)) return byLabel
  if (missing(av)) return 1
  if (missing(bv)) return -1
  let n = 0
  if (typeof av === 'number' && typeof bv === 'number') n = av - bv
  else n = String(av).localeCompare(String(bv), undefined, { numeric: true })
  if (sort.dir === 'desc') n = -n
  return n || byLabel
}

function flatten(map, sort, open) {
  const nodes = [...map.values()].sort((a, b) => cmpNodes(a, b, sort))
  const out = []
  for (const node of nodes) {
    const all = collect(node)
    const count = all.length
    const benchVals = all.map((r) => Number(r.tok_s)).filter((v) => Number.isFinite(v))
    const best = benchVals.length ? Math.max(...benchVals) : null
    const mix = {}
    for (const r of all) {
      const lc = r.lifecycle || 'works'
      mix[lc] = (mix[lc] || 0) + 1
    }
    const isOpen = open.has(node.key)
    out.push({ type: 'group', node, count, isOpen, best, mix })
    if (!isOpen) continue
    if (node.recipes.length) {
      const recipes = [...node.recipes].sort((a, b) => cmpRows(a, b, sort))
      for (const r of recipes) out.push({ type: 'recipe', r, depth: node.depth + 1 })
    }
    out.push(...flatten(node.kids, sort, open))
  }
  return out
}

function allKeys(map, into = []) {
  for (const node of map.values()) {
    into.push(node.key)
    allKeys(node.kids, into)
  }
  return into
}

function launchPayload(launch) {
  if (!launch) return {}
  const out = {}
  const ctx = Number(launch.ctx)
  if (Number.isFinite(ctx) && ctx > 0) out.ctx = ctx
  if (launch.kv && launch.kv !== 'auto') out.kv = launch.kv
  if (launch.preset) out.preset = launch.preset
  return out
}

function haystack(r) {
  const idn = ident(r)
  return [
    r.name, r.id, r.engine, r.tier, r.lifecycle, r.notes, r.inventory_path,
    idn.family, idn.lab, idn.version, idn.variant, idn.quant,
    idn.param_b, idn.param_active_b,
    ...(r.tags || []),
    ...(r.input_modes || []),
  ].filter((v) => v != null && v !== '').join(' ').toLowerCase()
}

export function InferencePage({ live, actions }) {
  const boot = useState(readFilters)[0]
  const active = live.inference?.active
  const loading = live.inference?.loading
  const activeId = active?.id
  const [q, setQ] = useState(boot.q)
  const [life, setLife] = useState(boot.life)
  const [enginesOn, setEnginesOn] = useState(boot.engines)
  const [switchable, setSwitchable] = useState(boot.switchable)
  const [modesOn, setModesOn] = useState(boot.modes)
  const [picked, setPicked] = useState(null)
  const [sort, setSort] = useState(boot.sort)
  const [groupBy, setGroupBy] = useState(boot.groupBy)
  const [view, setView] = useState(boot.view)
  const [open, setOpen] = useState(boot.open)
  const qRef = useRef(null)
  const wrapRef = useRef(null)
  const [plan, setPlan] = useState(null)
  const [launch, setLaunch] = useState({ preset: 'default', ctx: '', kv: 'auto' })
  const [lifeMsg, setLifeMsg] = useState(null)
  const [lifeBusy, setLifeBusy] = useState(false)

  const recipes = live.recipes || []
  const total = recipes.length

  useEffect(() => {
    try {
      window.localStorage.setItem(FILTER_STORE, JSON.stringify({
        q, life, engines: enginesOn, switchable, modes: modesOn, sort, groupBy,
        open: open ? [...open] : null,
        view,
      }))
    } catch { /* ignore */ }
  }, [q, life, enginesOn, switchable, modesOn, sort, groupBy, open, view])

  const engineChoices = useMemo(() => {
    const set = new Set(recipes.map((r) => r.engine).filter(Boolean))
    return [...set].sort()
  }, [recipes])

  const lifeChoices = useMemo(() => {
    const set = new Set(['production', 'works', 'testing', 'draft', 'failed'])
    for (const r of recipes) set.add(r.lifecycle || 'works')
    return [...set]
  }, [recipes])

  const rows = useMemo(() => {
    const query = q.trim().toLowerCase()
    return recipes.filter((r) => {
      if (switchable && r.switchable === false) return false
      if (life !== 'all' && (r.lifecycle || 'works') !== life) return false
      if (enginesOn.length && !enginesOn.includes(r.engine)) return false
      if (modesOn.length && !modesOn.every((m) => (r.input_modes || ['text']).includes(m))) return false
      if (!query) return true
      return haystack(r).includes(query)
    })
  }, [recipes, q, life, enginesOn, switchable, modesOn])

  const { tree, paths } = useMemo(() => buildTree(rows, groupBy), [rows, groupBy])
  const treeKeys = useMemo(() => (groupBy === 'flat' ? [] : allKeys(tree)), [tree, groupBy])
  const branchKeysFor = (r) => (r ? paths.get(r.id) || [] : [])

  useEffect(() => {
    function onKey(e) {
      if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return
      const t = e.target
      const tag = t?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || t?.isContentEditable) return
      e.preventDefault()
      qRef.current?.focus()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (!picked && activeId) {
      const hit = recipes.find((r) => r.id === activeId)
      if (hit) setPicked(hit)
    }
  }, [activeId, recipes, picked])

  const selected = picked || recipes.find((r) => r.id === activeId) || rows[0] || recipes[0]
  const inspectingOther = selected && activeId && selected.id !== activeId
  const searching = q.trim().length > 0
  const shownOpen = useMemo(() => {
    if (searching) return new Set(treeKeys)
    if (open) return open
    return new Set(selected ? paths.get(selected.id) || [] : [])
  }, [searching, treeKeys, open, selected, paths])

  const flat = useMemo(
    () => (groupBy === 'flat'
      ? rows.map((r) => ({ type: 'recipe', r, depth: 0 }))
      : flatten(tree, sort, shownOpen)),
    [groupBy, rows, tree, sort, shownOpen],
  )
  const maxBench = useMemo(() => {
    const vals = rows.map((r) => Number(r.tok_s)).filter((v) => Number.isFinite(v))
    return vals.length ? Math.max(...vals) : 0
  }, [rows])
  const activeHidden = Boolean(activeId) && !rows.some((r) => r.id === activeId)

  useEffect(() => {
    if (!selected?.id) {
      setPlan(null)
      return
    }
    let cancelled = false
    getInferenceContext(selected.id)
      .then((d) => {
        if (cancelled) return
        setPlan(d)
        const c = d.context || {}
        const ctx = c.effective ?? c.default ?? ''
        const kv = c.kv_effective || c.kv_default || 'auto'
        const match = (c.presets || []).find((p) => p.ctx === ctx && (!p.kv || p.kv === kv || kv === 'auto'))
        setLaunch({
          preset: match?.id || 'default',
          ctx,
          kv,
        })
      })
      .catch(() => {
        if (!cancelled) setPlan(null)
      })
    return () => {
      cancelled = true
    }
  }, [selected?.id])

  const ctx = plan?.context || {}
  const planReady = plan?.profile === selected?.id
  const presets = ctx.presets || []
  const kvChoices = (ctx.kv_tested && ctx.kv_tested.length)
    ? ctx.kv_tested
    : kvOptionsForEngine(plan?.engine || selected?.engine)
  const liveCtx = Number(ctx.effective ?? ctx.default)
  const liveKv = ctx.kv_effective || ctx.kv_default || 'auto'
  const dirty = planReady && (
    Number(launch.ctx) !== liveCtx
    || (launch.kv || 'auto') !== liveKv
  )
  const isLive = selected && selected.id === activeId
  const canServe = Boolean(selected) && planReady && selected.switchable !== false && (inspectingOther || (isLive && dirty))
  const filtersDirty = Boolean(q.trim()) || life !== 'all' || enginesOn.length > 0 || !switchable || modesOn.length > 0
  const selectedIdent = selected ? ident(selected) : null

  function toggleSort(key) {
    setSort((prev) => (
      prev.key === key
        ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: key === 'bench' || key === 'ctx' || key === 'active' || key === 'total' || key === 'fits' ? 'desc' : 'asc' }
    ))
  }

  function toggleChip(setList, value) {
    setList((prev) => (prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value]))
  }

  function toggleGroup(key) {
    setOpen((prev) => {
      const next = new Set(prev || shownOpen)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function pickRecipe(r) {
    setPicked(r)
    setOpen((prev) => {
      const next = new Set(prev || (selected ? branchKeysFor(selected) : []))
      for (const key of branchKeysFor(r)) next.add(key)
      return next
    })
  }

  function revealActive() {
    clearFilters()
    const hit = recipes.find((r) => r.id === activeId)
    if (hit) pickRecipe(hit)
  }

  function inspectRecipe(r) {
    setPicked(r)
    setView('picker')
  }

  function movePick(delta) {
    const list = flat.filter((f) => f.type === 'recipe')
    if (!list.length) return
    const idx = list.findIndex((f) => f.r.id === selected?.id)
    let next
    if (idx === -1) next = delta > 0 ? 0 : list.length - 1
    else next = Math.max(0, Math.min(list.length - 1, idx + delta))
    pickRecipe(list[next].r)
    requestAnimationFrame(() => {
      const el = wrapRef.current?.querySelector(`[data-r="${CSS.escape(list[next].r.id)}"]`)
      el?.scrollIntoView({ block: 'nearest' })
    })
  }

  function onPickerKey(e) {
    const tag = e.target?.tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      movePick(e.key === 'ArrowDown' ? 1 : -1)
    } else if (e.key === 'Enter' && tag !== 'BUTTON') {
      if (selected && selected.id !== activeId) {
        e.preventDefault()
        serveSelected(selected)
      }
    }
  }

  function clearFilters() {
    setQ('')
    setLife('all')
    setEnginesOn([])
    setSwitchable(true)
    setModesOn([])
  }

  function pickPreset(p) {
    setLaunch({ preset: p.id, ctx: p.ctx, kv: p.kv || 'auto' })
  }

  function serveSelected(recipe = selected) {
    if (!recipe) return
    actions?.askSwitch(recipe, launchPayload(recipe.id === selected?.id ? launch : null))
  }

  async function cycleLife(kind) {
    if (!selected?.id) return
    const id = selected.id
    const spec = {
      testing: { title: 'Mark testing', body: `Move ${id} to testing?`, confirmLabel: 'Mark testing' },
      promote: { title: 'Promote recipe', body: `Promote ${id} to production?`, confirmLabel: 'Promote' },
      discard: { title: 'Discard draft', body: `Discard the draft ${id}?`, confirmLabel: 'Discard draft', danger: true },
    }[kind]
    if (!spec) return
    actions?.askConfirm?.({
      ...spec,
      run: async () => {
        setLifeBusy(true)
        setLifeMsg(null)
        try {
          await setRecipeLifecycle(kind, id)
          setLifeMsg({ ok: true, text: `${kind} ${id}` })
          live.refresh?.()
        } catch (err) {
          setLifeMsg({ ok: false, text: err.message || 'lifecycle failed' })
        } finally {
          setLifeBusy(false)
        }
      },
    })
  }

  const lc = selected?.lifecycle || 'works'
  const showDiscard = lc === 'draft'
  const showTesting = lc === 'draft' || lc === 'works'
  const showPromote = lc === 'testing' || lc === 'draft'
  const recLines = (ctx.recommendations || [])
    .map((r) => `${r.label}: ${fmtCtx(r.ctx)} — ${r.reason}`)
    .join(' ')
  const mem = ctx.mem_avail_gb != null && ctx.weight_gb != null
    ? ` ~${Math.round(ctx.weight_gb)} GB weights · ${ctx.mem_avail_gb} GB free.`
    : ''
  const ds4Hint = plan?.engine === 'ds4'
    ? ' ds4: ship ctx 32k (OOM-safe); cap 128k.'
    : ''

  return (
    <div className="inf-page">
      <div className="inf-scroll">
        <div className="page-head inf-head">
          <div>
            <h1>Inference</h1>
            <p>What is on the GPU, then pick another recipe. Switch evicts the current one.</p>
          </div>
          <div className="view-toggle" role="group" aria-label="Inference view">
            {VIEWS.map(([key, label]) => (
              <button
                key={key}
                type="button"
                className={`chip${view === key ? ' on' : ''}`}
                aria-pressed={view === key}
                onClick={() => setView(key)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <section className={`card serve-now${active ? '' : ' idle'}`}>
          <div className="serve-now-main">
            <h2>Now serving</h2>
            {active ? (
              <>
                <p className="hero-name">{active.name || active.id}</p>
                <p className="hero-meta">
                  {stackLabel(active.engine)}
                  {active.ready ? ' · ready' : active.starting ? ' · starting' : ' · not ready'}
                  {` · ${fmtCtx(active.context?.effective || active.context?.default)} context`}
                  {modalitiesLabel(active.multimodal) ? ` · ${modalitiesLabel(active.multimodal)}` : ''}
                  {active.tok_s != null ? ` · bench ${fmtTokS(active.tok_s)} tok/s` : ''}
                </p>
                {loading && !active.ready ? <LoadMeter loading={loading} /> : null}
              </>
            ) : loading ? (
              <>
                <p className="hero-name">{loading.name || loading.profile || 'Loading'}</p>
                <LoadMeter loading={loading} />
              </>
            ) : (
              <p className="hero-name muted">Idle</p>
            )}
          </div>
          <button
            type="button"
            className="btn danger"
            disabled={!activeId}
            onClick={() => actions?.askStop()}
          >
            Stop
          </button>
        </section>
        {actions?.flash ? <p className={actions.flash.ok ? 'flash ok' : 'flash err'}>{actions.flash.text}</p> : null}

        {view === 'leaderboard' ? (
          <Leaderboard recipes={recipes} onInspect={inspectRecipe} />
        ) : (
        <div className="grid inf-grid">
          <section className="card">
            <h2>Pick a recipe · {rows.length} of {total}</h2>
            <div className="toolbar tight">
              <input
                ref={qRef}
                className="field grow"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Escape') setQ('') }}
                placeholder="Filter by family, lab, quant…  ( / )"
              />
              <select className="field" value={life} onChange={(e) => setLife(e.target.value)}>
                <option value="all">All lifecycle</option>
                {lifeChoices.map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
              {filtersDirty ? (
                <button type="button" className="btn" onClick={clearFilters}>Clear</button>
              ) : null}
              {groupBy !== 'flat' ? (
                <>
                  <button type="button" className="btn" onClick={() => setOpen(new Set(treeKeys))}>Expand</button>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => setOpen(new Set(selected ? branchKeysFor(selected) : []))}
                  >
                    Collapse
                  </button>
                </>
              ) : null}
            </div>
            <div className="chip-row">
              <button
                type="button"
                className={`chip${switchable ? ' on' : ''}`}
                onClick={() => setSwitchable((v) => !v)}
              >
                Switchable
              </button>
              {engineChoices.map((engine) => (
                <button
                  key={engine}
                  type="button"
                  className={`chip${enginesOn.includes(engine) ? ' on' : ''}`}
                  onClick={() => toggleChip(setEnginesOn, engine)}
                >
                  {engineLabel(engine)}
                </button>
              ))}
              {MODES.map((mode) => (
                <button
                  key={mode}
                  type="button"
                  className={`chip${modesOn.includes(mode) ? ' on' : ''}`}
                  onClick={() => toggleChip(setModesOn, mode)}
                >
                  {mode}
                </button>
              ))}
              <span className="groupby" role="group" aria-label="Group recipes by">
                <span className="gb-label">Group</span>
                {GROUP_BYS.map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    className={`chip gb${groupBy === key ? ' on' : ''}`}
                    onClick={() => setGroupBy(key)}
                  >
                    {label}
                  </button>
                ))}
              </span>
            </div>
            <div
              ref={wrapRef}
              className="table-wrap pick-wrap"
              tabIndex={0}
              role="region"
              aria-label="Recipe picker — arrow keys move, Enter serves"
              onKeyDown={onPickerKey}
            >
              <table className="pick-table">
                <thead>
                  <tr>
                    {COLS.map((col) => {
                      const on = sort.key === col.key
                      return (
                        <th
                          key={col.key}
                          className={col.num ? 'num' : ''}
                          aria-sort={on ? (sort.dir === 'desc' ? 'descending' : 'ascending') : 'none'}
                        >
                          <button
                            type="button"
                            className={`th-sort${on ? ' on' : ''}`}
                            onClick={() => toggleSort(col.key)}
                          >
                            {col.label}
                            {on ? (sort.dir === 'desc' ? ' ↓' : ' ↑') : ''}
                          </button>
                        </th>
                      )
                    })}
                  </tr>
                </thead>
                <tbody>
                  {activeHidden ? (
                    <tr className="live-anchor" onClick={revealActive} title="Clear filters and show the serving recipe">
                      <td colSpan={COLS.length}>
                        <span className="live-tag">live</span>
                        {active?.name || activeId} is serving · hidden by filter
                        <button
                          type="button"
                          className="btn"
                          onClick={(e) => { e.stopPropagation(); revealActive() }}
                        >
                          Show
                        </button>
                      </td>
                    </tr>
                  ) : null}
                  {flat.length ? flat.map((row) => {
                    if (row.type === 'group') {
                      const { node, count, isOpen } = row
                      return (
                        <tr key={node.key} className={`pick-group depth-${node.depth}`}>
                          <td colSpan={COLS.length}>
                            <button
                              type="button"
                              className="group-btn"
                              style={{ paddingLeft: `${node.depth * 0.85}rem` }}
                              aria-expanded={isOpen}
                              onClick={() => toggleGroup(node.key)}
                            >
                              <span className="caret">{isOpen ? '▾' : '▸'}</span>
                              {node.label}
                              <span className="pick-count">{count}</span>
                              {row.best != null ? <span className="grp-best">· {fmtTokS(row.best)} tok/s</span> : null}
                              <span className="grp-lives">
                                {LIFE_ORDER.filter((lc) => row.mix[lc]).map((lc) => (
                                  <span key={lc} className={`life-dot ${lc}`} title={`${row.mix[lc]} ${lc}`} />
                                ))}
                              </span>
                            </button>
                          </td>
                        </tr>
                      )
                    }
                    const r = row.r
                    const marks = specMarks(r)
                    const lc = r.lifecycle || 'works'
                    const tok = Number(r.tok_s)
                    const benchPct = Number.isFinite(tok) && maxBench > 0 ? (tok / maxBench) * 100 : 0
                    const weight = Number(r.context?.weight_gb)
                    const freeGb = Number(r.context?.mem_avail_gb)
                    // Only llamacpp GGUF and eugr weight dirs report the artifact that
                    // actually loads; other engines sum the whole model directory, so a
                    // fits verdict there would be misleading.
                    const engineScoped = r.engine === 'llamacpp' || r.engine === 'eugr'
                    const fitTone = engineScoped && Number.isFinite(weight) && Number.isFinite(freeGb) && freeGb > 0
                      ? (weight <= freeGb * 0.8 ? 'ok' : weight <= freeGb ? 'warn' : 'bad')
                      : ''
                    return (
                      <tr
                        key={r.id}
                        data-r={r.id}
                        className={`${r.id === activeId ? 'active' : ''} ${selected?.id === r.id ? 'picked' : ''}`}
                        onClick={() => pickRecipe(r)}
                        onDoubleClick={() => r.id !== activeId && serveSelected(r)}
                      >
                        <td title={r.id} style={{ paddingLeft: `${0.6 + row.depth * 0.85}rem` }}>
                          <div className="pid">
                            {ident(r).lab}
                            {r.id === activeId ? <span className="live-tag">live</span> : null}
                            {marks.map((mark) => <span key={mark} className="mod-tag">{mark}</span>)}
                          </div>
                          <div className="pname">{r.name || r.id}</div>
                        </td>
                        <td>{(r.input_modes || ['text']).join(' · ')}</td>
                        <td className="num">{fmtParam(ident(r).param_active_b)}</td>
                        <td className="num">{fmtParam(ident(r).param_b)}</td>
                        <td>{engineLabel(r.engine)}</td>
                        <td><span className={`life-dot ${lc}`} />{lc}</td>
                        <td className="num bench-cell">
                          {Number.isFinite(tok) ? (
                            <>
                              <span className="bench-bar" style={{ width: `${Math.max(4, benchPct)}%` }} />
                              <span className="bench-num">{fmtTokS(r.tok_s)}</span>
                            </>
                          ) : fmtTokS(r.tok_s)}
                        </td>
                        <td className="num">{fmtCtx(r.context?.default)}</td>
                        <td
                          className="num fits-cell"
                          title={Number.isFinite(weight)
                            ? (engineScoped
                              ? `engine weights ~${Math.round(weight)} GB · ${Number.isFinite(freeGb) ? `${Math.round(freeGb)} GB free` : 'free unknown'}${fitTone === 'bad' ? ' — likely will not fit' : ''}`
                              : `whole model dir ~${Math.round(weight)} GB (all formats) · ${Number.isFinite(freeGb) ? `${Math.round(freeGb)} GB free` : 'free unknown'}`)
                            : 'weight unknown'}
                        >
                          {Number.isFinite(weight) ? (
                            <>
                              <span className={`fit-dot ${fitTone}`} />
                              {`${Math.round(weight)} GB`}
                            </>
                          ) : '—'}
                          {r.id !== activeId ? (
                            <button
                              type="button"
                              className="row-serve"
                              title="Serve this recipe (or double-click the row)"
                              onClick={(e) => { e.stopPropagation(); serveSelected(r) }}
                            >
                              Serve ▸
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    )
                  }) : (
                    <tr>
                      <td className="pick-empty" colSpan={COLS.length}>
                        Nothing matches.
                        {filtersDirty ? (
                          <button type="button" className="btn" onClick={clearFilters}>Clear filters</button>
                        ) : null}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card">
            <h2>{inspectingOther ? 'Inspecting' : 'This recipe'}</h2>
            {selected ? (
              <>
                {inspectingOther ? (
                  <p className="flash warn">
                    Not on the GPU. {shortName(active?.name, activeId)} is still serving.
                  </p>
                ) : activeId ? (
                  <p className="flash ok">This is what is serving now.</p>
                ) : null}
                <p className="hero-name">{selected.name || selected.id}</p>
                {selectedIdent ? (
                  <p className="ident-line">
                    {selectedIdent.family} · {selectedIdent.version} · {selectedIdent.variant} · {selectedIdent.quant} · {selectedIdent.lab}
                    {selectedIdent.param_active_b != null && selectedIdent.param_b != null
                      && selectedIdent.param_active_b !== selectedIdent.param_b
                      ? ` · ${fmtParam(selectedIdent.param_active_b)} active / ${fmtParam(selectedIdent.param_b)} total`
                      : selectedIdent.param_b != null
                        ? ` · ${fmtParam(selectedIdent.param_b)}`
                        : ''}
                  </p>
                ) : null}
                <dl className="serve-facts">
                  <div>
                    <dt>Engine</dt>
                    <dd>{stackLabel(selected.engine)}</dd>
                  </div>
                  <div>
                    <dt>Input modes</dt>
                    <dd>{(selected.input_modes || ['text']).join(' · ')}</dd>
                  </div>
                  {selected.multimodal ? (
                    <div title={selected.multimodal.vision ? 'This recipe loads the vision tower.' : 'This recipe is language-only. Vision tower stays on disk.'}>
                      <dt>Modalities</dt>
                      <dd>{modalitiesLabel(selected.multimodal)}</dd>
                    </div>
                  ) : null}
                  {selected.multimodal?.vision ? (
                    <div className="vision" title="Cookbook image caps. Live image-turn stats show on Home when this profile is serving.">
                      <dt>Vision</dt>
                      <dd>{visionCapLabel(selected.multimodal) || 'on'}</dd>
                    </div>
                  ) : null}
                  <div>
                    <dt>Lifecycle</dt>
                    <dd>{selected.lifecycle || 'works'}</dd>
                  </div>
                  {selected.tier ? (
                    <div>
                      <dt>Tier</dt>
                      <dd>{selected.tier}</dd>
                    </div>
                  ) : null}
                  <div>
                    <dt>Typical load</dt>
                    <dd>
                      {fmtEtaS(selected.load?.typical_s)}
                      {selected.load?.source === 'observed' || selected.load?.source === 'engine'
                        ? ` · last ${fmtEtaS(selected.load.last_s)}`
                        : ' · estimate'}
                    </dd>
                  </div>
                  <div>
                    <dt>Bench speed</dt>
                    <dd>{fmtTokS(selected.tok_s)} tok/s</dd>
                  </div>
                  <div>
                    <dt>Bench method</dt>
                    <dd>{benchMethodLabel(selected.tok_s_method)}</dd>
                  </div>
                </dl>
                {selected.notes ? <p className="notes">{selected.notes}</p> : null}

                <div className="ctx-panel">
                  <div className="ctx-head">
                    <span>Context window</span>
                    <em>
                      {ctx.native ? `native ${fmtCtx(ctx.native)}` : 'native unknown'}
                      {ctx.default ? ` · default ${fmtCtx(ctx.default)}` : ''}
                    </em>
                  </div>
                  <div className="ctx-presets">
                    {presets.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        className={`ctx-preset${launch.preset === p.id ? ' on' : ''}${p.source === 'ctx_ladder' ? ' tested' : ''}`}
                        title={`${p.label} · ${fmtCtx(p.ctx)}${p.kv && p.kv !== 'auto' ? ` kv ${p.kv}` : ''}`}
                        onClick={() => pickPreset(p)}
                      >
                        {p.label} {fmtCtx(p.ctx)}
                      </button>
                    ))}
                  </div>
                  <div className="ctx-row">
                    <label>
                      Max context
                      <input
                        className="field"
                        type="number"
                        min="4096"
                        step="1024"
                        max={plan?.engine === 'ds4' ? '131072' : undefined}
                        placeholder={plan?.engine === 'ds4' ? '32768' : '65536'}
                        value={launch.ctx}
                        onChange={(e) => setLaunch((prev) => ({ ...prev, ctx: e.target.value, preset: null }))}
                      />
                    </label>
                    <label>
                      KV cache
                      <select
                        className="field"
                        value={launch.kv}
                        disabled={plan?.engine === 'ds4'}
                        onChange={(e) => setLaunch((prev) => ({ ...prev, kv: e.target.value }))}
                      >
                        {kvChoices.map((k) => (
                          <option key={k} value={k}>
                            {plan?.engine === 'ds4' && k === 'auto' ? 'auto (ds4 packed FP8/FP4)' : (KV_LABELS[k] || k)}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <p className="ctx-hint">{recLines}{mem}{ds4Hint}</p>
                  {selected?.switchable === false ? (
                    <p className="ctx-hint">Not switchable — add it to the production index to Serve.</p>
                  ) : null}
                </div>

                <div className="toolbar tight" style={{ marginTop: '.85rem' }}>
                  <button
                    type="button"
                    className="btn primary"
                    disabled={!canServe}
                    onClick={() => serveSelected(selected)}
                  >
                    {isLive ? (dirty ? 'Relaunch with these settings' : 'Running with these settings') : 'Serve this recipe'}
                  </button>
                </div>
                {(showTesting || showPromote || showDiscard) ? (
                  <details className="life-box">
                    <summary>Lifecycle</summary>
                    <div className="toolbar tight">
                      {showTesting ? (
                        <button type="button" className="btn" disabled={lifeBusy} onClick={() => cycleLife('testing')}>
                          Mark testing
                        </button>
                      ) : null}
                      {showPromote ? (
                        <button type="button" className="btn" disabled={lifeBusy} onClick={() => cycleLife('promote')}>
                          Promote
                        </button>
                      ) : null}
                      {showDiscard ? (
                        <button type="button" className="btn danger" disabled={lifeBusy} onClick={() => cycleLife('discard')}>
                          Discard draft
                        </button>
                      ) : null}
                    </div>
                  </details>
                ) : null}
                {lifeMsg ? <p className={lifeMsg.ok ? 'flash ok' : 'flash err'}>{lifeMsg.text}</p> : null}
              </>
            ) : (
              <p className="muted">No recipe selected.</p>
            )}
          </section>
        </div>
        )}
      </div>
      <EngineLogDock />
    </div>
  )
}
