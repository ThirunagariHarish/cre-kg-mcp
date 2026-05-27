import React, { Component, ReactNode, useState, useCallback } from 'react'
import clsx from 'clsx'
import { useQueryClient } from '@tanstack/react-query'
import LoginScreen from '@/components/auth/LoginScreen'
import { useAuthStore } from '@/stores/authStore'
import TerminalShell from '@/components/layout/TerminalShell'
import WatchlistPanel from '@/components/market/WatchlistPanel'
import PositionsGrid from '@/components/trading/PositionsGrid'
import SignalFeed from '@/components/signals/SignalFeed'
import OrderBlotter from '@/components/trading/OrderBlotter'
import RiskPanel from '@/components/risk/RiskPanel'
import AIRecommendationPanel from '@/components/ai/AIRecommendationPanel'
import TradeTicket from '@/components/trading/TradeTicket'
import OptionsTradeTicket from '@/components/trading/OptionsTradeTicket'
import SpreadBuilder from '@/components/trading/SpreadBuilder'
import PositionSizerPanel from '@/components/trading/PositionSizerPanel'
import AgentsPanel from '@/components/agents/AgentsPanel'
import CommandPalette from '@/components/shared/CommandPalette'
import AlertRail from '@/components/shared/AlertRail'
import ChartPanel from '@/components/charts/ChartPanel'
import EquityCurvePanel from '@/components/analytics/EquityCurvePanel'
import MetricsDashboard from '@/components/analytics/MetricsDashboard'
import AgentAttributionPanel from '@/components/analytics/AgentAttributionPanel'
import DrawdownPanel from '@/components/analytics/DrawdownPanel'
import SectorExposurePanel from '@/components/analytics/SectorExposurePanel'
import MarketRegimeBadge from '@/components/intelligence/MarketRegimeBadge'
import ConfluencePanel from '@/components/intelligence/ConfluencePanel'
import NewsFeed from '@/components/intelligence/NewsFeed'
import OptionsFlowFeed from '@/components/intelligence/OptionsFlowFeed'
import DarkPoolFeed from '@/components/intelligence/DarkPoolFeed'
import ShortSqueezePanel from '@/components/intelligence/ShortSqueezePanel'
import SocialBuzzPanel from '@/components/intelligence/SocialBuzzPanel'
import CongressTradePanel from '@/components/intelligence/CongressTradePanel'
import ApprovalsInbox from '@/components/intelligence/ApprovalsInbox'
import AuditTrailPanel from '@/components/intelligence/AuditTrailPanel'
import ExceptionQueuePanel from '@/components/intelligence/ExceptionQueuePanel'
import BacktestPanel from '@/components/shared/BacktestPanel'
import { useLivePortfolio } from '@/hooks/useLivePortfolio'
import { useLiveSignals } from '@/hooks/useLiveSignals'
import { useLiveOrders } from '@/hooks/useLiveOrders'
import { useWatchlist } from '@/hooks/useWatchlist'
import { useQuotes } from '@/hooks/useQuotes'
import { useRiskStatus } from '@/hooks/useRiskStatus'
import { apiPost } from '@/lib/api/client'
import { useTerminalStore } from '@/stores/terminalStore'
import type { WorkspaceTab } from '@/stores/terminalStore'
import type { Signal } from '@/types/signals'
import type { RiskStatus } from '@/types/risk'
import type { OrderRequest } from '@/types/orders'
import type { AIRecommendation } from '@/types/ai'

class ErrorBoundary extends Component<{ children: ReactNode; name: string }, { error: Error | null }> {
  state = { error: null }
  static getDerivedStateFromError(error: Error) { return { error } }
  render() {
    if (this.state.error) {
      return (
        <div className="p-3 text-[0.65rem] font-mono text-negative">
          <div className="text-text-muted uppercase mb-1">{this.props.name} error</div>
          <div>{(this.state.error as Error).message}</div>
        </div>
      )
    }
    return this.props.children
  }
}

/* ─────────────────────────────────────────────
   Default empty risk status — used while loading or when API is offline
───────────────────────────────────────────── */

const emptyRiskStatus: RiskStatus = {
  killSwitchActive: false,
  isHealthy: true,
  breaches: [],
  lastUpdated: Date.now(),
  metrics: {
    totalExposure: 0,
    totalExposurePercent: 0,
    netExposure: 0,
    longExposure: 0,
    shortExposure: 0,
    dailyPnl: 0,
    dailyPnlPercent: 0,
    dailyLossUsedPercent: 0,
    maxDrawdown: 0,
    maxDrawdownPercent: 0,
    openPositionCount: 0,
    timestamp: Date.now(),
  },
  policy: {
    id: 'default',
    name: 'Default',
    description: '',
    enabled: true,
    maxPositionSizePercent: 5,
    maxSinglePositionValue: 50000,
    maxPositionCount: 10,
    maxDailyLossPercent: 3,
    maxDailyLossAbsolute: 5000,
    maxDrawdownPercent: 10,
    maxOrderValue: 25000,
    maxOrderQuantity: 1000,
    maxSectorExposurePercent: 30,
    maxSymbolExposurePercent: 15,
    killSwitchEnabled: true,
    killSwitchDailyLossThreshold: 5000,
    updatedAt: Date.now(),
  },
}

/* ─────────────────────────────────────────────
   Tab Bar
───────────────────────────────────────────── */

type TabDef = { id: WorkspaceTab; label: string; shortLabel?: string }

const TABS: TabDef[] = [
  { id: 'POSITIONS',    label: 'Positions',    shortLabel: 'POS' },
  { id: 'AGENTS',       label: 'Agents',       shortLabel: 'AGT' },
  { id: 'ORDERS',       label: 'Orders',       shortLabel: 'ORD' },
  { id: 'SIGNALS',      label: 'Signals',      shortLabel: 'SIG' },
  { id: 'CHART',        label: 'Chart',        shortLabel: 'CHT' },
  { id: 'ANALYTICS',    label: 'Analytics',    shortLabel: 'ANA' },
  { id: 'INTELLIGENCE', label: 'Intelligence', shortLabel: 'INT' },
  { id: 'BACKTEST',     label: 'Backtest',     shortLabel: 'BKT' },
]

interface TabBarProps {
  active: WorkspaceTab
  onChange: (t: WorkspaceTab) => void
  positionsCount: number
  ordersCount: number
  signalsCount: number
}

function TabBar({ active, onChange, positionsCount, ordersCount, signalsCount }: TabBarProps) {
  const counts: Partial<Record<WorkspaceTab, number>> = {
    POSITIONS: positionsCount,
    ORDERS: ordersCount,
    SIGNALS: signalsCount,
  }
  return (
    <div className="flex items-center h-8 border-b border-border-subtle flex-shrink-0 bg-bg-panel overflow-x-auto">
      {TABS.map(tab => {
        const count = counts[tab.id]
        return (
          <button
            key={tab.id}
            onClick={() => onChange(tab.id)}
            className={clsx(
              'flex items-center gap-1.5 px-3 h-full font-mono text-[0.62rem] uppercase tracking-wide transition-colors flex-shrink-0 border-b-2',
              active === tab.id
                ? 'text-accent-cyan border-b-accent-cyan bg-bg-panel-raised'
                : 'text-text-muted border-b-transparent hover:text-text-secondary hover:bg-bg-panel-raised'
            )}
          >
            <span className="hidden sm:inline">{tab.label}</span>
            <span className="sm:hidden">{tab.shortLabel ?? tab.label}</span>
            {count !== undefined && count > 0 && (
              <span className={clsx(
                'font-mono text-[0.55rem] px-1 py-px rounded-sm',
                active === tab.id ? 'bg-[rgba(255,102,0,0.12)] text-accent-cyan' : 'text-text-dim'
              )}>
                {count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

/* ─────────────────────────────────────────────
   Analytics Tab Layout
───────────────────────────────────────────── */

function AnalyticsTab() {
  return (
    <div className="h-full overflow-y-auto p-2 grid grid-cols-2 gap-2" style={{ gridTemplateRows: 'auto auto auto' }}>
      <div className="col-span-2 h-56">
        <ErrorBoundary name="EquityCurve">
          <EquityCurvePanel />
        </ErrorBoundary>
      </div>
      <div className="h-52">
        <ErrorBoundary name="Drawdown">
          <DrawdownPanel />
        </ErrorBoundary>
      </div>
      <div className="h-52">
        <ErrorBoundary name="Metrics">
          <MetricsDashboard />
        </ErrorBoundary>
      </div>
      <div className="h-52">
        <ErrorBoundary name="AgentAttribution">
          <AgentAttributionPanel />
        </ErrorBoundary>
      </div>
      <div className="h-52">
        <ErrorBoundary name="SectorExposure">
          <SectorExposurePanel />
        </ErrorBoundary>
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────
   Intelligence Tab Layout
───────────────────────────────────────────── */

function IntelligenceTab() {
  return (
    <div className="h-full overflow-y-auto p-2 grid grid-cols-2 gap-2">
      <div className="col-span-2 h-36">
        <ErrorBoundary name="MarketRegime">
          <MarketRegimeBadge variant="panel" />
        </ErrorBoundary>
      </div>
      <div className="h-64">
        <ErrorBoundary name="Confluence">
          <ConfluencePanel />
        </ErrorBoundary>
      </div>
      <div className="h-64">
        <ErrorBoundary name="News">
          <NewsFeed />
        </ErrorBoundary>
      </div>
      <div className="h-64">
        <ErrorBoundary name="OptionsFlow">
          <OptionsFlowFeed />
        </ErrorBoundary>
      </div>
      <div className="h-64">
        <ErrorBoundary name="DarkPool">
          <DarkPoolFeed />
        </ErrorBoundary>
      </div>
      <div className="col-span-2 h-64">
        <ErrorBoundary name="ShortSqueeze">
          <ShortSqueezePanel />
        </ErrorBoundary>
      </div>
      <div className="h-64">
        <ErrorBoundary name="SocialBuzz">
          <SocialBuzzPanel />
        </ErrorBoundary>
      </div>
      <div className="h-64">
        <ErrorBoundary name="CongressTrade">
          <CongressTradePanel />
        </ErrorBoundary>
      </div>
      <div className="col-span-2 h-64">
        <ErrorBoundary name="ApprovalsInbox">
          <ApprovalsInbox />
        </ErrorBoundary>
      </div>
      <div className="h-64">
        <ErrorBoundary name="AuditTrail">
          <AuditTrailPanel />
        </ErrorBoundary>
      </div>
      <div className="h-64">
        <ErrorBoundary name="ExceptionQueue">
          <ExceptionQueuePanel />
        </ErrorBoundary>
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────
   App
───────────────────────────────────────────── */

export default function App() {
  const isAuthenticated = useAuthStore(s => s.isAuthenticated)

  if (!isAuthenticated) return <LoginScreen />

  const qc = useQueryClient()
  const [selectedSymbol, setSelectedSymbol] = useState<string>('AAPL')
  const [aiRecommendation, setAiRecommendation] = useState<AIRecommendation | undefined>()
  const [aiLoading, setAiLoading] = useState(false)
  const [tradeTab, setTradeTab] = useState<'EQUITY' | 'OPTIONS' | 'SPREAD'>('EQUITY')

  // Read/write workspace tab from global store so CommandPalette can switch it
  const activeTab = useTerminalStore(s => s.workspaceTab)
  const setActiveTab = useTerminalStore(s => s.setWorkspaceTab)

  // Real data hooks
  const { items: watchlist, addSymbol, removeSymbol } = useWatchlist()
  const { quotes } = useQuotes(watchlist.map(i => i.symbol))
  const { positions } = useLivePortfolio()
  const { signals } = useLiveSignals()
  const { orders } = useLiveOrders()
  const { riskStatus, activateEmergencyStop } = useRiskStatus()

  // Order submission — calls POST /api/orders, then invalidates cache
  const handleSubmitOrder = useCallback(async (orderRequest: OrderRequest) => {
    await apiPost('/api/orders', {
      symbol: orderRequest.symbol,
      side: orderRequest.side.toLowerCase(),
      order_type: orderRequest.type.toLowerCase(),
      quantity: orderRequest.quantity,
      limit_price: orderRequest.limitPrice,
      time_in_force: orderRequest.timeInForce?.toLowerCase() ?? 'day',
    })
    qc.invalidateQueries({ queryKey: ['orders'] })
    qc.invalidateQueries({ queryKey: ['portfolio-summary'] })
  }, [qc])

  // AI analysis handler — calls POST /api/ai/recommend
  const handleAnalyzeSignal = useCallback(async (signal: Signal) => {
    setAiLoading(true)
    setAiRecommendation(undefined)
    try {
      const rec = await apiPost<AIRecommendation>('/api/ai/recommend', {
        signal_id: signal.id,
        signal_text: signal.rawMessage,
        symbol: signal.ticker,
      })
      setAiRecommendation(rec)
    } catch {
      setAiRecommendation(undefined)
    } finally {
      setAiLoading(false)
    }
  }, [])

  // Dynamic risk preview based on selected symbol
  const selectedQuote = quotes.get(selectedSymbol)
  const tradeQty = 100
  const estimatedValue = selectedQuote ? selectedQuote.last * tradeQty : 0
  const portfolioTotal = 100_000
  const riskPreview = {
    estimatedValue,
    portfolioPercent: parseFloat(((estimatedValue / portfolioTotal) * 100).toFixed(1)),
    maxLoss: parseFloat((estimatedValue * 0.02).toFixed(0)),
    riskReward: 2.5,
  }

  return (
    <div className="h-screen w-screen overflow-hidden bg-bg-root text-text-primary font-mono">
      {/* Global overlays — mounted at root so they float above everything */}
      <CommandPalette symbols={Array.from(quotes.keys())} />
      <AlertRail />

      <TerminalShell
        leftPanel={
          <ErrorBoundary name="Watchlist">
            <WatchlistPanel
              items={watchlist}
              quotes={quotes}
              selectedSymbol={selectedSymbol}
              onSymbolSelect={setSelectedSymbol}
              onAddSymbol={addSymbol}
              onRemoveSymbol={removeSymbol}
            />
          </ErrorBoundary>
        }
        mainWorkspace={
          <div className="flex flex-col h-full overflow-hidden">
            <TabBar
              active={activeTab}
              onChange={setActiveTab}
              positionsCount={positions.length}
              ordersCount={orders.length}
              signalsCount={signals.length}
            />

            <div className="flex-1 overflow-hidden min-h-0">
              {activeTab === 'POSITIONS' && (
                <ErrorBoundary name="Positions">
                  <PositionsGrid
                    positions={positions}
                    selectedSymbol={selectedSymbol}
                    onSymbolSelect={setSelectedSymbol}
                  />
                </ErrorBoundary>
              )}
              {activeTab === 'AGENTS' && (
                <ErrorBoundary name="Agents">
                  <AgentsPanel />
                </ErrorBoundary>
              )}
              {activeTab === 'ORDERS' && (
                <ErrorBoundary name="Orders">
                  <OrderBlotter orders={orders} />
                </ErrorBoundary>
              )}
              {activeTab === 'SIGNALS' && (
                <ErrorBoundary name="Signals">
                  <SignalFeed
                    signals={signals}
                    onAnalyzeSignal={handleAnalyzeSignal}
                  />
                </ErrorBoundary>
              )}
              {activeTab === 'CHART' && (
                <ErrorBoundary name="Chart">
                  <ChartPanel
                    defaultSymbol={selectedSymbol}
                    onSymbolChange={setSelectedSymbol}
                  />
                </ErrorBoundary>
              )}
              {activeTab === 'ANALYTICS' && (
                <ErrorBoundary name="Analytics">
                  <AnalyticsTab />
                </ErrorBoundary>
              )}
              {activeTab === 'INTELLIGENCE' && (
                <ErrorBoundary name="Intelligence">
                  <IntelligenceTab />
                </ErrorBoundary>
              )}
              {activeTab === 'BACKTEST' && (
                <ErrorBoundary name="Backtest">
                  <BacktestPanel />
                </ErrorBoundary>
              )}
            </div>
          </div>
        }
        rightPanel={
          <div className="flex flex-col h-full overflow-hidden">
            {/* Trade area with 3-tab switcher */}
            <div className="flex-shrink-0 border-b border-border-subtle">
              {/* Tab switcher row */}
              <div className="flex border-b border-border-subtle bg-bg-panel">
                {(['EQUITY', 'OPTIONS', 'SPREAD'] as const).map(tab => (
                  <button
                    key={tab}
                    type="button"
                    onClick={() => setTradeTab(tab)}
                    className={clsx(
                      'flex-1 py-1.5 font-mono text-[0.6rem] uppercase tracking-wide transition-colors border-b-2',
                      tradeTab === tab
                        ? 'text-accent-cyan border-b-accent-cyan bg-bg-panel-raised'
                        : 'text-text-muted border-b-transparent hover:text-text-secondary hover:bg-bg-panel-raised'
                    )}
                  >
                    {tab}
                  </button>
                ))}
              </div>
              {tradeTab === 'EQUITY' && (
                <ErrorBoundary name="TradeTicket">
                  <TradeTicket
                    defaultSymbol={selectedSymbol}
                    availableCash={35_157.44}
                    onSubmit={handleSubmitOrder}
                    riskPreview={riskPreview}
                  />
                </ErrorBoundary>
              )}
              {tradeTab === 'OPTIONS' && (
                <ErrorBoundary name="OptionsTradeTicket">
                  <OptionsTradeTicket defaultSymbol={selectedSymbol} />
                </ErrorBoundary>
              )}
              {tradeTab === 'SPREAD' && (
                <ErrorBoundary name="SpreadBuilder">
                  <SpreadBuilder symbol={selectedSymbol} />
                </ErrorBoundary>
              )}
            </div>

            <div className="flex-1 overflow-hidden min-h-0 border-b border-border-subtle">
              <ErrorBoundary name="Risk">
                <RiskPanel
                  riskStatus={riskStatus ?? emptyRiskStatus}
                  onKillSwitch={() => activateEmergencyStop('manual')}
                />
              </ErrorBoundary>
            </div>

            <div className="flex-[0.5] overflow-hidden min-h-0 border-b border-border-subtle">
              <ErrorBoundary name="PositionSizer">
                <PositionSizerPanel />
              </ErrorBoundary>
            </div>

            <div className="flex-[0.6] overflow-hidden min-h-0">
              <ErrorBoundary name="AI">
                <AIRecommendationPanel
                  recommendation={aiRecommendation}
                  loading={aiLoading}
                />
              </ErrorBoundary>
            </div>
          </div>
        }
      />
    </div>
  )
}
