import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell.jsx'
import { HomePage } from './pages/HomePage.jsx'
import { InferencePage } from './pages/InferencePage.jsx'
import { PlaceholderPage } from './pages/PlaceholderPage.jsx'
import { useLive } from './lib/live.js'

export default function App() {
  const live = useLive()
  return (
    <AppShell live={live}>
      <Routes>
        <Route index element={<HomePage live={live} />} />
        <Route path="inference" element={<InferencePage live={live} />} />
        <Route
          path="explore"
          element={<PlaceholderPage title="Explore" legacyHash="#explore" />}
        />
        <Route
          path="benchmaster"
          element={<PlaceholderPage title="Benchmaster" legacyHash="#benchmaster" />}
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  )
}
