import { describe, it, expect } from 'vitest'
import {
  formatNumber,
  formatCurrency,
  formatPnl,
  formatPercent,
  formatVolume,
} from './formatters'

// ---------------------------------------------------------------------------
// formatNumber
// ---------------------------------------------------------------------------
describe('formatNumber', () => {
  it('formats a regular positive number with default 2 decimals', () => {
    expect(formatNumber(42.5)).toBe('42.50')
  })

  it('formats zero', () => {
    expect(formatNumber(0)).toBe('0.00')
  })

  it('formats a negative number below 1 000', () => {
    expect(formatNumber(-3.14159)).toBe('-3.14')
  })

  it('formats thousands as K (positive)', () => {
    expect(formatNumber(1500)).toBe('1.5K')
  })

  it('formats negative thousands as -K', () => {
    expect(formatNumber(-2500)).toBe('-2.5K')
  })

  it('formats millions as M (positive)', () => {
    expect(formatNumber(1_500_000)).toBe('1.5M')
  })

  it('formats negative millions as -M', () => {
    expect(formatNumber(-3_200_000)).toBe('-3.2M')
  })

  it('respects custom decimals for small numbers', () => {
    expect(formatNumber(1.23456, 4)).toBe('1.2346')
  })

  it('formats exactly 1 000 as K', () => {
    expect(formatNumber(1000)).toBe('1.0K')
  })

  it('formats exactly 1 000 000 as M', () => {
    expect(formatNumber(1_000_000)).toBe('1.0M')
  })
})

// ---------------------------------------------------------------------------
// formatCurrency
// ---------------------------------------------------------------------------
describe('formatCurrency', () => {
  it('formats a positive value under 1 000', () => {
    expect(formatCurrency(99.99)).toBe('$99.99')
  })

  it('formats zero as $0.00', () => {
    expect(formatCurrency(0)).toBe('$0.00')
  })

  it('formats a negative value under 1 000', () => {
    expect(formatCurrency(-25.5)).toBe('-$25.50')
  })

  it('formats thousands as K with $ prefix', () => {
    expect(formatCurrency(5000)).toBe('$5.0K')
  })

  it('formats negative thousands as -$K', () => {
    expect(formatCurrency(-12500)).toBe('-$12.5K')
  })

  it('formats millions as M with $ prefix', () => {
    expect(formatCurrency(2_500_000)).toBe('$2.50M')
  })

  it('formats negative millions as -$M', () => {
    expect(formatCurrency(-1_000_000)).toBe('-$1.00M')
  })

  it('respects custom decimals', () => {
    expect(formatCurrency(1.5, 0)).toBe('$2')
  })
})

// ---------------------------------------------------------------------------
// formatPnl
// ---------------------------------------------------------------------------
describe('formatPnl', () => {
  it('shows + sign for positive P&L', () => {
    expect(formatPnl(500)).toBe('+$500.00')
  })

  it('shows no + sign for zero', () => {
    // zero is not > 0 so no '+' prefix
    expect(formatPnl(0)).toBe('$0.00')
  })

  it('shows - sign for negative P&L (from formatCurrency)', () => {
    expect(formatPnl(-250)).toBe('-$250.00')
  })

  it('handles thousands with + sign', () => {
    expect(formatPnl(1500)).toBe('+$1.5K')
  })

  it('omits the + sign when showSign is false', () => {
    expect(formatPnl(500, false)).toBe('$500.00')
  })

  it('handles millions with + sign', () => {
    expect(formatPnl(2_000_000)).toBe('+$2.00M')
  })
})

// ---------------------------------------------------------------------------
// formatPercent
// ---------------------------------------------------------------------------
describe('formatPercent', () => {
  it('formats a positive percent with + sign', () => {
    expect(formatPercent(1.25)).toBe('+1.25%')
  })

  it('formats zero with no sign', () => {
    expect(formatPercent(0)).toBe('0.00%')
  })

  it('formats a negative percent with - sign', () => {
    expect(formatPercent(-3.5)).toBe('-3.50%')
  })

  it('respects custom decimal places', () => {
    expect(formatPercent(1.234, 1)).toBe('+1.2%')
  })

  it('formats large positive percent', () => {
    expect(formatPercent(150)).toBe('+150.00%')
  })
})

// ---------------------------------------------------------------------------
// formatVolume
// ---------------------------------------------------------------------------
describe('formatVolume', () => {
  it('returns raw string for volume under 1 000', () => {
    expect(formatVolume(500)).toBe('500')
  })

  it('formats thousands as K (no decimal)', () => {
    expect(formatVolume(1500)).toBe('2K')
  })

  it('formats exactly 1 000 as K', () => {
    expect(formatVolume(1000)).toBe('1K')
  })

  it('formats millions as M with one decimal', () => {
    expect(formatVolume(2_500_000)).toBe('2.5M')
  })

  it('formats exactly 1 000 000 as 1.0M', () => {
    expect(formatVolume(1_000_000)).toBe('1.0M')
  })

  it('formats zero', () => {
    expect(formatVolume(0)).toBe('0')
  })

  it('formats large volume', () => {
    expect(formatVolume(12_345_678)).toBe('12.3M')
  })
})
