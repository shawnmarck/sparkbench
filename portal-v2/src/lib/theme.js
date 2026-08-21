import { THEMES } from './omarchy-themes.js'

const KEY = 'spark-theme'

export { THEMES }

export function themeById(id) {
  return THEMES.find((t) => t.id === id) || THEMES[0]
}

export function currentThemeId() {
  try {
    return localStorage.getItem(KEY) || 'spark'
  } catch {
    return 'spark'
  }
}

export function applyTheme(id) {
  const theme = themeById(id)
  const root = document.documentElement
  root.dataset.theme = theme.id
  root.style.colorScheme = theme.mode
  for (const [key, value] of Object.entries(theme.vars)) {
    root.style.setProperty(key, value)
  }
  try {
    localStorage.setItem(KEY, theme.id)
  } catch {
    /* private mode */
  }
  return theme
}

export function initTheme() {
  return applyTheme(currentThemeId())
}
