interface Props {
  size?: number
  className?: string
}

const base = (size: number) => ({
  width: size,
  height: size,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.7,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
})

export const IconLibrary = ({ size = 18 }: Props) => (
  <svg {...base(size)}>
    <rect x="3" y="4" width="8" height="7" rx="1.5" />
    <rect x="13" y="4" width="8" height="7" rx="1.5" />
    <rect x="3" y="13" width="8" height="7" rx="1.5" />
    <rect x="13" y="13" width="8" height="7" rx="1.5" />
  </svg>
)

export const IconUpload = ({ size = 18 }: Props) => (
  <svg {...base(size)}>
    <path d="M12 16V4" />
    <path d="M7 9l5-5 5 5" />
    <path d="M4 15v3a2 2 0 002 2h12a2 2 0 002-2v-3" />
  </svg>
)

export const IconStats = ({ size = 18 }: Props) => (
  <svg {...base(size)}>
    <path d="M4 20V10" />
    <path d="M10 20V4" />
    <path d="M16 20v-7" />
    <path d="M22 20H2" />
  </svg>
)

export const IconTools = ({ size = 18 }: Props) => (
  <svg {...base(size)}>
    <path d="M3 7h11" />
    <path d="M18 7h3" />
    <circle cx="16" cy="7" r="2" />
    <path d="M3 17h5" />
    <path d="M12 17h9" />
    <circle cx="10" cy="17" r="2" />
  </svg>
)

export const IconSearch = ({ size = 15 }: Props) => (
  <svg {...base(size)}>
    <circle cx="11" cy="11" r="7" />
    <path d="M20 20l-3.5-3.5" />
  </svg>
)

export const IconFilter = ({ size = 16 }: Props) => (
  <svg {...base(size)}>
    <path d="M3 5h18" />
    <path d="M6 12h12" />
    <path d="M10 19h4" />
  </svg>
)

export const IconClose = ({ size = 14 }: Props) => (
  <svg {...base(size)}>
    <path d="M6 6l12 12M18 6L6 18" />
  </svg>
)

export const IconCheck = ({ size = 13 }: Props) => (
  <svg {...base(size)} strokeWidth={2.4}>
    <path d="M5 12.5l4.5 4.5L19 7" />
  </svg>
)

export const IconDownload = ({ size = 15 }: Props) => (
  <svg {...base(size)}>
    <path d="M12 4v12" />
    <path d="M7 11l5 5 5-5" />
    <path d="M4 20h16" />
  </svg>
)

export const IconStar = ({ size = 15, filled = false }: Props & { filled?: boolean }) => (
  <svg {...base(size)} fill={filled ? 'currentColor' : 'none'}>
    <path d="M12 3.6l2.6 5.3 5.8.8-4.2 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8L3.6 9.7l5.8-.8z" />
  </svg>
)

export const IconRefresh = ({ size = 15 }: Props) => (
  <svg {...base(size)}>
    <path d="M20 11a8 8 0 10-2.3 6.3" />
    <path d="M20 5v6h-6" />
  </svg>
)

export const IconTrash = ({ size = 15 }: Props) => (
  <svg {...base(size)}>
    <path d="M4 7h16" />
    <path d="M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2" />
    <path d="M6 7l1 13h10l1-13" />
  </svg>
)

export const IconArrowLeft = ({ size = 15 }: Props) => (
  <svg {...base(size)}>
    <path d="M15 5l-7 7 7 7" />
  </svg>
)

export const IconArrowRight = ({ size = 15 }: Props) => (
  <svg {...base(size)}>
    <path d="M9 5l7 7-7 7" />
  </svg>
)

export const IconFolder = ({ size = 15 }: Props) => (
  <svg {...base(size)}>
    <path d="M3 7a2 2 0 012-2h4l2 2.5h8a2 2 0 012 2V18a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
  </svg>
)

export const IconLogo = ({ size = 18 }: Props) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
    <rect x="3" y="6" width="12" height="12" rx="2" stroke="currentColor" strokeWidth="1.8" />
    <path d="M17 10.2l4-2.4v8.4l-4-2.4z" fill="currentColor" />
  </svg>
)

export const IconFilm = ({ size = 34 }: Props) => (
  <svg {...base(size)} strokeWidth={1.2}>
    <rect x="2.5" y="5" width="19" height="14" rx="2" />
    <path d="M7 5v14M17 5v14" />
    <path d="M2.5 12h19" />
  </svg>
)

export const IconSun = ({ size = 17 }: Props) => (
  <svg {...base(size)}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </svg>
)

export const IconMoon = ({ size = 17 }: Props) => (
  <svg {...base(size)}>
    <path d="M20 14.5A8.5 8.5 0 019.5 4a8.5 8.5 0 1010.5 10.5z" />
  </svg>
)

export const IconMonitor = ({ size = 17 }: Props) => (
  <svg {...base(size)}>
    <rect x="3" y="4" width="18" height="12" rx="2" />
    <path d="M8 20h8M12 16v4" />
  </svg>
)

export const IconCollection = ({ size = 18 }: Props) => (
  <svg {...base(size)}>
    <rect x="3" y="7" width="13" height="13" rx="2" />
    <path d="M7 4h11a2 2 0 012 2v10" />
  </svg>
)

export const IconPlus = ({ size = 14 }: Props) => (
  <svg {...base(size)}>
    <path d="M12 5v14M5 12h14" />
  </svg>
)

export const IconTag = ({ size = 14 }: Props) => (
  <svg {...base(size)}>
    <path d="M11 3H4a1 1 0 00-1 1v7l9.5 9.5a1.5 1.5 0 002.1 0l6.9-6.9a1.5 1.5 0 000-2.1z" />
    <circle cx="7.5" cy="7.5" r="1.3" />
  </svg>
)

export const IconSimilar = ({ size = 15 }: Props) => (
  <svg {...base(size)}>
    <circle cx="9" cy="9" r="5.5" />
    <circle cx="15" cy="15" r="5.5" />
  </svg>
)

export const IconKeyboard = ({ size = 17 }: Props) => (
  <svg {...base(size)}>
    <rect x="2.5" y="6" width="19" height="12" rx="2" />
    <path d="M6.5 10h.01M10 10h.01M13.5 10h.01M17 10h.01M8 14h8" />
  </svg>
)

export const IconEdit = ({ size = 13 }: Props) => (
  <svg {...base(size)}>
    <path d="M4 20h4l10-10-4-4L4 16z" />
    <path d="M13.5 6.5l4 4" />
  </svg>
)

export const IconLogout = ({ size = 18 }: Props) => (
  <svg {...base(size)}>
    <path d="M14 20H6a2 2 0 01-2-2V6a2 2 0 012-2h8" />
    <path d="M17 15l4-3-4-3" />
    <path d="M21 12H10" />
  </svg>
)
