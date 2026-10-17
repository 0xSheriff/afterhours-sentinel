import React, { useState, useMemo, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

// ── Strict Numeric & Formatting Utilities ──
const fmtUSD = (n) => {
  const num = Number(n) || 0
  const sign = num > 0 ? '+' : num < 0 ? '-' : ''
  const abs = Math.abs(num)
  return `${sign}$${abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

const fmtUSDPlain = (n) => {
  const num = Number(n) || 0
  return `$${num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

const fmtTime = (ts) => {
  if (!ts) return '—'
  try {
    const d = new Date(ts)
    return d.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: 'UTC'
    }) + ' UTC'
  } catch {
    return ts
  }
}

const formatAge = (ts) => {
  if (!ts) return '—'
  try {
    const now = Date.now()
    const diffMs = now - new Date(ts).getTime()
    const diffMins = Math.floor(diffMs / 60000)
    if (diffMins < 60) return `${Math.max(1, diffMins)}m ago`
    const diffHours = Math.floor(diffMins / 60)
    if (diffHours < 24) return `${diffHours}h ago`
    const diffDays = Math.floor(diffHours / 24)
    return `${diffDays}d ago`
  } catch {
    return '—'
  }
}

// ── Smooth Numeric Count-Up Hook (Under 700ms) ──
function useCountUp(target, duration = 600) {
  const [val, setVal] = useState(0)
  const targetNum = Number(target) || 0

  useEffect(() => {
    if (typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setVal(targetNum)
      return
    }

    let startTimestamp = null
    const startVal = 0
    let rafId

    const step = (timestamp) => {
      if (!startTimestamp) startTimestamp = timestamp
      const progress = Math.min((timestamp - startTimestamp) / duration, 1)
      const ease = 1 - Math.pow(1 - progress, 3) // easeOutCubic
      setVal(startVal + (targetNum - startVal) * ease)
      if (progress < 1) {
        rafId = requestAnimationFrame(step)
      } else {
        setVal(targetNum)
      }
    }

    rafId = requestAnimationFrame(step)
    const timeoutId = setTimeout(() => {
      setVal(targetNum)
    }, duration + 50)

    return () => {
      cancelAnimationFrame(rafId)
      clearTimeout(timeoutId)
    }
  }, [targetNum, duration])

  return val
}

// ── Interactive Cumulative P&L Timeline Component ──
function CumulativePnLChart({ trades, routeName, dark }) {
  const [hoverIndex, setHoverIndex] = useState(null)
  const svgRef = useRef(null)

  // Chronological closed trades
  const series = useMemo(() => {
    const closed = trades
      .filter(t => t.status !== 'OPEN')
      .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))

    let runningPnl = 0
    return closed.map((t, idx) => {
      runningPnl = Math.round((runningPnl + (Number(t.pnl) || 0)) * 100) / 100
      return {
        id: t.id || idx,
        timestamp: t.timestamp,
        symbol: t.symbol,
        side: t.side,
        pnl: Number(t.pnl) || 0,
        cumulativePnl: runningPnl
      }
    })
  }, [trades])

  if (series.length === 0) {
    return (
      <div className="py-12 text-center text-sm" style={{ color: 'var(--text-muted)' }}>
        No closed trades recorded yet for this route.
      </div>
    )
  }

  // Chart coordinates calculation
  const width = 800
  const height = 260
  const padding = { top: 25, right: 35, bottom: 40, left: 65 }

  const pnlValues = series.map(d => d.cumulativePnl)
  const minPnl = Math.min(0, ...pnlValues)
  const maxPnl = Math.max(10, ...pnlValues)
  const pnlRange = maxPnl - minPnl || 1

  const getY = (val) => {
    const norm = (val - minPnl) / pnlRange
    return height - padding.bottom - norm * (height - padding.top - padding.bottom)
  }

  const getX = (idx) => {
    if (series.length <= 1) return padding.left
    const usableWidth = width - padding.left - padding.right
    return padding.left + (idx / (series.length - 1)) * usableWidth
  }

  const zeroY = getY(0)

  // Construct SVG Path
  const points = series.map((d, i) => `${getX(i)},${getY(d.cumulativePnl)}`).join(' ')
  const pathD = `M ${points.split(' ').join(' L ')}`

  // Y-axis grid ticks (4 ticks)
  const yTicks = [
    minPnl,
    minPnl + pnlRange * 0.33,
    minPnl + pnlRange * 0.66,
    maxPnl
  ].map(v => Math.round(v))

  // X-axis time ticks (up to 5 labels)
  const xTickIndices = [
    0,
    Math.floor((series.length - 1) * 0.25),
    Math.floor((series.length - 1) * 0.5),
    Math.floor((series.length - 1) * 0.75),
    series.length - 1
  ].filter((v, i, a) => a.indexOf(v) === i)

  const activePoint = hoverIndex !== null && series[hoverIndex] ? series[hoverIndex] : null

  return (
    <div className="relative w-full">
      <div className="overflow-x-auto scrollbar-none">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${width} ${height}`}
          className="w-full h-auto min-w-[620px] select-none block"
          onMouseLeave={() => setHoverIndex(null)}
          onMouseMove={(e) => {
            if (!svgRef.current || series.length === 0) return
            const rect = svgRef.current.getBoundingClientRect()
            const mouseX = ((e.clientX - rect.left) / rect.width) * width
            let closestIdx = 0
            let closestDist = Infinity
            series.forEach((_, i) => {
              const x = getX(i)
              const dist = Math.abs(x - mouseX)
              if (dist < closestDist) {
                closestDist = dist
                closestIdx = i
              }
            })
            setHoverIndex(closestIdx)
          }}
        >
          {/* Subtle Gridlines */}
          {yTicks.map((tick, i) => {
            const y = getY(tick)
            return (
              <g key={i}>
                <line
                  x1={padding.left}
                  y1={y}
                  x2={width - padding.right}
                  y2={y}
                  stroke={dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'}
                  strokeDasharray="4 4"
                />
                <text
                  x={padding.left - 8}
                  y={y + 4}
                  textAnchor="end"
                  className="font-mono-data text-[10px]"
                  fill={dark ? '#9DA6B5' : '#5E6573'}
                >
                  {tick >= 0 ? `+$${tick}` : `-$${Math.abs(tick)}`}
                </text>
              </g>
            )
          })}

          {/* Zero Baseline */}
          {minPnl < 0 && (
            <line
              x1={padding.left}
              y1={zeroY}
              x2={width - padding.right}
              y2={zeroY}
              stroke={dark ? 'rgba(255,255,255,0.22)' : 'rgba(0,0,0,0.22)'}
              strokeWidth="1.5"
            />
          )}

          {/* Main Flat Trend Line (High Contrast - Flat Color Only, No Gradient) */}
          <motion.path
            d={pathD}
            fill="none"
            stroke={dark ? '#D4FF3F' : '#059669'}
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 0.8, ease: 'easeOut' }}
          />

          {/* Data Points */}
          {series.map((d, i) => {
            const cx = getX(i)
            const cy = getY(d.cumulativePnl)
            const isHovered = hoverIndex === i
            return (
              <circle
                key={i}
                cx={cx}
                cy={cy}
                r={isHovered ? 5.5 : 2.5}
                fill={isHovered ? (dark ? '#D4FF3F' : '#059669') : (dark ? '#14171D' : '#FFFFFF')}
                stroke={dark ? '#D4FF3F' : '#059669'}
                strokeWidth={isHovered ? 2.5 : 1.5}
                className="transition-all duration-150 cursor-pointer"
              />
            )
          })}

          {/* Crosshair indicator on hover */}
          {activePoint && (
            <g pointerEvents="none">
              <line
                x1={getX(hoverIndex)}
                y1={padding.top}
                x2={getX(hoverIndex)}
                y2={height - padding.bottom}
                stroke={dark ? 'rgba(212,255,63,0.45)' : 'rgba(5,150,105,0.45)'}
                strokeDasharray="2 2"
                strokeWidth="1"
              />
            </g>
          )}

          {/* X-Axis Time Labels */}
          {xTickIndices.map((idx) => {
            const d = series[idx]
            if (!d) return null
            const x = getX(idx)
            let dateStr = ''
            try {
              const dt = new Date(d.timestamp)
              dateStr = dt.toLocaleString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })
            } catch {
              dateStr = `T${idx + 1}`
            }
            return (
              <text
                key={idx}
                x={x}
                y={height - 12}
                textAnchor={idx === 0 ? 'start' : idx === series.length - 1 ? 'end' : 'middle'}
                className="font-mono-data text-[10px]"
                fill={dark ? '#9DA6B5' : '#5E6573'}
              >
                {dateStr}
              </text>
            )
          })}
        </svg>
      </div>

      {/* Floating Interactive Crosshair Tooltip */}
      {activePoint && (
        <div
          className="absolute z-30 pointer-events-none rounded-xl p-3 shadow-xl text-xs border"
          style={{
            top: '8px',
            right: '16px',
            background: dark ? 'rgba(20, 23, 29, 0.95)' : 'rgba(255, 255, 255, 0.96)',
            borderColor: 'var(--border-hairline)',
            backdropFilter: 'blur(10px)'
          }}
        >
          <div className="flex items-center gap-2 mb-1.5 pb-1 border-b" style={{ borderColor: 'var(--border-hairline)' }}>
            <span className="font-display font-bold text-sm" style={{ color: 'var(--text-primary)' }}>
              {activePoint.symbol}
            </span>
            <span
              className={`px-1.5 py-0.5 rounded text-[10px] font-mono-data font-bold ${
                activePoint.side === 'LONG'
                  ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                  : 'bg-rose-500/15 text-rose-600 dark:text-rose-400'
              }`}
            >
              {activePoint.side}
            </span>
            <span className="font-mono-data text-[10px]" style={{ color: 'var(--text-muted)' }}>
              {fmtTime(activePoint.timestamp)}
            </span>
          </div>
          <div className="space-y-1 font-mono-data text-[11px]">
            <div className="flex justify-between gap-4">
              <span style={{ color: 'var(--text-secondary)' }}>Trade Realized:</span>
              <span className={activePoint.pnl >= 0 ? 'text-emerald-600 dark:text-emerald-400 font-bold' : 'text-rose-600 dark:text-rose-400 font-bold'}>
                {activePoint.pnl >= 0 ? `+${fmtUSDPlain(activePoint.pnl)}` : `-${fmtUSDPlain(Math.abs(activePoint.pnl))}`}
              </span>
            </div>
            <div className="flex justify-between gap-4 pt-0.5 border-t" style={{ borderColor: 'var(--border-hairline)' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Cumulative P&L:</span>
              <span className={activePoint.cumulativePnl >= 0 ? 'text-emerald-600 dark:text-emerald-400 font-bold' : 'text-rose-600 dark:text-rose-400 font-bold'}>
                {activePoint.cumulativePnl >= 0 ? `+${fmtUSDPlain(activePoint.cumulativePnl)}` : `-${fmtUSDPlain(Math.abs(activePoint.cumulativePnl))}`}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main PnL View Component ──
export default function PnLView({ dark, pnlData }) {
  const [activeChartRoute, setActiveChartRoute] = useState('A')
  const [feedRouteFilter, setFeedRouteFilter] = useState('all') // all | A | B
  const [feedPage, setFeedPage] = useState(1)
  const FEED_PAGE_SIZE = 20

  const [sortField, setSortField] = useState('pnl')
  const [sortAsc, setSortAsc] = useState(false)

  // Segregate Route A and Route B strictly
  const { routeA, routeB, openPositions } = useMemo(() => {
    if (!pnlData || !pnlData.length) {
      return { routeA: [], routeB: [], openPositions: [] }
    }
    const a = pnlData.filter(t => t.route === 'A')
    const b = pnlData.filter(t => t.route === 'B')
    const open = pnlData.filter(t => t.status === 'OPEN')
    return { routeA: a, routeB: b, openPositions: open }
  }, [pnlData])

  // Route A metrics calculation
  const metricsA = useMemo(() => {
    const closed = routeA.filter(t => t.status !== 'OPEN')
    const open = routeA.filter(t => t.status === 'OPEN')
    const wins = closed.filter(t => (t.pnl || 0) > 0)
    const losses = closed.filter(t => (t.pnl || 0) < 0)
    const breakeven = closed.filter(t => (t.pnl || 0) === 0)
    const totalPnl = closed.reduce((acc, t) => acc + (Number(t.pnl) || 0), 0)
    const winRate = closed.length > 0 ? ((wins.length / closed.length) * 100).toFixed(1) : '0.0'
    return {
      totalTrades: routeA.length,
      closedTrades: closed.length,
      winsCount: wins.length,
      lossesCount: losses.length,
      breakevenCount: breakeven.length,
      openCount: open.length,
      realizedPnl: Math.round(totalPnl * 100) / 100,
      winRate
    }
  }, [routeA])

  // Route B metrics calculation (Paper simulation)
  const metricsB = useMemo(() => {
    const closed = routeB.filter(t => t.status !== 'OPEN')
    const open = routeB.filter(t => t.status === 'OPEN')
    const wins = closed.filter(t => (t.pnl || 0) > 0)
    const losses = closed.filter(t => (t.pnl || 0) < 0)
    const breakeven = closed.filter(t => (t.pnl || 0) === 0)
    const totalPnl = closed.reduce((acc, t) => acc + (Number(t.pnl) || 0), 0)
    const winRate = closed.length > 0 ? ((wins.length / closed.length) * 100).toFixed(1) : '0.0'
    return {
      totalTrades: routeB.length,
      closedTrades: closed.length,
      winsCount: wins.length,
      lossesCount: losses.length,
      breakevenCount: breakeven.length,
      openCount: open.length,
      realizedPnl: Math.round(totalPnl * 100) / 100,
      winRate
    }
  }, [routeB])

  // Animated Count-Up for Realized P&L
  const displayPnlA = useCountUp(metricsA.realizedPnl, 650)
  const displayPnlB = useCountUp(metricsB.realizedPnl, 650)

  // Per-Asset Breakdown Aggregations
  const assetBreakdown = useMemo(() => {
    if (!pnlData || !pnlData.length) return []
    const map = new Map()

    pnlData.forEach(t => {
      const sym = t.symbol || 'UNKNOWN'
      if (!map.has(sym)) {
        map.set(sym, {
          symbol: sym,
          route: t.route,
          routeName: t.route_name,
          trades: 0,
          wins: 0,
          losses: 0,
          breakeven: 0,
          open: 0,
          pnl: 0
        })
      }
      const item = map.get(sym)
      item.trades += 1
      if (t.status === 'OPEN') {
        item.open += 1
      } else {
        const p = Number(t.pnl) || 0
        item.pnl += p
        if (p > 0) item.wins += 1
        else if (p < 0) item.losses += 1
        else item.breakeven += 1
      }
    })

    const list = Array.from(map.values()).map(item => ({
      ...item,
      pnl: Math.round(item.pnl * 100) / 100,
      winRate: (item.wins + item.losses) > 0 ? ((item.wins / (item.wins + item.losses)) * 100).toFixed(0) : '—'
    }))

    list.sort((a, b) => {
      let va = a[sortField]
      let vb = b[sortField]
      if (typeof va === 'string') {
        return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va)
      }
      return sortAsc ? (va - vb) : (vb - va)
    })

    return list
  }, [pnlData, sortField, sortAsc])

  // Filtered & Paginated Trades Feed
  const filteredClosedTrades = useMemo(() => {
    if (!pnlData) return []
    return pnlData
      .filter(t => {
        if (t.status === 'OPEN') return false
        if (feedRouteFilter === 'A') return t.route === 'A'
        if (feedRouteFilter === 'B') return t.route === 'B'
        return true
      })
      .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
  }, [pnlData, feedRouteFilter])

  const totalFeedPages = Math.max(1, Math.ceil(filteredClosedTrades.length / FEED_PAGE_SIZE))
  const paginatedTrades = useMemo(() => {
    const start = (feedPage - 1) * FEED_PAGE_SIZE
    return filteredClosedTrades.slice(start, start + FEED_PAGE_SIZE)
  }, [filteredClosedTrades, feedPage])

  const handleSort = (field) => {
    if (sortField === field) {
      setSortAsc(!sortAsc)
    } else {
      setSortField(field)
      setSortAsc(false)
    }
  }

  return (
    <div className="relative space-y-8 pb-12">
      {/* ── SVG Refraction Filter Definitions (Hidden SVG) ── */}
      <svg width="0" height="0" className="absolute pointer-events-none" aria-hidden="true">
        <defs>
          <filter id="refract-glass" x="-10%" y="-10%" width="120%" height="120%">
            <feTurbulence type="fractalNoise" baseFrequency="0.03" numOctaves="2" result="noise" />
            <feDisplacementMap in="SourceGraphic" in2="noise" scale="3" xChannelSelector="R" yChannelSelector="G" />
          </filter>
        </defs>
      </svg>

      {/* ── Ambient Glow Field (Fixed behind Header & Hero area only) ── */}
      <div className="ambient-field-container" aria-hidden="true">
        <div className="ambient-blob-chartreuse" />
        <div className="ambient-blob-blue" />
      </div>

      {/* ── Section Title & Route Legend ── */}
      <div className="relative z-10 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="inline-block w-2 h-2 rounded-full bg-[var(--brand-chartreuse)] shadow-[0_0_8px_var(--brand-chartreuse)]" />
            <span className="text-[11px] font-mono-data uppercase tracking-wider font-bold text-[var(--brand-chartreuse)]">
              Liquidity & Performance Analytics
            </span>
          </div>
          <h2 className="font-display font-black text-2xl sm:text-3xl tracking-tight text-[var(--text-primary)]">
            Autonomous P&L Architecture
          </h2>
          <p className="text-xs sm:text-sm" style={{ color: 'var(--text-secondary)' }}>
            Strict segregation of listed Bitget Demo execution contracts and unlisted paper simulation models.
          </p>
        </div>

        {/* Legend Badges */}
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}>
            <span className="w-2 h-2 rounded-full bg-[var(--brand-chartreuse)]" />
            <span className="font-display font-bold text-[var(--text-primary)]">Route A:</span>
            <span style={{ color: 'var(--text-secondary)' }}>Bitget Demo</span>
          </div>
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}>
            <span className="w-2 h-2 rounded-full bg-zinc-400" />
            <span className="font-display font-bold text-[var(--text-primary)]">Route B:</span>
            <span style={{ color: 'var(--text-secondary)' }}>Paper Simulation</span>
          </div>
        </div>
      </div>

      {/* ── 1. HERO CARDS: SIDE-BY-SIDE DUAL ROUTE (NO COMBINED TOTAL) ── */}
      <div className="relative z-10 grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Route A Card (Primary / Large Card - 7 cols on desktop) */}
        <div className="lg:col-span-7 liquid-glass-card p-6 sm:p-7 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <span className="px-2.5 py-1 rounded-md text-[11px] font-mono-data font-bold tracking-wide uppercase bg-[var(--brand-chartreuse)] text-black">
                  ROUTE A
                </span>
                <span className="font-display font-bold text-sm text-[var(--text-primary)]">
                  Bitget Demo Exchange Contracts
                </span>
              </div>
              <span className="text-[11px] font-mono-data px-2 py-0.5 rounded border border-[var(--border-hairline)]" style={{ color: 'var(--text-muted)' }}>
                Order IDs Verified
              </span>
            </div>

            <div className="mb-1 text-xs uppercase tracking-wider font-semibold" style={{ color: 'var(--text-secondary)' }}>
              Realized Net P&L
            </div>

            {/* Flat high-contrast number, tabular-nums */}
            <div className="flex items-baseline gap-2 mb-4">
              <span className="font-display font-black text-4xl sm:text-5xl tracking-tight font-mono-data text-[var(--text-primary)]">
                {displayPnlA >= 0 ? `+${fmtUSDPlain(displayPnlA)}` : `-${fmtUSDPlain(Math.abs(displayPnlA))}`}
              </span>
              <span className="text-xs font-mono-data font-semibold text-emerald-600 dark:text-emerald-400 flex items-center">
                ▲ {metricsA.winRate}% win rate
              </span>
            </div>

            <p className="text-xs leading-relaxed mb-6" style={{ color: 'var(--text-secondary)' }}>
              Tracked single-stock equity contracts listed on Bitget Demo (<code className="font-mono-data text-[11px] font-semibold">NVDA, TSLA, AAPL, AMZN, META, COIN, MSTR</code>).
            </p>
          </div>

          {/* KPI Mini Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-4 border-t border-[var(--border-hairline)]">
            <div className="p-2.5 rounded-xl border" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}>
              <div className="text-[10px] uppercase font-semibold tracking-wider" style={{ color: 'var(--text-muted)' }}>Trades</div>
              <div className="font-mono-data text-lg font-bold text-[var(--text-primary)]">{metricsA.totalTrades}</div>
            </div>
            <div className="p-2.5 rounded-xl border" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}>
              <div className="text-[10px] uppercase font-semibold tracking-wider" style={{ color: 'var(--text-muted)' }}>W / L Record</div>
              <div className="font-mono-data text-lg font-bold text-[var(--text-primary)]">
                <span className="text-emerald-600 dark:text-emerald-400">{metricsA.winsCount}W</span>
                <span style={{ color: 'var(--text-muted)' }}> / </span>
                <span className="text-rose-600 dark:text-rose-400">{metricsA.lossesCount}L</span>
              </div>
            </div>
            <div className="p-2.5 rounded-xl border" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}>
              <div className="text-[10px] uppercase font-semibold tracking-wider" style={{ color: 'var(--text-muted)' }}>Breakeven</div>
              <div className="font-mono-data text-lg font-bold" style={{ color: 'var(--text-secondary)' }}>{metricsA.breakevenCount}</div>
            </div>
            <div className="p-2.5 rounded-xl border" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}>
              <div className="text-[10px] uppercase font-semibold tracking-wider" style={{ color: 'var(--text-muted)' }}>Open Positions</div>
              <div className="font-mono-data text-lg font-bold text-amber-500">{metricsA.openCount}</div>
            </div>
          </div>
        </div>

        {/* Route B Card (Secondary / Quiet Card - 5 cols on desktop) */}
        <div className="lg:col-span-5 liquid-glass-card p-6 sm:p-7 flex flex-col justify-between" style={{ opacity: 0.95 }}>
          <div>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <span className="px-2.5 py-1 rounded-md text-[11px] font-mono-data font-bold tracking-wide uppercase bg-zinc-700/20 text-zinc-700 dark:text-zinc-300 border border-zinc-500/20">
                  ROUTE B
                </span>
                <span className="font-display font-bold text-sm text-[var(--text-primary)]">
                  Synthetic Model
                </span>
              </div>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono-data font-medium bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 border border-zinc-500/20">
                Paper simulation
              </span>
            </div>

            <div className="mb-1 text-xs uppercase tracking-wider font-semibold" style={{ color: 'var(--text-secondary)' }}>
              Realized Net P&L
            </div>

            <div className="flex items-baseline gap-2 mb-4">
              <span className="font-display font-black text-3xl sm:text-4xl tracking-tight font-mono-data text-[var(--text-primary)]">
                {displayPnlB >= 0 ? `+${fmtUSDPlain(displayPnlB)}` : `-${fmtUSDPlain(Math.abs(displayPnlB))}`}
              </span>
              <span className="text-xs font-mono-data font-semibold text-emerald-600 dark:text-emerald-400 flex items-center">
                ▲ {metricsB.winRate}% win rate
              </span>
            </div>

            <p className="text-xs leading-relaxed mb-6" style={{ color: 'var(--text-secondary)' }}>
              Evaluated unlisted equities (<code className="font-mono-data text-[11px]">PLTR, AMD, INTC, MSFT, BABA, NFLX</code>) plus historical harness baseline.
            </p>
          </div>

          {/* KPI Mini Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-4 border-t border-[var(--border-hairline)]">
            <div className="p-2.5 rounded-xl border" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}>
              <div className="text-[10px] uppercase font-semibold tracking-wider" style={{ color: 'var(--text-muted)' }}>Trades</div>
              <div className="font-mono-data text-base font-bold text-[var(--text-primary)]">{metricsB.totalTrades}</div>
            </div>
            <div className="p-2.5 rounded-xl border" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}>
              <div className="text-[10px] uppercase font-semibold tracking-wider" style={{ color: 'var(--text-muted)' }}>W / L Record</div>
              <div className="font-mono-data text-base font-bold text-[var(--text-primary)]">
                <span className="text-emerald-600 dark:text-emerald-400">{metricsB.winsCount}W</span>
                <span style={{ color: 'var(--text-muted)' }}> / </span>
                <span className="text-rose-600 dark:text-rose-400">{metricsB.lossesCount}L</span>
              </div>
            </div>
            <div className="p-2.5 rounded-xl border" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}>
              <div className="text-[10px] uppercase font-semibold tracking-wider" style={{ color: 'var(--text-muted)' }}>Breakeven</div>
              <div className="font-mono-data text-base font-bold" style={{ color: 'var(--text-secondary)' }}>{metricsB.breakevenCount}</div>
            </div>
            <div className="p-2.5 rounded-xl border" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}>
              <div className="text-[10px] uppercase font-semibold tracking-wider" style={{ color: 'var(--text-muted)' }}>Open Positions</div>
              <div className="font-mono-data text-base font-bold text-zinc-500">{metricsB.openCount}</div>
            </div>
          </div>
        </div>
      </div>

      {/* ── 2. CUMULATIVE P&L TIMELINE (ONE LINE PER ROUTE WITH TOGGLE) ── */}
      <div className="liquid-glass-card p-5 sm:p-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4">
          <div>
            <h3 className="font-display font-bold text-lg text-[var(--text-primary)]">
              Cumulative Realized P&L Timeline
            </h3>
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              Independent cumulative trajectory of closed executions over session span.
            </p>
          </div>

          {/* Route Switcher Toggle */}
          <div className="flex items-center p-1 rounded-xl border self-start sm:self-auto" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}>
            <button
              onClick={() => setActiveChartRoute('A')}
              className={`px-3 py-1.5 rounded-lg text-xs font-display font-bold transition-all duration-200 ${
                activeChartRoute === 'A'
                  ? 'bg-[var(--brand-chartreuse)] text-black shadow-sm'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
            >
              Route A (Bitget Demo)
            </button>
            <button
              onClick={() => setActiveChartRoute('B')}
              className={`px-3 py-1.5 rounded-lg text-xs font-display font-bold transition-all duration-200 ${
                activeChartRoute === 'B'
                  ? 'bg-zinc-700/20 text-[var(--text-primary)] dark:bg-zinc-600/30'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
            >
              Route B (Paper Simulation)
            </button>
          </div>
        </div>

        <CumulativePnLChart
          trades={activeChartRoute === 'A' ? routeA : routeB}
          routeName={activeChartRoute === 'A' ? 'Route A (Bitget Demo)' : 'Route B (Paper Simulation)'}
          dark={dark}
        />
      </div>

      {/* ── 3. OPEN POSITIONS STRIP ── */}
      <div className="rounded-2xl p-5 border" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
            <h3 className="font-display font-bold text-sm uppercase tracking-wider text-[var(--text-primary)]">
              Active Open Positions ({openPositions.length})
            </h3>
          </div>
          <span className="text-[11px] font-mono-data" style={{ color: 'var(--text-muted)' }}>
            Gated by 1.5% Hard Stop Loss
          </span>
        </div>

        {openPositions.length === 0 ? (
          <div className="text-center py-6 text-xs" style={{ color: 'var(--text-muted)' }}>
            Zero active open positions at this moment. Engine is monitoring the 7×24 event feed.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {openPositions.map((pos) => (
              <div
                key={pos.id || `${pos.symbol}-${pos.timestamp}`}
                className="p-4 rounded-xl border flex flex-col justify-between gap-3"
                style={{ background: 'var(--bg-canvas)', borderColor: 'var(--border-hairline)' }}
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-display font-black text-lg text-[var(--text-primary)]">
                        {pos.symbol}
                      </span>
                      <span
                        className={`px-2 py-0.5 rounded text-[11px] font-mono-data font-bold ${
                          pos.side === 'LONG'
                            ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                            : 'bg-rose-500/15 text-rose-600 dark:text-rose-400'
                        }`}
                      >
                        {pos.side}
                      </span>
                      <span className="text-[10px] font-mono-data px-1.5 py-0.5 rounded bg-[var(--bg-surface)] text-[var(--text-secondary)] border border-[var(--border-hairline)]">
                        Route {pos.route}
                      </span>
                    </div>
                    <p className="text-xs line-clamp-1" style={{ color: 'var(--text-secondary)' }}>
                      {pos.headline}
                    </p>
                  </div>
                  <span className="text-xs font-mono-data whitespace-nowrap" style={{ color: 'var(--text-muted)' }}>
                    {formatAge(pos.entry_time)}
                  </span>
                </div>

                <div className="grid grid-cols-3 gap-2 pt-2 border-t border-[var(--border-hairline)] font-mono-data text-xs">
                  <div>
                    <span className="text-[10px] uppercase block" style={{ color: 'var(--text-muted)' }}>Entry</span>
                    <span className="font-bold text-[var(--text-primary)]">{fmtUSDPlain(pos.entry_price)}</span>
                  </div>
                  <div>
                    <span className="text-[10px] uppercase block" style={{ color: 'var(--text-muted)' }}>Stop Loss</span>
                    <span className="font-bold text-rose-600 dark:text-rose-400">{fmtUSDPlain(pos.stop_price)}</span>
                  </div>
                  <div>
                    <span className="text-[10px] uppercase block" style={{ color: 'var(--text-muted)' }}>Allocation</span>
                    <span className="font-bold text-[var(--text-primary)]">{fmtUSDPlain(pos.position_size)}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── 4. PER-ASSET BREAKDOWN TABLE (CALM SOLID SURFACE) ── */}
      <div className="rounded-2xl border overflow-hidden" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}>
        <div className="p-5 border-b flex flex-col sm:flex-row sm:items-center justify-between gap-3" style={{ borderColor: 'var(--border-hairline)' }}>
          <div>
            <h3 className="font-display font-bold text-base text-[var(--text-primary)]">
              Per-Asset Performance Breakdown
            </h3>
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              Individual ledger metrics across all 13 traded equities. Click headers to sort.
            </p>
          </div>
          <span className="text-xs font-mono-data self-start sm:self-auto" style={{ color: 'var(--text-muted)' }}>
            {assetBreakdown.length} Traded Assets
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left border-collapse" role="table">
            <thead>
              <tr className="border-b text-[11px] font-mono-data uppercase tracking-wider select-none" style={{ background: 'var(--bg-surface-elevated)', borderColor: 'var(--border-hairline)' }}>
                <th scope="col" onClick={() => handleSort('symbol')} className="px-4 py-3 cursor-pointer hover:text-[var(--text-primary)]">
                  Asset {sortField === 'symbol' && (sortAsc ? '▲' : '▼')}
                </th>
                <th scope="col" onClick={() => handleSort('route')} className="px-4 py-3 cursor-pointer hover:text-[var(--text-primary)]">
                  Route {sortField === 'route' && (sortAsc ? '▲' : '▼')}
                </th>
                <th scope="col" onClick={() => handleSort('trades')} className="px-4 py-3 text-right cursor-pointer hover:text-[var(--text-primary)]">
                  Trades {sortField === 'trades' && (sortAsc ? '▲' : '▼')}
                </th>
                <th scope="col" className="px-4 py-3 text-center">
                  Record (W / L / BE)
                </th>
                <th scope="col" onClick={() => handleSort('open')} className="px-4 py-3 text-center cursor-pointer hover:text-[var(--text-primary)]">
                  Open {sortField === 'open' && (sortAsc ? '▲' : '▼')}
                </th>
                <th scope="col" onClick={() => handleSort('pnl')} className="px-4 py-3 text-right cursor-pointer hover:text-[var(--text-primary)]">
                  Realized P&L {sortField === 'pnl' && (sortAsc ? '▲' : '▼')}
                </th>
              </tr>
            </thead>
            <tbody>
              {assetBreakdown.map((row) => {
                const isPositive = row.pnl > 0
                const isNegative = row.pnl < 0
                const pnlSign = isPositive ? '+' : isNegative ? '-' : ''
                const pnlArrow = isPositive ? '▲' : isNegative ? '▼' : '—'
                return (
                  <tr
                    key={row.symbol}
                    className="border-b transition-colors hover:bg-[var(--bg-canvas)]"
                    style={{ borderColor: 'var(--border-hairline)' }}
                  >
                    <td className="px-4 py-3 font-display font-bold text-sm text-[var(--text-primary)]">
                      {row.symbol}
                    </td>
                    <td className="px-4 py-3">
                      {row.route === 'A' ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono-data font-bold bg-[var(--brand-chartreuse)]/20 text-black dark:text-[var(--brand-chartreuse)] border border-[var(--brand-chartreuse)]/40">
                          Bitget Demo
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono-data font-medium bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 border border-zinc-500/20">
                          Paper simulation
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right font-mono-data text-[var(--text-primary)]">
                      {row.trades}
                    </td>
                    <td className="px-4 py-3 text-center font-mono-data text-xs">
                      <span className="text-emerald-600 dark:text-emerald-400 font-bold">{row.wins}W</span>
                      <span style={{ color: 'var(--text-muted)' }}> - </span>
                      <span className="text-rose-600 dark:text-rose-400 font-bold">{row.losses}L</span>
                      <span style={{ color: 'var(--text-muted)' }}> - </span>
                      <span style={{ color: 'var(--text-secondary)' }}>{row.breakeven}BE</span>
                    </td>
                    <td className="px-4 py-3 text-center font-mono-data">
                      {row.open > 0 ? (
                        <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-amber-500/15 text-amber-600 dark:text-amber-400">
                          {row.open}
                        </span>
                      ) : (
                        <span style={{ color: 'var(--text-muted)' }}>0</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right font-mono-data font-bold text-sm">
                      <span
                        className={
                          isPositive
                            ? 'text-emerald-600 dark:text-emerald-400'
                            : isNegative
                            ? 'text-rose-600 dark:text-rose-400'
                            : 'text-[var(--text-muted)]'
                        }
                      >
                        {pnlSign}${Math.abs(row.pnl).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        <span className="ml-1 text-[11px] font-normal">{pnlArrow}</span>
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── 5. RECENT CLOSED TRADES LIST (PAGINATED 20 PER PAGE) ── */}
      <div className="rounded-2xl border overflow-hidden" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}>
        <div className="p-5 border-b flex flex-col sm:flex-row sm:items-center justify-between gap-4" style={{ borderColor: 'var(--border-hairline)' }}>
          <div>
            <h3 className="font-display font-bold text-base text-[var(--text-primary)]">
              Closed Execution Ledger
            </h3>
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              Complete audit record of realized positions ({filteredClosedTrades.length} trades).
            </p>
          </div>

          {/* Route Filter Selector */}
          <div className="flex items-center gap-2 self-start sm:self-auto">
            <span className="text-xs font-mono-data" style={{ color: 'var(--text-muted)' }}>Filter:</span>
            <div className="flex rounded-lg border p-0.5 text-xs font-mono-data" style={{ background: 'var(--bg-canvas)', borderColor: 'var(--border-hairline)' }}>
              {['all', 'A', 'B'].map((f) => (
                <button
                  key={f}
                  onClick={() => {
                    setFeedRouteFilter(f)
                    setFeedPage(1)
                  }}
                  className={`px-2.5 py-1 rounded transition-colors ${
                    feedRouteFilter === f
                      ? 'bg-[var(--brand-chartreuse)] text-black font-bold'
                      : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
                  }`}
                >
                  {f === 'all' ? 'All Routes' : f === 'A' ? 'Route A' : 'Route B'}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left border-collapse" role="table">
            <thead>
              <tr className="border-b text-[11px] font-mono-data uppercase tracking-wider" style={{ background: 'var(--bg-surface-elevated)', borderColor: 'var(--border-hairline)' }}>
                <th scope="col" className="px-4 py-3">Timestamp</th>
                <th scope="col" className="px-4 py-3">Symbol</th>
                <th scope="col" className="px-4 py-3">Route</th>
                <th scope="col" className="px-4 py-3">Side</th>
                <th scope="col" className="px-4 py-3 text-right">Size</th>
                <th scope="col" className="px-4 py-3 text-right">Entry</th>
                <th scope="col" className="px-4 py-3 text-right">Exit</th>
                <th scope="col" className="px-4 py-3">Exit Reason</th>
                <th scope="col" className="px-4 py-3 text-right">Realized P&L</th>
              </tr>
            </thead>
            <tbody>
              {paginatedTrades.map((t) => {
                const isPositive = (t.pnl || 0) > 0
                const isNegative = (t.pnl || 0) < 0
                const pnlSign = isPositive ? '+' : isNegative ? '-' : ''
                const pnlArrow = isPositive ? '▲' : isNegative ? '▼' : '—'
                return (
                  <tr
                    key={t.id || `${t.symbol}-${t.timestamp}`}
                    className="border-b transition-colors hover:bg-[var(--bg-canvas)]"
                    style={{ borderColor: 'var(--border-hairline)' }}
                  >
                    <td className="px-4 py-3 font-mono-data text-xs whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>
                      {fmtTime(t.timestamp)}
                    </td>
                    <td className="px-4 py-3 font-display font-bold text-[var(--text-primary)]">
                      {t.symbol}
                    </td>
                    <td className="px-4 py-3">
                      {t.route === 'A' ? (
                        <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-mono-data font-bold bg-[var(--brand-chartreuse)]/20 text-black dark:text-[var(--brand-chartreuse)] border border-[var(--brand-chartreuse)]/30">
                          Route A
                        </span>
                      ) : (
                        <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-mono-data font-medium bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 border border-zinc-500/20">
                          Route B
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-mono-data font-bold ${
                          t.side === 'LONG'
                            ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                            : 'bg-rose-500/15 text-rose-600 dark:text-rose-400'
                        }`}
                      >
                        {t.side}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right font-mono-data text-xs text-[var(--text-primary)]">
                      {fmtUSDPlain(t.position_size)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono-data text-xs text-[var(--text-primary)]">
                      {fmtUSDPlain(t.entry_price)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono-data text-xs text-[var(--text-primary)]">
                      {fmtUSDPlain(t.exit_price)}
                    </td>
                    <td className="px-4 py-3 text-xs max-w-xs truncate" style={{ color: 'var(--text-secondary)' }}>
                      {t.exit_reason}
                    </td>
                    <td className="px-4 py-3 text-right font-mono-data font-bold text-sm whitespace-nowrap">
                      <span
                        className={
                          isPositive
                            ? 'text-emerald-600 dark:text-emerald-400'
                            : isNegative
                            ? 'text-rose-600 dark:text-rose-400'
                            : 'text-[var(--text-muted)]'
                        }
                      >
                        {pnlSign}${Math.abs(t.pnl).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        <span className="ml-1 text-[11px] font-normal">{pnlArrow}</span>
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Pagination Controls */}
        <div className="p-4 border-t flex items-center justify-between gap-2" style={{ borderColor: 'var(--border-hairline)' }}>
          <div className="text-xs font-mono-data" style={{ color: 'var(--text-muted)' }}>
            Showing {paginatedTrades.length ? (feedPage - 1) * FEED_PAGE_SIZE + 1 : 0} to{' '}
            {Math.min(feedPage * FEED_PAGE_SIZE, filteredClosedTrades.length)} of {filteredClosedTrades.length} trades
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setFeedPage(p => Math.max(1, p - 1))}
              disabled={feedPage === 1}
              className="px-3 py-1.5 rounded-lg text-xs font-display font-bold border transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              style={{ background: 'var(--bg-canvas)', borderColor: 'var(--border-hairline)', color: 'var(--text-primary)' }}
            >
              Previous
            </button>
            <span className="text-xs font-mono-data px-2" style={{ color: 'var(--text-secondary)' }}>
              Page {feedPage} of {totalFeedPages}
            </span>
            <button
              onClick={() => setFeedPage(p => Math.min(totalFeedPages, p + 1))}
              disabled={feedPage === totalFeedPages}
              className="px-3 py-1.5 rounded-lg text-xs font-display font-bold border transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              style={{ background: 'var(--bg-canvas)', borderColor: 'var(--border-hairline)', color: 'var(--text-primary)' }}
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
