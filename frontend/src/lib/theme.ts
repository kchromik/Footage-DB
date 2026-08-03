import { useCallback, useEffect, useState } from 'react'

export type ThemeChoice = 'system' | 'light' | 'dark'

const KEY = 'fdb-theme'
const ORDER: ThemeChoice[] = ['system', 'light', 'dark']

export function readTheme(): ThemeChoice {
  const stored = window.localStorage.getItem(KEY)
  return stored === 'light' || stored === 'dark' ? stored : 'system'
}

/* Das aufgelöste Ergebnis hängt am <html>, damit die Marken in styles.css
   greifen. index.html setzt dasselbe Attribut vor dem ersten Bild, sonst
   blitzt beim Laden kurz das helle Thema auf. */
export function applyTheme(choice: ThemeChoice): void {
  const dark =
    choice === 'dark' ||
    (choice === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
}

export function useTheme() {
  const [choice, setChoice] = useState<ThemeChoice>(readTheme)

  useEffect(() => {
    applyTheme(choice)
    window.localStorage.setItem(KEY, choice)
    if (choice !== 'system') return
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => applyTheme('system')
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [choice])

  const cycle = useCallback(() => {
    setChoice((current) => ORDER[(ORDER.indexOf(current) + 1) % ORDER.length])
  }, [])

  return { choice, cycle }
}
