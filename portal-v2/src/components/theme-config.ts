export const THEMES = ['light', 'green', 'dark'] as const
export type AppTheme = (typeof THEMES)[number]

/** Map logical theme names to explicit html classes. */
export const THEME_CLASS: Record<AppTheme, string> = {
  light: 'theme-light',
  green: 'theme-green',
  dark: 'theme-dark',
}
