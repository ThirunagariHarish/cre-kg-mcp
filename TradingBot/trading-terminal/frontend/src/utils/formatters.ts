export function formatNumber(value: number, decimals = 2): string {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}K`
  return value.toFixed(decimals)
}

export function formatVolume(volume: number): string {
  if (volume >= 1_000_000) return `${(volume / 1_000_000).toFixed(1)}M`
  if (volume >= 1_000) return `${(volume / 1_000).toFixed(0)}K`
  return volume.toString()
}

export function formatCurrency(value: number, decimals = 2): string {
  const abs = Math.abs(value)
  const prefix = value < 0 ? '-$' : '$'
  if (abs >= 1_000_000) return `${prefix}${(abs / 1_000_000).toFixed(2)}M`
  if (abs >= 1_000) return `${prefix}${(abs / 1_000).toFixed(1)}K`
  return `${prefix}${abs.toFixed(decimals)}`
}

export function formatPnl(value: number, showSign = true): string {
  const sign = showSign && value > 0 ? '+' : ''
  return `${sign}${formatCurrency(value)}`
}

export function formatPercent(value: number, decimals = 2): string {
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(decimals)}%`
}
