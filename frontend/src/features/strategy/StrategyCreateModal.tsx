import { useState, useEffect, useCallback } from 'react'
import {
  Modal, Form, Input, Select, Divider,
  Row, Col, Space, Tooltip, Alert, InputNumber, Switch, Spin, Button, Table, Tag, message,
} from 'antd'
import { InfoCircleOutlined, RiseOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { strategyApi, marketApi, aiApi } from '@/services/api'
import { API_BASE_URL } from '@/config/api'
import { extractCoin, getAdaptiveGridTrendPreset } from '@/config/strategyPresets'
import type { TopAltcoinStrategyCandidate } from '@/types'

const { TextArea } = Input
const TOP_GAINERS_SYMBOL = 'TOP-GAINERS-USDT-SWAP'
const TOP_GAINERS_NAME = '涨幅榜前三15m动量实盘'
const EXPLOSIVE_SYMBOL = 'EXPLOSIVE-MOMENTUM-USDT-SWAP'
const EXPLOSIVE_NAME = '爆量急拉追涨模拟'

interface StrategyCreateModalProps {
  open: boolean
  onCancel: () => void
  onSuccess: () => void
  /** 从下拉菜单预选的策略类型，打开时自动填入 */
  initialType?: string
  /** 若有值则为编辑模式，提交时调用 update 而非 create */
  editStrategyId?: number
  backtestData?: {
    strategy_type: string
    symbol: string
    parameters: Record<string, any>
    name?: string
  } | null
}

interface APIConfigOption {
  id: number
  name: string
  exchange: string
  is_simulated: boolean
  is_active: boolean
  is_valid: boolean
}

interface AdaptiveGridTrendRecommendationItem {
  symbol: string
  score: number
  return_pct: number
  max_drawdown_pct: number
  reason: string
}

interface AdaptiveGridTrendRecommendation {
  profile: string
  params: Record<string, any>
  active: AdaptiveGridTrendRecommendationItem[]
  watch: AdaptiveGridTrendRecommendationItem[]
  excluded: AdaptiveGridTrendRecommendationItem[]
  warning?: string
}

// 可用实盘策略类型（已通过回测验证）
const STRATEGY_TYPES: { value: string; label: string; desc: string }[] = [
  {
    value: 'adaptive_grid_trend',
    label: '自适应趋势网格',
    desc: '趋势过滤后按ATR回撤入场，固定风险仓位，硬止损止盈，不马丁不无限补仓',
  },
  {
    value: 'arbitrage',
    label: '现货-永续套利',
    desc: '买入现货并做空USDT永续，捕捉正向基差收敛，建议先用模拟盘小额验证',
  },
  {
    value: 'top_gainers_momentum',
    label: '涨幅榜前三15m动量',
    desc: '跟踪OKX USDT永续涨幅榜前三，用15m/5m动量和ATR风控自动交易，风险极高，建议先模拟盘',
  },
  {
    value: 'explosive_momentum_chaser',
    label: '爆量急拉追涨',
    desc: '扫描OKX高流动性USDT永续，按所选K线周期追爆量急拉币，固定持有，硬止损，高风险先模拟盘',
  },
]

// 交易对列表：合约（SWAP）优先，后接现货（SPOT）
const DEFAULT_SYMBOLS = [
  // ── 合约（USDT 本位永续）──
  'BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'SOL-USDT-SWAP', 'BNB-USDT-SWAP',
  'XRP-USDT-SWAP', 'DOGE-USDT-SWAP', 'ADA-USDT-SWAP', 'AVAX-USDT-SWAP',
  'LINK-USDT-SWAP', 'DOT-USDT-SWAP', 'LTC-USDT-SWAP', 'ATOM-USDT-SWAP',
  'ETC-USDT-SWAP', 'ARB-USDT-SWAP', 'OP-USDT-SWAP', 'APT-USDT-SWAP',
  'NEAR-USDT-SWAP', 'SUI-USDT-SWAP', 'TRX-USDT-SWAP', 'TON-USDT-SWAP',
  'KSM-USDT-SWAP', 'INJ-USDT-SWAP', 'SEI-USDT-SWAP', 'ORDI-USDT-SWAP',
  'WLD-USDT-SWAP', 'PEPE-USDT-SWAP',
  // ── 现货（SPOT）──
  'BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'BNB-USDT',
  'XRP-USDT', 'DOGE-USDT', 'ADA-USDT', 'AVAX-USDT',
  'LINK-USDT', 'DOT-USDT', 'LTC-USDT', 'ATOM-USDT',
]

const TIMEFRAMES = [
  { value: '1m', label: '1分钟' }, { value: '5m', label: '5分钟' },
  { value: '15m', label: '15分钟' }, { value: '30m', label: '30分钟' },
  { value: '1H', label: '1小时' }, { value: '4H', label: '4小时' },
  { value: '1D', label: '1天' },
]

// 策略类型短名（用于自动命名）
const TYPE_SHORT: Record<string, string> = {
  trend: '趋势跟踪',
  dual_side: '双向持仓',
  grid: '网格交易',
  adaptive_grid_trend: '自适应趋势网格',
  arbitrage: '现货-永续套利',
  top_gainers_momentum: '涨幅榜前三动量',
  explosive_momentum_chaser: '爆量急拉追涨',
}

// 生成自动名称，例如 BTC 趋势跟踪
function buildAutoName(type: string, symbol: string): string {
  if (type === 'top_gainers_momentum') return TOP_GAINERS_NAME
  if (type === 'explosive_momentum_chaser') return EXPLOSIVE_NAME
  const coin = extractCoin(symbol)
  const typeName = TYPE_SHORT[type] ?? type
  if (coin && typeName) return `${coin} ${typeName}`
  return ''
}

function percentValue(value: any, fallback?: number): number | undefined {
  if (value == null) return fallback
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return fallback
  return numeric <= 1 ? numeric * 100 : numeric
}

const StrategyCreateModal: React.FC<StrategyCreateModalProps> = ({
  open, onCancel, onSuccess, initialType, editStrategyId, backtestData,
}) => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [topAltcoinLoading, setTopAltcoinLoading] = useState(false)
  const [topAltcoinCandidates, setTopAltcoinCandidates] = useState<TopAltcoinStrategyCandidate[]>([])
  const [candidateMode, setCandidateMode] = useState<'top' | 'stealth'>('stealth')
  // 记录上一次自动生成的名称，用于判断用户是否手动修改过
  const [lastAutoName, setLastAutoName] = useState('')

  const { data: apiConfigs = [], isLoading: apiConfigsLoading } = useQuery<APIConfigOption[]>({
    queryKey: ['api-configs'],
    queryFn: async () => {
      const response = await fetch('/api/v1/api-configs/list')
      if (!response.ok) throw new Error('获取API配置失败')
      return response.json()
    },
    staleTime: 30 * 1000,
  })

  // 从OKX动态获取全量交易对（SWAP合约 + SPOT现货），USDT计价
  const { data: availableSymbols, isLoading: symbolsLoading } = useQuery({
    queryKey: ['okx-instruments-all'],
    queryFn: async () => {
      try {
        const [swapRes, spotRes] = await Promise.all([
          fetch(`${API_BASE_URL}/api/v1/market/instruments?inst_type=SWAP&quote_ccy=USDT`),
          fetch(`${API_BASE_URL}/api/v1/market/instruments?inst_type=SPOT&quote_ccy=USDT`),
        ])
        const swapJson = swapRes.ok ? await swapRes.json() : { data: [] }
        const spotJson = spotRes.ok ? await spotRes.json() : { data: [] }

        const swapSymbols: string[] = (swapJson.data ?? [])
          .map((i: any) => i.instId as string)
          .filter(Boolean)
          .sort()

        const spotSymbols: string[] = (spotJson.data ?? [])
          .map((i: any) => i.instId as string)
          .filter(Boolean)
          .sort()

        const all = [...swapSymbols, ...spotSymbols]
        return all.length > 0 ? all : DEFAULT_SYMBOLS
      } catch {
        return DEFAULT_SYMBOLS
      }
    },
    staleTime: 5 * 60 * 1000, // 5分钟内不重复请求
  })

  // 从下拉菜单预选类型
  useEffect(() => {
    if (initialType && open && !backtestData) {
      if (initialType === 'top_gainers_momentum') {
        form.setFieldsValue({
          type: initialType,
          symbol: TOP_GAINERS_SYMBOL,
          name: TOP_GAINERS_NAME,
          timeframe: '15m',
          tgm_timeframe: '15m',
        })
        setLastAutoName(TOP_GAINERS_NAME)
      } else if (initialType === 'explosive_momentum_chaser') {
        form.setFieldsValue({
          type: initialType,
          symbol: EXPLOSIVE_SYMBOL,
          name: EXPLOSIVE_NAME,
          timeframe: '1H',
          emc_timeframe: '1H',
        })
        setLastAutoName(EXPLOSIVE_NAME)
      } else {
        form.setFieldValue('type', initialType)
      }
    }
  }, [initialType, open, backtestData, form])

  useEffect(() => {
    if (!open || form.getFieldValue('api_config_id') != null || apiConfigs.length === 0) return
    const activeConfig = apiConfigs.find(config => config.is_active && config.is_valid)
    const firstValidConfig = apiConfigs.find(config => config.is_valid)
    const defaultConfig = activeConfig ?? firstValidConfig
    if (defaultConfig) {
      form.setFieldValue('api_config_id', defaultConfig.id)
    }
  }, [open, apiConfigs, form])

  // 从回测/策略预填数据
  useEffect(() => {
    if (backtestData && open) {
      const params = backtestData.parameters || {}
      const riskFuse = params.risk_fuse || {}
      form.setFieldsValue({
        type: backtestData.strategy_type,
        symbol: backtestData.symbol,
        name: backtestData.name || `${backtestData.symbol} ${backtestData.strategy_type}策略`,
        position_ratio: percentValue(params.position_ratio),
        stop_loss: percentValue(params.stop_loss),
        take_profit: percentValue(params.take_profit),
        use_rsi_filter: params.use_rsi_filter,
        leverage: params.leverage,
        use_trailing_stop: params.trailing_stop != null && Number(params.trailing_stop) > 0,
        trailing_stop: percentValue(params.trailing_stop),

        dual_position_ratio: percentValue(params.position_ratio),
        dual_leverage: params.leverage,
        dual_stop_loss: percentValue(params.stop_loss),
        dual_take_profit: percentValue(params.take_profit),
        use_dual_trailing_stop: params.trailing_stop != null && Number(params.trailing_stop) > 0,
        dual_trailing_stop: percentValue(params.trailing_stop),
        dual_timeframe: params.timeframe,

        grid_price_upper: params.price_upper,
        grid_price_lower: params.price_lower,
        grid_count: params.grid_count,
        grid_total_amount: params.total_amount,
        grid_leverage: params.leverage,
        grid_stop_loss: percentValue(params.stop_loss),

        agt_direction: params.direction,
        agt_timeframe: params.trend_timeframe || params.timeframe,
        agt_fast_period: params.fast_period,
        agt_slow_period: params.slow_period,
        agt_atr_period: params.atr_period,
        agt_entry_atr_multiple: params.entry_atr_multiple,
        agt_stop_atr_multiple: params.stop_atr_multiple,
        agt_take_profit_atr_multiple: params.take_profit_atr_multiple,
        agt_risk_per_trade: percentValue(params.risk_per_trade),
        agt_max_position_usd: params.max_position_usd,
        agt_leverage: params.leverage,
        agt_margin_mode: params.margin_mode,
        agt_cooldown_minutes: params.cooldown_seconds != null
          ? Math.round(Number(params.cooldown_seconds) / 60)
          : undefined,
        agt_notify_near_trigger: params.notify_near_trigger ?? true,
        agt_near_trigger_pct: params.near_trigger_pct != null
          ? percentValue(params.near_trigger_pct)
          : 0.3,
        agt_near_trigger_cooldown_minutes: params.near_trigger_cooldown_seconds != null
          ? Math.round(Number(params.near_trigger_cooldown_seconds) / 60)
          : 10,
        agt_fuse_enabled: riskFuse.enabled,
        agt_fuse_max_consecutive_losses: riskFuse.max_consecutive_losses,
        agt_fuse_daily_loss_pct: percentValue(riskFuse.daily_loss_limit_pct),
        agt_fuse_max_drawdown_pct: percentValue(riskFuse.max_drawdown_pct),
        agt_fuse_profit_factor_window: riskFuse.profit_factor_window,
        agt_fuse_min_trades: riskFuse.min_trades_for_profit_factor,
        agt_fuse_min_profit_factor: riskFuse.min_profit_factor,
        agt_fuse_cancel_orders: riskFuse.cancel_orders_on_trigger,
        agt_fuse_close_position: riskFuse.close_position_on_trigger,

        emc_timeframe: params.timeframe || '1H',
        emc_rank_feature: params.rank_feature,
        emc_hold_hours: params.hold_hours,
        emc_top_n: params.top_n,
        emc_min_signal_pct: percentValue(params.min_signal),
        emc_min_gap_pct: percentValue(params.min_gap),
        emc_min_vol_ratio: params.min_vol_ratio,
        emc_stop_loss_pct: percentValue(params.stop_loss_pct),
        emc_market_filter: params.market_filter,
        emc_universe_size: params.universe_size,
        emc_max_leverage: params.max_leverage,
        emc_max_position_usd: params.max_position_usd,
        emc_max_total_position_usd: params.max_total_position_usd,
        emc_max_open_positions: params.max_open_positions,
        emc_margin_mode: params.margin_mode,
        emc_loop_interval_seconds: params.loop_interval_seconds,
        emc_cooldown_minutes: params.cooldown_seconds != null
          ? Math.round(Number(params.cooldown_seconds) / 60)
          : undefined,
        emc_observe_first_scan: params.observe_first_scan,
        emc_use_volume_profile_filter: params.use_volume_profile_filter,
        emc_volume_profile_hours: params.volume_profile_hours,
        emc_volume_profile_bins: params.volume_profile_bins,
        emc_volume_profile_level: params.volume_profile_level,
        emc_max_high_pullback_pct: percentValue(params.max_high_pullback_pct),
        emc_initial_capital: riskFuse.risk_base_usd,
        emc_fuse_max_consecutive_losses: riskFuse.max_consecutive_losses,
        emc_fuse_daily_loss_pct: percentValue(riskFuse.daily_loss_limit_pct),
        emc_fuse_max_drawdown_pct: percentValue(riskFuse.max_drawdown_pct),
      })
    }
  }, [backtestData, open, form])

  // 自动命名：监听类型和交易对，只要名称为空或等于上次自动生成的值就覆盖
  const watchedType   = Form.useWatch('type',   form)
  const watchedSymbol = Form.useWatch('symbol', form)
  const watchedTgmTimeframe = Form.useWatch('tgm_timeframe', form)
  const watchedEmcTimeframe = Form.useWatch('emc_timeframe', form)
  const watchedEmcVolumeProfile = Form.useWatch('emc_use_volume_profile_filter', form)
  const isDynamicUniverse = watchedType === 'top_gainers_momentum' || watchedType === 'explosive_momentum_chaser'

  const { data: agtRecommendation, isLoading: agtRecommendationLoading } = useQuery<AdaptiveGridTrendRecommendation>({
    queryKey: ['adaptive-grid-trend-recommendation'],
    queryFn: () => strategyApi.getAdaptiveGridTrendRecommendation(),
    enabled: open && watchedType === 'adaptive_grid_trend' && !backtestData && editStrategyId == null,
    staleTime: 60 * 1000,
  })

  useEffect(() => {
    if (!open || backtestData || watchedType !== 'adaptive_grid_trend') return
    const preset = getAdaptiveGridTrendPreset(watchedSymbol)
    form.setFieldsValue({
      agt_fast_period: preset.fast,
      agt_slow_period: preset.slow,
      agt_entry_atr_multiple: preset.entry,
      agt_stop_atr_multiple: preset.stop,
      agt_take_profit_atr_multiple: preset.takeProfit,
      agt_cooldown_minutes: preset.cooldownMinutes,
      agt_risk_per_trade: preset.riskPercent ?? 2,
      agt_max_position_usd: preset.maxPositionUsd ?? 800,
      agt_leverage: preset.leverage ?? 5,
      agt_notify_near_trigger: true,
      agt_near_trigger_pct: 0.3,
      agt_near_trigger_cooldown_minutes: 10,
    })
  }, [open, backtestData, watchedType, watchedSymbol, form])

  useEffect(() => {
    if (!open || backtestData || watchedType !== 'top_gainers_momentum') return
    const current = form.getFieldValue('name') ?? ''
    if (current === '' || current === lastAutoName || current.includes('BTC') || current.includes('自适应趋势网格')) {
      form.setFieldValue('name', TOP_GAINERS_NAME)
      setLastAutoName(TOP_GAINERS_NAME)
    }
    if (form.getFieldValue('symbol') !== TOP_GAINERS_SYMBOL) {
      form.setFieldValue('symbol', TOP_GAINERS_SYMBOL)
    }
    form.setFieldValue('timeframe', form.getFieldValue('tgm_timeframe') ?? '15m')
  }, [open, backtestData, watchedType, form, lastAutoName])

  useEffect(() => {
    if (!open || backtestData || watchedType !== 'explosive_momentum_chaser') return
    const current = form.getFieldValue('name') ?? ''
    if (current === '' || current === lastAutoName || current.includes('BTC') || current.includes('自适应趋势网格')) {
      form.setFieldValue('name', EXPLOSIVE_NAME)
      setLastAutoName(EXPLOSIVE_NAME)
    }
    if (form.getFieldValue('symbol') !== EXPLOSIVE_SYMBOL) {
      form.setFieldValue('symbol', EXPLOSIVE_SYMBOL)
    }
    const timeframe = form.getFieldValue('emc_timeframe') ?? '1H'
    form.setFieldsValue({ timeframe, emc_timeframe: timeframe })
  }, [open, backtestData, watchedType, watchedEmcTimeframe, form, lastAutoName])

  useEffect(() => {
    if (!open || backtestData || watchedType !== 'top_gainers_momentum') return
    if (watchedTgmTimeframe === '5m') {
      form.setFieldsValue({
        tgm_risk_per_trade: 2.5,
        tgm_max_leverage: 5,
        tgm_stop_atr: 1.8,
        tgm_take_profit_r: 1.8,
        tgm_trailing_atr: 1.6,
      })
    } else if (watchedTgmTimeframe === '15m') {
      form.setFieldsValue({
        tgm_risk_per_trade: 3.5,
        tgm_max_leverage: 7,
        tgm_stop_atr: 2.1,
        tgm_take_profit_r: 2,
        tgm_trailing_atr: 1.8,
      })
    }
  }, [open, backtestData, watchedType, watchedTgmTimeframe, form])

  useEffect(() => {
    if (backtestData) return   // 回测模式不覆盖
    const auto = buildAutoName(watchedType, watchedSymbol)
    if (!auto) return
    const current = form.getFieldValue('name') ?? ''
    if (current === '' || current === lastAutoName) {
      form.setFieldValue('name', auto)
      setLastAutoName(auto)
    }
  }, [watchedType, watchedSymbol])

  // 弹窗关闭时重置自动名称记录
  useEffect(() => {
    if (!open) {
      setLastAutoName('')
      setGridTickerLoading(false)
      setTopAltcoinCandidates([])
      setCandidateMode('stealth')
    }
  }, [open])

  // ── 网格策略：选择交易对后自动获取24h行情填充上下界 ──
  const [gridTickerLoading, setGridTickerLoading] = useState(false)
  const fetchGridTicker = useCallback(async (symbol: string) => {
    if (!symbol) return
    setGridTickerLoading(true)
    try {
      const ticker = await marketApi.getTicker(symbol)
      if (ticker) {
        const last = parseFloat(ticker.last || '0')
        const high24h = parseFloat(ticker.high24h || '0')
        const low24h = parseFloat(ticker.low24h || '0')

        if (last > 0 && high24h > 0 && low24h > 0) {
          // 以24h高低价为基础，向外扩展一定比例作为网格范围
          const range = high24h - low24h
          const padding = range * 0.2 // 上下各扩展20%
          const lower = Math.max(0, low24h - padding)
          const upper = high24h + padding

          // 根据价格量级决定小数位数
          const decimals = last >= 1000 ? 1 : last >= 10 ? 2 : last >= 1 ? 4 : 6
          form.setFieldsValue({
            grid_price_lower: parseFloat(lower.toFixed(decimals)),
            grid_price_upper: parseFloat(upper.toFixed(decimals)),
          })
        }
      }
    } catch (e) {
      // 获取失败不阻塞用户操作
    } finally {
      setGridTickerLoading(false)
    }
  }, [form])

  // 监听交易对变化：如果是网格类型，切换交易对时自动重新获取价格
  const [prevGridSymbol, setPrevGridSymbol] = useState<string>('')
  useEffect(() => {
    if (watchedType === 'grid' && watchedSymbol && !backtestData && watchedSymbol !== prevGridSymbol) {
      setPrevGridSymbol(watchedSymbol)
      form.setFieldsValue({ grid_price_lower: undefined, grid_price_upper: undefined })
      fetchGridTicker(watchedSymbol)
    }
  }, [watchedSymbol])

  // 切换到网格类型时，如果已有交易对，自动获取价格
  useEffect(() => {
    if (watchedType === 'grid' && watchedSymbol && !backtestData) {
      const currentLower = form.getFieldValue('grid_price_lower')
      const currentUpper = form.getFieldValue('grid_price_upper')
      if (!currentLower && !currentUpper) {
        setPrevGridSymbol(watchedSymbol)
        fetchGridTicker(watchedSymbol)
      }
    }
  }, [watchedType])

  // 提交
  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setLoading(true)

      // 构建策略参数（根据策略类型提取对应字段）
      const parameters: Record<string, any> = {}
      if (values.type === 'trend') {
        parameters.position_ratio  = (values.position_ratio ?? 40) / 100   // 百分比 → 小数
        parameters.stop_loss       = (values.stop_loss ?? 3) / 100
        parameters.take_profit     = (values.take_profit ?? 8) / 100
        parameters.use_rsi_filter  = values.use_rsi_filter ?? true
        parameters.leverage        = values.leverage ?? 10
        parameters.trailing_stop   = values.use_trailing_stop
          ? (values.trailing_stop ?? 2) / 100
          : 0  // 0 表示禁用移动止损，使用固定止损
        // fast_period / slow_period 使用策略内置最优值（12/40），不对外暴露
      } else if (values.type === 'dual_side') {
        // 双向持仓策略参数
        parameters.position_ratio  = (values.dual_position_ratio ?? 30) / 100
        parameters.leverage        = values.dual_leverage ?? 5
        parameters.stop_loss       = (values.dual_stop_loss ?? 2) / 100
        parameters.take_profit     = (values.dual_take_profit ?? 6) / 100
        parameters.trailing_stop   = values.use_dual_trailing_stop
          ? (values.dual_trailing_stop ?? 2) / 100
          : 0.02  // 默认启用2%移动止损
        parameters.timeframe       = values.dual_timeframe ?? '15m'
      } else if (values.type === 'grid') {
        parameters.price_upper   = values.grid_price_upper
        parameters.price_lower   = values.grid_price_lower
        parameters.grid_count    = values.grid_count ?? 10
        parameters.total_amount  = values.grid_total_amount ?? 100
        parameters.leverage      = values.grid_leverage ?? 1
        parameters.stop_loss     = (values.grid_stop_loss ?? 5) / 100
      } else if (values.type === 'adaptive_grid_trend') {
        parameters.direction                = values.agt_direction ?? 'both'
        parameters.trend_timeframe          = values.agt_timeframe ?? '15m'
        parameters.fast_period              = values.agt_fast_period ?? 30
        parameters.slow_period              = values.agt_slow_period ?? 60
        parameters.atr_period               = values.agt_atr_period ?? 14
        parameters.entry_atr_multiple       = values.agt_entry_atr_multiple ?? 0.6
        parameters.stop_atr_multiple        = values.agt_stop_atr_multiple ?? 2.8
        parameters.take_profit_atr_multiple = values.agt_take_profit_atr_multiple ?? 3.2
        parameters.risk_per_trade           = (values.agt_risk_per_trade ?? 2) / 100
        parameters.max_position_usd         = values.agt_max_position_usd ?? 800
        parameters.leverage                 = values.agt_leverage ?? 5
        parameters.margin_mode              = values.agt_margin_mode ?? 'isolated'
        parameters.cooldown_seconds         = (values.agt_cooldown_minutes ?? 60) * 60
        parameters.notify_near_trigger      = values.agt_notify_near_trigger ?? true
        parameters.near_trigger_pct         = (values.agt_near_trigger_pct ?? 0.3) / 100
        parameters.near_trigger_cooldown_seconds = (values.agt_near_trigger_cooldown_minutes ?? 10) * 60
        parameters.risk_fuse                = {
          enabled: values.agt_fuse_enabled ?? true,
          max_consecutive_losses: values.agt_fuse_max_consecutive_losses ?? 2,
          daily_loss_limit_pct: (values.agt_fuse_daily_loss_pct ?? 3) / 100,
          max_drawdown_pct: (values.agt_fuse_max_drawdown_pct ?? 5) / 100,
          profit_factor_window: values.agt_fuse_profit_factor_window ?? 10,
          min_trades_for_profit_factor: values.agt_fuse_min_trades ?? 8,
          min_profit_factor: values.agt_fuse_min_profit_factor ?? 0.8,
          cancel_orders_on_trigger: values.agt_fuse_cancel_orders ?? true,
          close_position_on_trigger: values.agt_fuse_close_position ?? false,
        }
      } else if (values.type === 'arbitrage') {
        const baseSymbol = String(values.symbol || 'BTC-USDT-SWAP').replace(/-SWAP$/, '')
        parameters.spot_symbol          = values.arb_spot_symbol || baseSymbol
        parameters.perp_symbol          = values.arb_perp_symbol || `${baseSymbol}-SWAP`
        parameters.target_notional_usd  = values.arb_target_notional_usd ?? 100
        parameters.max_notional_usd     = values.arb_max_notional_usd ?? values.arb_target_notional_usd ?? 100
        parameters.open_edge_threshold  = (values.arb_open_edge_pct ?? 0.3) / 100
        parameters.close_edge_threshold = (values.arb_close_edge_pct ?? 0.08) / 100
        parameters.min_net_edge         = (values.arb_min_net_edge_pct ?? 0.15) / 100
        parameters.fee_buffer           = (values.arb_fee_buffer_pct ?? 0.12) / 100
        parameters.slippage_buffer      = (values.arb_slippage_buffer_pct ?? 0.08) / 100
        parameters.poll_interval        = values.arb_poll_interval ?? 1
        parameters.leverage             = values.arb_leverage ?? 1
        parameters.margin_mode          = values.arb_margin_mode ?? 'isolated'
        parameters.close_on_stop        = values.arb_close_on_stop ?? false
      } else if (values.type === 'top_gainers_momentum') {
        parameters.mode                 = 'live_trading'
        parameters.universe             = 'okx_usdt_swap_top_gainers'
        parameters.direction            = values.tgm_direction ?? 'both'
        parameters.top_n                = values.tgm_top_n ?? 3
        parameters.timeframe            = values.tgm_timeframe ?? '15m'
        parameters.initial_capital      = values.tgm_initial_capital ?? 1000
        parameters.lookback_hours       = values.tgm_lookback_hours ?? 24
        parameters.risk_per_trade       = (values.tgm_risk_per_trade ?? 3.5) / 100
        parameters.max_leverage         = values.tgm_max_leverage ?? 7
        parameters.max_position_usd     = values.tgm_max_position_usd ?? 300
        parameters.max_total_position_usd = values.tgm_max_total_position_usd ?? values.tgm_max_position_usd ?? 300
        parameters.max_open_positions   = values.tgm_max_open_positions ?? 1
        parameters.margin_mode          = values.tgm_margin_mode ?? 'isolated'
        parameters.loop_interval_seconds = values.tgm_loop_interval_seconds ?? 60
        parameters.cooldown_seconds     = (values.tgm_cooldown_minutes ?? 15) * 60
        parameters.observe_first_scan   = values.tgm_observe_first_scan ?? true
        parameters.use_attached_tp_sl   = values.tgm_use_attached_tp_sl ?? true
        parameters.close_when_out_of_top = values.tgm_close_when_out_of_top ?? false
        parameters.stop_atr             = values.tgm_stop_atr ?? 2.1
        parameters.take_profit_r        = values.tgm_take_profit_r ?? 2
        parameters.trailing_atr         = values.tgm_trailing_atr ?? 1.8
        parameters.min_24h_change_pct   = values.tgm_min_24h_change_pct ?? 0
        parameters.risk_fuse            = {
          enabled: true,
          max_consecutive_losses: values.tgm_fuse_max_consecutive_losses ?? 2,
          daily_loss_limit_pct: (values.tgm_fuse_daily_loss_pct ?? 8) / 100,
          max_drawdown_pct: (values.tgm_fuse_max_drawdown_pct ?? 12) / 100,
          cancel_orders_on_trigger: true,
          close_position_on_trigger: false,
          risk_base_usd: values.tgm_initial_capital ?? 1000,
        }
      } else if (values.type === 'explosive_momentum_chaser') {
        parameters.mode                  = 'sim_first_live_capable'
        parameters.universe              = 'okx_usdt_swap_liquid_intraday'
        parameters.timeframe             = values.emc_timeframe ?? '1H'
        parameters.rank_feature          = values.emc_rank_feature ?? 'ret_1h'
        parameters.hold_hours            = values.emc_hold_hours ?? 4
        parameters.top_n                 = values.emc_top_n ?? 1
        parameters.min_signal            = (values.emc_min_signal_pct ?? 6) / 100
        parameters.min_gap               = (values.emc_min_gap_pct ?? 1) / 100
        parameters.min_vol_ratio         = values.emc_min_vol_ratio ?? 1.2
        parameters.stop_loss_pct         = (values.emc_stop_loss_pct ?? 4) / 100
        parameters.market_filter         = values.emc_market_filter ?? 'btc_4h_positive'
        parameters.universe_size         = values.emc_universe_size ?? 50
        parameters.max_leverage          = values.emc_max_leverage ?? 3
        parameters.max_position_usd      = values.emc_max_position_usd ?? 300
        parameters.max_total_position_usd = values.emc_max_total_position_usd ?? values.emc_max_position_usd ?? 300
        parameters.max_open_positions    = values.emc_max_open_positions ?? 1
        parameters.margin_mode           = values.emc_margin_mode ?? 'isolated'
        parameters.loop_interval_seconds = values.emc_loop_interval_seconds ?? 60
        parameters.cooldown_seconds      = (values.emc_cooldown_minutes ?? 240) * 60
        parameters.observe_first_scan    = values.emc_observe_first_scan ?? true
        parameters.use_attached_tp_sl     = true
        parameters.use_volume_profile_filter = values.emc_use_volume_profile_filter ?? false
        parameters.volume_profile_hours  = values.emc_volume_profile_hours ?? 8
        parameters.volume_profile_bins   = values.emc_volume_profile_bins ?? 48
        parameters.volume_profile_level  = values.emc_volume_profile_level ?? 'poc'
        parameters.max_high_pullback_pct = (values.emc_max_high_pullback_pct ?? 2) / 100
        parameters.risk_fuse             = {
          enabled: true,
          max_consecutive_losses: values.emc_fuse_max_consecutive_losses ?? 2,
          daily_loss_limit_pct: (values.emc_fuse_daily_loss_pct ?? 20) / 100,
          max_drawdown_pct: (values.emc_fuse_max_drawdown_pct ?? 30) / 100,
          cancel_orders_on_trigger: true,
          close_position_on_trigger: true,
          risk_base_usd: values.emc_initial_capital ?? 1000,
        }
      }

      const payload = {
        name: values.name,
        type: values.type as any,
        symbol: values.type === 'top_gainers_momentum' ? TOP_GAINERS_SYMBOL
               : values.type === 'explosive_momentum_chaser' ? EXPLOSIVE_SYMBOL
               : values.symbol,
        api_config_id: values.api_config_id,
        timeframe: values.type === 'trend' ? '15m'
                 : values.type === 'dual_side' ? (values.dual_timeframe ?? '15m')
                 : values.type === 'grid' ? '1m'
                 : values.type === 'adaptive_grid_trend' ? (values.agt_timeframe ?? '15m')
                 : values.type === 'arbitrage' ? '1m'
                 : values.type === 'top_gainers_momentum' ? (values.tgm_timeframe ?? '15m')
                 : values.type === 'explosive_momentum_chaser' ? (values.emc_timeframe ?? '1H')
                 : (values.timeframe ?? '1H'),
        parameters,
        description: values.description,
      } as any

      if (editStrategyId != null) {
        await strategyApi.update(editStrategyId, payload)
      } else {
        await strategyApi.create(payload)
      }

      form.resetFields()
      onSuccess()
    } catch (err: any) {
      if (err?.errorFields) return
    } finally {
      setLoading(false)
    }
  }

  const handleCancel = () => { form.resetFields(); onCancel() }

  const applyAdaptiveGridTrendRecommendation = (
    item: AdaptiveGridTrendRecommendationItem,
    groupLabel: string
  ) => {
    const params = agtRecommendation?.params || {}
    const coin = extractCoin(item.symbol)
    form.setFieldsValue({
      name: `${coin} 自适应趋势网格 1000U稳健`,
      symbol: item.symbol,
      timeframe: params.trend_timeframe ?? '15m',
      agt_direction: params.direction ?? 'both',
      agt_timeframe: params.trend_timeframe ?? '15m',
      agt_fast_period: params.fast_period ?? 30,
      agt_slow_period: params.slow_period ?? 60,
      agt_atr_period: params.atr_period ?? 14,
      agt_entry_atr_multiple: params.entry_atr_multiple ?? 0.6,
      agt_stop_atr_multiple: params.stop_atr_multiple ?? 2.8,
      agt_take_profit_atr_multiple: params.take_profit_atr_multiple ?? 3.2,
      agt_risk_per_trade: percentValue(params.risk_per_trade, 2),
      agt_max_position_usd: params.max_position_usd ?? 800,
      agt_leverage: params.leverage ?? 5,
      agt_margin_mode: params.margin_mode ?? 'isolated',
      agt_cooldown_minutes: params.cooldown_seconds != null ? Math.round(Number(params.cooldown_seconds) / 60) : 60,
      agt_notify_near_trigger: params.notify_near_trigger ?? true,
      agt_near_trigger_pct: params.near_trigger_pct != null ? percentValue(params.near_trigger_pct, 0.3) : 0.3,
      agt_near_trigger_cooldown_minutes: params.near_trigger_cooldown_seconds != null
        ? Math.round(Number(params.near_trigger_cooldown_seconds) / 60)
        : 10,
      agt_fuse_enabled: params.risk_fuse?.enabled ?? true,
      agt_fuse_max_consecutive_losses: params.risk_fuse?.max_consecutive_losses ?? 2,
      agt_fuse_daily_loss_pct: percentValue(params.risk_fuse?.daily_loss_limit_pct, 3),
      agt_fuse_max_drawdown_pct: percentValue(params.risk_fuse?.max_drawdown_pct, 5),
      agt_fuse_profit_factor_window: params.risk_fuse?.profit_factor_window ?? 10,
      agt_fuse_min_trades: params.risk_fuse?.min_trades_for_profit_factor ?? 8,
      agt_fuse_min_profit_factor: params.risk_fuse?.min_profit_factor ?? 0.8,
      agt_fuse_cancel_orders: params.risk_fuse?.cancel_orders_on_trigger ?? true,
      agt_fuse_close_position: params.risk_fuse?.close_position_on_trigger ?? false,
    })
    setLastAutoName(`${coin} 自适应趋势网格 1000U稳健`)
    message.success(`已套用${groupLabel}: ${item.symbol}`)
  }

  const applyStrategyRecommendation = (candidate: TopAltcoinStrategyCandidate) => {
    const params = candidate.recommended_strategy.parameters || {}
    form.setFieldsValue({
      type: candidate.recommended_strategy.type,
      symbol: candidate.symbol,
      timeframe: candidate.recommended_strategy.timeframe,
      name: buildAutoName(candidate.recommended_strategy.type, candidate.symbol),
      agt_direction: params.direction,
      agt_timeframe: params.trend_timeframe,
      agt_fast_period: params.fast_period,
      agt_slow_period: params.slow_period,
      agt_atr_period: params.atr_period,
      agt_entry_atr_multiple: params.entry_atr_multiple,
      agt_stop_atr_multiple: params.stop_atr_multiple,
      agt_take_profit_atr_multiple: params.take_profit_atr_multiple,
      agt_risk_per_trade: percentValue(params.risk_per_trade),
      agt_max_position_usd: params.max_position_usd,
      agt_leverage: params.leverage,
      agt_margin_mode: params.margin_mode,
      agt_cooldown_minutes: params.cooldown_seconds != null ? Math.round(Number(params.cooldown_seconds) / 60) : undefined,
      agt_notify_near_trigger: params.notify_near_trigger,
      agt_near_trigger_pct: percentValue(params.near_trigger_pct),
      agt_near_trigger_cooldown_minutes: params.near_trigger_cooldown_seconds != null
        ? Math.round(Number(params.near_trigger_cooldown_seconds) / 60)
        : undefined,
      agt_fuse_enabled: params.risk_fuse?.enabled,
      agt_fuse_max_consecutive_losses: params.risk_fuse?.max_consecutive_losses,
      agt_fuse_daily_loss_pct: percentValue(params.risk_fuse?.daily_loss_limit_pct),
      agt_fuse_max_drawdown_pct: percentValue(params.risk_fuse?.max_drawdown_pct),
      agt_fuse_profit_factor_window: params.risk_fuse?.profit_factor_window,
      agt_fuse_min_trades: params.risk_fuse?.min_trades_for_profit_factor,
      agt_fuse_min_profit_factor: params.risk_fuse?.min_profit_factor,
      agt_fuse_cancel_orders: params.risk_fuse?.cancel_orders_on_trigger,
      agt_fuse_close_position: params.risk_fuse?.close_position_on_trigger,
      description: `来自${candidateMode === 'stealth' ? '潜伏候选' : '24h涨幅榜'}分析：涨幅 ${candidate.change_pct.toFixed(2)}%，${candidate.analysis.reasoning}`,
    })
    message.success(`已套用 ${candidate.symbol} 的策略建议`)
  }

  const fetchTopAltcoinStrategies = async () => {
    setTopAltcoinLoading(true)
    try {
      const result = await aiApi.analyzeTopAltcoinStrategies({
        limit: 5,
        inst_type: 'SWAP',
        quote_ccy: 'USDT',
        min_volume_usdt: 1000000,
        exclude_majors: true,
      })
      setCandidateMode('top')
      setTopAltcoinCandidates(result.items || [])
      if (!result.items?.length) {
        message.info('暂未找到满足成交量条件的涨幅榜山寨币')
      }
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '涨幅榜分析失败')
    } finally {
      setTopAltcoinLoading(false)
    }
  }

  const fetchStealthAltcoinStrategies = async () => {
    setTopAltcoinLoading(true)
    try {
      const result = await aiApi.analyzeStealthAltcoinStrategies({
        limit: 5,
        inst_type: 'SWAP',
        quote_ccy: 'USDT',
        min_volume_usdt: 3000000,
        min_range_pct: 3,
        max_range_pct: 12,
        min_change_pct: -8,
        max_change_pct: 8,
        trend_timeframe: '15m',
        trend_lookback: 192,
        max_lookback_drop_pct: 10,
        min_ma_gap_pct: -2,
        max_recent_position: 0.75,
        exclude_majors: true,
      })
      setCandidateMode('stealth')
      setTopAltcoinCandidates(result.items || [])
      if (!result.items?.length) {
        message.info('暂未找到满足潜伏条件的山寨币')
      }
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '潜伏候选分析失败')
    } finally {
      setTopAltcoinLoading(false)
    }
  }

  const compactDivider = { fontSize: 12, color: '#8c8c8c', margin: '12px 0 8px' }
  const compactItem = { marginBottom: 8 }

  const noTypes = STRATEGY_TYPES.length === 0
  const selectedType = Form.useWatch('type', form)
  const useTrailingStop = Form.useWatch('use_trailing_stop', form)
  const decisionColor: Record<string, string> = { long: 'green', short: 'red', wait: 'default' }
  const decisionText: Record<string, string> = { long: '做多', short: '做空', wait: '观望' }

  return (
    <Modal
      title={editStrategyId != null ? '编辑策略' : backtestData ? '从回测创建策略' : '创建策略'}
      open={open}
      onCancel={handleCancel}
      onOk={handleSubmit}
      okText={editStrategyId != null ? '保存' : '创建'}
      cancelText="取消"
      width={600}
      confirmLoading={loading}
      okButtonProps={{ disabled: noTypes && !backtestData }}
      destroyOnHidden
      styles={{ body: { maxHeight: '65vh', overflowY: 'auto', paddingRight: 4 } }}
    >
      {backtestData && (
        <Alert
          message="已自动填充回测参数，可按需调整"
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
        />
      )}

      {noTypes && !backtestData && (
        <Alert
          message="暂无可用实盘策略类型"
          description="所有实盘策略均在开发中，敬请期待。"
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
        />
      )}

      <Form
        form={form}
        layout="vertical"
        initialValues={{
          type: backtestData?.strategy_type ?? 'adaptive_grid_trend',
          symbol: backtestData?.symbol || 'BTC-USDT-SWAP',
          api_config_id: undefined,
          timeframe: '15m',
          position_ratio: 40,
          stop_loss: 3,
          take_profit: 8,
          leverage: 10,
          use_rsi_filter: true,
          use_trailing_stop: false,
          trailing_stop: 2,
          // 网格策略默认值
          grid_count: 10,
          grid_total_amount: 100,
          grid_leverage: 1,
          grid_stop_loss: 5,
          // 自适应趋势网格默认值
          agt_direction: 'both',
          agt_timeframe: '15m',
          agt_fast_period: 30,
          agt_slow_period: 60,
          agt_atr_period: 14,
          agt_entry_atr_multiple: 0.6,
          agt_stop_atr_multiple: 2.8,
          agt_take_profit_atr_multiple: 3.2,
          agt_risk_per_trade: 2,
          agt_max_position_usd: 800,
          agt_leverage: 5,
          agt_margin_mode: 'isolated',
          agt_cooldown_minutes: 60,
          agt_notify_near_trigger: true,
          agt_near_trigger_pct: 0.3,
          agt_near_trigger_cooldown_minutes: 10,
          agt_fuse_enabled: true,
          agt_fuse_max_consecutive_losses: 2,
          agt_fuse_daily_loss_pct: 3,
          agt_fuse_max_drawdown_pct: 5,
          agt_fuse_profit_factor_window: 10,
          agt_fuse_min_trades: 8,
          agt_fuse_min_profit_factor: 0.8,
          agt_fuse_cancel_orders: true,
          agt_fuse_close_position: false,
          arb_target_notional_usd: 100,
          arb_max_notional_usd: 100,
          arb_open_edge_pct: 0.3,
          arb_close_edge_pct: 0.08,
          arb_min_net_edge_pct: 0.15,
          arb_fee_buffer_pct: 0.12,
          arb_slippage_buffer_pct: 0.08,
          arb_poll_interval: 1,
          arb_leverage: 1,
          arb_margin_mode: 'isolated',
          arb_close_on_stop: false,
          tgm_timeframe: '15m',
          tgm_direction: 'both',
          tgm_top_n: 3,
          tgm_initial_capital: 1000,
          tgm_lookback_hours: 24,
          tgm_risk_per_trade: 3.5,
          tgm_max_leverage: 7,
          tgm_max_position_usd: 300,
          tgm_max_total_position_usd: 300,
          tgm_max_open_positions: 1,
          tgm_margin_mode: 'isolated',
          tgm_loop_interval_seconds: 60,
          tgm_cooldown_minutes: 15,
          tgm_observe_first_scan: true,
          tgm_use_attached_tp_sl: true,
          tgm_close_when_out_of_top: false,
          tgm_stop_atr: 2.1,
          tgm_take_profit_r: 2,
          tgm_trailing_atr: 1.8,
          tgm_min_24h_change_pct: 0,
          tgm_fuse_max_consecutive_losses: 2,
          tgm_fuse_daily_loss_pct: 8,
          tgm_fuse_max_drawdown_pct: 12,
          emc_timeframe: '1H',
          emc_rank_feature: 'ret_1h',
          emc_hold_hours: 4,
          emc_top_n: 1,
          emc_min_signal_pct: 6,
          emc_min_gap_pct: 1,
          emc_min_vol_ratio: 1.2,
          emc_stop_loss_pct: 4,
          emc_market_filter: 'btc_4h_positive',
          emc_universe_size: 50,
          emc_initial_capital: 1000,
          emc_max_leverage: 3,
          emc_max_position_usd: 300,
          emc_max_total_position_usd: 300,
          emc_max_open_positions: 1,
          emc_margin_mode: 'isolated',
          emc_loop_interval_seconds: 60,
          emc_cooldown_minutes: 240,
          emc_observe_first_scan: true,
          emc_use_volume_profile_filter: false,
          emc_volume_profile_hours: 8,
          emc_volume_profile_bins: 48,
          emc_volume_profile_level: 'poc',
          emc_max_high_pullback_pct: 2,
          emc_fuse_max_consecutive_losses: 2,
          emc_fuse_daily_loss_pct: 20,
          emc_fuse_max_drawdown_pct: 30,
        }}
      >
        {/* ── 基础信息 ── */}
        <Divider orientation="left" style={compactDivider}>基础信息</Divider>
        <Row gutter={12}>
          <Col span={24}>
            <Form.Item name="name" label="策略名称" rules={[{ required: true, message: '请输入策略名称' }]} style={compactItem}>
              <Input placeholder="为策略起一个名字，如：BTC网格01" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="type" label="策略类型" rules={[{ required: true, message: '请选择策略类型' }]} style={compactItem}>
              <Select
                placeholder={noTypes ? '暂无可用策略类型' : '选择策略类型'}
                disabled={noTypes && !backtestData}
                options={STRATEGY_TYPES.map(t => ({ value: t.value, label: t.label }))}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              name="api_config_id"
              label="交易账户"
              rules={[{ required: true, message: '请选择交易账户' }]}
              style={compactItem}
            >
              <Select
                loading={apiConfigsLoading}
                placeholder="选择实盘或模拟盘账户"
                options={apiConfigs.map(config => ({
                  value: config.id,
                  label: `${config.name} · ${config.is_simulated ? '模拟盘' : '实盘'}${config.is_valid ? '' : ' · 无效'}`,
                  disabled: !config.is_valid,
                }))}
              />
            </Form.Item>
          </Col>
          {!isDynamicUniverse && (
            <Col span={12}>
              <Form.Item name="timeframe" label="K线周期" style={compactItem}>
                <Select placeholder="选择周期">
                  {TIMEFRAMES.map(tf => (
                    <Select.Option key={tf.value} value={tf.value}>{tf.label}</Select.Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
          )}
          <Col span={24}>
            <Form.Item
              name="symbol"
              label={
                <Space size={4}>
                  交易对
                  <Tooltip title={isDynamicUniverse
                    ? '动态策略会自动从OKX USDT永续池选择币种，这里只保存动态池占位符'
                    : '合约策略请选择 XXX-USDT-SWAP 格式；现货策略请选择 XXX-USDT 格式'
                  }>
                    <InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 13 }} />
                  </Tooltip>
                </Space>
              }
              rules={[{ required: true, message: '请选择交易对' }]}
              style={compactItem}
            >
              <Select
                showSearch
                allowClear
                disabled={isDynamicUniverse}
                loading={isDynamicUniverse ? false : symbolsLoading}
                placeholder={isDynamicUniverse
                  ? '动态OKX USDT永续池'
                  : symbolsLoading ? '加载交易对中...' : '搜索交易对，如 BTC-USDT-SWAP'
                }
                filterOption={(input, option) =>
                  String(option?.value ?? '').toLowerCase().includes(input.toLowerCase())
                }
              >
                {selectedType === 'top_gainers_momentum' && (
                  <Select.Option value={TOP_GAINERS_SYMBOL}>
                    动态涨幅榜前三 · OKX USDT永续
                  </Select.Option>
                )}
                {selectedType === 'explosive_momentum_chaser' && (
                  <Select.Option value={EXPLOSIVE_SYMBOL}>
                    动态爆量急拉池 · OKX USDT永续
                  </Select.Option>
                )}
                <Select.OptGroup label="合约（SWAP）">
                  {(availableSymbols ?? DEFAULT_SYMBOLS)
                    .filter(s => s.endsWith('-SWAP'))
                    .map(s => <Select.Option key={s} value={s}>{s}</Select.Option>)}
                </Select.OptGroup>
                <Select.OptGroup label="现货（SPOT）">
                  {(availableSymbols ?? DEFAULT_SYMBOLS)
                    .filter(s => !s.endsWith('-SWAP'))
                    .map(s => <Select.Option key={s} value={s}>{s}</Select.Option>)}
                </Select.OptGroup>
              </Select>
            </Form.Item>
          </Col>
        </Row>

        {!editStrategyId && !backtestData && !isDynamicUniverse && (
          <>
            <Divider orientation="left" style={compactDivider}>候选分析</Divider>
            {selectedType === 'adaptive_grid_trend' && (
              <Alert
                message={
                  <Space direction="vertical" size={8} style={{ width: '100%' }}>
                    <Space wrap>
                      <span style={{ fontWeight: 600 }}>1000U稳健实盘选币</span>
                      {agtRecommendationLoading && <Tag>加载中</Tag>}
                      {agtRecommendation?.warning && <Tag color="orange">静态推荐</Tag>}
                    </Space>
                    <Space direction="vertical" size={6} style={{ width: '100%' }}>
                      <Space wrap>
                        <span style={{ color: '#595959' }}>建议运行</span>
                        {(agtRecommendation?.active || []).map(item => (
                          <Button
                            key={item.symbol}
                            size="small"
                            type={watchedSymbol === item.symbol ? 'primary' : 'default'}
                            onClick={() => applyAdaptiveGridTrendRecommendation(item, '建议运行')}
                          >
                            {item.symbol.replace('-USDT-SWAP', '')}
                          </Button>
                        ))}
                      </Space>
                      <Space wrap>
                        <span style={{ color: '#595959' }}>观察候选</span>
                        {(agtRecommendation?.watch || []).map(item => (
                          <Button
                            key={item.symbol}
                            size="small"
                            onClick={() => applyAdaptiveGridTrendRecommendation(item, '观察候选')}
                          >
                            {item.symbol.replace('-USDT-SWAP', '')}
                          </Button>
                        ))}
                      </Space>
                      <Space wrap>
                        <span style={{ color: '#595959' }}>暂缓</span>
                        {(agtRecommendation?.excluded || []).map(item => (
                          <Tag key={item.symbol} color="default">
                            {item.symbol.replace('-USDT-SWAP', '')}
                          </Tag>
                        ))}
                      </Space>
                    </Space>
                  </Space>
                }
                description="推荐器会用1000U稳健参数和昨日验证结果做初始篮子：先跑 LTC/XRP/LINK，DOT/AVAX/SOL 作为加仓观察，DOGE/TRX 暂缓。点击币种可直接套用交易对、策略名和参数。"
                type="success"
                showIcon
                style={{ marginBottom: 10, fontSize: 12 }}
              />
            )}
            <Alert
              message={candidateMode === 'stealth'
                ? '筛选成交量足够、涨幅未过热、价格位置偏低的潜伏候选，分析后可一键套用推荐策略。'
                : '选择OKX USDT永续24h涨幅榜前五山寨币，分析后可一键套用推荐策略。'
              }
              type="info"
              showIcon
              style={{ marginBottom: 10, fontSize: 12 }}
              action={
                <Space size={6}>
                  <Button
                    size="small"
                    type={candidateMode === 'stealth' ? 'primary' : 'default'}
                    loading={topAltcoinLoading}
                    onClick={fetchStealthAltcoinStrategies}
                  >
                    潜伏候选
                  </Button>
                  <Button
                    size="small"
                    type={candidateMode === 'top' ? 'primary' : 'default'}
                    icon={<RiseOutlined />}
                    loading={topAltcoinLoading}
                    onClick={fetchTopAltcoinStrategies}
                  >
                    涨幅前五
                  </Button>
                </Space>
              }
            />
            {topAltcoinCandidates.length > 0 && (
              <Table<TopAltcoinStrategyCandidate>
                size="small"
                rowKey="symbol"
                pagination={false}
                dataSource={topAltcoinCandidates}
                style={{ marginBottom: 10 }}
                columns={[
                  {
                    title: '交易对',
                    dataIndex: 'symbol',
                    width: 130,
                    render: (value) => <span style={{ fontWeight: 600 }}>{value}</span>,
                  },
                  {
                    title: '涨幅',
                    dataIndex: 'change_pct',
                    width: 80,
                    render: (value) => <span style={{ color: '#16a34a' }}>{Number(value).toFixed(2)}%</span>,
                  },
                  {
                    title: '决策',
                    dataIndex: ['analysis', 'decision'],
                    width: 80,
                    render: (value) => <Tag color={decisionColor[value] || 'default'}>{decisionText[value] || value}</Tag>,
                  },
                  {
                    title: '信心',
                    dataIndex: ['analysis', 'confidence'],
                    width: 70,
                    render: (value) => `${(Number(value || 0) * 100).toFixed(0)}%`,
                  },
                  {
                    title: '策略',
                    dataIndex: ['recommended_strategy', 'label'],
                    ellipsis: true,
                  },
                  {
                    title: '',
                    width: 72,
                    render: (_, record) => (
                      <Button size="small" type="link" onClick={() => applyStrategyRecommendation(record)}>
                        套用
                      </Button>
                    ),
                  },
                ]}
              />
            )}
          </>
        )}

        {/* ── EMA 趋势跟踪参数 ── */}
        {selectedType === 'trend' && (
          <>
            <Divider orientation="left" style={compactDivider}>
              策略参数
              <Tooltip title="EMA快线=12 慢线=40 已固定（回测最优），无需调整">
                <InfoCircleOutlined style={{ marginLeft: 6, color: '#8c8c8c', fontSize: 12 }} />
              </Tooltip>
            </Divider>
            <Alert
              message="EMA(12,40) 参数已通过 256 组回测验证固定，仅需配置仓位与风控"
              type="info"
              showIcon
              style={{ marginBottom: 10, fontSize: 12 }}
            />
            <Row gutter={12}>
              <Col span={8}>
                <Form.Item
                  name="position_ratio"
                  label={<Space size={4}>仓位比例(%)<Tooltip title="每次开仓占可用余额的百分比"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={5} max={90} step={5} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              {/* 止损：固定 or 移动，二选一 */}
              <Col span={8}>
                <Form.Item
                  name="use_trailing_stop"
                  label={<Space size={4}>移动止损<Tooltip title="开启后：止损价随价格上涨自动上移，锁住浮动盈利，避免利润回吐。开启后固定止损失效"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                  valuePropName="checked"
                >
                  <Switch checkedChildren="开启" unCheckedChildren="关闭" />
                </Form.Item>
              </Col>
              {useTrailingStop ? (
                <Col span={8}>
                  <Form.Item
                    name="trailing_stop"
                    label={<Space size={4}>回撤幅度(%)<Tooltip title="价格从最高点回撤此比例时触发止损。建议 1.5~3%，兼顾锁利与持续性"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                    style={compactItem}
                  >
                    <InputNumber min={0.5} max={10} step={0.5} suffix="%" style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              ) : (
                <Col span={8}>
                  <Form.Item
                    name="stop_loss"
                    label={<Space size={4}>固定止损(%)<Tooltip title="持仓亏损达到此比例时触发市价平仓（相对开仓价）"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                    style={compactItem}
                  >
                    <InputNumber min={0.1} max={20} step={0.5} suffix="%" style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              )}
              <Col span={8}>
                <Form.Item
                  name="take_profit"
                  label={<Space size={4}>止盈(%)<Tooltip title="持仓盈利达到此比例时触发市价平仓（实时价格）"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={1} max={50} step={1} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="leverage"
                  label={<Space size={4}>杠杆倍数<Tooltip title="合约杠杆倍数，策略启动时自动设置到交易所。趋势策略建议 5~20x，过高容易强平"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={1} max={100} step={1} suffix="x" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={16}>
                <Form.Item
                  name="use_rsi_filter"
                  label={<Space size={4}>RSI 超买过滤<Tooltip title="开启后：金叉信号出现时如果 RSI14 ≥ 65（超买区），则跳过本次开仓。回测验证可将收益从 +3.2% 提升到 +7.7%"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                  valuePropName="checked"
                >
                  <Switch checkedChildren="开启" unCheckedChildren="关闭" />
                </Form.Item>
              </Col>
            </Row>

          </>
        )}

        {/* ── 双向持仓策略参数 ── */}
        {selectedType === 'dual_side' && (
          <>
            <Divider orientation="left" style={compactDivider}>
              双向持仓参数
              <Tooltip title="EMA快线=12 慢线=40，金叉开多/死叉开空">
                <InfoCircleOutlined style={{ marginLeft: 6, color: '#8c8c8c', fontSize: 12 }} />
              </Tooltip>
            </Divider>
            <Alert
              message="支持多空双向交易，趋势反转时自动平仓并反向开仓"
              type="info"
              showIcon
              style={{ marginBottom: 10, fontSize: 12 }}
            />
            <Row gutter={12}>
              <Col span={8}>
                <Form.Item
                  name="dual_position_ratio"
                  label={<Space size={4}>仓位比例(%)<Tooltip title="每次开仓占可用余额的百分比，建议30%"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                  initialValue={30}
                >
                  <InputNumber min={5} max={90} step={5} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="dual_leverage"
                  label={<Space size={4}>杠杆倍数<Tooltip title="建议3x-5x低杠杆，控制风险"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                  initialValue={5}
                >
                  <InputNumber min={1} max={20} step={1} suffix="x" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="dual_stop_loss"
                  label={<Space size={4}>止损(%)<Tooltip title="亏损达到此比例时平仓"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                  initialValue={2}
                >
                  <InputNumber min={0.5} max={20} step={0.5} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="dual_take_profit"
                  label={<Space size={4}>止盈(%)<Tooltip title="盈利达到此比例时平仓"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                  initialValue={6}
                >
                  <InputNumber min={1} max={50} step={1} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="use_dual_trailing_stop"
                  label={<Space size={4}>移动止损<Tooltip title="开启后止损价随价格移动，锁定盈利"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                  valuePropName="checked"
                  initialValue={true}
                >
                  <Switch checkedChildren="开启" unCheckedChildren="关闭" />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="dual_trailing_stop"
                  label={<Space size={4}>回撤幅度(%)<Tooltip title="价格回撤此比例时触发止损"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                  initialValue={2}
                >
                  <InputNumber min={0.5} max={10} step={0.5} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>

          </>
        )}

        {/* ── 网格交易参数 ── */}
        {selectedType === 'grid' && (
          <>
            <Divider orientation="left" style={compactDivider}>
              网格参数
            </Divider>
            <Alert
              message={gridTickerLoading
                ? '正在获取行情数据，自动计算网格区间...'
                : '网格区间已根据24h高低价自动填充（上下扩展20%），可手动调整'
              }
              type="info"
              showIcon
              icon={gridTickerLoading ? <Spin size="small" /> : undefined}
              style={{ marginBottom: 10, fontSize: 12 }}
              action={
                !gridTickerLoading && watchedSymbol ? (
                  <a onClick={() => {
                    form.setFieldsValue({ grid_price_lower: undefined, grid_price_upper: undefined })
                    fetchGridTicker(watchedSymbol)
                  }} style={{ fontSize: 12, whiteSpace: 'nowrap' }}>
                    重新获取
                  </a>
                ) : undefined
              }
            />
            <Row gutter={12}>
              <Col span={12}>
                <Form.Item
                  name="grid_price_lower"
                  label={<Space size={4}>网格下界<Tooltip title="网格的最低价格，低于此价格不再挂买单"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  rules={[{ required: selectedType === 'grid', message: '请输入网格下界' }]}
                  style={compactItem}
                >
                  <InputNumber min={0} step={0.01} placeholder="如 80000" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item
                  name="grid_price_upper"
                  label={<Space size={4}>网格上界<Tooltip title="网格的最高价格，高于此价格不再挂卖单"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  rules={[{ required: selectedType === 'grid', message: '请输入网格上界' }]}
                  style={compactItem}
                >
                  <InputNumber min={0} step={0.01} placeholder="如 100000" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="grid_count"
                  label={<Space size={4}>网格数量<Tooltip title="价格区间等分为多少格，越多则每格利润越小但成交越频繁"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={2} max={200} step={1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="grid_total_amount"
                  label={<Space size={4}>投资总额(USDT)<Tooltip title="投入的总USDT金额，会平均分配到每个网格"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={10} step={10} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="grid_leverage"
                  label={<Space size={4}>杠杆倍数<Tooltip title="合约杠杆，现货可设为1"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={1} max={100} step={1} suffix="x" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="grid_stop_loss"
                  label={<Space size={4}>止损(%)<Tooltip title="价格跌破网格下界此比例后触发止损，撤销所有挂单"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={1} max={50} step={1} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>
          </>
        )}

        {/* ── 自适应趋势网格参数 ── */}
        {selectedType === 'adaptive_grid_trend' && (
          <>
            <Divider orientation="left" style={compactDivider}>
              自适应趋势网格参数
              <Tooltip title="EMA趋势过滤 + ATR回撤入场 + 固定风险仓位，适合先用模拟盘观察">
                <InfoCircleOutlined style={{ marginLeft: 6, color: '#8c8c8c', fontSize: 12 }} />
              </Tooltip>
            </Divider>
            <Alert
              message="按账户权益固定比例承担单笔风险，合约会读取 ctVal / lotSz / minSz 后按张数下单，不使用马丁补仓。"
              type="warning"
              showIcon
              style={{ marginBottom: 10, fontSize: 12 }}
            />
            <Row gutter={12}>
              <Col span={8}>
                <Form.Item
                  name="agt_direction"
                  label={<Space size={4}>交易方向<Tooltip title="现货只支持做多；合约可选择多空或只做单边"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <Select
                    options={[
                      { label: '多空双向', value: 'both' },
                      { label: '只做多', value: 'long' },
                      { label: '只做空', value: 'short' },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_timeframe"
                  label={<Space size={4}>趋势周期<Tooltip title="用于计算EMA趋势和ATR波动，周期越大交易越少"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <Select
                    options={[
                      { label: '15分钟', value: '15m' },
                      { label: '1小时', value: '1H' },
                      { label: '4小时', value: '4H' },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_margin_mode"
                  label={<Space size={4}>保证金模式<Tooltip title="合约下单使用，isolated为逐仓，cross为全仓"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <Select
                    options={[
                      { label: '逐仓', value: 'isolated' },
                      { label: '全仓', value: 'cross' },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_fast_period"
                  label={<Space size={4}>EMA快线<Tooltip title="趋势快线周期，1000U稳健版默认30"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={5} max={80} step={1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_slow_period"
                  label={<Space size={4}>EMA慢线<Tooltip title="趋势慢线周期，必须大于快线，1000U稳健版默认60"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={20} max={200} step={5} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_atr_period"
                  label={<Space size={4}>ATR周期<Tooltip title="用于计算波动和止损距离，默认14"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={5} max={50} step={1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_risk_per_trade"
                  label={<Space size={4}>单笔风险<Tooltip title="每笔最多亏损账户权益的比例，建议0.3%到1%"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={0.1} max={5} step={0.1} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_max_position_usd"
                  label={<Space size={4}>最大仓位<Tooltip title="单次开仓名义价值上限，单位USDT"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={10} step={10} prefix="$" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_leverage"
                  label={<Space size={4}>杠杆倍数<Tooltip title="合约启动时自动设置，1000U稳健版默认5x"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={1} max={20} step={1} suffix="x" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_entry_atr_multiple"
                  label={<Space size={4}>入场回撤ATR<Tooltip title="趋势成立后，价格回撤到快线附近多少ATR内才入场"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={0} max={2} step={0.05} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_stop_atr_multiple"
                  label={<Space size={4}>止损ATR<Tooltip title="止损距离 = ATR × 此倍数"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={0.5} max={5} step={0.1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_take_profit_atr_multiple"
                  label={<Space size={4}>止盈ATR<Tooltip title="止盈距离 = ATR × 此倍数，1000U稳健版默认3.2"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={0.5} max={8} step={0.1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_cooldown_minutes"
                  label={<Space size={4}>冷却时间<Tooltip title="平仓后等待多少分钟才允许下一次开仓"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={1} max={240} step={1} suffix="分钟" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_notify_near_trigger"
                  label={<Space size={4}>临近提醒<Tooltip title="价格接近止盈或止损线时发送系统通知；配置 Bark 后手机也会收到"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  valuePropName="checked"
                  style={compactItem}
                >
                  <Switch checkedChildren="开启" unCheckedChildren="关闭" />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_near_trigger_pct"
                  label={<Space size={4}>提醒距离<Tooltip title="距离止盈或止损价小于该百分比时提醒，默认0.3%"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={0.05} max={5} step={0.05} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_near_trigger_cooldown_minutes"
                  label={<Space size={4}>提醒冷却<Tooltip title="同一持仓同一触发线重复提醒的最小间隔"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={1} max={120} step={1} suffix="分钟" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>

            <Divider orientation="left" style={compactDivider}>
              运行熔断
              <Tooltip title="触发后策略自动暂停，默认撤未成交委托，不主动强平已有持仓">
                <InfoCircleOutlined style={{ marginLeft: 6, color: '#8c8c8c', fontSize: 12 }} />
              </Tooltip>
            </Divider>
            <Row gutter={12}>
              <Col span={8}>
                <Form.Item
                  name="agt_fuse_enabled"
                  label={<Space size={4}>熔断保护<Tooltip title="开启后，连续亏损、日亏损、运行回撤或盈亏比恶化会自动暂停策略"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  valuePropName="checked"
                  style={compactItem}
                >
                  <Switch checkedChildren="开启" unCheckedChildren="关闭" />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_fuse_max_consecutive_losses"
                  label={<Space size={4}>连续亏损<Tooltip title="连续亏损达到该次数后暂停策略"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={1} max={10} step={1} suffix="次" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_fuse_daily_loss_pct"
                  label={<Space size={4}>日亏损上限<Tooltip title="按风险基准资金计算，1000U稳健版默认3%"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={0.1} max={20} step={0.1} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_fuse_max_drawdown_pct"
                  label={<Space size={4}>运行回撤上限<Tooltip title="本次启动后的已实现盈亏曲线最大回撤阈值"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={0.5} max={30} step={0.5} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_fuse_min_profit_factor"
                  label={<Space size={4}>最低盈亏比<Tooltip title="最近窗口内盈亏比低于该值后暂停，默认0.8"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={0} max={5} step={0.1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_fuse_profit_factor_window"
                  label={<Space size={4}>盈亏比窗口<Tooltip title="计算最近多少笔平仓交易的盈亏比"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={3} max={50} step={1} suffix="笔" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_fuse_min_trades"
                  label={<Space size={4}>最少统计笔数<Tooltip title="平仓交易数达到该数量后才启用盈亏比熔断"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={3} max={50} step={1} suffix="笔" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_fuse_cancel_orders"
                  label={<Space size={4}>触发后撤单<Tooltip title="熔断暂停时撤销未成交委托"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  valuePropName="checked"
                  style={compactItem}
                >
                  <Switch checkedChildren="撤单" unCheckedChildren="保留" />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="agt_fuse_close_position"
                  label={<Space size={4}>触发后平仓<Tooltip title="实盘初期建议关闭；开启后熔断会尝试市价平掉已有持仓"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  valuePropName="checked"
                  style={compactItem}
                >
                  <Switch checkedChildren="平仓" unCheckedChildren="不平" />
                </Form.Item>
              </Col>
            </Row>
          </>
        )}

        {/* ── 爆量急拉追涨参数 ── */}
        {selectedType === 'explosive_momentum_chaser' && (
          <>
            <Divider orientation="left" style={compactDivider}>
              爆量急拉追涨参数
              <Tooltip title="动态扫描OKX高流动性USDT永续，按所选K线周期扫描，使用近1小时/近4小时累计涨幅排行，固定持有或硬止损退出">
                <InfoCircleOutlined style={{ marginLeft: 6, color: '#8c8c8c', fontSize: 12 }} />
              </Tooltip>
            </Divider>
            <Alert
              message="高风险模拟优先：该策略捕捉短线急拉延续，默认3x逐仓、4%止损、首轮只观察。确认稳定后再考虑提高到5x。"
              type="warning"
              showIcon
              style={{ marginBottom: 10, fontSize: 12 }}
            />
            <Row gutter={12}>
              <Col span={8}>
                <Form.Item
                  name="emc_timeframe"
                  label={<Space size={4}>K线周期<Tooltip title="周期越短越敏感、交易更多；周期越长信号更少但噪音更低"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <Select
                    options={[
                      { label: '1分钟', value: '1m' },
                      { label: '5分钟', value: '5m' },
                      { label: '15分钟', value: '15m' },
                      { label: '30分钟', value: '30m' },
                      { label: '1小时', value: '1H' },
                      { label: '4小时', value: '4H' },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_rank_feature" label="排行因子" style={compactItem}>
                  <Select
                    options={[
                      { label: '1小时涨幅', value: 'ret_1h' },
                      { label: '4小时涨幅', value: 'ret_4h' },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_min_signal_pct" label="最小涨幅" style={compactItem}>
                  <InputNumber min={1} max={30} step={0.5} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_min_gap_pct" label="领先差距" style={compactItem}>
                  <InputNumber min={0} max={10} step={0.5} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_min_vol_ratio" label="最小量比" style={compactItem}>
                  <InputNumber min={0.5} max={10} step={0.1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_hold_hours" label="持仓时间" style={compactItem}>
                  <InputNumber min={1} max={12} step={1} suffix="小时" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_stop_loss_pct" label="硬止损" style={compactItem}>
                  <InputNumber min={1} max={20} step={0.5} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_market_filter" label="市场过滤" style={compactItem}>
                  <Select
                    options={[
                      { label: 'BTC 4小时上涨', value: 'btc_4h_positive' },
                      { label: 'BTC/ETH 1小时同涨', value: 'btc_eth_1h_positive' },
                      { label: 'BTC/ETH 4小时同涨', value: 'btc_eth_4h_positive' },
                      { label: '不过滤', value: 'none' },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_universe_size" label="流动性池" style={compactItem}>
                  <InputNumber min={10} max={200} step={5} suffix="个" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_top_n" label="开仓名次" style={compactItem}>
                  <InputNumber min={1} max={3} step={1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_max_leverage" label="最大杠杆" style={compactItem}>
                  <InputNumber min={1} max={10} step={1} suffix="x" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_max_position_usd" label="单仓上限" style={compactItem}>
                  <InputNumber min={20} step={10} prefix="$" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_max_total_position_usd" label="总仓上限" style={compactItem}>
                  <InputNumber min={20} step={10} prefix="$" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_margin_mode" label="保证金模式" style={compactItem}>
                  <Select
                    options={[
                      { label: '逐仓', value: 'isolated' },
                      { label: '全仓', value: 'cross' },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_loop_interval_seconds" label="风控检查" style={compactItem}>
                  <InputNumber min={15} max={300} step={15} suffix="秒" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_cooldown_minutes" label="同币冷却" style={compactItem}>
                  <InputNumber min={0} max={720} step={30} suffix="分钟" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_observe_first_scan" label="首轮只观察" valuePropName="checked" style={compactItem}>
                  <Switch checkedChildren="观察" unCheckedChildren="可开仓" />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_use_volume_profile_filter" label="成交量分布过滤" valuePropName="checked" style={compactItem}>
                  <Switch checkedChildren="启用" unCheckedChildren="关闭" />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_volume_profile_level" label="接受价位" style={compactItem}>
                  <Select
                    disabled={!watchedEmcVolumeProfile}
                    options={[
                      { label: 'POC 控制点', value: 'poc' },
                      { label: 'VAH 价值区高点', value: 'vah' },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_max_high_pullback_pct" label="高点最大回落" style={compactItem}>
                  <InputNumber disabled={!watchedEmcVolumeProfile} min={0.5} max={10} step={0.5} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_volume_profile_hours" label="分布回看" style={compactItem}>
                  <InputNumber disabled={!watchedEmcVolumeProfile} min={4} max={24} step={1} suffix="小时" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_volume_profile_bins" label="价格分箱" style={compactItem}>
                  <InputNumber disabled={!watchedEmcVolumeProfile} min={20} max={100} step={4} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_fuse_max_consecutive_losses" label="连续亏损熔断" style={compactItem}>
                  <InputNumber min={1} max={10} step={1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_fuse_daily_loss_pct" label="日亏损熔断" style={compactItem}>
                  <InputNumber min={1} max={80} step={1} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="emc_fuse_max_drawdown_pct" label="回撤熔断" style={compactItem}>
                  <InputNumber min={1} max={90} step={1} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>
          </>
        )}

        {/* ── 涨幅榜前三动量参数 ── */}
        {selectedType === 'top_gainers_momentum' && (
          <>
            <Divider orientation="left" style={compactDivider}>
              涨幅榜前三动量参数
              <Tooltip title="动态读取OKX USDT永续24h涨幅榜前三，支持多空双向，用短周期动量信号和ATR风控交易">
                <InfoCircleOutlined style={{ marginLeft: 6, color: '#8c8c8c', fontSize: 12 }} />
              </Tooltip>
            </Divider>
            <Alert
              message="已接入自动交易：会用绑定账户在OKX USDT永续逐仓市价开平多/空仓，并优先附带OKX原生止盈止损。山寨币短线波动极大，实盘前强烈建议先跑模拟盘。"
              type="warning"
              showIcon
              style={{ marginBottom: 10, fontSize: 12 }}
            />
            <Row gutter={12}>
              <Col span={8}>
                <Form.Item
                  name="tgm_timeframe"
                  label={<Space size={4}>信号周期<Tooltip title="15分钟更稳，5分钟更激进且噪音更高"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <Select
                    options={[
                      { label: '15分钟', value: '15m' },
                      { label: '5分钟', value: '5m' },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="tgm_direction"
                  label={<Space size={4}>交易方向<Tooltip title="双向会根据涨幅榜币种的动量延续做多，过热转弱或下跌趋势做空"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <Select
                    options={[
                      { label: '多空双向', value: 'both' },
                      { label: '只做多', value: 'long' },
                      { label: '只做空', value: 'short' },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="tgm_top_n"
                  label={<Space size={4}>涨幅榜数量<Tooltip title="从24h涨幅榜中取前N个USDT永续合约，当前建议前三"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={1} max={10} step={1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="tgm_initial_capital"
                  label={<Space size={4}>模拟本金<Tooltip title="用于分析面板和回测展示的权益基准，不代表自动下单金额"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={100} step={100} prefix="$" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="tgm_lookback_hours"
                  label={<Space size={4}>分析窗口<Tooltip title="读取最近多少小时K线用于动量和回测观察"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={6} max={168} step={6} suffix="小时" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="tgm_risk_per_trade"
                  label={<Space size={4}>单笔风险<Tooltip title="每笔交易按账户权益承担的最大止损风险，高风险策略默认3.5%"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={0.5} max={20} step={0.5} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="tgm_max_leverage"
                  label={<Space size={4}>最大杠杆<Tooltip title="分析用杠杆上限；山寨币短线波动极大，实盘需更保守"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={1} max={20} step={1} suffix="x" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="tgm_max_position_usd"
                  label={<Space size={4}>单仓上限<Tooltip title="单个山寨币持仓的最大名义价值，实盘建议先小额"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={20} step={10} prefix="$" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="tgm_max_total_position_usd"
                  label={<Space size={4}>总持仓上限<Tooltip title="策略所有动态币种合计最大名义价值"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={20} step={10} prefix="$" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="tgm_max_open_positions"
                  label={<Space size={4}>最多持仓数<Tooltip title="涨幅榜前三中最多同时持有几个币，默认只持有1个降低相关风险"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={1} max={3} step={1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="tgm_margin_mode"
                  label={<Space size={4}>保证金模式<Tooltip title="高风险短线默认逐仓，避免单个币种拖累全仓"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <Select
                    options={[
                      { label: '逐仓', value: 'isolated' },
                      { label: '全仓', value: 'cross' },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="tgm_loop_interval_seconds"
                  label={<Space size={4}>扫描间隔<Tooltip title="多久刷新一次涨幅榜和持仓风控"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={15} max={300} step={15} suffix="秒" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="tgm_cooldown_minutes"
                  label={<Space size={4}>同币冷却<Tooltip title="同一个币平仓后多久内不再重新开仓"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={0} max={240} step={5} suffix="分钟" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="tgm_observe_first_scan"
                  label={<Space size={4}>首轮只观察<Tooltip title="启动后第一次扫描只记录信号，不立刻开仓，降低刚启动撞上假突破的风险"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  valuePropName="checked"
                  style={compactItem}
                >
                  <Switch checkedChildren="观察" unCheckedChildren="可开仓" />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="tgm_use_attached_tp_sl"
                  label={<Space size={4}>原生止盈止损<Tooltip title="下单时附带OKX止盈止损，程序断线时仍有交易所侧保护；程序仍会轮询移动止损"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  valuePropName="checked"
                  style={compactItem}
                >
                  <Switch checkedChildren="附带" unCheckedChildren="仅轮询" />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="tgm_close_when_out_of_top"
                  label={<Space size={4}>跌出榜单平仓<Tooltip title="持仓币种不再位于动态涨幅榜前N时是否平仓；默认关闭，避免频繁换手"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  valuePropName="checked"
                  style={compactItem}
                >
                  <Switch checkedChildren="平仓" unCheckedChildren="持有" />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="tgm_stop_atr"
                  label={<Space size={4}>止损ATR倍数<Tooltip title="用ATR衡量波动，倍数越小越容易被洗出"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={0.5} max={6} step={0.1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="tgm_take_profit_r"
                  label={<Space size={4}>止盈R倍数<Tooltip title="以初始风险R计算目标止盈，例如2R表示盈利达到止损距离2倍时止盈"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={0.5} max={8} step={0.25} suffix="R" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="tgm_trailing_atr"
                  label={<Space size={4}>移动止损ATR<Tooltip title="盈利后用ATR跟踪回撤，数值越小锁利越快但更容易提前离场"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={0.5} max={6} step={0.1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="tgm_fuse_max_consecutive_losses"
                  label={<Space size={4}>连续亏损熔断<Tooltip title="连续亏损达到该次数后自动暂停策略"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={1} max={10} step={1} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="tgm_fuse_daily_loss_pct"
                  label={<Space size={4}>日亏损熔断<Tooltip title="按模拟本金/风险基准计算，当日已实现亏损达到该比例后暂停"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={1} max={50} step={1} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="tgm_fuse_max_drawdown_pct"
                  label={<Space size={4}>回撤熔断<Tooltip title="运行期最大已实现回撤达到该比例后暂停"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={1} max={80} step={1} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>
          </>
        )}

        {/* ── 现货-永续套利参数 ── */}
        {selectedType === 'arbitrage' && (
          <>
            <Divider orientation="left" style={compactDivider}>
              现货-永续套利参数
              <Tooltip title="当前版本执行正向基差套利：买现货、做空USDT永续，等待基差收敛后平仓">
                <InfoCircleOutlined style={{ marginLeft: 6, color: '#8c8c8c', fontSize: 12 }} />
              </Tooltip>
            </Divider>
            <Alert
              message="建议先选择模拟盘并使用小额名义金额。策略会按盘口买入现货并做空永续，单边失败时会尝试立即补偿。"
              type="warning"
              showIcon
              style={{ marginBottom: 10, fontSize: 12 }}
            />
            <Row gutter={12}>
              <Col span={12}>
                <Form.Item
                  name="arb_spot_symbol"
                  label={<Space size={4}>现货交易对<Tooltip title="留空时根据主交易对自动推导，例如 BTC-USDT-SWAP -> BTC-USDT"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <Input placeholder="BTC-USDT" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item
                  name="arb_perp_symbol"
                  label={<Space size={4}>永续交易对<Tooltip title="留空时根据主交易对自动推导，例如 BTC-USDT -> BTC-USDT-SWAP"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <Input placeholder="BTC-USDT-SWAP" />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="arb_target_notional_usd"
                  label={<Space size={4}>单笔名义金额<Tooltip title="每次套利尝试的目标名义价值，单位USDT"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={10} step={10} prefix="$" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="arb_max_notional_usd"
                  label={<Space size={4}>最大名义金额<Tooltip title="策略会取单笔名义金额和该上限的较小值"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={10} step={10} prefix="$" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="arb_leverage"
                  label={<Space size={4}>永续杠杆<Tooltip title="套利初期建议1x，降低强平和保证金风险"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={1} max={10} step={1} suffix="x" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="arb_open_edge_pct"
                  label={<Space size={4}>开仓基差<Tooltip title="永续买一相对现货卖一的溢价达到该比例后尝试开仓"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={0.05} max={5} step={0.01} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="arb_close_edge_pct"
                  label={<Space size={4}>平仓基差<Tooltip title="基差回落到该比例以下时卖出现货并买回永续"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={0} max={2} step={0.01} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="arb_min_net_edge_pct"
                  label={<Space size={4}>最低净基差<Tooltip title="扣除手续费和滑点缓冲后仍需达到该比例才开仓"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={0} max={3} step={0.01} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="arb_fee_buffer_pct"
                  label={<Space size={4}>手续费缓冲<Tooltip title="开仓判断时预扣的双边手续费缓冲"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={0} max={2} step={0.01} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="arb_slippage_buffer_pct"
                  label={<Space size={4}>滑点缓冲<Tooltip title="开仓判断时预扣的成交滑点缓冲"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={0} max={2} step={0.01} suffix="%" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="arb_poll_interval"
                  label={<Space size={4}>检查间隔<Tooltip title="REST保守版的行情检查间隔，后续可升级为WebSocket事件驱动"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <InputNumber min={0.5} max={10} step={0.5} suffix="秒" style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="arb_margin_mode"
                  label={<Space size={4}>保证金模式<Tooltip title="永续腿使用的保证金模式"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  style={compactItem}
                >
                  <Select
                    options={[
                      { label: '逐仓', value: 'isolated' },
                      { label: '全仓', value: 'cross' },
                    ]}
                  />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  name="arb_close_on_stop"
                  label={<Space size={4}>停止时平仓<Tooltip title="关闭时会尝试市价平掉套利组合；实盘初期建议关闭，手动确认后处理"><InfoCircleOutlined style={{ color: '#8c8c8c', fontSize: 12 }} /></Tooltip></Space>}
                  valuePropName="checked"
                  style={compactItem}
                >
                  <Switch checkedChildren="平仓" unCheckedChildren="保留" />
                </Form.Item>
              </Col>
            </Row>
          </>
        )}

        {/* ── 备注 ── */}
        <Divider orientation="left" style={compactDivider}>备注</Divider>
        <Form.Item name="description" style={compactItem}>
          <TextArea placeholder="可选：描述策略目标、注意事项等" rows={1} />
        </Form.Item>
      </Form>
    </Modal>
  )
}

export default StrategyCreateModal
