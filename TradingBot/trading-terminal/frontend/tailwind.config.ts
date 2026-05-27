import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './index.html',
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        // ── Bloomberg Backgrounds ──
        'bg-root': '#000000',
        'bg-panel': '#070707',
        'bg-panel-raised': '#0f0f0f',
        'bg-panel-hover': '#141414',

        // ── Borders ──
        'border-subtle': '#1e1e1e',
        'border-active': '#ff6600',
        'border-muted': '#141414',

        // ── Typography ──
        'text-primary': '#f0f0f0',
        'text-secondary': '#888888',
        'text-muted': '#444444',
        'text-dim': '#2a2a2a',

        // ── Bloomberg Orange (primary accent) ──
        'accent-cyan': '#ff6600',
        'accent-cyan-dim': '#cc4400',
        'accent-amber': '#ffcc00',
        'accent-amber-dim': '#b8960c',
        'accent-purple': '#ab47bc',
        'accent-green': '#00e676',
        'accent-red': '#ff1744',

        // ── P&L ──
        positive: '#00e676',
        'positive-dim': '#00a152',
        'positive-bg': '#001a0a',
        negative: '#ff1744',
        'negative-dim': '#c41234',
        'negative-bg': '#1a0005',
        warning: '#ffcc00',
        'warning-dim': '#b8960c',
        'warning-bg': '#1a1500',
        info: '#00bcd4',
        'info-dim': '#00838f',
        'info-bg': '#001a1f',
      },
      fontFamily: {
        ui: ['Inter', 'IBM Plex Sans', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', '"JetBrains Mono"', '"Fira Code"', 'Consolas', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.625rem', { lineHeight: '0.875rem' }],
        xs: ['0.7rem', { lineHeight: '1rem' }],
        sm: ['0.75rem', { lineHeight: '1.125rem' }],
        base: ['0.8125rem', { lineHeight: '1.25rem' }],
        md: ['0.875rem', { lineHeight: '1.375rem' }],
        lg: ['1rem', { lineHeight: '1.5rem' }],
        xl: ['1.125rem', { lineHeight: '1.625rem' }],
      },
      borderRadius: {
        none: '0px',
        sm: '1px',
        DEFAULT: '2px',
        md: '2px',
        lg: '3px',
        xl: '4px',
      },
      boxShadow: {
        panel: '0 0 0 1px #1e1e1e',
        'panel-active': '0 0 0 1px #ff6600, 0 0 12px rgba(255,102,0,0.15)',
        glow: '0 0 10px rgba(255, 102, 0, 0.45)',
        'glow-green': '0 0 10px rgba(0, 230, 118, 0.4)',
        'glow-red': '0 0 10px rgba(255, 23, 68, 0.4)',
        'inner-subtle': 'inset 0 1px 0 rgba(255,255,255,0.03)',
      },
      animation: {
        'price-flash-up': 'priceFlashUp 0.8s ease-out',
        'price-flash-down': 'priceFlashDown 0.8s ease-out',
        'pulse-alert': 'pulseAlert 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'ticker-scroll': 'tickerScroll 60s linear infinite',
        'slide-in-right': 'slideInRight 0.2s ease-out',
        'slide-in-up': 'slideInUp 0.2s ease-out',
        'fade-in': 'fadeIn 0.15s ease-out',
        blink: 'blink 1s step-end infinite',
        shimmer: 'shimmer 1.5s infinite',
      },
      keyframes: {
        priceFlashUp: {
          '0%': { backgroundColor: 'rgba(0, 230, 118, 0.35)' },
          '100%': { backgroundColor: 'transparent' },
        },
        priceFlashDown: {
          '0%': { backgroundColor: 'rgba(255, 23, 68, 0.35)' },
          '100%': { backgroundColor: 'transparent' },
        },
        pulseAlert: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.4' },
        },
        tickerScroll: {
          '0%': { transform: 'translateX(0)' },
          '100%': { transform: 'translateX(-50%)' },
        },
        slideInRight: {
          '0%': { transform: 'translateX(100%)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
        slideInUp: {
          '0%': { transform: 'translateY(8px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
      },
      zIndex: {
        base: '0',
        raised: '10',
        dropdown: '100',
        modal: '200',
        toast: '300',
        tooltip: '400',
        overlay: '500',
      },
    },
  },
  plugins: [],
}

export default config
