export interface AdaptiveGridTrendPreset {
  fast: number
  slow: number
  entry: number
  stop: number
  takeProfit: number
  cooldownMinutes: number
  riskPercent?: number
  maxPositionUsd?: number
  leverage?: number
}

export const DEFAULT_ADAPTIVE_GRID_TREND_PRESET: AdaptiveGridTrendPreset = {
  fast: 30,
  slow: 60,
  entry: 0.6,
  stop: 2.8,
  takeProfit: 3.2,
  cooldownMinutes: 60,
  riskPercent: 2,
  maxPositionUsd: 800,
  leverage: 5,
}

export const ADAPTIVE_GRID_TREND_PRESETS: Record<string, AdaptiveGridTrendPreset> = {
  BTC: DEFAULT_ADAPTIVE_GRID_TREND_PRESET,
  ETH: DEFAULT_ADAPTIVE_GRID_TREND_PRESET,
  SOL: DEFAULT_ADAPTIVE_GRID_TREND_PRESET,
  XRP: DEFAULT_ADAPTIVE_GRID_TREND_PRESET,
  AVAX: DEFAULT_ADAPTIVE_GRID_TREND_PRESET,
  LINK: DEFAULT_ADAPTIVE_GRID_TREND_PRESET,
  LTC: DEFAULT_ADAPTIVE_GRID_TREND_PRESET,
  DOT: DEFAULT_ADAPTIVE_GRID_TREND_PRESET,
  BCH: DEFAULT_ADAPTIVE_GRID_TREND_PRESET,
  ADA: DEFAULT_ADAPTIVE_GRID_TREND_PRESET,
  DOGE: DEFAULT_ADAPTIVE_GRID_TREND_PRESET,
  TRX: DEFAULT_ADAPTIVE_GRID_TREND_PRESET,
}

export function extractCoin(symbol?: string): string {
  return symbol?.split('-')[0] ?? ''
}

export function getAdaptiveGridTrendPreset(symbol?: string): AdaptiveGridTrendPreset {
  const coin = extractCoin(symbol || 'BTC-USDT-SWAP')
  return ADAPTIVE_GRID_TREND_PRESETS[coin] ?? DEFAULT_ADAPTIVE_GRID_TREND_PRESET
}

export function getAdaptiveGridTrendPresetForBacktest(symbol?: string) {
  const preset = getAdaptiveGridTrendPreset(symbol)
  return {
    fast: preset.fast,
    slow: preset.slow,
    entry: preset.entry,
    stop: preset.stop,
    takeProfit: preset.takeProfit,
    cooldownSeconds: preset.cooldownMinutes * 60,
    riskPerTrade: (preset.riskPercent ?? DEFAULT_ADAPTIVE_GRID_TREND_PRESET.riskPercent ?? 2) / 100,
    maxPositionUsd:
      preset.maxPositionUsd ?? DEFAULT_ADAPTIVE_GRID_TREND_PRESET.maxPositionUsd ?? 800,
  }
}
