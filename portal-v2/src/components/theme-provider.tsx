import { ThemeProvider as NextThemesProvider, useTheme } from 'next-themes'
import { useEffect, type ReactNode } from 'react'
import { THEME_CLASS, THEMES } from '@/components/theme-config'

function ThemeColorSchemeSync() {
  const { theme, resolvedTheme } = useTheme()
  useEffect(() => {
    const root = document.documentElement
    // Drop legacy class names from the previous theme scheme.
    root.classList.remove('light', 'green', 'dark')
    const name = (theme || resolvedTheme || 'green') as string
    const scheme = name === 'light' ? 'light' : 'dark'
    root.style.colorScheme = scheme
  }, [theme, resolvedTheme])
  return null
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="green"
      enableSystem={false}
      themes={[...THEMES]}
      value={THEME_CLASS}
      disableTransitionOnChange
    >
      <ThemeColorSchemeSync />
      {children}
    </NextThemesProvider>
  )
}
