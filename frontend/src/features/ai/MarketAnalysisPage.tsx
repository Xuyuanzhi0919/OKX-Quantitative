import { useState, useEffect } from 'react'
import {
  Card,
  Button,
  Select,
  Space,
  Spin,
  Alert,
  Row,
  Col,
  Tag,
  Statistic,
  Progress,
  Divider,
  Descriptions,
  App,
  Typography,
} from 'antd'
import {
  Brain,
  TrendingUp,
  TrendingDown,
  Activity,
  BarChart3,
  Zap,
  AlertTriangle,
  Sparkles,
  Cpu,
  Gauge,
  Target,
  Hexagon,
} from 'lucide-react'
import { aiApi, marketApi } from '@/services/api'
import { formatPrice, formatPercent } from '@/utils/format'

const { Title, Text } = Typography

// 赛博朋克交易终端风格 - 使用等宽字体
const FONT_FAMILY = '"JetBrains Mono", "IBM Plex Mono", "Fira Code", monospace'

interface AnalysisResult {
  symbol: string
  timestamp: string
  decision: 'long' | 'short' | 'wait'
  confidence: number
  scores: {
    long_score: number
    short_score: number
    wait_score: number
  }
  factors: {
    technical: any
    sentiment: any
    ai: any
  }
  risk_level: 'low' | 'medium' | 'high'
  suggested_strategy: string | null
  reasoning: string
}

const MarketAnalysisPage = () => {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [symbol, setSymbol] = useState<string>('BTC-USDT-SWAP') // 默认使用BTC（模拟盘支持）
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [instruments, setInstruments] = useState<any[]>([])
  const [hasAIConfig, setHasAIConfig] = useState(false)

  useEffect(() => {
    fetchInstruments()
    checkAIConfig()
  }, [])

  const checkAIConfig = async () => {
    try {
      await aiApi.getActiveConfig()
      setHasAIConfig(true)
    } catch (error) {
      setHasAIConfig(false)
    }
  }

  const fetchInstruments = async () => {
    try {
      const data = await marketApi.getInstruments({
        inst_type: 'SWAP',
        quote_ccy: 'USDT',
      })

      // 模拟盘支持的交易对白名单（避免选择模拟盘不支持的币种）
      const simulatedWhitelist = [
        'BTC-USDT-SWAP',
        'ETH-USDT-SWAP',
        'SOL-USDT-SWAP',
        'DOGE-USDT-SWAP',
        'XRP-USDT-SWAP',
        'ADA-USDT-SWAP',
        'AVAX-USDT-SWAP',
        'DOT-USDT-SWAP',
        'MATIC-USDT-SWAP',
        'LINK-USDT-SWAP',
        'UNI-USDT-SWAP',
        'LTC-USDT-SWAP',
        'BCH-USDT-SWAP',
        'ETC-USDT-SWAP',
        'XLM-USDT-SWAP',
      ]

      // 过滤出模拟盘支持的交易对
      const filteredData = data.filter((inst) => simulatedWhitelist.includes(inst.instId))

      setInstruments(filteredData)
    } catch (error) {
      message.error('获取交易对列表失败')
    }
  }

  const handleAnalyze = async () => {
    if (!symbol) {
      message.warning('请选择交易对')
      return
    }

    if (!hasAIConfig) {
      message.warning({
        content: '请先配置AI服务',
        duration: 5,
      })
      setTimeout(() => {
        if (confirm('是否前往AI配置页面？')) {
          window.location.href = '/ai-config'
        }
      }, 100)
      return
    }

    setAnalyzing(true)
    try {
      const data = await aiApi.analyze(symbol, true)
      setResult(data)
      message.success('分析完成')
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '分析失败')
    } finally {
      setAnalyzing(false)
    }
  }

  const getDecisionColor = (decision: string) => {
    switch (decision) {
      case 'long':
        return '#00ff9d'
      case 'short':
        return '#ff2a6d'
      default:
        return '#737373'
    }
  }

  const getDecisionBgColor = (decision: string) => {
    switch (decision) {
      case 'long':
        return 'rgba(0, 255, 157, 0.08)'
      case 'short':
        return 'rgba(255, 42, 109, 0.08)'
      default:
        return 'rgba(115, 115, 115, 0.08)'
    }
  }

  const getDecisionIcon = (decision: string) => {
    switch (decision) {
      case 'long':
        return <TrendingUp size={36} strokeWidth={2.5} />
      case 'short':
        return <TrendingDown size={36} strokeWidth={2.5} />
      default:
        return <Activity size={36} strokeWidth={2.5} />
    }
  }

  const getDecisionText = (decision: string) => {
    switch (decision) {
      case 'long':
        return '做多 LONG'
      case 'short':
        return '做空 SHORT'
      default:
        return '观望 WAIT'
    }
  }

  const getRiskColor = (level: string) => {
    switch (level) {
      case 'low':
        return '#00ff9d'
      case 'medium':
        return '#ffae00'
      case 'high':
        return '#ff2a6d'
      default:
        return '#737373'
    }
  }

  const getRiskText = (level: string) => {
    switch (level) {
      case 'low':
        return '低风险 LOW'
      case 'medium':
        return '中风险 MED'
      case 'high':
        return '高风险 HIGH'
      default:
        return level
    }
  }

  return (
    <div
      style={{
        padding: '24px',
        maxWidth: '1600px',
        margin: '0 auto',
        background: '#050505',
        minHeight: '100vh',
        fontFamily: FONT_FAMILY,
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* 背景网格效果 */}
      <div
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background:
            'linear-gradient(rgba(0, 255, 157, 0.02) 1px, transparent 1px), ' +
            'linear-gradient(90deg, rgba(0, 255, 157, 0.02) 1px, transparent 1px)',
          backgroundSize: '50px 50px',
          pointerEvents: 'none',
          zIndex: 0,
        }}
      />

      {/* 扫描线效果 */}
      <div
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background:
            'repeating-linear-gradient(0deg, rgba(0, 0, 0, 0.1), rgba(0, 0, 0, 0.1) 1px, transparent 1px, transparent 2px)',
          pointerEvents: 'none',
          zIndex: 1,
          opacity: 0.3,
        }}
      />

      {/* 内容区域 */}
      <div style={{ position: 'relative', zIndex: 2 }}>
        {/* 页面标题区 - 赛博朋克风格 */}
        <div style={{ marginBottom: 32 }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 20,
              padding: '20px 24px',
              background:
                'linear-gradient(135deg, rgba(0, 255, 157, 0.05) 0%, rgba(255, 42, 109, 0.05) 100%)',
              border: '1px solid rgba(0, 255, 157, 0.2)',
              borderRadius: 4,
              position: 'relative',
              overflow: 'hidden',
            }}
          >
            {/* 装饰性边角 */}
            <div
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: 20,
                height: 20,
                borderTop: '2px solid #00ff9d',
                borderLeft: '2px solid #00ff9d',
              }}
            />
            <div
              style={{
                position: 'absolute',
                top: 0,
                right: 0,
                width: 20,
                height: 20,
                borderTop: '2px solid #ff2a6d',
                borderRight: '2px solid #ff2a6d',
              }}
            />
            <div
              style={{
                position: 'absolute',
                bottom: 0,
                left: 0,
                width: 20,
                height: 20,
                borderBottom: '2px solid #ff2a6d',
                borderLeft: '2px solid #ff2a6d',
              }}
            />
            <div
              style={{
                position: 'absolute',
                bottom: 0,
                right: 0,
                width: 20,
                height: 20,
                borderBottom: '2px solid #00ff9d',
                borderRight: '2px solid #00ff9d',
              }}
            />

            <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
              <div
                style={{
                  width: 64,
                  height: 64,
                  position: 'relative',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Hexagon size={64} style={{ color: '#00ff9d', opacity: 0.3 }} />
                <Brain size={28} style={{ color: '#00ff9d', position: 'absolute' }} />
              </div>
              <div>
                <div
                  style={{
                    fontSize: 28,
                    fontWeight: 700,
                    color: '#00ff9d',
                    marginBottom: 4,
                    letterSpacing: '2px',
                    textShadow: '0 0 20px rgba(0, 255, 157, 0.5)',
                  }}
                >
                  AI MARKET ANALYZER
                </div>
                <div
                  style={{
                    fontSize: 11,
                    color: '#737373',
                    letterSpacing: '3px',
                    textTransform: 'uppercase',
                    fontFamily: FONT_FAMILY,
                  }}
                >
                  多因子量化决策系统 // MULTI-FACTOR QUANTITATIVE SYSTEM
                </div>
              </div>
            </div>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
              }}
            >
              <div
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: analyzing ? '#ffae00' : '#00ff9d',
                  boxShadow: analyzing ? '0 0 10px #ffae00' : '0 0 10px #00ff9d',
                  animation: analyzing ? 'pulse 1s infinite' : 'none',
                }}
              />
              <Text style={{ color: '#00ff9d', fontSize: 12, letterSpacing: '1px' }}>
                {analyzing ? 'ANALYZING' : 'READY'}
              </Text>
            </div>
          </div>
        </div>

        {/* AI配置提醒 - 霓虹警告风格 */}
        {!hasAIConfig && (
          <Alert
            message={
              <span style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <Sparkles size={18} style={{ color: '#ffae00' }} />
                <span
                  style={{ fontSize: 14, fontWeight: 600, letterSpacing: '1px', color: '#ffae00' }}
                >
                  AI SERVICE CONFIGURATION REQUIRED
                </span>
              </span>
            }
            description={
              <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginTop: 16 }}>
                <Text style={{ color: '#a3a3a3', flex: 1, fontSize: 13 }}>
                  DeepSeek API密钥未配置。AI深度分析功能需要配置API密钥才能使用。
                </Text>
                <Button
                  type="primary"
                  size="large"
                  icon={<Zap size={16} />}
                  onClick={() => (window.location.href = '/ai-config')}
                  style={{
                    height: 40,
                    background: '#ffae00',
                    border: 'none',
                    color: '#000',
                    fontWeight: 600,
                    letterSpacing: '1px',
                    boxShadow: '0 0 20px rgba(255, 174, 0, 0.3)',
                  }}
                >
                  立即配置
                </Button>
              </div>
            }
            type="warning"
            showIcon={false}
            closable
            style={{
              marginBottom: 32,
              background:
                'linear-gradient(135deg, rgba(255, 174, 0, 0.08) 0%, rgba(255, 174, 0, 0.03) 100%)',
              border: '1px solid rgba(255, 174, 0, 0.3)',
              borderRadius: 4,
            }}
          />
        )}

        {/* 分析控制区 - 技术面板风格 */}
        <Card
          style={{
            marginBottom: 32,
            background: 'rgba(10, 10, 10, 0.95)',
            border: '1px solid #1a1a1a',
            borderRadius: 4,
            boxShadow: '0 4px 20px rgba(0, 0, 0, 0.5)',
          }}
          styles={{ body: { padding: '24px' } }}
        >
          <Row gutter={24} align="middle">
            <Col flex="auto">
              <div>
                <Text
                  style={{
                    display: 'block',
                    color: '#00ff9d',
                    marginBottom: 12,
                    fontSize: 11,
                    fontWeight: 600,
                    letterSpacing: '2px',
                    textTransform: 'uppercase',
                  }}
                >
                  // TARGET INSTRUMENT
                </Text>
                <Select
                  showSearch
                  style={{
                    width: '100%',
                    minWidth: 320,
                    fontFamily: FONT_FAMILY,
                  }}
                  placeholder="SELECT TRADING PAIR"
                  value={symbol}
                  onChange={setSymbol}
                  size="large"
                  filterOption={(input, option) =>
                    (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
                  }
                  options={instruments.map((inst) => ({
                    label: inst.instId,
                    value: inst.instId,
                  }))}
                />
              </div>
            </Col>
            <Col>
              <Button
                type="primary"
                size="large"
                icon={<Cpu size={20} />}
                loading={analyzing}
                onClick={handleAnalyze}
                style={{
                  height: 52,
                  minWidth: 180,
                  fontSize: 14,
                  fontWeight: 700,
                  letterSpacing: '1.5px',
                  background: analyzing
                    ? '#1a1a1a'
                    : 'linear-gradient(135deg, #00ff9d 0%, #00cc7d 100%)',
                  border: 'none',
                  color: '#000',
                  boxShadow: analyzing ? 'none' : '0 0 30px rgba(0, 255, 157, 0.4)',
                  fontFamily: FONT_FAMILY,
                }}
              >
                {analyzing ? 'ANALYZING...' : 'EXECUTE ANALYSIS'}
              </Button>
            </Col>
          </Row>
        </Card>

        {/* 分析结果 */}
        {result && (
          <>
            {/* 决策概览卡片 - 主视觉焦点 */}
            <Card
              style={{
                marginBottom: 32,
                background: 'rgba(10, 10, 10, 0.95)',
                border: `2px solid ${getDecisionColor(result.decision)}`,
                borderRadius: 4,
                boxShadow: `0 0 40px ${getDecisionColor(result.decision)}20`,
                overflow: 'hidden',
              }}
              styles={{ body: { padding: 0 } }}
            >
              {/* 决策展示区 - 超大视觉冲击 */}
              <div
                style={{
                  padding: '60px 40px',
                  background: getDecisionBgColor(result.decision),
                  textAlign: 'center',
                  position: 'relative',
                  overflow: 'hidden',
                }}
              >
                {/* 动态背景网格 */}
                <div
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    background: `repeating-linear-gradient(${getDecisionColor(result.decision)}08 0px, transparent 1px, transparent 40px), repeating-linear-gradient(90deg, ${getDecisionColor(result.decision)}08 0px, transparent 1px, transparent 40px)`,
                    backgroundSize: '40px 40px',
                    opacity: 0.5,
                  }}
                />

                <div style={{ position: 'relative', zIndex: 1 }}>
                  {/* 决策图标 */}
                  <div
                    style={{
                      color: getDecisionColor(result.decision),
                      marginBottom: 24,
                      filter: `drop-shadow(0 0 20px ${getDecisionColor(result.decision)}60)`,
                    }}
                  >
                    {getDecisionIcon(result.decision)}
                  </div>

                  {/* 决策文字 - 超大字号 */}
                  <div
                    style={{
                      fontSize: 72,
                      fontWeight: 900,
                      color: getDecisionColor(result.decision),
                      marginBottom: 16,
                      letterSpacing: '4px',
                      fontFamily: FONT_FAMILY,
                      textShadow: `0 0 40px ${getDecisionColor(result.decision)}40`,
                      lineHeight: 1,
                    }}
                  >
                    {getDecisionText(result.decision)}
                  </div>

                  {/* 标签 */}
                  <div
                    style={{
                      display: 'inline-block',
                      padding: '8px 24px',
                      background: `${getDecisionColor(result.decision)}15`,
                      border: `1px solid ${getDecisionColor(result.decision)}40`,
                      borderRadius: 4,
                      marginBottom: 40,
                    }}
                  >
                    <Text
                      style={{
                        fontSize: 12,
                        color: getDecisionColor(result.decision),
                        letterSpacing: '3px',
                        fontWeight: 600,
                      }}
                    >
                      AI 综合决策信号
                    </Text>
                  </div>

                  {/* 关键指标 */}
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 60,
                    }}
                  >
                    {/* 信心度 */}
                    <div style={{ textAlign: 'center' }}>
                      <div
                        style={{
                          fontSize: 11,
                          color: '#737373',
                          marginBottom: 12,
                          letterSpacing: '2px',
                          textTransform: 'uppercase',
                        }}
                      >
                        Confidence
                      </div>
                      <div
                        style={{
                          fontSize: 56,
                          fontWeight: 900,
                          color:
                            result.confidence >= 0.7
                              ? '#00ff9d'
                              : result.confidence >= 0.5
                                ? '#ffae00'
                                : '#ff2a6d',
                          fontFamily: FONT_FAMILY,
                          textShadow:
                            result.confidence >= 0.7 ? '0 0 30px rgba(0, 255, 157, 0.5)' : 'none',
                          lineHeight: 1,
                        }}
                      >
                        {(result.confidence * 100).toFixed(0)}
                        <span style={{ fontSize: 32 }}>%</span>
                      </div>
                      <div
                        style={{
                          fontSize: 11,
                          color: '#525252',
                          marginTop: 8,
                          letterSpacing: '1px',
                        }}
                      >
                        信心度指标
                      </div>
                    </div>

                    {/* 分隔线 */}
                    <div
                      style={{
                        width: 2,
                        height: 80,
                        background: 'linear-gradient(to bottom, transparent, #262626, transparent)',
                      }}
                    />

                    {/* 风险等级 */}
                    <div style={{ textAlign: 'center' }}>
                      <div
                        style={{
                          fontSize: 11,
                          color: '#737373',
                          marginBottom: 12,
                          letterSpacing: '2px',
                          textTransform: 'uppercase',
                        }}
                      >
                        Risk Level
                      </div>
                      <div
                        style={{
                          fontSize: 40,
                          fontWeight: 900,
                          color: getRiskColor(result.risk_level),
                          fontFamily: FONT_FAMILY,
                          textShadow: `0 0 30px ${getRiskColor(result.risk_level)}50`,
                          lineHeight: 1,
                          marginBottom: 8,
                        }}
                      >
                        {getRiskText(result.risk_level)}
                      </div>
                      <Tag
                        color={
                          result.risk_level === 'low'
                            ? 'success'
                            : result.risk_level === 'medium'
                              ? 'warning'
                              : 'error'
                        }
                        style={{
                          fontSize: 11,
                          fontWeight: 600,
                          letterSpacing: '1px',
                          padding: '4px 12px',
                        }}
                      >
                        RISK ASSESSMENT
                      </Tag>
                    </div>
                  </div>
                </div>
              </div>

              {/* 得分对比 - 技术指标风格 */}
              <div style={{ padding: '32px 40px', background: 'rgba(26, 26, 26, 0.5)' }}>
                <div style={{ marginBottom: 20 }}>
                  <Text
                    style={{
                      fontSize: 11,
                      color: '#737373',
                      letterSpacing: '2px',
                      textTransform: 'uppercase',
                      fontWeight: 600,
                    }}
                  >
                    // FACTOR SCORES COMPARISON
                  </Text>
                </div>
                <Row gutter={24}>
                  <Col span={12}>
                    <div
                      style={{
                        padding: 20,
                        background: 'rgba(0, 255, 157, 0.03)',
                        border: '1px solid rgba(0, 255, 157, 0.2)',
                        borderRadius: 4,
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          marginBottom: 16,
                        }}
                      >
                        <Text
                          style={{
                            color: '#737373',
                            fontSize: 12,
                            fontWeight: 600,
                            letterSpacing: '1px',
                          }}
                        >
                          LONG SCORE
                        </Text>
                        <Text
                          style={{
                            color: '#00ff9d',
                            fontSize: 32,
                            fontWeight: 900,
                            fontFamily: FONT_FAMILY,
                          }}
                        >
                          {(result.scores.long_score * 100).toFixed(1)}
                        </Text>
                      </div>
                      <Progress
                        percent={result.scores.long_score * 100}
                        strokeColor="#00ff9d"
                        trailColor="rgba(0, 255, 157, 0.1)"
                        showInfo={false}
                        size={10}
                        style={{ marginBottom: 12 }}
                      />
                      <div style={{ display: 'flex', gap: 8 }}>
                        <Tag
                          color="#00ff9d"
                          style={{ fontSize: 10, margin: 0, padding: '2px 8px' }}
                        >
                          BULLISH
                        </Tag>
                        <Tag
                          color="default"
                          style={{ fontSize: 10, margin: 0, padding: '2px 8px', color: '#737373' }}
                        >
                          做多信号强度
                        </Tag>
                      </div>
                    </div>
                  </Col>
                  <Col span={12}>
                    <div
                      style={{
                        padding: 20,
                        background: 'rgba(255, 42, 109, 0.03)',
                        border: '1px solid rgba(255, 42, 109, 0.2)',
                        borderRadius: 4,
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          marginBottom: 16,
                        }}
                      >
                        <Text
                          style={{
                            color: '#737373',
                            fontSize: 12,
                            fontWeight: 600,
                            letterSpacing: '1px',
                          }}
                        >
                          SHORT SCORE
                        </Text>
                        <Text
                          style={{
                            color: '#ff2a6d',
                            fontSize: 32,
                            fontWeight: 900,
                            fontFamily: FONT_FAMILY,
                          }}
                        >
                          {(result.scores.short_score * 100).toFixed(1)}
                        </Text>
                      </div>
                      <Progress
                        percent={result.scores.short_score * 100}
                        strokeColor="#ff2a6d"
                        trailColor="rgba(255, 42, 109, 0.1)"
                        showInfo={false}
                        size={10}
                        style={{ marginBottom: 12 }}
                      />
                      <div style={{ display: 'flex', gap: 8 }}>
                        <Tag
                          color="#ff2a6d"
                          style={{ fontSize: 10, margin: 0, padding: '2px 8px' }}
                        >
                          BEARISH
                        </Tag>
                        <Tag
                          color="default"
                          style={{ fontSize: 10, margin: 0, padding: '2px 8px', color: '#737373' }}
                        >
                          做空信号强度
                        </Tag>
                      </div>
                    </div>
                  </Col>
                </Row>

                {/* 决策依据 */}
                {result.reasoning && (
                  <div
                    style={{
                      marginTop: 24,
                      padding: 20,
                      background: 'rgba(26, 26, 26, 0.8)',
                      border: '1px solid #262626',
                      borderRadius: 4,
                    }}
                  >
                    <Text
                      style={{
                        fontSize: 11,
                        color: '#737373',
                        letterSpacing: '2px',
                        textTransform: 'uppercase',
                        fontWeight: 600,
                        display: 'block',
                        marginBottom: 12,
                      }}
                    >
                      // DECISION RATIONALE
                    </Text>
                    <Text style={{ color: '#a3a3a3', fontSize: 13, lineHeight: '1.8' }}>
                      {result.reasoning}
                    </Text>
                  </div>
                )}

                {/* 操作按钮 */}
                {result.suggested_strategy && (
                  <div style={{ textAlign: 'center', marginTop: 28 }}>
                    <Button
                      type="primary"
                      size="large"
                      icon={<Target size={18} />}
                      onClick={() =>
                        (window.location.href = `/strategies?action=create&type=${result.suggested_strategy}&symbol=${result.symbol}`)
                      }
                      style={{
                        height: 48,
                        minWidth: 220,
                        fontSize: 14,
                        fontWeight: 700,
                        letterSpacing: '1px',
                        background: 'linear-gradient(135deg, #00ff9d 0%, #00cc7d 100%)',
                        border: 'none',
                        color: '#000',
                        boxShadow: '0 0 30px rgba(0, 255, 157, 0.4)',
                        fontFamily: FONT_FAMILY,
                      }}
                    >
                      创建{result.suggested_strategy === 'swing_long' ? '做多' : '做空'}策略
                    </Button>
                  </div>
                )}
              </div>
            </Card>

            {/* 三因子分析详情 - 数据卡片网格 */}
            <Row gutter={24}>
              {/* 技术指标 */}
              <Col span={8}>
                <Card
                  title={
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <BarChart3 size={20} style={{ color: '#00d4ff' }} />
                      <span
                        style={{
                          fontSize: 15,
                          fontWeight: 700,
                          letterSpacing: '1px',
                          color: '#00d4ff',
                        }}
                      >
                        TECHNICAL
                      </span>
                      <Tag
                        style={{
                          marginLeft: 'auto',
                          fontSize: 11,
                          fontWeight: 700,
                          padding: '4px 10px',
                          background: '#00d4ff',
                          color: '#000',
                          border: 'none',
                        }}
                      >
                        40%
                      </Tag>
                    </div>
                  }
                  size="small"
                  style={{
                    background: 'rgba(10, 10, 10, 0.95)',
                    border: '1px solid #1a1a1a',
                    borderRadius: 4,
                    height: '100%',
                  }}
                  styles={{ body: { padding: '20px' } }}
                >
                  <div style={{ marginBottom: 20 }}>
                    <div
                      style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}
                    >
                      <Text
                        style={{
                          color: '#737373',
                          fontSize: 11,
                          fontWeight: 600,
                          letterSpacing: '1px',
                        }}
                      >
                        综合评分
                      </Text>
                      <Text
                        style={{
                          color: result.factors.technical.score >= 0.6 ? '#00ff9d' : '#ffae00',
                          fontSize: 24,
                          fontWeight: 900,
                          fontFamily: FONT_FAMILY,
                        }}
                      >
                        {(result.factors.technical.score * 100).toFixed(0)}
                      </Text>
                    </div>
                    <Progress
                      percent={result.factors.technical.score * 100}
                      strokeColor={result.factors.technical.score >= 0.6 ? '#00ff9d' : '#ffae00'}
                      trailColor="rgba(255, 255, 255, 0.05)"
                      showInfo={false}
                      size={8}
                    />
                  </div>
                  <Divider style={{ borderColor: '#1a1a1a', margin: '20px 0' }} />

                  <Descriptions column={1} size="small">
                    {result.factors.technical.details?.trend && (
                      <Descriptions.Item
                        label={<Text style={{ color: '#737373', fontSize: 12 }}>趋势</Text>}
                      >
                        <div style={{ color: '#a3a3a3', fontSize: 13 }}>
                          {result.factors.technical.details.trend.analysis || '-'}
                        </div>
                      </Descriptions.Item>
                    )}
                    {result.factors.technical.details?.momentum && (
                      <>
                        <Descriptions.Item
                          label={<Text style={{ color: '#737373', fontSize: 12 }}>RSI</Text>}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                            <Text
                              style={{
                                color:
                                  result.factors.technical.details.momentum.rsi > 70
                                    ? '#ff2a6d'
                                    : result.factors.technical.details.momentum.rsi < 30
                                      ? '#00ff9d'
                                      : '#a3a3a3',
                                fontSize: 18,
                                fontWeight: 700,
                                fontFamily: FONT_FAMILY,
                              }}
                            >
                              {result.factors.technical.details.momentum.rsi ?? '-'}
                            </Text>
                            {result.factors.technical.details.momentum.rsi > 70 && (
                              <Tag color="#ff2a6d" style={{ fontSize: 10, margin: 0 }}>
                                超买
                              </Tag>
                            )}
                            {result.factors.technical.details.momentum.rsi < 30 && (
                              <Tag color="#00ff9d" style={{ fontSize: 10, margin: 0 }}>
                                超卖
                              </Tag>
                            )}
                          </div>
                        </Descriptions.Item>
                        <Descriptions.Item
                          label={<Text style={{ color: '#737373', fontSize: 12 }}>动量</Text>}
                        >
                          <Text
                            style={{
                              color:
                                result.factors.technical.details.momentum.momentum > 0
                                  ? '#00ff9d'
                                  : '#ff2a6d',
                              fontSize: 14,
                              fontWeight: 600,
                              fontFamily: FONT_FAMILY,
                            }}
                          >
                            {result.factors.technical.details.momentum.momentum > 0 ? '+' : ''}
                            {result.factors.technical.details.momentum.momentum ?? 0}%
                          </Text>
                        </Descriptions.Item>
                      </>
                    )}
                    {result.factors.technical.details?.volatility !== undefined && (
                      <Descriptions.Item
                        label={<Text style={{ color: '#737373', fontSize: 12 }}>波动率</Text>}
                      >
                        <Tag
                          color={
                            result.factors.technical.details.volatility > 5 ? '#ff2a6d' : '#00ff9d'
                          }
                          style={{ fontSize: 12, fontWeight: 600 }}
                        >
                          {result.factors.technical.details.volatility}%
                        </Tag>
                      </Descriptions.Item>
                    )}
                  </Descriptions>
                </Card>
              </Col>

              {/* 市场情绪 */}
              <Col span={8}>
                <Card
                  title={
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <Activity size={20} style={{ color: '#ffae00' }} />
                      <span
                        style={{
                          fontSize: 15,
                          fontWeight: 700,
                          letterSpacing: '1px',
                          color: '#ffae00',
                        }}
                      >
                        SENTIMENT
                      </span>
                      <Tag
                        style={{
                          marginLeft: 'auto',
                          fontSize: 11,
                          fontWeight: 700,
                          padding: '4px 10px',
                          background: '#ffae00',
                          color: '#000',
                          border: 'none',
                        }}
                      >
                        30%
                      </Tag>
                    </div>
                  }
                  size="small"
                  style={{
                    background: 'rgba(10, 10, 10, 0.95)',
                    border: '1px solid #1a1a1a',
                    borderRadius: 4,
                    height: '100%',
                  }}
                  styles={{ body: { padding: '20px' } }}
                >
                  <div style={{ marginBottom: 20 }}>
                    <div
                      style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}
                    >
                      <Text
                        style={{
                          color: '#737373',
                          fontSize: 11,
                          fontWeight: 600,
                          letterSpacing: '1px',
                        }}
                      >
                        综合得分
                      </Text>
                      <Text
                        style={{
                          color: result.factors.sentiment.score >= 0.6 ? '#00ff9d' : '#ffae00',
                          fontSize: 24,
                          fontWeight: 900,
                          fontFamily: FONT_FAMILY,
                        }}
                      >
                        {(result.factors.sentiment.score * 100).toFixed(0)}
                      </Text>
                    </div>
                    <Progress
                      percent={result.factors.sentiment.score * 100}
                      strokeColor={result.factors.sentiment.score >= 0.6 ? '#00ff9d' : '#ffae00'}
                      trailColor="rgba(255, 255, 255, 0.05)"
                      showInfo={false}
                      size={8}
                    />
                  </div>
                  <Divider style={{ borderColor: '#1a1a1a', margin: '20px 0' }} />

                  <Descriptions column={1} size="small">
                    {result.factors.sentiment.details?.funding_rate !== undefined && (
                      <Descriptions.Item
                        label={<Text style={{ color: '#737373', fontSize: 12 }}>资金费率</Text>}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <Text
                            style={{
                              color:
                                result.factors.sentiment.details.funding_rate > 0.01
                                  ? '#ff2a6d'
                                  : result.factors.sentiment.details.funding_rate < -0.01
                                    ? '#00ff9d'
                                    : '#a3a3a3',
                              fontSize: 15,
                              fontWeight: 600,
                              fontFamily: FONT_FAMILY,
                            }}
                          >
                            {formatPercent(result.factors.sentiment.details.funding_rate / 100)}
                          </Text>
                          {result.factors.sentiment.details.funding_rate > 0.01 && (
                            <Tag color="#ff2a6d" style={{ fontSize: 10, margin: 0 }}>
                              多头过热
                            </Tag>
                          )}
                          {result.factors.sentiment.details.funding_rate < -0.01 && (
                            <Tag color="#00ff9d" style={{ fontSize: 10, margin: 0 }}>
                              空头过热
                            </Tag>
                          )}
                        </div>
                      </Descriptions.Item>
                    )}
                    {result.factors.sentiment.details?.sentiment && (
                      <Descriptions.Item
                        label={<Text style={{ color: '#737373', fontSize: 12 }}>市场情绪</Text>}
                      >
                        <Tag
                          color={
                            result.factors.sentiment.details.sentiment === 'bullish'
                              ? '#00ff9d'
                              : result.factors.sentiment.details.sentiment === 'bearish'
                                ? '#ff2a6d'
                                : 'default'
                          }
                          style={{
                            fontSize: 11,
                            fontWeight: 600,
                            padding: '4px 12px',
                          }}
                        >
                          {result.factors.sentiment.details.sentiment === 'bullish'
                            ? '看涨 BULLISH'
                            : result.factors.sentiment.details.sentiment === 'bearish'
                              ? '看跌 BEARISH'
                              : '中性 NEUTRAL'}
                        </Tag>
                      </Descriptions.Item>
                    )}
                  </Descriptions>
                </Card>
              </Col>

              {/* AI深度分析 */}
              <Col span={8}>
                <Card
                  title={
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <Brain size={20} style={{ color: '#a855f7' }} />
                      <span
                        style={{
                          fontSize: 15,
                          fontWeight: 700,
                          letterSpacing: '1px',
                          color: '#a855f7',
                        }}
                      >
                        AI ANALYSIS
                      </span>
                      <Tag
                        style={{
                          marginLeft: 'auto',
                          fontSize: 11,
                          fontWeight: 700,
                          padding: '4px 10px',
                          background: '#a855f7',
                          color: '#fff',
                          border: 'none',
                        }}
                      >
                        30%
                      </Tag>
                    </div>
                  }
                  size="small"
                  style={{
                    background: 'rgba(10, 10, 10, 0.95)',
                    border: '1px solid #1a1a1a',
                    borderRadius: 4,
                    height: '100%',
                  }}
                  styles={{ body: { padding: '20px' } }}
                >
                  <div style={{ marginBottom: 20 }}>
                    <div
                      style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}
                    >
                      <Text
                        style={{
                          color: '#737373',
                          fontSize: 11,
                          fontWeight: 600,
                          letterSpacing: '1px',
                        }}
                      >
                        信心度
                      </Text>
                      <Text
                        style={{
                          color: result.factors.ai.score >= 0.7 ? '#00ff9d' : '#ffae00',
                          fontSize: 24,
                          fontWeight: 900,
                          fontFamily: FONT_FAMILY,
                        }}
                      >
                        {(result.factors.ai.score * 100).toFixed(0)}
                      </Text>
                    </div>
                    <Progress
                      percent={result.factors.ai.score * 100}
                      strokeColor={result.factors.ai.score >= 0.7 ? '#00ff9d' : '#ffae00'}
                      trailColor="rgba(255, 255, 255, 0.05)"
                      showInfo={false}
                      size={8}
                    />
                  </div>
                  <Divider style={{ borderColor: '#1a1a1a', margin: '20px 0' }} />

                  {result.factors.ai.analysis && result.factors.ai.analysis !== '未配置AI服务' ? (
                    <div
                      style={{
                        padding: 16,
                        background: 'rgba(168, 85, 247, 0.05)',
                        borderRadius: 4,
                        border: '1px dashed rgba(168, 85, 247, 0.3)',
                        position: 'relative',
                        overflow: 'hidden',
                      }}
                    >
                      {/* 装饰性光效 */}
                      <div
                        style={{
                          position: 'absolute',
                          top: -20,
                          right: -20,
                          width: 60,
                          height: 60,
                          background:
                            'radial-gradient(circle, rgba(168, 85, 247, 0.2) 0%, transparent 70%)',
                          borderRadius: '50%',
                        }}
                      />
                      <Text
                        style={{
                          color: '#a3a3a3',
                          fontSize: 13,
                          lineHeight: '1.8',
                          display: 'block',
                          position: 'relative',
                          zIndex: 1,
                        }}
                      >
                        {result.factors.ai.analysis}
                      </Text>
                    </div>
                  ) : (
                    <div
                      style={{
                        padding: 32,
                        textAlign: 'center',
                        background: 'rgba(26, 26, 26, 0.5)',
                        borderRadius: 4,
                      }}
                    >
                      <Brain size={32} style={{ color: '#3b3b3b', marginBottom: 12 }} />
                      <Text style={{ color: '#525252', fontSize: 12 }}>AI分析服务未配置</Text>
                    </div>
                  )}
                </Card>
              </Col>
            </Row>

            {/* 风险提示 - 技术终端风格 */}
            <Alert
              message={
                <span
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 12,
                    fontSize: 13,
                    fontWeight: 600,
                    letterSpacing: '1px',
                    color: '#ffae00',
                  }}
                >
                  <AlertTriangle size={18} />⚠ RISK DISCLAIMER // 风险提示
                </span>
              }
              description={
                <div style={{ fontSize: 12, marginTop: 16 }}>
                  <div
                    style={{
                      marginBottom: 10,
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: 10,
                      padding: '8px 0',
                    }}
                  >
                    <div
                      style={{
                        width: 4,
                        height: 4,
                        borderRadius: '50%',
                        background: '#ffae00',
                        marginTop: 6,
                        flexShrink: 0,
                      }}
                    />
                    <span style={{ color: '#a3a3a3', lineHeight: '1.6' }}>
                      本分析仅供参考，不构成投资建议。所有投资决策需自行承担风险。
                    </span>
                  </div>
                  <div
                    style={{
                      marginBottom: 10,
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: 10,
                      padding: '8px 0',
                    }}
                  >
                    <div
                      style={{
                        width: 4,
                        height: 4,
                        borderRadius: '50%',
                        background: '#ffae00',
                        marginTop: 6,
                        flexShrink: 0,
                      }}
                    />
                    <span style={{ color: '#a3a3a3', lineHeight: '1.6' }}>
                      信心度低于 60% 时，建议观望等待更明确的市场信号。
                    </span>
                  </div>
                  <div
                    style={{
                      marginBottom: 10,
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: 10,
                      padding: '8px 0',
                    }}
                  >
                    <div
                      style={{
                        width: 4,
                        height: 4,
                        borderRadius: '50%',
                        background: '#ffae00',
                        marginTop: 6,
                        flexShrink: 0,
                      }}
                    />
                    <span style={{ color: '#a3a3a3', lineHeight: '1.6' }}>
                      实际交易前请结合多重时间框架分析，并严格执行风险管理。
                    </span>
                  </div>
                  <div
                    style={{
                      marginBottom: 10,
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: 10,
                      padding: '8px 0',
                    }}
                  >
                    <div
                      style={{
                        width: 4,
                        height: 4,
                        borderRadius: '50%',
                        background: '#ffae00',
                        marginTop: 6,
                        flexShrink: 0,
                      }}
                    />
                    <span style={{ color: '#a3a3a3', lineHeight: '1.6' }}>
                      严格控制仓位，设置合理的止损止盈，避免单次交易风险过大。
                    </span>
                  </div>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: 10,
                      padding: '8px 0',
                    }}
                  >
                    <div
                      style={{
                        width: 4,
                        height: 4,
                        borderRadius: '50%',
                        background: '#ffae00',
                        marginTop: 6,
                        flexShrink: 0,
                      }}
                    />
                    <span style={{ color: '#a3a3a3', lineHeight: '1.6' }}>
                      建议先用小金额测试策略效果，验证系统稳定性和盈利能力。
                    </span>
                  </div>
                </div>
              }
              type="warning"
              showIcon={false}
              style={{
                marginTop: 32,
                background:
                  'linear-gradient(135deg, rgba(255, 174, 0, 0.05) 0%, rgba(255, 174, 0, 0.02) 100%)',
                border: '1px solid rgba(255, 174, 0, 0.2)',
                borderRadius: 4,
              }}
            />
          </>
        )}

        {/* 初始状态 - 赛博朋克空状态 */}
        {!result && !analyzing && (
          <div
            style={{
              textAlign: 'center',
              padding: '100px 40px',
              background: 'rgba(10, 10, 10, 0.8)',
              border: '2px dashed #1a1a1a',
              borderRadius: 4,
              position: 'relative',
              overflow: 'hidden',
            }}
          >
            {/* 装饰性背景 */}
            <div
              style={{
                position: 'absolute',
                top: '50%',
                left: '50%',
                transform: 'translate(-50%, -50%)',
                width: 400,
                height: 400,
                background: 'radial-gradient(circle, rgba(0, 255, 157, 0.03) 0%, transparent 70%)',
                borderRadius: '50%',
              }}
            />

            <div style={{ position: 'relative', zIndex: 1 }}>
              <div
                style={{
                  width: 100,
                  height: 100,
                  position: 'relative',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  margin: '0 auto 32px',
                }}
              >
                <Hexagon size={100} style={{ color: '#1a1a1a' }} />
                <Brain size={48} style={{ color: '#262626', position: 'absolute' }} />
              </div>
              <Title
                level={3}
                style={{
                  color: '#525252',
                  marginBottom: 16,
                  fontSize: 24,
                  fontWeight: 700,
                  letterSpacing: '2px',
                }}
              >
                AWAITING INPUT
              </Title>
              <Text
                style={{
                  color: '#3b3b3b',
                  fontSize: 14,
                  letterSpacing: '1px',
                }}
              >
                选择交易对 // AI将基于多因子量化模型给出综合判断
              </Text>
            </div>
          </div>
        )}
      </div>

      {/* 脉冲动画 */}
      <style>{`
        @keyframes pulse {
          0%, 100% {
            opacity: 1;
            transform: scale(1);
          }
          50% {
            opacity: 0.5;
            transform: scale(1.1);
          }
        }

        .ant-progress-bg {
          position: relative !important;
          overflow: visible !important;
        }

        .ant-progress-bg::after {
          content: '';
          position: absolute;
          top: 0;
          right: 0;
          width: 100%;
          height: 100%;
          background: inherit;
          filter: blur(8px);
          opacity: 0.5;
          z-index: -1;
        }
      `}</style>
    </div>
  )
}

export default MarketAnalysisPage
