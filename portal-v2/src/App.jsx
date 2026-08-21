import { useState } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AppShell } from './components/AppShell.jsx'
import { CommandPalette } from './components/CommandPalette.jsx'
import { ConfirmDialog } from './components/ConfirmDialog.jsx'
import { LogPage } from './components/EngineLog.jsx'
import { stopInference, switchProfile } from './lib/api.js'
import { useLive } from './lib/live.js'
import { fmtCtx, shortName } from './lib/fmt.js'
import { HomePage } from './pages/HomePage.jsx'
import { InferencePage } from './pages/InferencePage.jsx'
import { ExplorePage } from './pages/ExplorePage.jsx'
import { BenchmasterPage } from './pages/BenchmasterPage.jsx'
import { ModelsPage } from './pages/ModelsPage.jsx'
import { HardwarePage } from './pages/HardwarePage.jsx'
import { ActivityPage } from './pages/ActivityPage.jsx'

function launchNote(launch) {
  if (!launch) return ''
  const bits = []
  if (launch.ctx) bits.push(`${fmtCtx(launch.ctx)} context`)
  if (launch.kv) bits.push(`kv ${launch.kv}`)
  return bits.length ? ` ${bits.join(' · ')}.` : ''
}

export default function App() {
  const live = useLive()
  const loc = useLocation()
  const [confirm, setConfirm] = useState(null)
  const [busy, setBusy] = useState(false)
  const [flash, setFlash] = useState(null)
  const active = live.inference?.active

  function askSwitch(recipe, launch) {
    if (!recipe) return
    const relaunch = recipe.id === active?.id
    if (relaunch && !launch) return
    const evict = shortName(active?.name, active?.id) || 'the current profile'
    setConfirm({
      kind: 'switch',
      recipe,
      launch,
      title: relaunch ? 'Relaunch inference' : 'Switch inference',
      body: relaunch
        ? `Reload ${recipe.name || recipe.id} with new context settings.${launchNote(launch)} GPU goes offline while it comes back.`
        : `This evicts ${evict} and loads ${recipe.name || recipe.id}.${launchNote(launch)} One GPU engine at a time.`,
      confirmLabel: recipe.tier === 'heavy' ? 'Confirm heavy switch' : (relaunch ? 'Relaunch now' : 'Switch now'),
      danger: true,
    })
  }

  function askStop() {
    if (!active?.id) return
    setConfirm({
      kind: 'down',
      title: 'Stop inference',
      body: `Stop ${shortName(active.name, active.id)} and free the GPU.`,
      confirmLabel: 'Stop',
      danger: true,
    })
  }

  async function runConfirm() {
    if (!confirm) return
    setBusy(true)
    setFlash(null)
    try {
      if (confirm.kind === 'switch') {
        await switchProfile(confirm.recipe.id, {
          confirmHeavy: confirm.recipe.tier === 'heavy',
          ctx: confirm.launch?.ctx,
          kv: confirm.launch?.kv,
          preset: confirm.launch?.preset,
        })
        setFlash({ ok: true, text: `Switch started for ${confirm.recipe.id}` })
      } else if (confirm.kind === 'down') {
        await stopInference()
        setFlash({ ok: true, text: 'Inference stopped' })
      }
      setConfirm(null)
      live.refresh?.()
    } catch (err) {
      setFlash({ ok: false, text: err.message || 'failed' })
    } finally {
      setBusy(false)
    }
  }

  const actions = { askSwitch, askStop, flash }

  if (loc.pathname === '/inference/log') {
    return <LogPage />
  }

  return (
    <AppShell live={live}>
      <Routes>
        <Route index element={<HomePage live={live} />} />
        <Route path="inference" element={<InferencePage live={live} actions={actions} />} />
        <Route path="explore" element={<ExplorePage />} />
        <Route path="benchmaster" element={<BenchmasterPage live={live} />} />
        <Route path="models" element={<ModelsPage />} />
        <Route path="hardware" element={<HardwarePage live={live} />} />
        <Route path="activity" element={<ActivityPage live={live} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <CommandPalette live={live} onSwitch={askSwitch} onStop={askStop} />
      {confirm ? (
        <ConfirmDialog
          title={confirm.title}
          body={confirm.body}
          confirmLabel={confirm.confirmLabel}
          danger={confirm.danger}
          busy={busy}
          onCancel={() => !busy && setConfirm(null)}
          onConfirm={runConfirm}
        />
      ) : null}
    </AppShell>
  )
}
