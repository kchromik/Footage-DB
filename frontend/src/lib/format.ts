import type { Look } from './types'

export const LOOK_LABEL: Record<Look, string> = {
  log: 'LOG',
  graded: 'Graded',
  hdr: 'HDR',
  rec709: 'Rec.709',
  unknown: 'Unklar',
}

export const LOOK_COLOR: Record<Look, string> = {
  log: 'var(--look-log)',
  graded: 'var(--look-graded)',
  hdr: 'var(--look-hdr)',
  rec709: 'var(--look-rec709)',
  unknown: 'var(--look-unknown)',
}

export const CATEGORY_LABEL: Record<string, string> = {
  camera: 'Kamera',
  lens: 'Objektiv',
  look: 'Look',
  tech: 'Technik',
  source: 'Herkunft',
  custom: 'Eigene Tags',
}

export const CATEGORY_ORDER = ['camera', 'tech', 'look', 'source', 'lens', 'custom']

export function formatDate(value: string | null, withTime = false): string {
  if (!value) return '-'
  const date = new Date(value.length === 10 ? `${value}T00:00:00` : value)
  if (Number.isNaN(date.getTime())) return value
  const options: Intl.DateTimeFormatOptions = withTime
    ? { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }
    : { day: '2-digit', month: '2-digit', year: 'numeric' }
  return new Intl.DateTimeFormat('de-DE', options).format(date)
}

export function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${index === 0 ? value : value.toFixed(1)} ${units[index]}`
}

export function formatBitrate(bitrate: number | null): string {
  if (!bitrate) return '-'
  return `${(bitrate / 1_000_000).toFixed(1)} Mbit/s`
}

export function formatDuration(seconds: number | null): string {
  if (!seconds || seconds < 0) return '0:00'
  const total = Math.round(seconds)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const rest = total % 60
  if (hours) return `${hours}:${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`
  return `${minutes}:${String(rest).padStart(2, '0')}`
}

export function formatLongDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (hours >= 1) return `${hours} h ${minutes} min`
  if (minutes >= 1) return `${minutes} min`
  return `${Math.round(seconds)} s`
}

export function formatFps(fps: number | null): string {
  if (!fps) return '-'
  const rounded = Math.round(fps * 100) / 100
  return Number.isInteger(rounded) ? `${rounded}` : rounded.toFixed(2)
}
