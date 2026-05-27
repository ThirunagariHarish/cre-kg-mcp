/* ============================================================
   Component Variants — Class Variance Authority (CVA)
   Bloomberg Terminal Design System
   ============================================================ */

import { cva } from 'class-variance-authority'

// ---------------------
// Button Variants
// ---------------------
export const buttonVariants = cva(
  // Base styles
  [
    'inline-flex items-center justify-center gap-1.5',
    'font-ui font-medium text-xs uppercase tracking-wider',
    'border transition-all duration-100',
    'focus-visible:outline focus-visible:outline-1 focus-visible:outline-[#38bdf8]',
    'disabled:opacity-40 disabled:cursor-not-allowed disabled:pointer-events-none',
    'select-none whitespace-nowrap',
    'rounded-sm',
  ],
  {
    variants: {
      variant: {
        primary: [
          'bg-accent-cyan text-bg-root border-accent-cyan',
          'hover:bg-[#7dd3fc] hover:border-[#7dd3fc]',
          'active:bg-[#0ea5e9]',
        ],
        secondary: [
          'bg-bg-panel-raised text-text-primary border-border-subtle',
          'hover:border-accent-cyan hover:text-accent-cyan',
          'active:bg-bg-panel',
        ],
        danger: [
          'bg-negative text-white border-negative',
          'hover:bg-[#f87171] hover:border-[#f87171]',
          'active:bg-[#dc2626]',
        ],
        'danger-outline': [
          'bg-transparent text-negative border-negative',
          'hover:bg-negative-bg hover:text-[#f87171]',
          'active:bg-[#450a0a]',
        ],
        ghost: [
          'bg-transparent text-text-secondary border-transparent',
          'hover:text-text-primary hover:bg-bg-panel-raised hover:border-border-subtle',
          'active:bg-bg-panel',
        ],
        warning: [
          'bg-warning text-bg-root border-warning',
          'hover:bg-[#fbbf24] hover:border-[#fbbf24]',
          'active:bg-[#d97706]',
        ],
        link: [
          'bg-transparent text-accent-cyan border-transparent underline-offset-2',
          'hover:underline hover:text-[#7dd3fc]',
          'active:text-[#0ea5e9]',
          'h-auto px-0',
        ],
      },
      size: {
        xs: 'h-5 px-1.5 text-[0.6rem]',
        sm: 'h-6 px-2 text-[0.65rem]',
        md: 'h-7 px-2.5 text-xs',
        lg: 'h-8 px-3 text-sm',
        xl: 'h-10 px-4 text-sm',
        icon: 'h-6 w-6 p-0',
        'icon-sm': 'h-5 w-5 p-0',
        'icon-lg': 'h-8 w-8 p-0',
      },
    },
    defaultVariants: {
      variant: 'secondary',
      size: 'md',
    },
  }
)

// ---------------------
// Badge Variants
// ---------------------
export const badgeVariants = cva(
  [
    'inline-flex items-center justify-center',
    'font-mono text-[0.6rem] font-medium uppercase tracking-wider',
    'rounded-sm border px-1 py-0',
    'whitespace-nowrap select-none',
  ],
  {
    variants: {
      variant: {
        positive: 'bg-positive-bg text-positive border-positive-dim',
        negative: 'bg-negative-bg text-negative border-negative-dim',
        warning: 'bg-warning-bg text-warning border-warning-dim',
        neutral: 'bg-bg-panel-raised text-text-secondary border-border-subtle',
        info: 'bg-info-bg text-info border-info-dim',
        muted: 'bg-transparent text-text-muted border-border-muted',
        buy: 'bg-positive-bg text-positive border-positive-dim',
        sell: 'bg-negative-bg text-negative border-negative-dim',
        hold: 'bg-warning-bg text-warning border-warning-dim',
        paper: 'bg-info-bg text-info border-info-dim',
        live: [
          'bg-negative-bg text-negative border-negative',
          'animate-pulse-alert',
        ],
      },
      size: {
        xs: 'text-[0.55rem] px-0.5',
        sm: 'text-[0.6rem] px-1',
        md: 'text-[0.65rem] px-1.5 py-px',
        lg: 'text-xs px-2 py-0.5',
      },
    },
    defaultVariants: {
      variant: 'neutral',
      size: 'sm',
    },
  }
)

// ---------------------
// Panel Variants
// ---------------------
export const panelVariants = cva(
  [
    'flex flex-col overflow-hidden',
    'border border-border-subtle',
  ],
  {
    variants: {
      variant: {
        default: 'bg-bg-panel',
        raised: 'bg-bg-panel-raised',
        sunken: 'bg-bg-root',
        ghost: 'bg-transparent border-transparent',
      },
      focused: {
        true: 'border-border-active shadow-panel-active',
        false: '',
      },
      rounded: {
        none: 'rounded-none',
        sm: 'rounded-sm',
        md: 'rounded',
        lg: 'rounded-md',
      },
    },
    defaultVariants: {
      variant: 'default',
      focused: false,
      rounded: 'none',
    },
  }
)

// ---------------------
// Input Variants
// ---------------------
export const inputVariants = cva(
  [
    'w-full bg-bg-root border',
    'text-text-primary placeholder:text-text-muted',
    'transition-colors duration-100',
    'focus:outline-none focus:ring-0',
    'disabled:opacity-40 disabled:cursor-not-allowed',
  ],
  {
    variants: {
      variant: {
        default: [
          'border-border-subtle',
          'focus:border-accent-cyan focus:shadow-[0_0_0_1px_rgba(56,189,248,0.2)]',
        ],
        error: [
          'border-negative',
          'focus:border-negative focus:shadow-[0_0_0_1px_rgba(239,68,68,0.2)]',
        ],
        success: [
          'border-positive',
          'focus:border-positive focus:shadow-[0_0_0_1px_rgba(34,197,94,0.2)]',
        ],
      },
      inputSize: {
        xs: 'h-5 px-1.5 text-xs rounded-sm',
        sm: 'h-6 px-2 text-xs rounded-sm',
        md: 'h-7 px-2.5 text-sm rounded',
        lg: 'h-9 px-3 text-sm rounded',
      },
      mono: {
        true: 'font-mono',
        false: 'font-ui',
      },
    },
    defaultVariants: {
      variant: 'default',
      inputSize: 'md',
      mono: false,
    },
  }
)

// ---------------------
// Status Dot Variants
// ---------------------
export const statusDotVariants = cva(
  ['rounded-full flex-shrink-0'],
  {
    variants: {
      status: {
        online: 'bg-positive',
        offline: 'bg-negative',
        warning: 'bg-warning',
        unknown: 'bg-text-muted',
        active: 'bg-accent-cyan',
      },
      size: {
        xs: 'w-1 h-1',
        sm: 'w-1.5 h-1.5',
        md: 'w-2 h-2',
        lg: 'w-2.5 h-2.5',
      },
      pulse: {
        true: 'animate-pulse',
        false: '',
      },
    },
    defaultVariants: {
      status: 'unknown',
      size: 'sm',
      pulse: false,
    },
  }
)

// ---------------------
// Table Cell Variants
// ---------------------
export const tableCellVariants = cva(
  ['px-2 py-1 text-xs font-mono tabular-nums whitespace-nowrap'],
  {
    variants: {
      align: {
        left: 'text-left',
        right: 'text-right',
        center: 'text-center',
      },
      type: {
        default: 'text-text-primary',
        positive: 'text-positive',
        negative: 'text-negative',
        warning: 'text-warning',
        muted: 'text-text-secondary',
        symbol: 'text-accent-cyan font-medium font-mono',
      },
    },
    defaultVariants: {
      align: 'right',
      type: 'default',
    },
  }
)

// ---------------------
// Alert/Toast Variants
// ---------------------
export const alertVariants = cva(
  [
    'flex items-start gap-2 p-2.5 border rounded-sm',
    'font-ui text-xs animate-slide-in-right',
  ],
  {
    variants: {
      variant: {
        info: 'bg-info-bg border-info-dim text-info',
        success: 'bg-positive-bg border-positive-dim text-positive',
        warning: 'bg-warning-bg border-warning-dim text-warning',
        error: 'bg-negative-bg border-negative-dim text-negative',
        signal: 'bg-bg-panel-raised border-accent-cyan text-text-primary',
      },
    },
    defaultVariants: {
      variant: 'info',
    },
  }
)
