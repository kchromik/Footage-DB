import { useTheme } from '../lib/theme'
import { IconMonitor, IconMoon, IconSun } from './Icons'

const LABEL = {
  system: 'Darstellung: Systemvorgabe',
  light: 'Darstellung: hell',
  dark: 'Darstellung: dunkel',
}

export function ThemeToggle() {
  const { choice, cycle } = useTheme()

  return (
    <button className="rail-btn" onClick={cycle} aria-label={LABEL[choice]}>
      {choice === 'system' ? <IconMonitor /> : choice === 'light' ? <IconSun /> : <IconMoon />}
      <span className="tip">{LABEL[choice]}</span>
    </button>
  )
}
