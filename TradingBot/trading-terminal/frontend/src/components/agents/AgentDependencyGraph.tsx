import React, { useState, useRef, useCallback, useMemo } from 'react'
import clsx from 'clsx'

/* ─────────────────────────────────────────────
   Types
───────────────────────────────────────────── */

interface GraphAgent {
  name: string
  category: string
  dependencies?: string[]
}

interface AgentDependencyGraphProps {
  agents?: GraphAgent[]
}

/* ─────────────────────────────────────────────
   Category colors
───────────────────────────────────────────── */

const CAT_COLOR: Record<string, { fill: string; stroke: string; text: string; label: string }> = {
  ALGORITHM: { fill: '#1a0800', stroke: '#ff6600', text: '#ff6600', label: 'ALGO' },
  DISCORD:   { fill: '#1a0020', stroke: '#ab47bc', text: '#ab47bc', label: 'DISC' },
  AI:        { fill: '#1a1400', stroke: '#ffcc00', text: '#ffcc00', label: 'AI' },
  DATA:      { fill: '#001a1f', stroke: '#00bcd4', text: '#00bcd4', label: 'DATA' },
  PORTFOLIO: { fill: '#111111', stroke: '#888888', text: '#888888', label: 'PORT' },
  OPTIONS:   { fill: '#001a0a', stroke: '#00e676', text: '#00e676', label: 'OPTS' },
}

const DEFAULT_CAT = { fill: '#111111', stroke: '#444444', text: '#888888', label: '?' }

/* ─────────────────────────────────────────────
   Hardcoded graph layout
   Tier 0 (top): data providers
   Tier 1 (mid): signals / analytics
   Tier 2 (mid-low): trading agents
   Tier 3 (bottom): portfolio / risk
───────────────────────────────────────────── */

interface NodeDef {
  id: string
  label: string
  category: string
  tier: number
  col: number
}

const GRAPH_NODES: NodeDef[] = [
  // Tier 0 — data providers
  { id: 'breadth_analyzer',       label: 'Breadth\nAnalyzer',   category: 'DATA',      tier: 0, col: 0 },
  { id: 'market_regime_detector', label: 'Regime\nDetector',    category: 'DATA',      tier: 0, col: 1 },
  { id: 'broker_health',          label: 'Broker\nHealth',      category: 'DATA',      tier: 0, col: 2 },
  { id: 'uw_congress_trader',     label: 'Congress\nTracker',   category: 'DATA',      tier: 0, col: 3 },
  { id: 'discord_context_reader', label: 'Discord\nReader',     category: 'DISCORD',   tier: 0, col: 4 },

  // Tier 1 — AI / signal sources
  { id: 'nlp_sentiment',          label: 'NLP\nSentiment',      category: 'AI',        tier: 1, col: 0 },
  { id: 'lstm_prediction',        label: 'LSTM\nPredictor',     category: 'AI',        tier: 1, col: 1 },
  { id: 'stbn_ai_signals',        label: 'STBN AI\nSignals',    category: 'AI',        tier: 1, col: 2 },
  { id: 'iron_condor',            label: 'Iron\nCondor',        category: 'OPTIONS',   tier: 1, col: 3 },

  // Tier 2 — trading agents (algo row)
  { id: 'breakout_trader',        label: 'Breakout\nTrader',    category: 'ALGORITHM', tier: 2, col: 0 },
  { id: 'uw_flow_signals_trader', label: 'UW Flow\nSignals',    category: 'ALGORITHM', tier: 2, col: 1 },
  { id: 'dark_pool_followthrough',label: 'Dark Pool\nFollow',   category: 'ALGORITHM', tier: 2, col: 2 },
  { id: 'gap_executor',           label: 'Gap & Go\nExecutor',  category: 'ALGORITHM', tier: 2, col: 3 },
  { id: 'earnings_momentum',      label: 'Earnings\nMomentum',  category: 'ALGORITHM', tier: 2, col: 4 },
  { id: 'mean_reversion',         label: 'Mean\nReversion',     category: 'ALGORITHM', tier: 2, col: 5 },

  // Tier 2b — more algos
  { id: 'albert_pro_trader',      label: 'Albert Pro\nTrader',  category: 'DISCORD',   tier: 3, col: 0 },
  { id: 'vcp_setups_trader',      label: 'VCP Setups\nTrader',  category: 'DISCORD',   tier: 3, col: 1 },
  { id: 'uw_darkpool_trader',     label: 'UW Dark\nPool',       category: 'ALGORITHM', tier: 3, col: 2 },
  { id: 'sector_rotation',        label: 'Sector\nRotation',    category: 'ALGORITHM', tier: 3, col: 3 },
  { id: 'short_squeeze',          label: 'Short\nSqueeze',      category: 'ALGORITHM', tier: 3, col: 4 },

  // Tier 3 — portfolio managers
  { id: 'portfolio_manager',      label: 'Portfolio\nManager',  category: 'PORTFOLIO', tier: 4, col: 1 },
  { id: 'auto_hedging',           label: 'Auto\nHedge',         category: 'PORTFOLIO', tier: 4, col: 2 },
  { id: 'risk_monitor',           label: 'Risk\nMonitor',       category: 'PORTFOLIO', tier: 4, col: 3 },
]

// Edges: [source, target]
const GRAPH_EDGES: [string, string][] = [
  ['breadth_analyzer',       'market_regime_detector'],
  ['market_regime_detector', 'breakout_trader'],
  ['market_regime_detector', 'uw_flow_signals_trader'],
  ['market_regime_detector', 'sector_rotation'],
  ['market_regime_detector', 'lstm_prediction'],
  ['nlp_sentiment',          'stbn_ai_signals'],
  ['nlp_sentiment',          'albert_pro_trader'],
  ['lstm_prediction',        'uw_flow_signals_trader'],
  ['lstm_prediction',        'breakout_trader'],
  ['stbn_ai_signals',        'uw_flow_signals_trader'],
  ['stbn_ai_signals',        'gap_executor'],
  ['discord_context_reader', 'albert_pro_trader'],
  ['discord_context_reader', 'vcp_setups_trader'],
  ['broker_health',          'portfolio_manager'],
  ['broker_health',          'auto_hedging'],
  ['uw_flow_signals_trader', 'portfolio_manager'],
  ['breakout_trader',        'portfolio_manager'],
  ['dark_pool_followthrough','portfolio_manager'],
  ['earnings_momentum',      'portfolio_manager'],
  ['gap_executor',           'portfolio_manager'],
  ['mean_reversion',         'portfolio_manager'],
  ['albert_pro_trader',      'portfolio_manager'],
  ['vcp_setups_trader',      'portfolio_manager'],
  ['uw_darkpool_trader',     'portfolio_manager'],
  ['iron_condor',            'portfolio_manager'],
  ['portfolio_manager',      'auto_hedging'],
  ['portfolio_manager',      'risk_monitor'],
  ['risk_monitor',           'auto_hedging'],
  ['uw_congress_trader',     'sector_rotation'],
  ['sector_rotation',        'portfolio_manager'],
]

/* ─────────────────────────────────────────────
   Layout constants
───────────────────────────────────────────── */

const NODE_R = 24
const NODE_W = 78
const TIER_H = 100
const COL_W = 110
const PAD_X = 60
const PAD_Y = 30

function getNodePos(node: NodeDef, tierCounts: Record<number, number>): { x: number; y: number } {
  const totalInTier = tierCounts[node.tier] ?? 1
  const totalW = totalInTier * COL_W
  const startX = PAD_X + node.col * COL_W + (node.tier % 2 === 1 ? COL_W / 2 : 0)
  return {
    x: startX,
    y: PAD_Y + node.tier * TIER_H + NODE_R,
  }
}

/* ─────────────────────────────────────────────
   Main component
───────────────────────────────────────────── */

export default function AgentDependencyGraph({ agents }: AgentDependencyGraphProps) {
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const [scale, setScale] = useState(1)
  const svgRef = useRef<SVGSVGElement>(null)

  // Use hardcoded layout; if custom agents passed, merge
  const nodes = useMemo(() => {
    if (!agents || agents.length === 0) return GRAPH_NODES
    // Merge custom agents as new nodes not in the hardcoded set
    const known = new Set(GRAPH_NODES.map(n => n.id))
    const extras: NodeDef[] = agents
      .filter(a => !known.has(a.name))
      .map((a, i) => ({ id: a.name, label: a.name, category: a.category, tier: 5, col: i }))
    return [...GRAPH_NODES, ...extras]
  }, [agents])

  const tierCounts = useMemo(() => {
    const counts: Record<number, number> = {}
    nodes.forEach(n => { counts[n.tier] = (counts[n.tier] ?? 0) + 1 })
    return counts
  }, [nodes])

  const positions = useMemo(() => {
    const map: Record<string, { x: number; y: number }> = {}
    nodes.forEach(n => { map[n.id] = getNodePos(n, tierCounts) })
    return map
  }, [nodes, tierCounts])

  const maxTier = Math.max(...nodes.map(n => n.tier))
  const maxCol = Math.max(...nodes.map(n => n.col))
  const svgWidth = PAD_X * 2 + (maxCol + 1) * COL_W + COL_W
  const svgHeight = PAD_Y * 2 + (maxTier + 1) * TIER_H + NODE_R * 2

  // Connected nodes for highlight
  const connectedTo = useMemo((): Set<string> => {
    if (!selectedNode) return new Set()
    const connected = new Set<string>()
    GRAPH_EDGES.forEach(([s, t]) => {
      if (s === selectedNode || t === selectedNode) {
        connected.add(s)
        connected.add(t)
      }
    })
    return connected
  }, [selectedNode])

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault()
    setScale(prev => Math.min(2, Math.max(0.4, prev - e.deltaY * 0.001)))
  }, [])

  return (
    <div className="flex flex-col h-full overflow-hidden bg-bg-panel">
      {/* Header */}
      <div className="panel-header">
        <span className="flex-1">◈ Agent Dependencies</span>
        <span className="font-mono text-[0.52rem] text-text-muted">
          {nodes.length} nodes · {GRAPH_EDGES.length} edges
        </span>
        <button
          onClick={() => setScale(1)}
          className="font-mono text-[0.52rem] text-text-muted hover:text-text-secondary ml-2"
          aria-label="Reset zoom"
        >
          {Math.round(scale * 100)}% ↺
        </button>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-3 px-3 py-1.5 border-b border-border-subtle flex-shrink-0 overflow-x-auto">
        {Object.entries(CAT_COLOR).map(([cat, cfg]) => (
          <div key={cat} className="flex items-center gap-1 flex-shrink-0">
            <div
              className="w-2.5 h-2.5 rounded-full border"
              style={{ backgroundColor: cfg.fill, borderColor: cfg.stroke }}
            />
            <span className="font-mono text-[0.52rem]" style={{ color: cfg.text }}>{cfg.label}</span>
          </div>
        ))}
        {selectedNode && (
          <>
            <div className="w-px h-3 bg-border-subtle flex-shrink-0" />
            <button
              onClick={() => setSelectedNode(null)}
              className="font-mono text-[0.55rem] text-accent-cyan hover:text-text-secondary flex items-center gap-1 flex-shrink-0"
            >
              <span className="text-text-muted">{selectedNode}</span> — CLEAR SELECTION
            </button>
          </>
        )}
      </div>

      {/* SVG Graph */}
      <div
        className="flex-1 overflow-auto min-h-0 bg-bg-root"
        onWheel={handleWheel}
        role="img"
        aria-label="Agent dependency graph"
      >
        <svg
          ref={svgRef}
          width={svgWidth * scale}
          height={svgHeight * scale}
          viewBox={`0 0 ${svgWidth} ${svgHeight}`}
          className="block"
          style={{ transform: `scale(${scale})`, transformOrigin: 'top left' }}
        >
          {/* Edges */}
          <defs>
            <marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill="#1e1e1e" />
            </marker>
            <marker id="arrow-active" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill="#ff6600" />
            </marker>
          </defs>

          {GRAPH_EDGES.map(([src, tgt], i) => {
            const sp = positions[src]
            const tp = positions[tgt]
            if (!sp || !tp) return null

            const isActive = selectedNode === src || selectedNode === tgt ||
              (connectedTo.has(src) && connectedTo.has(tgt))
            const isHighlighted = selectedNode
              ? (selectedNode === src || selectedNode === tgt)
              : false

            // Compute edge endpoints at circle borders
            const dx = tp.x - sp.x
            const dy = tp.y - sp.y
            const dist = Math.sqrt(dx * dx + dy * dy) || 1
            const x1 = sp.x + (dx / dist) * NODE_R
            const y1 = sp.y + (dy / dist) * NODE_R
            const x2 = tp.x - (dx / dist) * (NODE_R + 6)
            const y2 = tp.y - (dy / dist) * (NODE_R + 6)

            return (
              <line
                key={i}
                x1={x1} y1={y1} x2={x2} y2={y2}
                stroke={isHighlighted ? '#ff6600' : selectedNode ? '#1e1e1e' : '#252525'}
                strokeWidth={isHighlighted ? 1.5 : 0.8}
                strokeOpacity={selectedNode && !isHighlighted ? 0.2 : 1}
                markerEnd={isHighlighted ? 'url(#arrow-active)' : 'url(#arrow)'}
                style={{ transition: 'stroke 0.15s, stroke-opacity 0.15s' }}
              />
            )
          })}

          {/* Nodes */}
          {nodes.map(node => {
            const pos = positions[node.id]
            if (!pos) return null
            const cfg = CAT_COLOR[node.category] ?? DEFAULT_CAT
            const isSelected = selectedNode === node.id
            const isConnected = connectedTo.has(node.id)
            const isDimmed = selectedNode !== null && !isSelected && !isConnected

            const lines = node.label.split('\n')

            return (
              <g
                key={node.id}
                transform={`translate(${pos.x}, ${pos.y})`}
                onClick={() => setSelectedNode(prev => prev === node.id ? null : node.id)}
                className="cursor-pointer"
                role="button"
                aria-pressed={isSelected}
                aria-label={`${node.id} — ${node.category}`}
                style={{ opacity: isDimmed ? 0.25 : 1, transition: 'opacity 0.15s' }}
              >
                {/* Glow ring for selected */}
                {isSelected && (
                  <circle
                    r={NODE_R + 6}
                    fill="none"
                    stroke={cfg.stroke}
                    strokeWidth={1.5}
                    strokeOpacity={0.4}
                  />
                )}
                {/* Main circle */}
                <circle
                  r={NODE_R}
                  fill={isSelected ? cfg.fill : isDimmed ? '#080808' : cfg.fill}
                  stroke={isConnected || isSelected ? cfg.stroke : '#252525'}
                  strokeWidth={isSelected ? 2 : isConnected ? 1.5 : 0.8}
                />
                {/* Category label inside */}
                <text
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fontSize={7}
                  fontFamily="'IBM Plex Mono', monospace"
                  fill={cfg.text}
                  y={-6}
                  fontWeight="600"
                >
                  {cfg.label}
                </text>
                {/* Agent name below circle */}
                {lines.map((line, li) => (
                  <text
                    key={li}
                    textAnchor="middle"
                    y={NODE_R + 10 + li * 11}
                    fontSize={7.5}
                    fontFamily="'IBM Plex Mono', monospace"
                    fill={isSelected ? cfg.text : isConnected ? '#cccccc' : '#666666'}
                    fontWeight={isSelected ? '600' : '400'}
                  >
                    {line}
                  </text>
                ))}
              </g>
            )
          })}
        </svg>
      </div>
    </div>
  )
}
