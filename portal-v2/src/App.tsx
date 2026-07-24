import { lazy } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/app-shell'
import { ThemeProvider } from '@/components/theme-provider'

const HomePage = lazy(() => import('@/features/home/home-page').then((module) => ({ default: module.HomePage })))
const CatalogPage = lazy(() => import('@/features/catalog/catalog-page').then((module) => ({ default: module.CatalogPage })))
const LibraryPage = lazy(() => import('@/features/library/library-page').then((module) => ({ default: module.LibraryPage })))
const FindModelsPage = lazy(() => import('@/features/library/find-models-page').then((module) => ({ default: module.FindModelsPage })))
const RecipesPage = lazy(() => import('@/features/recipes/recipes-page').then((module) => ({ default: module.RecipesPage })))
const BenchmasterPage = lazy(() => import('@/features/benchmaster/benchmaster-page').then((module) => ({ default: module.BenchmasterPage })))
const OperatorPage = lazy(() => import('@/features/operator/operator-page').then((module) => ({ default: module.OperatorPage })))
const HealthPage = lazy(() => import('@/features/health/health-page').then((module) => ({ default: module.HealthPage })))
const AddonsPage = lazy(() => import('@/features/addons/addons-page').then((module) => ({ default: module.AddonsPage })))
const SetupPage = lazy(() => import('@/features/setup/setup-page').then((module) => ({ default: module.SetupPage })))

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter basename="/v2">
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<HomePage />} />
            <Route path="catalog" element={<CatalogPage />} />
            <Route path="library" element={<LibraryPage />} />
            <Route path="library/find" element={<FindModelsPage />} />
            <Route path="recipes" element={<RecipesPage />} />
            <Route path="benchmaster" element={<BenchmasterPage />} />
            <Route path="operator" element={<OperatorPage />} />
            <Route path="health" element={<HealthPage />} />
            <Route path="addons" element={<AddonsPage />} />
            <Route path="setup" element={<SetupPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  )
}
