/* ============================================================
   Design Tokens — Bloomberg Terminal Design System
   ============================================================ */

// ---------------------
// Colors
// ---------------------
export const colors = {
  // Background layers
  bgRoot: '#05080c',
  bgPanel: '#0b0f14',
  bgPanelRaised: '#111827',
  bgPanelHover: '#141c26',

  // Borders
  borderSubtle: '#263241',
  borderActive: '#38bdf8',
  borderMuted: '#1a2535',

  // Text hierarchy
  textPrimary: '#e6edf3',
  textSecondary: '#8b9ab0',
  textMuted: '#4a5568',

  // Accents
  accentCyan: '#38bdf8',
  accentCyanDim: '#0e7490',
  accentAmber: '#f59e0b',
  accentAmberDim: '#92400e',
  accentPurple: '#a78bfa',
  accentPurpleDim: '#5b21b6',

  // Status semantic
  positive: '#22c55e',
  positiveDim: '#14532d',
  positiveBg: '#052e16',
  negative: '#ef4444',
  negativeDim: '#991b1b',
  negativeBg: '#450a0a',
  warning: '#f59e0b',
  warningDim: '#92400e',
  warningBg: '#451a03',
  info: '#38bdf8',
  infoDim: '#0e7490',
  infoBg: '#082f49',
} as const

export type ColorToken = keyof typeof colors

// ---------------------
// Typography
// ---------------------
export const typography = {
  fontUi: '"Inter", "IBM Plex Sans", system-ui, sans-serif',
  fontMono: '"IBM Plex Mono", "JetBrains Mono", monospace',

  size2xs: '0.625rem',  // 10px
  sizeXs: '0.6875rem',  // 11px
  sizeSm: '0.75rem',    // 12px
  sizeBase: '0.8125rem',// 13px
  sizeMd: '0.875rem',   // 14px
  sizeLg: '1rem',       // 16px
  sizeXl: '1.125rem',   // 18px

  weightLight: '300',
  weightRegular: '400',
  weightMedium: '500',
  weightSemibold: '600',
  weightBold: '700',

  lineHeightTight: '1.2',
  lineHeightBase: '1.4',
  lineHeightRelaxed: '1.6',

  letterSpacingTight: '-0.02em',
  letterSpacingBase: '0',
  letterSpacingWide: '0.04em',
  letterSpacingWidest: '0.12em',
} as const

// ---------------------
// Spacing
// ---------------------
export const spacing = {
  px: '1px',
  0: '0px',
  0.5: '2px',
  1: '4px',
  1.5: '6px',
  2: '8px',
  2.5: '10px',
  3: '12px',
  3.5: '14px',
  4: '16px',
  5: '20px',
  6: '24px',
  8: '32px',
  10: '40px',
  12: '48px',
  16: '64px',
} as const

// ---------------------
// Border Radius
// ---------------------
export const radii = {
  none: '0px',
  sm: '2px',
  md: '3px',
  lg: '4px',
  xl: '6px',
} as const

// ---------------------
// Shadows
// ---------------------
export const shadows = {
  panel: '0 0 0 1px #263241, 0 4px 16px rgba(0,0,0,0.6)',
  panelActive: '0 0 0 1px #38bdf8, 0 4px 16px rgba(56,189,248,0.15)',
  panelFocus: '0 0 0 2px #38bdf8',
  glow: '0 0 12px rgba(56, 189, 248, 0.4)',
  glowGreen: '0 0 12px rgba(34, 197, 94, 0.4)',
  glowRed: '0 0 12px rgba(239, 68, 68, 0.4)',
  dropdown: '0 8px 32px rgba(0,0,0,0.8), 0 0 0 1px #263241',
} as const

// ---------------------
// Z-Index Scale
// ---------------------
export const zIndex = {
  base: 0,
  raised: 10,
  dropdown: 100,
  modal: 200,
  toast: 300,
  tooltip: 400,
  overlay: 500,
} as const

// ---------------------
// Transitions
// ---------------------
export const transitions = {
  fast: '100ms ease',
  base: '150ms ease',
  slow: '250ms ease',
  xslow: '400ms ease',
} as const

// ---------------------
// Component Size Variants
// ---------------------
export const componentSizes = {
  xs: { height: '20px', padding: '0 6px', fontSize: '0.625rem' },
  sm: { height: '24px', padding: '0 8px', fontSize: '0.7rem' },
  md: { height: '28px', padding: '0 10px', fontSize: '0.75rem' },
  lg: { height: '34px', padding: '0 14px', fontSize: '0.8125rem' },
  xl: { height: '40px', padding: '0 18px', fontSize: '0.875rem' },
} as const

export type ComponentSize = keyof typeof componentSizes

// ---------------------
// Panel Layout
// ---------------------
export const layout = {
  commandBarHeight: '36px',
  consoleHeight: '200px',
  consoleMinHeight: '120px',
  consoleMaxHeight: '400px',
  leftPanelWidth: '240px',
  leftPanelMinWidth: '180px',
  leftPanelMaxWidth: '360px',
  rightPanelWidth: '280px',
  rightPanelMinWidth: '220px',
  rightPanelMaxWidth: '400px',
} as const

// ---------------------
// Animation Durations
// ---------------------
export const animation = {
  priceFlashDuration: '600ms',
  alertPulseDuration: '2000ms',
  slideInDuration: '200ms',
  fadeInDuration: '150ms',
  shimmerDuration: '1500ms',
} as const

// ---------------------
// Chart Colors
// ---------------------
export const chartColors = {
  up: '#22c55e',
  down: '#ef4444',
  neutral: '#8b9ab0',
  volume: '#263241',
  grid: '#1a2535',
  axis: '#4a5568',
  tooltip: '#0b0f14',
  series: ['#38bdf8', '#a78bfa', '#f59e0b', '#22c55e', '#ef4444', '#fb7185'],
} as const
