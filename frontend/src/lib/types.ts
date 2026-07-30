export type Look = 'log' | 'graded' | 'hdr' | 'rec709' | 'unknown'

export interface Tag {
  name: string
  category: string
  source?: string
}

export interface SpriteInfo {
  url: string
  columns: number
  rows: number
  count: number
  tile_width: number
  tile_height: number
}

export interface Clip {
  id: number
  path: string
  filename: string
  original_filename: string | null
  folder: string
  ext: string
  status: string
  error: string | null
  size_bytes: number
  size_label: string
  duration: number | null
  duration_label: string
  width: number | null
  height: number | null
  resolution: string | null
  fps: number | null
  video_codec: string | null
  audio_codec: string | null
  audio_channels: number | null
  bit_depth: number | null
  pix_fmt: string | null
  color_transfer: string | null
  color_primaries: string | null
  bitrate: number | null
  container: string | null
  encoder: string | null
  rotation: number
  camera: string | null
  camera_make: string | null
  camera_model: string | null
  lens: string | null
  recorded_at: string | null
  recorded_source: string | null
  gps: { lat: number; lon: number } | null
  look: Look
  look_auto: Look | null
  look_manual: Look | null
  look_reason: string | null
  title: string | null
  notes: string | null
  favorite: boolean
  rating: number
  created_at: string
  updated_at: string
  poster_status: string
  proxy_status: string
  sprite_status: string
  embed_status: string
  poster_url: string | null
  play_url: string
  download_url: string
  playable: boolean
  sprite: SpriteInfo | null
  tags: Tag[]
  score?: number
  neighbours?: { previous: number | null; next: number | null }
}

export interface FacetEntry {
  name: string
  count: number
}

export interface Facets {
  tags: Record<string, FacetEntry[]>
  looks: FacetEntry[]
  folders: FacetEntry[]
}

export interface ClipPage {
  items: Clip[]
  total: number
  offset: number
  limit: number
  mode: string
  facets: Facets | null
}

export interface Stats {
  clips: number
  bytes: number
  size_label: string
  seconds: number
  duration_label: string
  missing: number
  errors: number
  pending: { poster: number; proxy: number; embed: number }
  by_camera: { name: string; count: number; seconds: number }[]
  by_year: { year: string; count: number }[]
  by_look: { name: string; count: number }[]
  by_resolution: { name: string; count: number }[]
  queue: { queued: number; running: number; failed: number }
  scanning: boolean
  last_scan_at: string | null
  semantic: {
    enabled: boolean
    model_status: string
    ready: boolean
    indexed: number
    pending: number
  }
  acceleration: string
  media_root: string
}

export interface Filters {
  q: string
  mode: 'auto' | 'text' | 'semantic'
  tags: string[]
  folder: string
  look: string
  date_from: string
  date_to: string
  duration_min: string
  duration_max: string
  favorite: boolean
  only_missing: boolean
  sort: string
}

export const EMPTY_FILTERS: Filters = {
  q: '',
  mode: 'auto',
  tags: [],
  folder: '',
  look: '',
  date_from: '',
  date_to: '',
  duration_min: '',
  duration_max: '',
  favorite: false,
  only_missing: false,
  sort: 'recorded_desc',
}

export interface SetupStatus {
  complete: boolean
  has_password: boolean
  password_from_env: boolean
  auth_user: string
  logged_in: boolean
  media_root: string
  media_exists: boolean
}

export interface SystemCheck {
  media: {
    path: string
    exists: boolean
    readable: boolean
    writable: boolean
    free_label: string
    total_label: string
    used_percent: number
  }
  data: { path: string; writable: boolean; free_label: string; total_label: string }
  permissions: {
    container_uid: number
    container_gid: number
    media_uid: number | null
    media_gid: number | null
    mode: string | null
    matches: boolean
  }
  tools: { ffmpeg: string | null; ffprobe: string | null; exiftool: string | null }
  hwaccel: { available: boolean; device: string; device_present: boolean }
  cpu_count: number
  internet: boolean
  warnings: string[]
  ok: boolean
}

export interface MediaPreview {
  available: boolean
  count: number
  truncated?: boolean
  size_label?: string
  folders: { name: string; count: number }[]
  kinds: Record<string, number>
  newest: string | null
  oldest: string | null
  estimate_minutes: number
}

export interface AppSettings {
  auth_user: string
  has_password: boolean
  password_from_env: boolean
  proxy_height: number
  proxy_crf: number
  hwaccel: string
  hwaccel_active: string
  semantic_enabled: boolean
  worker_count: number
  organize_uploads: boolean
  organize_pattern: string
  rescan_interval_minutes: number
  media_root: string
}

export interface MovePlan {
  count: number
  already_sorted: number
  truncated: boolean
  pattern: string
  preview: { clip_id: number; from: string; to: string; reason: string }[]
  skipped: { clip_id: number; path: string; reason: string }[]
}

export interface MoveBatch {
  batch: string
  total: number
  done: number
  reverted: number
  created_at: string
}
