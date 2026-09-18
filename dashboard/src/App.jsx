import React, { useState, useMemo, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import riskConfig from './data/riskConfig.json'

// ── Dev mode flag (set to false for submission build) ──
const USE_DEMO_DATA = false

const DEMO_RECORDS = [
  { id: 99, timestamp: '2026-09-18T00:00:00Z', mode: 'live', execution_client: 'DemoClient', llm_source: 'groq_qwen3.8-27b [live_api]', event_headline: 'DEMO EVENT — NOT REAL', event_type: 'earnings', expected_move: 0.01, actual_move: 0.03, divergence: 0.02, z_score: 2.5, volume_ratio: 0.3, qwen_direction: 'BULLISH', qwen_reasoning: 'Demo reasoning — not real data.', decision: 'NO_TRADE', signals_aligned: '0/3', position_size: 0, stop_price: 0, entry_price: 100, exit_price: 0, exit_reason: 'N/A', pnl: 0, reason: 'DEMO: This is synthetic data for development only.' }
]

// ── Strict Numerical Formatters (JetBrains Mono tabular figures) ──
const fmt = (n, d = 2) => Number(n).toFixed(d)
const fmtPct = (n) => `${(Number(n) * 100).toFixed(2)}%`
const fmtUSD = (n) => `$${Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const fmtTime = (ts) => {
  try {
    const d = new Date(ts)
    return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' }) + ' UTC'
  } catch {
    return ts
  }
}

function isLiveMode(r) {
  return r.mode === 'live'
}
function isBacktestMode(r) {
  return r.mode === 'backtest' || r.mode === 'historical_replay'
}
// ── Three-Way LLM Evaluation Classification ──
// 1. LIVE: Groq API was called and returned verified model inference
// 2. FALLBACK: An equity asset matched, but dropped to local rule classifier (rare / fallback allowed)
// 3. SKIPPED: Pre-filter discarded event (no target ticker); zero LLM tokens spent (not an evaluation failure)
function getLLMSourceCategory(r) {
  if (!r) return 'skipped'
  if (r.decision === 'SKIPPED_NO_ASSET_MATCH' || r.llm_source === 'skipped') {
    return 'skipped'
  }
  if (r.llm_source && r.llm_source.includes('[live_api]')) {
    return 'live'
  }
  if (r.llm_source && (r.llm_source.includes('fallback') || r.llm_source.includes('pending'))) {
    return 'fallback'
  }
  return r.symbol ? 'fallback' : 'skipped'
}

function isLiveCall(r) {
  return getLLMSourceCategory(r) === 'live'
}
function isFallbackCall(r) {
  return getLLMSourceCategory(r) === 'fallback'
}
function isSkippedCall(r) {
  return getLLMSourceCategory(r) === 'skipped'
}

// ── Hand-Drawn Doodle Components (Landing & Brand Flourishes only) ──
function DoodleSquiggle({ className = '' }) {
  return (
    <svg className={className} viewBox="0 0 100 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M2 14C18 4 32 18 48 8C64 -2 78 16 98 6" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function DoodleArrow({ className = '' }) {
  return (
    <svg className={className} viewBox="0 0 72 48" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M4 28C22 10 44 8 62 20M62 20L48 14M62 20L54 32" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function DoodleCircle({ className = '' }) {
  return (
    <svg className={className} viewBox="0 0 120 50" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M8 26C12 10 52 4 98 12C118 16 116 38 88 44C44 52 4 40 14 20" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}

// ── Animated Z-Score Gauge ──
function ZScoreGauge({ value, threshold = 2.0 }) {
  const absVal = Math.abs(value || 0)
  const maxSigma = 4
  const pct = Math.min((absVal / maxSigma) * 100, 100)
  const threshPct = (threshold / maxSigma) * 100
  const aboveThresh = absVal >= threshold

  return (
    <div className="w-full">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[11px] font-mono-data" style={{ color: 'var(--text-muted)' }}>0.0σ</span>
        <span className="font-mono-data text-xs font-bold px-2 py-0.5 rounded" style={{
          color: aboveThresh ? '#10B981' : '#F43F5E',
          background: aboveThresh ? 'rgba(16, 185, 129, 0.12)' : 'rgba(244, 63, 94, 0.12)'
        }}>
          |z| = {fmt(absVal, 2)}σ
        </span>
        <span className="text-[11px] font-mono-data" style={{ color: 'var(--text-muted)' }}>4.0σ</span>
      </div>
      <div className="relative h-3 rounded-full overflow-hidden" style={{ background: 'var(--bg-canvas)', border: '1px solid var(--border-hairline)' }}>
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
          className="absolute h-full rounded-full"
          style={{
            background: aboveThresh
              ? 'linear-gradient(90deg, #F43F5E 0%, #F59E0B 40%, #D4FF3F 100%)'
              : '#F43F5E',
          }}
        />
        {/* Tick mark at threshold */}
        <div
          className="absolute top-0 h-full w-[2px] z-10"
          style={{
            left: `${threshPct}%`,
            background: 'var(--text-primary)',
            boxShadow: '0 0 6px rgba(212,255,63,0.5)'
          }}
        />
      </div>
      <div className="flex items-center justify-between mt-1">
        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>Reversion Zone (&lt; 2.0σ)</span>
        <div className="text-[10px] font-mono-data font-bold" style={{ color: 'var(--text-secondary)' }}>
          Risk Gate: {threshold.toFixed(1)}σ
        </div>
      </div>
    </div>
  )
}

// ── Badges: Live API (Chartreuse) vs Fallback (Amber) vs Pre-Filter Skipped (Indigo) ──
function SourceBadge({ record, isDark = false }) {
  const cat = getLLMSourceCategory(record)
  if (cat === 'live') {
    return (
      <span
        className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold uppercase tracking-wider transition-all"
        style={{
          background: 'var(--badge-live-bg)',
          color: 'var(--badge-live-text)',
          border: '1px solid var(--badge-live-border)',
        }}
        title="Live LLM API Ping: Groq Qwen 3.8-27B successfully executed"
      >
        <span
          className="inline-block w-1.5 h-1.5 rounded-full"
          style={{ background: 'var(--badge-live-text)' }}
        />
        Live API
      </span>
    )
  }
  if (cat === 'fallback') {
    return (
      <span
        className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold uppercase tracking-wider transition-all"
        style={{
          background: 'var(--badge-fallback-bg)',
          color: 'var(--badge-fallback-text)',
          border: '1px solid var(--badge-fallback-border)',
        }}
        title="Deterministic Fallback Rules: Target asset matched, but processed via fallback"
      >
        <span
          className="inline-block w-1.5 h-1.5 rounded-full"
          style={{ background: 'var(--badge-fallback-text)' }}
        />
        Fallback
      </span>
    )
  }
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold uppercase tracking-wider transition-all"
      style={{
        background: 'var(--badge-skipped-bg)',
        color: 'var(--badge-skipped-text)',
        border: '1px solid var(--badge-skipped-border)',
      }}
      title="Pre-Filter Skipped: Headline contained no target ticker (zero LLM tokens consumed)"
    >
      <span
        className="inline-block w-1.5 h-1.5 rounded-full"
        style={{ background: 'var(--badge-skipped-text)' }}
      />
      Pre-Filter Skipped
    </span>
  )
}

function ModeBadge({ mode, isDark = false }) {
  const isLive = mode === 'live' || (typeof mode === 'string' && mode.startsWith('live'))
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono-data font-bold uppercase tracking-wider border"
      style={{
        background: isLive
          ? (isDark ? 'rgba(212, 255, 63, 0.12)' : 'rgba(212, 255, 63, 0.28)')
          : 'rgba(99, 102, 241, 0.12)',
        color: isLive
          ? (isDark ? '#D4FF3F' : '#223602')
          : (isDark ? '#A5B4FC' : '#4338CA'),
        borderColor: isLive
          ? (isDark ? 'rgba(212, 255, 63, 0.35)' : 'rgba(180, 220, 40, 0.75)')
          : (isDark ? 'rgba(99, 102, 241, 0.3)' : 'rgba(99, 102, 241, 0.4)'),
      }}
    >
      {isLive ? 'Live Paper' : 'Backtest'}
    </span>
  )
}

function StrategyBadge({ mode, isDark = false }) {
  const isMomentum = mode === 'MOMENTUM'
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono-data font-bold uppercase tracking-wider border"
      style={{
        background: isMomentum
          ? (isDark ? 'rgba(56, 189, 248, 0.12)' : 'rgba(56, 189, 248, 0.22)')
          : (isDark ? 'rgba(245, 158, 11, 0.12)' : 'rgba(245, 158, 11, 0.22)'),
        color: isMomentum
          ? (isDark ? '#38BDF8' : '#0369A1')
          : (isDark ? '#F59E0B' : '#B45309'),
        borderColor: isMomentum
          ? (isDark ? 'rgba(56, 189, 248, 0.35)' : 'rgba(56, 189, 248, 0.5)')
          : (isDark ? 'rgba(245, 158, 11, 0.35)' : 'rgba(245, 158, 11, 0.5)'),
      }}
      title={isMomentum ? 'Momentum Strategy (PEAD trend continuation)' : 'Mean-Reversion Strategy (Transitory dislocation fade)'}
    >
      {isMomentum ? 'Momentum' : 'Fade'}
    </span>
  )
}

function DecisionBadge({ decision }) {
  const styles = {
    'LONG': { bg: 'rgba(16, 185, 129, 0.15)', text: '#10B981', border: 'rgba(16, 185, 129, 0.3)' },
    'SHORT': { bg: 'rgba(244, 63, 94, 0.15)', text: '#F43F5E', border: 'rgba(244, 63, 94, 0.3)' },
    'NO_TRADE': { bg: 'rgba(160, 160, 160, 0.12)', text: 'var(--text-secondary)', border: 'var(--border-hairline)' },
    'SKIPPED_NO_ASSET_MATCH': { bg: 'rgba(120, 120, 120, 0.08)', text: 'var(--text-muted)', border: 'transparent' },
  }
  const s = styles[decision] || { bg: 'rgba(120, 120, 120, 0.1)', text: 'var(--text-muted)', border: 'transparent' }
  return (
    <span
      className="inline-flex px-2 py-0.5 rounded text-[11px] font-mono-data font-bold border"
      style={{ background: s.bg, color: s.text, borderColor: s.border }}
    >
      {decision}
    </span>
  )
}

const NAV_ITEMS = ['Home', 'Dashboard', 'Decision Feed', 'Event Detail', 'Risk Config']

export default function App() {
  const queryParams = typeof window !== 'undefined' ? new URLSearchParams(window.location.search) : null
  const initialDark = queryParams ? queryParams.get('theme') === 'dark' : false
  const initialScreen = queryParams && queryParams.get('screen') ? queryParams.get('screen') : 'Home'
  const initialSource = queryParams && queryParams.get('source') ? queryParams.get('source') : 'all'

  // Requirement 1: Default theme is light mode
  const [dark, setDark] = useState(initialDark)
  const [activeScreen, setActiveScreen] = useState(initialScreen)
  const [selectedId, setSelectedId] = useState(null)
  const [filterMode, setFilterMode] = useState('all')     // all | live | backtest
  const [filterSource, setFilterSource] = useState(initialSource) // all | live | fallback | skipped
  const [filterSymbol, setFilterSymbol] = useState('')
  const [scrolled, setScrolled] = useState(false)
  const [records, setRecords] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [isDemo, setIsDemo] = useState(false)
  const [lastRefreshed, setLastRefreshed] = useState(null)

  const loadRecords = useCallback(async (silent = false) => {
    try {
      if (!silent) setIsLoading(true)
      const baseUrl = import.meta.env.BASE_URL || './'
      const normalizedBase = baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`
      const url = `${normalizedBase}data/records.json?_t=${Date.now()}`
      const res = await fetch(url)
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: failed to fetch records.json`)
      }
      const data = await res.json()
      if (Array.isArray(data)) {
        setRecords(data)
        setIsDemo(false)
        setLastRefreshed(new Date())
      } else {
        throw new Error('Data is not an array')
      }
    } catch (err) {
      console.warn('Dashboard records fetch warning:', err)
      setRecords((prev) => {
        if (prev && prev.length > 0) return prev
        if (USE_DEMO_DATA) {
          setIsDemo(true)
          return DEMO_RECORDS
        }
        return []
      })
    } finally {
      if (!silent) setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadRecords(false)
    const interval = setInterval(() => {
      loadRecords(true)
    }, 60000)
    return () => clearInterval(interval)
  }, [loadRecords])

  useEffect(() => {
    const handleScroll = () => {
      setScrolled(window.scrollY > 40)
    }
    window.addEventListener('scroll', handleScroll)
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  // 1. LIVE PAPER TRADING STATS (Strict separation)
  const liveStats = useMemo(() => {
    const liveRecs = records.filter(isLiveMode)
    if (!liveRecs.length) return null

    const timestamps = liveRecs.map(r => new Date(r.timestamp).getTime()).filter(t => !isNaN(t))
    const minT = Math.min(...timestamps)
    const maxT = Math.max(...timestamps)
    const durationHrs = ((maxT - minT) / 3600000).toFixed(1)

    const trades = liveRecs.filter(r => r.decision === 'LONG' || r.decision === 'SHORT')
    const wins = trades.filter(r => (r.pnl || 0) > 0)
    const totalPnl = trades.reduce((s, r) => s + (r.pnl || 0), 0)

    // Three-Way LLM Breakdown:
    // - liveCalls: Groq Qwen 3.8-27B live HTTP inference succeeded
    // - fallbackCalls: Target asset matched, but dropped to local rule classifier (rare / fallback allowed)
    // - skippedCalls: Pre-filtered out before LLM because headline did not mention target assets (zero tokens spent)
    const liveCalls = liveRecs.filter(isLiveCall).length
    const fallbackCalls = liveRecs.filter(isFallbackCall).length
    const skippedCalls = liveRecs.filter(isSkippedCall).length

    // LLM Reliability Denominator:
    // Only count events that actually reached the LLM evaluation stage (asset matched).
    // Pre-filtered macro headlines (skippedCalls) must NOT dilute API reliability.
    const evaluatedCalls = liveCalls + fallbackCalls
    const liveCallRate = evaluatedCalls > 0 ? ((liveCalls / evaluatedCalls) * 100).toFixed(0) : '100'

    const noTrades = liveRecs.filter(r => r.decision === 'NO_TRADE').length
    const skipped = skippedCalls

    return {
      total: liveRecs.length,
      tradesCount: trades.length,
      winsCount: wins.length,
      winRate: trades.length > 0 ? ((wins.length / trades.length) * 100).toFixed(0) : null,
      totalPnl,
      durationHrs,
      startTime: minT,
      endTime: maxT,
      liveCalls,
      fallbackCalls,
      skippedCalls,
      evaluatedCalls,
      liveCallRate,
      noTrades,
      skipped
    }
  }, [records])

  // 2. BACKTEST CALIBRATION STATS (Secondary validation sample)
  const backtestStats = useMemo(() => {
    const btRecs = records.filter(isBacktestMode)
    if (!btRecs.length) return null

    const timestamps = btRecs.map(r => new Date(r.timestamp).getTime()).filter(t => !isNaN(t))
    const minT = Math.min(...timestamps)
    const maxT = Math.max(...timestamps)

    const trades = btRecs.filter(r => r.decision === 'LONG' || r.decision === 'SHORT')
    const wins = trades.filter(r => (r.pnl || 0) > 0)
    const totalPnl = btRecs.reduce((s, r) => s + (r.pnl || 0), 0)
    const noTrades = btRecs.filter(r => r.decision === 'NO_TRADE').length

    return {
      total: btRecs.length,
      tradesCount: trades.length,
      winsCount: wins.length,
      winRate: trades.length > 0 ? ((wins.length / trades.length) * 100).toFixed(0) : '0',
      totalPnl,
      minT,
      maxT,
      noTrades
    }
  }, [records])

  // Filtered records for Decision Feed
  const filteredRecords = useMemo(() => {
    let r = [...records]
    if (filterMode === 'live') r = r.filter(isLiveMode)
    if (filterMode === 'backtest') r = r.filter(isBacktestMode)
    if (filterSource === 'live') r = r.filter(isLiveCall)
    if (filterSource === 'fallback') r = r.filter(isFallbackCall)
    if (filterSource === 'skipped') r = r.filter(isSkippedCall)
    if (filterSymbol) r = r.filter(rec => rec.event_headline?.toLowerCase().includes(filterSymbol.toLowerCase()))
    return r.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
  }, [records, filterMode, filterSource, filterSymbol])

  // Featured decision: latest real record from records.json
  const featuredRecord = useMemo(() => {
    const liveRecs = records.filter(isLiveMode)
    if (liveRecs.length > 0) {
      return [...liveRecs].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0]
    }
    return records[0] || null
  }, [records])

  const selectedRecord = selectedId != null ? records.find(r => r.id === selectedId) : null

  function selectAndViewDetail(record) {
    setSelectedId(record.id)
    setActiveScreen('Event Detail')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  function navigateTo(screen) {
    setActiveScreen(screen)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <div className={dark ? 'dark' : ''}>
      <div
        className="min-h-screen transition-colors duration-200 antialiased flex flex-col justify-between"
        style={{ background: 'var(--bg-canvas)', color: 'var(--text-primary)' }}
      >
        {/* Demo Banner */}
        {isDemo && (
          <div className="bg-amber-400 text-black text-center py-2 text-xs sm:text-sm font-display font-bold tracking-wide sticky top-0 z-50 shadow-md">
            ⚠ DEMO DATA — NOT FOR SUBMISSION ⚠
          </div>
        )}

        {/* ═══════════════════════════════════════════════════════════
            PERSISTENT BRAND NAVIGATION (Sticky with backdrop blur)
           ═══════════════════════════════════════════════════════════ */}
        <header
          className={`sticky ${isDemo ? 'top-8' : 'top-0'} z-40 transition-all duration-300 ${
            scrolled ? 'backdrop-blur-xl border-b py-2.5 shadow-sm' : 'bg-transparent py-4'
          }`}
          style={{
            borderColor: scrolled ? 'var(--border-hairline)' : 'transparent',
            backgroundColor: scrolled
              ? (dark ? 'rgba(13, 15, 18, 0.88)' : 'rgba(248, 249, 250, 0.88)')
              : 'transparent',
          }}
        >
          <div className="max-w-7xl mx-auto px-4 sm:px-6 flex items-center justify-between gap-4">
            {/* Logo / Wordmark */}
            <div
              onClick={() => navigateTo('Home')}
              className="flex items-center gap-3 cursor-pointer group select-none"
            >
              <div
                className="w-8 h-8 rounded-xl flex items-center justify-center font-display font-black text-sm transition-transform duration-200 group-hover:scale-105 shadow-sm"
                style={{ background: 'var(--brand-chartreuse)', color: '#0D0F12' }}
              >
                AH
              </div>
              <div className="flex flex-col">
                <span className="font-display font-black text-lg sm:text-xl tracking-tight leading-none group-hover:opacity-90 transition-opacity">
                  AfterHours Sentinel
                </span>
                <span className="text-[10px] font-mono-data tracking-wider uppercase" style={{ color: 'var(--text-muted)' }}>
                  Autonomous rToken Agent
                </span>
              </div>
            </div>

            {/* Nav Links */}
            <nav className="hidden md:flex items-center gap-1.5 p-1 rounded-full border" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}>
              {NAV_ITEMS.map((item) => {
                const active = activeScreen === item
                return (
                  <button
                    key={item}
                    onClick={() => navigateTo(item)}
                    className="relative px-3.5 py-1.5 text-xs font-display font-bold rounded-full transition-all duration-200"
                    style={{
                      color: active ? '#0D0F12' : 'var(--text-secondary)',
                    }}
                  >
                    {active && (
                      <motion.div
                        layoutId="navPill"
                        className="absolute inset-0 rounded-full shadow-sm"
                        style={{ background: 'var(--brand-chartreuse)' }}
                        transition={{ type: 'spring', stiffness: 450, damping: 35 }}
                      />
                    )}
                    <span className="relative z-10">{item}</span>
                  </button>
                )
              })}
            </nav>

            {/* Right Controls: Light/Dark Toggle + Launch App CTA */}
            <div className="flex items-center gap-2 sm:gap-3">
              <div
                className="hidden lg:flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl border text-[11px] font-mono-data select-none"
                style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)', color: 'var(--text-secondary)' }}
                title="Telemetric background polling active (refreshes every 60s without reload)"
              >
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                <span>Live Feed (60s)</span>
              </div>

              <button
                onClick={() => setDark(!dark)}
                className="p-2 rounded-xl border text-xs font-display font-bold transition-transform hover:scale-105"
                style={{
                  background: 'var(--bg-surface)',
                  borderColor: 'var(--border-hairline)',
                  color: 'var(--text-primary)',
                }}
                aria-label="Toggle Light/Dark Theme"
              >
                {dark ? '☀️' : '🌙'}
              </button>

              {activeScreen === 'Home' ? (
                <button
                  onClick={() => navigateTo('Dashboard')}
                  className="btn-chartreuse px-4 py-2 rounded-xl text-xs sm:text-sm font-display font-bold flex items-center gap-1.5"
                >
                  <span>Open Sentinel</span>
                  <span className="text-xs">→</span>
                </button>
              ) : (
                <button
                  onClick={() => navigateTo('Home')}
                  className="px-3.5 py-2 rounded-xl border text-xs font-display font-bold transition-all hover:opacity-80"
                  style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)', color: 'var(--text-secondary)' }}
                >
                  Landing
                </button>
              )}
            </div>
          </div>

          {/* Mobile Navigation bar */}
          <div className="flex md:hidden px-4 pt-2.5 overflow-x-auto gap-2 scrollbar-none">
            {NAV_ITEMS.map((item) => (
              <button
                key={item}
                onClick={() => navigateTo(item)}
                className="px-3 py-1.5 text-xs font-display font-bold rounded-lg whitespace-nowrap transition-colors"
                style={{
                  background: activeScreen === item ? 'var(--brand-chartreuse)' : 'var(--bg-surface)',
                  color: activeScreen === item ? '#0D0F12' : 'var(--text-secondary)',
                  border: '1px solid var(--border-hairline)'
                }}
              >
                {item}
              </button>
            ))}
          </div>
        </header>

        {/* ═══════════════════════════════════════════════════════════
            MAIN CONTENT AREA
           ═══════════════════════════════════════════════════════════ */}
        <main className="flex-1">
          {isLoading ? (
            <div className="flex flex-col items-center justify-center min-h-[50vh] space-y-4">
              <div className="w-10 h-10 border-2 rounded-full animate-spin" style={{ borderColor: 'var(--border-hairline)', borderTopColor: 'var(--brand-chartreuse)' }} />
              <div className="font-mono-data text-xs tracking-wider uppercase text-center" style={{ color: 'var(--text-muted)' }}>
                Syncing Autonomous Audit Trail...
              </div>
            </div>
          ) : (
          <AnimatePresence mode="wait">
            {/* ─────────────────────────────────────────────────────────
                1. LANDING PAGE SCREEN (ProFinance Chartreuse/Dark Framer Style)
               ───────────────────────────────────────────────────────── */}
            {activeScreen === 'Home' && (
              <motion.div
                key="landing"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -12 }}
                transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
                className="space-y-16 sm:space-y-24 pb-20"
              >
                {/* 1.1 Hero Section: Bold Solid Chartreuse Fill */}
                <section className="max-w-7xl mx-auto px-4 sm:px-6 pt-4 sm:pt-8">
                  <div
                    className="relative overflow-hidden rounded-3xl p-8 sm:p-14 lg:p-20 shadow-2xl"
                    style={{
                      background: 'var(--brand-chartreuse)',
                      color: '#0D0F12',
                    }}
                  >
                    {/* Hand-drawn decorative flourishes in hero */}
                    <DoodleCircle className="absolute -top-8 -right-8 w-40 h-40 text-black/15 pointer-events-none rotate-12" />
                    <DoodleArrow className="absolute bottom-8 right-12 hidden lg:block w-20 h-14 text-black/30 pointer-events-none" />

                    <div className="relative z-10 grid grid-cols-1 lg:grid-cols-12 gap-10 items-center">
                      <div className="lg:col-span-7 space-y-6">
                        <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full text-xs font-display font-bold uppercase tracking-wider bg-black/10 border border-black/15">
                          <span className="w-2 h-2 rounded-full bg-black animate-ping" />
                          Continuous 7×24 rToken Mean Reversion
                        </div>

                        <h1 className="font-display font-black text-4xl sm:text-6xl lg:text-7xl tracking-tighter leading-[0.95] text-balance">
                          Beat the bell. Trade the after-hours gap.
                        </h1>

                        <p className="text-base sm:text-xl font-medium text-black/80 max-w-xl leading-relaxed">
                          AfterHours Sentinel is an autonomous event-driven agent. It ingests breaking macro and earnings news, models real-time beta divergence against QQQ, and enforces strict risk rules before submitting live paper orders to Bitget.
                        </p>

                        <div className="flex flex-wrap items-center gap-3 pt-2">
                          <button
                            onClick={() => navigateTo('Dashboard')}
                            className="px-6 py-3.5 rounded-2xl bg-[#0D0F12] text-[#F4F6F8] font-display font-bold text-sm sm:text-base hover:bg-black/90 hover:scale-105 transition-all shadow-xl flex items-center gap-2"
                          >
                            <span>Launch Live Audit Dashboard</span>
                            <span>→</span>
                          </button>
                          <button
                            onClick={() => navigateTo('Decision Feed')}
                            className="px-6 py-3.5 rounded-2xl bg-black/10 border border-black/20 text-[#0D0F12] font-display font-bold text-sm sm:text-base hover:bg-black/15 transition-all"
                          >
                            Explore Real Feeds
                          </button>
                        </div>

                        {/* Honest Trust Bar - Computed real count from liveStats (excluding pre-filtered macro noise) */}
                        <div className="flex flex-wrap items-center gap-6 pt-4 text-xs font-display font-bold text-black/70 border-t border-black/10">
                          <div>✓ {liveStats ? `${liveStats.liveCalls} Verified Live AI Calls (${liveStats.liveCallRate}% of Evaluated Events)` : 'Groq Qwen3.8-27B Connected'}</div>
                          <div>✓ 2.0σ Strict Overreaction Gate</div>
                          <div>✓ Bitget Agent Hub Demo</div>
                        </div>
                      </div>

                      {/* Right Hero Stack: Layered floating decision preview */}
                      <div className="lg:col-span-5 relative layered-card-stack">
                        {/* Under card for realistic stacked depth */}
                        <div
                          className="layered-card-under"
                          style={{
                            background: '#0D0F12',
                            borderColor: 'rgba(0,0,0,0.3)',
                            transform: 'rotate(-3deg) translateY(10px)',
                          }}
                        />

                        {/* Main floating card */}
                        <div
                          className="layered-card-main rounded-2xl p-6 border shadow-2xl"
                          style={{
                            background: '#14171D',
                            borderColor: 'rgba(255,255,255,0.1)',
                            color: '#F4F6F8',
                          }}
                        >
                          <div className="flex items-center justify-between pb-3 border-b border-white/10">
                            <div className="flex items-center gap-2">
                              <span className="w-2.5 h-2.5 rounded-full" style={{ background: '#D4FF3F' }} />
                              <span className="text-[11px] font-mono-data font-bold uppercase tracking-wider" style={{ color: '#D4FF3F' }}>
                                LIVE TELEMETRY SAMPLE
                              </span>
                            </div>
                            <span className="text-[10px] font-mono-data px-2 py-0.5 rounded bg-white/10 text-white/70">
                              {featuredRecord && featuredRecord.event_headline.includes('Tesla') ? 'TSLA / QQQ' : 'NVDA / QQQ'}
                            </span>
                          </div>

                          <div className="mt-4 space-y-3">
                            <div className="text-xs text-white/50 font-mono-data">Event Catalyst:</div>
                            <div className="text-sm font-display font-bold line-clamp-2 leading-snug">
                              {featuredRecord ? featuredRecord.event_headline : 'NVIDIA Partners with Hyperscalers on Next-Gen Tensor Core Architecture'}
                            </div>

                            <div className="p-3 rounded-xl bg-black/40 border border-white/5 space-y-2">
                              <div className="flex justify-between items-center text-xs font-mono-data">
                                <span className="text-white/60">Residual Z-Score:</span>
                                <span className="font-bold" style={{ color: '#D4FF3F' }}>
                                  {featuredRecord ? fmt(featuredRecord.z_score, 2) : '0.00'}σ
                                </span>
                              </div>
                              {/* Requirement 4: Volume Confirmation reading dynamically from featuredRecord */}
                              {(() => {
                                const vRatio = featuredRecord ? Number(featuredRecord.volume_ratio || 0) : 0
                                const isWeak = vRatio < riskConfig.volumeWeakThreshold
                                return (
                                  <div className="flex justify-between items-center text-xs font-mono-data">
                                    <span className="text-white/60">Volume Confirmation:</span>
                                    <span className={`font-bold ${isWeak ? 'text-emerald-400' : 'text-rose-400'}`}>
                                      {fmt(vRatio, 4)}x ({isWeak ? 'Weak AH Vol' : 'Normal Vol'})
                                    </span>
                                  </div>
                                )
                              })()}
                              <div className="flex justify-between items-center text-xs font-mono-data">
                                <span className="text-white/60">Gatekeeper Decision:</span>
                                <span className="font-bold px-2 py-0.5 rounded bg-white/10 text-white/90">
                                  {featuredRecord ? featuredRecord.decision : 'NO_TRADE'}
                                </span>
                              </div>
                            </div>

                            <button
                              onClick={() => navigateTo('Dashboard')}
                              className="w-full py-2.5 rounded-xl btn-chartreuse text-xs font-display font-bold text-center"
                            >
                              Inspect Full 5-Stage Audit Trail →
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </section>

                {/* 1.2 Core Pillars Section: Consumer-Friendly Plain Language */}
                <section className="max-w-7xl mx-auto px-4 sm:px-6">
                  <div className="text-center max-w-2xl mx-auto mb-12 space-y-3">
                    <div className="inline-flex items-center gap-1 text-xs font-mono-data font-bold uppercase tracking-wider text-[var(--text-muted)]">
                      <span>Institutional Grade</span>
                      <DoodleSquiggle className="w-12 h-3 inline" style={{ color: dark ? '#D4FF3F' : '#223602' }} />
                    </div>
                    <h2 className="font-display font-black text-3xl sm:text-5xl tracking-tight">
                      Engineered for high noise, low liquidity hours.
                    </h2>
                    <p className="text-sm sm:text-base" style={{ color: 'var(--text-secondary)' }}>
                      Most traders lose money after-hours on illiquid fakeouts. Sentinel mathematically separates genuine fundamental shifts from temporary retail overreactions.
                    </p>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                    {[
                      {
                        num: '01',
                        title: 'Expected Move Modeling',
                        desc: 'Compares how a stock moves against its normal relationship with the broader market (QQQ). If a stock drops 4% when the market only predicted a 1% dip, that extra 3% is an unpriced gap.',
                        tag: 'Fair Pricing'
                      },
                      {
                        num: '02',
                        title: 'Unbiased AI News Analysis',
                        desc: 'Our AI reads the breaking headlines and earnings reports on its own without knowing current prices. This keeps its analysis completely honest and prevents it from simply agreeing with market hype.',
                        tag: 'Zero Bias'
                      },
                      {
                        num: '03',
                        title: '3-Step Safety Protection',
                        desc: 'Sentinel never risks money on hunches. It only trades when three conditions agree: an unusually large price move, clear news opposing that move, and thin trading volume indicating an overreaction.',
                        tag: 'Capital Defense'
                      }
                    ].map((feature) => (
                      <div
                        key={feature.num}
                        className="layered-card-stack group"
                      >
                        <div className="layered-card-under group-hover:rotate-[-3deg]" />
                        <div
                          className="layered-card-main rounded-2xl p-7 border relative"
                          style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}
                        >
                          <div className="flex items-center justify-between mb-5">
                            <span className="font-display font-black text-2xl" style={{ color: dark ? '#D4FF3F' : '#223602' }}>
                              {feature.num}
                            </span>
                            <span className="text-[10px] font-mono-data px-2.5 py-1 rounded-full border" style={{ background: 'var(--bg-surface-elevated)', borderColor: 'var(--border-hairline)', color: 'var(--text-muted)' }}>
                              {feature.tag}
                            </span>
                          </div>
                          <h3 className="font-display font-extrabold text-xl mb-2">
                            {feature.title}
                          </h3>
                          <p className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                            {feature.desc}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                </section>

                {/* 1.3 Dark Feature Section: Genuine Real Telemetry Block (Requirement 3 & 6) */}
                <section className="max-w-7xl mx-auto px-4 sm:px-6">
                  <div
                    className="rounded-3xl p-8 sm:p-14 border shadow-2xl relative overflow-hidden"
                    style={{
                      background: '#0D0F12',
                      borderColor: 'rgba(255,255,255,0.08)',
                      color: '#F4F6F8'
                    }}
                  >
                    {/* Glowing ambient background circle */}
                    <div
                      className="absolute -bottom-20 -right-20 w-96 h-96 rounded-full blur-3xl opacity-20 pointer-events-none"
                      style={{ background: 'var(--brand-chartreuse)' }}
                    />

                    <div className="grid grid-cols-1 lg:grid-cols-12 gap-10 items-center relative z-10">
                      <div className="lg:col-span-6 space-y-5">
                        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-mono-data font-bold uppercase tracking-wider bg-white/5 border border-white/10" style={{ color: '#D4FF3F' }}>
                          Execution Integrity
                        </div>
                        <h2 className="font-display font-black text-3xl sm:text-5xl tracking-tight leading-tight">
                          Real logs only. Zero simulated blurring.
                        </h2>
                        <p className="text-sm sm:text-base text-white/70 leading-relaxed">
                          Judges can verify our competition audit trail with 100% transparency. Pre-competition backtests are strictly quarantined from live paper trading records. Every LLM decision records full tokens, prompt latency, and execution timestamps.
                        </p>

                        {/* Real Stats Grid (Requirement 6: no fake 100%) */}
                        <div className="grid grid-cols-2 gap-4 pt-2">
                          <div className="p-4 rounded-xl bg-white/5 border border-white/5">
                            <div className="font-mono-data text-2xl font-bold" style={{ color: '#D4FF3F' }}>
                              {liveStats ? liveStats.total : records.length}
                            </div>
                            <div className="text-xs text-white/60 font-display font-medium mt-1">
                              Real Ingested Events
                            </div>
                          </div>
                          <div className="p-4 rounded-xl bg-white/5 border border-white/5">
                            <div className="font-mono-data text-2xl font-bold text-amber-400">
                              {liveStats ? liveStats.noTrades : 0}
                            </div>
                            <div className="text-xs text-white/60 font-display font-medium mt-1">
                              Risk Gate Defenses (NO_TRADE)
                            </div>
                          </div>
                        </div>

                        <div className="pt-2">
                          <button
                            onClick={() => navigateTo('Risk Config')}
                            className="btn-chartreuse px-5 py-3 rounded-xl text-xs sm:text-sm font-display font-bold flex items-center gap-2"
                          >
                            <span>Inspect Stage 4 Risk Parameters</span>
                            <span>→</span>
                          </button>
                        </div>
                      </div>

                      {/* Right Terminal: Requirement 3 (b) - Genuinely Live-Computed Real Record */}
                      {featuredRecord ? (
                        <div className="lg:col-span-6 rounded-2xl p-5 bg-[#14171D] border border-white/10 font-mono-data text-xs space-y-2.5 shadow-xl">
                          <div className="flex items-center justify-between pb-3 border-b border-white/10 text-white/40 text-[11px]">
                            <span>verified_audit_log — records.json</span>
                            <span className="text-emerald-400">● REAL RECORD #{featuredRecord.id}</span>
                          </div>
                          <div className="text-white/50 text-[11px] truncate">TIMESTAMP: {featuredRecord.timestamp}</div>
                          <div className="text-white/90 font-bold line-clamp-1">EVENT: &quot;{featuredRecord.event_headline}&quot;</div>
                          <div className="p-2.5 rounded-lg bg-black/50 border border-white/5 space-y-1 text-[11px]">
                            <div className="flex justify-between">
                              <span className="text-white/50">Engine / Source:</span>
                              <span style={{ color: '#D4FF3F' }}>{featuredRecord.llm_source}</span>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-white/50">Residual Z-Score:</span>
                              <span className="font-bold text-white">{fmt(featuredRecord.z_score, 2)}σ (Threshold: {riskConfig.zScoreThreshold}σ)</span>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-white/50">Observed Move:</span>
                              <span className="text-white">{fmtPct(featuredRecord.actual_move)}</span>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-white/50">Decision Verdict:</span>
                              <span className="font-bold text-amber-400">{featuredRecord.decision} ({featuredRecord.signals_aligned || '0/3'})</span>
                            </div>
                          </div>
                          <div className="text-white/70 text-[11px] leading-relaxed line-clamp-2">
                            VERDICT DETAIL: {featuredRecord.reason || featuredRecord.qwen_reasoning}
                          </div>
                          <div className="pt-2 border-t border-white/10 flex justify-between items-center text-[10px] text-white/40">
                            <span>MODE: {featuredRecord.mode}</span>
                            <button
                              onClick={() => selectAndViewDetail(featuredRecord)}
                              className="text-[var(--brand-chartreuse)] hover:underline font-bold"
                            >
                              Inspect Full Pipeline →
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="lg:col-span-6 rounded-2xl p-5 bg-[#14171D] border border-white/10 font-mono-data text-xs text-white/50">
                          Awaiting live market events...
                        </div>
                      )}
                    </div>
                  </div>
                </section>

                {/* 1.4 Closing CTA Banner */}
                <section className="max-w-7xl mx-auto px-4 sm:px-6">
                  <div
                    className="rounded-3xl p-10 sm:p-16 text-center border relative overflow-hidden"
                    style={{
                      background: 'var(--brand-chartreuse)',
                      color: '#0D0F12',
                      borderColor: 'rgba(0,0,0,0.1)'
                    }}
                  >
                    <DoodleSquiggle className="w-24 h-6 mx-auto mb-4 text-black/40" />
                    <h2 className="font-display font-black text-3xl sm:text-5xl tracking-tight mb-4 max-w-2xl mx-auto">
                      Audit the full autonomous pipeline now.
                    </h2>
                    <p className="text-sm sm:text-base font-medium text-black/75 max-w-xl mx-auto mb-8">
                      Zero simulated stats. Real live Groq classifications, real Bitget Agent Hub credentials, and real mathematical derivations.
                    </p>
                    <div className="flex flex-wrap items-center justify-center gap-4">
                      <button
                        onClick={() => navigateTo('Dashboard')}
                        className="px-8 py-4 rounded-2xl bg-[#0D0F12] text-[#F4F6F8] font-display font-black text-sm sm:text-base hover:scale-105 transition-all shadow-xl"
                      >
                        Enter Audit Dashboard →
                      </button>
                      <button
                        onClick={() => navigateTo('Risk Config')}
                        className="px-6 py-4 rounded-2xl bg-black/10 border border-black/20 text-[#0D0F12] font-display font-bold text-sm sm:text-base hover:bg-black/15 transition-all"
                      >
                        Review Risk Boundaries
                      </button>
                    </div>
                  </div>
                </section>

                {/* 1.5 Full Landing Page Footer (Only displayed on Home) */}
                <footer className="border-t pt-12 mt-16" style={{ borderColor: 'var(--border-hairline)' }}>
                  <div className="max-w-7xl mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-6">
                    <div className="space-y-1 text-center sm:text-left">
                      <div className="font-display font-black text-lg">
                        AfterHours Sentinel
                      </div>
                      <div className="text-xs font-mono-data" style={{ color: 'var(--text-muted)' }}>
                        Bitget AI Base Camp Hackathon S2 · Agentic Trading Track
                      </div>
                    </div>

                    <div className="flex items-center gap-6 text-sm font-display font-bold">
                      <a
                        href="https://github.com/0xSheriff"
                        target="_blank"
                        rel="noreferrer"
                        className="hover:opacity-80 transition-opacity flex items-center gap-1.5"
                        style={{ color: dark ? '#D4FF3F' : '#223602' }}
                      >
                        <span>GitHub</span>
                        <span className="text-xs">↗</span>
                      </a>
                      <a
                        href="https://x.com/0xearthh"
                        target="_blank"
                        rel="noreferrer"
                        className="hover:opacity-80 transition-opacity flex items-center gap-1.5"
                        style={{ color: dark ? '#D4FF3F' : '#223602' }}
                      >
                        <span>X (Twitter)</span>
                        <span className="text-xs">↗</span>
                      </a>
                    </div>
                  </div>
                </footer>
              </motion.div>
            )}

            {/* ─────────────────────────────────────────────────────────
                2. DASHBOARD SCREEN (With Chartreuse accents, layered depth)
               ───────────────────────────────────────────────────────── */}
            {activeScreen === 'Dashboard' && (
              <motion.div
                key="dashboard"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.3 }}
                className="max-w-7xl mx-auto px-4 sm:px-6 py-6 space-y-8"
              >
                {/* Asymmetric Hero Container with ProFinance Depth Motif */}
                <div
                  className="relative overflow-hidden rounded-3xl border p-6 sm:p-10 shadow-lg"
                  style={{
                    background: 'var(--bg-surface)',
                    borderColor: 'var(--border-hairline)',
                  }}
                >
                  {/* Subtle Chartreuse Glow in the corner */}
                  <div
                    className="absolute pointer-events-none -top-24 -left-20 w-[500px] h-[340px] rounded-full blur-3xl opacity-20 dark:opacity-25"
                    style={{ background: 'var(--brand-chartreuse)' }}
                  />

                  <div className="relative z-10 grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
                    {/* Left Column: Wordmark & Live Session Status */}
                    <div className="lg:col-span-7 space-y-4">
                      <div
                        className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full text-xs font-display font-bold uppercase tracking-wider border"
                        style={{
                          background: 'var(--brand-chartreuse-subtle)',
                          borderColor: 'var(--brand-chartreuse-border)',
                          color: dark ? '#D4FF3F' : '#223602',
                        }}
                      >
                        <span className="w-2 h-2 rounded-full animate-ping" style={{ background: 'var(--brand-chartreuse)' }} />
                        Continuous Event-Driven Divergence Engine
                      </div>
                      <h2 className="font-display font-black text-3xl sm:text-5xl tracking-tight leading-tight text-balance">
                        Autonomous 7×24 rToken Audit Interface
                      </h2>
                      <p className="text-sm sm:text-base max-w-xl leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                        Monitors after-hours US equity news catalysts, prices synthetic divergence against rolling benchmark betas, and enforces autonomous risk gates before submitting paper orders to Bitget Agent Hub.
                      </p>
                    </div>

                    {/* Right Column: Featured Decision Spotlight (Layered Card Depth Motif) */}
                    {featuredRecord && (
                      <div className="lg:col-span-5 relative layered-card-stack">
                        <div className="layered-card-under" />
                        <div
                          className="layered-card-main rounded-2xl p-6 border relative"
                          style={{ background: 'var(--bg-surface-elevated)', borderColor: 'var(--border-hairline)' }}
                        >
                          {/* Corner accent in chartreuse */}
                          <div
                            className="absolute top-0 right-0 w-8 h-8 rounded-tr-2xl rounded-bl-2xl opacity-80"
                            style={{ background: 'var(--brand-chartreuse-subtle)', borderTop: '2px solid var(--brand-chartreuse)', borderRight: '2px solid var(--brand-chartreuse)' }}
                          />

                          <div className="flex items-center justify-between mb-2.5">
                            <span className="text-[11px] font-display font-bold uppercase tracking-widest" style={{ color: 'var(--text-muted)' }}>
                              Latest Logged Decision
                            </span>
                            <div className="flex items-center gap-2">
                              <ModeBadge mode={featuredRecord.mode} isDark={dark} />
                              <SourceBadge record={featuredRecord} isDark={dark} />
                            </div>
                          </div>

                          <h3 className="font-display font-bold text-sm line-clamp-2 mb-3">
                            {featuredRecord.event_headline}
                          </h3>

                          <div className="space-y-3">
                            <div>
                              <div className="text-[10px] font-display font-semibold uppercase tracking-wider mb-1" style={{ color: 'var(--text-muted)' }}>
                                Residual Z-Score <span className="text-[9px] font-normal normal-case">(how unusual this price move was vs 2.0σ gate)</span>
                              </div>
                              <ZScoreGauge value={featuredRecord.z_score} threshold={riskConfig.zScoreThreshold} />
                            </div>

                            <div className="grid grid-cols-3 gap-2 pt-2 border-t" style={{ borderColor: 'var(--border-hairline)' }}>
                              <div>
                                <div className="text-[10px] uppercase font-display font-semibold" style={{ color: 'var(--text-muted)' }}>Decision</div>
                                <DecisionBadge decision={featuredRecord.decision} />
                              </div>
                              <div>
                                <div className="text-[10px] uppercase font-display font-semibold" style={{ color: 'var(--text-muted)' }}>Volume Ratio</div>
                                <div className="font-mono-data text-xs font-semibold">{fmt(featuredRecord.volume_ratio, 4)}</div>
                              </div>
                              <div>
                                <div className="text-[10px] uppercase font-display font-semibold" style={{ color: 'var(--text-muted)' }}>Observed Move</div>
                                <div className="font-mono-data text-xs font-semibold">{fmtPct(featuredRecord.actual_move)}</div>
                              </div>
                            </div>

                            <button
                              onClick={() => selectAndViewDetail(featuredRecord)}
                              className="w-full mt-2 text-center text-xs font-display font-bold py-2.5 px-3 rounded-xl btn-chartreuse"
                            >
                              Inspect 5-Stage Mathematical Pipeline →
                            </button>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {/* ═══════════════════════════════════════════════════════
                    SECTION 1: LIVE PAPER TRADING — COMPETITION PERIOD
                   ═══════════════════════════════════════════════════════ */}
                <section className="space-y-4">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2 border-b" style={{ borderColor: 'var(--border-hairline)' }}>
                    <div className="flex items-center gap-2.5">
                      <span className="w-2.5 h-2.5 rounded-full animate-ping" style={{ background: 'var(--brand-chartreuse)' }} />
                      <h3 className="font-display font-black text-lg sm:text-xl tracking-tight">
                        LIVE PAPER TRADING — COMPETITION PERIOD
                      </h3>
                    </div>
                    <div className="font-mono-data text-xs" style={{ color: 'var(--text-secondary)' }}>
                      Filter: <span className="font-bold" style={{ color: dark ? '#D4FF3F' : '#223602' }}>mode = &quot;live&quot;</span>
                      {liveStats && ` · Range: ${fmtTime(liveStats.startTime)} → ${fmtTime(liveStats.endTime)}`}
                    </div>
                  </div>

                  {liveStats ? (
                    <div className="space-y-4">
                      {/* Primary KPI Grid for Live Mode */}
                      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3.5">
                        <KPI
                          label="Monitoring Span"
                          value={`${liveStats.durationHrs} hrs`}
                          sublabel="Continuous loop"
                        />
                        <KPI
                          label="Events Ingested"
                          value={liveStats.total}
                          sublabel="Total RSS headlines"
                        />
                        <KPI
                          label="LLM Evaluation Split"
                          value={
                            <div className="flex flex-wrap items-baseline gap-1 text-sm sm:text-base font-bold font-mono-data">
                              <span style={{ color: dark ? '#D4FF3F' : '#223602' }}>{liveStats.liveCalls} Live</span>
                              <span style={{ color: 'var(--text-muted)' }}>/</span>
                              <span style={{ color: '#F59E0B' }}>{liveStats.fallbackCalls} Fallback</span>
                              <span style={{ color: 'var(--text-muted)' }}>/</span>
                              <span style={{ color: '#818CF8' }}>{liveStats.skippedCalls} Skipped</span>
                            </div>
                          }
                          valueClassName="font-mono-data py-0.5"
                          sublabel="Live API vs fallback vs pre-filtered noise"
                        />
                        <KPI
                          label="Trades Executed"
                          value={liveStats.tradesCount}
                          sublabel={liveStats.tradesCount === 0 ? `${liveStats.evaluatedCalls} evaluated (${liveStats.skippedCalls} pre-filtered)` : 'Orders submitted'}
                          accent={liveStats.tradesCount > 0 ? '#10B981' : undefined}
                        />
                        <KPI
                          label="Win Rate"
                          value={liveStats.tradesCount > 0 ? `${liveStats.winRate}%` : '0%'}
                          sublabel={liveStats.tradesCount === 0 ? `${liveStats.evaluatedCalls} gate reviews (0 trades)` : `${liveStats.winsCount} wins`}
                        />
                        <KPI
                          label="Realized P&L"
                          value={fmtUSD(liveStats.totalPnl)}
                          sublabel="Paper balance"
                          accent={liveStats.totalPnl >= 0 ? '#10B981' : '#F43F5E'}
                        />
                      </div>

                      {/* Live Decision Breakdown Banner */}
                      <div className="rounded-2xl p-4 border grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}>
                        <div className="flex items-center gap-3">
                          <div className="p-2.5 rounded-xl text-lg" style={{ background: 'var(--brand-chartreuse-subtle)', color: dark ? '#D4FF3F' : '#223602' }}>⚡</div>
                          <div>
                            <div className="font-mono-data text-lg font-bold">{liveStats.tradesCount}</div>
                            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>Executed Orders (LONG / SHORT)</div>
                          </div>
                        </div>
                        <div className="flex items-center gap-3">
                          <div className="p-2.5 rounded-xl bg-zinc-500/10 text-zinc-400 text-lg">🛡️</div>
                          <div>
                            <div className="font-mono-data text-lg font-bold">{liveStats.noTrades}</div>
                            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>Risk Gate Evaluated &amp; Blocked (NO_TRADE)</div>
                          </div>
                        </div>
                        <div className="flex items-center gap-3">
                          <div className="p-2.5 rounded-xl text-lg" style={{ background: 'var(--badge-skipped-bg)', color: 'var(--badge-skipped-text)' }}>⏭️</div>
                          <div>
                            <div className="font-mono-data text-lg font-bold">{liveStats.skippedCalls}</div>
                            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>Pre-Filter Skipped (No Target Equity Ticker)</div>
                          </div>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="rounded-2xl p-8 text-center border" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}>
                      <p className="text-sm font-semibold">No live competition records found yet.</p>
                    </div>
                  )}
                </section>

                {/* ═══════════════════════════════════════════════════════
                    SECTION 2: BACKTEST CALIBRATION SAMPLE (Secondary)
                   ═══════════════════════════════════════════════════════ */}
                <section className="space-y-3 pt-2">
                  <div className="flex items-center justify-between pb-2 border-b" style={{ borderColor: 'var(--border-hairline)' }}>
                    <div className="flex items-center gap-2">
                      <span className="w-2 h-2 rounded bg-indigo-500" />
                      <h3 className="font-display font-bold text-sm sm:text-base tracking-tight" style={{ color: 'var(--text-secondary)' }}>
                        BACKTEST CALIBRATION SAMPLE
                      </h3>
                    </div>
                    <span className="text-[11px] font-mono-data px-2 py-0.5 rounded border" style={{ background: 'var(--bg-surface-elevated)', borderColor: 'var(--border-hairline)', color: 'var(--text-muted)' }}>
                      Pre-competition calibration · Mode: &quot;backtest&quot;
                    </span>
                  </div>

                  <div className="rounded-2xl p-5 border" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}>
                    <p className="text-xs mb-3.5" style={{ color: 'var(--text-muted)' }}>
                      Historical replay sample run against pre-competition macro and earnings events (Aug 20 – Sep 8, 2026). Used strictly to verify rolling beta convergence, residual standard deviation bounds, and mean-reversion exit mechanics.
                    </p>

                    {backtestStats ? (
                      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                        <div className="p-3 rounded-xl" style={{ background: 'var(--bg-surface-elevated)' }}>
                          <div className="text-[10px] uppercase font-display font-semibold" style={{ color: 'var(--text-muted)' }}>Calibration Events</div>
                          <div className="font-mono-data text-base font-bold">{backtestStats.total}</div>
                        </div>
                        <div className="p-3 rounded-xl" style={{ background: 'var(--bg-surface-elevated)' }}>
                          <div className="text-[10px] uppercase font-display font-semibold" style={{ color: 'var(--text-muted)' }}>Simulated Trades</div>
                          <div className="font-mono-data text-base font-bold">{backtestStats.tradesCount}</div>
                        </div>
                        <div className="p-3 rounded-xl" style={{ background: 'var(--bg-surface-elevated)' }}>
                          <div className="text-[10px] uppercase font-display font-semibold" style={{ color: 'var(--text-muted)' }}>Calibration Win Rate</div>
                          <div className="font-mono-data text-base font-bold text-emerald-500">{backtestStats.winRate}%</div>
                        </div>
                        <div className="p-3 rounded-xl" style={{ background: 'var(--bg-surface-elevated)' }}>
                          <div className="text-[10px] uppercase font-display font-semibold" style={{ color: 'var(--text-muted)' }}>Sample P&amp;L</div>
                          <div className="font-mono-data text-base font-bold text-emerald-500">{fmtUSD(backtestStats.totalPnl)}</div>
                        </div>
                        <div className="p-3 rounded-xl" style={{ background: 'var(--bg-surface-elevated)' }}>
                          <div className="text-[10px] uppercase font-display font-semibold" style={{ color: 'var(--text-muted)' }}>NO_TRADE Rejections</div>
                          <div className="font-mono-data text-base font-bold">{backtestStats.noTrades}</div>
                        </div>
                      </div>
                    ) : (
                      <p className="text-xs" style={{ color: 'var(--text-muted)' }}>No backtest records present.</p>
                    )}
                  </div>
                </section>
              </motion.div>
            )}

            {/* ─────────────────────────────────────────────────────────
                3. DECISION FEED SCREEN (Chartreuse vs Neutral Left Bars)
               ───────────────────────────────────────────────────────── */}
            {activeScreen === 'Decision Feed' && (
              <motion.div
                key="feed"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.3 }}
                className="max-w-7xl mx-auto px-4 sm:px-6 py-6 space-y-4"
              >
                {/* Header Filters */}
                <div className="flex flex-wrap gap-3 items-center justify-between">
                  <div className="flex flex-wrap gap-2.5 items-center">
                    <input
                      type="text"
                      placeholder="Search headline or reason..."
                      value={filterSymbol}
                      onChange={e => setFilterSymbol(e.target.value)}
                      className="px-3.5 py-2.5 rounded-xl text-sm outline-none w-56 sm:w-72 font-display"
                      style={{
                        background: 'var(--bg-surface)',
                        border: '1px solid var(--border-hairline)',
                        color: 'var(--text-primary)',
                      }}
                    />

                    {/* Mode Filter: Live vs Backtest */}
                    <select
                      value={filterMode}
                      onChange={e => setFilterMode(e.target.value)}
                      className="px-3.5 py-2.5 rounded-xl text-sm outline-none font-display"
                      style={{
                        background: 'var(--bg-surface)',
                        border: '1px solid var(--border-hairline)',
                        color: 'var(--text-primary)',
                      }}
                    >
                      <option value="all">All Modes (Live &amp; Backtest)</option>
                      <option value="live">Live Paper Only</option>
                      <option value="backtest">Backtest Calibration Only</option>
                    </select>

                    {/* Source Filter: Live API vs Fallback vs Skipped */}
                    <select
                      value={filterSource}
                      onChange={e => setFilterSource(e.target.value)}
                      className="px-3.5 py-2.5 rounded-xl text-sm outline-none font-display"
                      style={{
                        background: 'var(--bg-surface)',
                        border: '1px solid var(--border-hairline)',
                        color: 'var(--text-primary)',
                      }}
                    >
                      <option value="all">All Sources (Live, Fallback &amp; Skipped)</option>
                      <option value="live">Live API Calls (Groq Qwen 3.8-27B)</option>
                      <option value="fallback">Fallback Rules (Target Asset Matched)</option>
                      <option value="skipped">Pre-Filter Skipped (No Target Asset)</option>
                    </select>
                  </div>

                  <div className="flex items-center gap-4 text-xs font-mono-data" style={{ color: 'var(--text-muted)' }}>
                    <div className="flex items-center gap-1.5">
                      <span className="w-2.5 h-2.5 rounded-sm" style={{ background: 'var(--brand-chartreuse)' }} />
                      <span>Live API</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span className="w-2.5 h-2.5 rounded-sm" style={{ background: '#F59E0B' }} />
                      <span>Fallback</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span className="w-2.5 h-2.5 rounded-sm" style={{ background: '#818CF8' }} />
                      <span>Pre-Filter Skipped</span>
                    </div>
                    <span className="font-bold">{filteredRecords.length} records</span>
                  </div>
                </div>

                {/* Table Container */}
                <div className="rounded-2xl overflow-hidden border shadow-sm" style={{ borderColor: 'var(--border-hairline)' }}>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm border-collapse">
                      <thead>
                        <tr style={{ background: 'var(--bg-surface-elevated)' }}>
                          <th className="px-3.5 py-3 text-left text-xs font-display font-bold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Source</th>
                          <th className="px-3.5 py-3 text-left text-xs font-display font-bold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Time</th>
                          <th className="px-3.5 py-3 text-left text-xs font-display font-bold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Mode</th>
                          <th className="px-3.5 py-3 text-left text-xs font-display font-bold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Headline &amp; Reasoning</th>
                          <th className="px-3.5 py-3 text-left text-xs font-display font-bold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                            Z-Score <span className="text-[9px] font-normal normal-case block text-muted">(move vs avg)</span>
                          </th>
                          <th className="px-3.5 py-3 text-left text-xs font-display font-bold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Decision</th>
                          <th className="px-3.5 py-3 text-right text-xs font-display font-bold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>P&amp;L</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredRecords.map((r, idx) => {
                          const cat = getLLMSourceCategory(r)
                          const barColor = cat === 'live'
                            ? 'var(--brand-chartreuse)'
                            : cat === 'fallback'
                              ? '#F59E0B'
                              : '#818CF8'

                          return (
                            <motion.tr
                              key={`${r.id}-${r.timestamp}`}
                              initial={{ opacity: 0, y: 4 }}
                              animate={{ opacity: 1, y: 0 }}
                              transition={{ duration: 0.2, delay: Math.min(idx * 0.015, 0.35) }}
                              onClick={() => selectAndViewDetail(r)}
                              className="group cursor-pointer transition-colors"
                              style={{
                                background: 'var(--bg-surface)',
                                borderBottom: '1px solid var(--border-hairline)',
                                borderLeft: `4px solid ${barColor}`,
                              }}
                            >
                              <td className="px-3.5 py-3 whitespace-nowrap">
                                <SourceBadge record={r} isDark={dark} />
                              </td>
                              <td className="px-3.5 py-3 font-mono-data text-xs whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>
                                {fmtTime(r.timestamp)}
                              </td>
                              <td className="px-3.5 py-3 whitespace-nowrap">
                                <ModeBadge mode={r.mode} isDark={dark} />
                              </td>
                              <td className="px-3.5 py-3 max-w-md">
                                <div className="font-display font-bold text-sm line-clamp-1 group-hover:underline transition-colors">
                                  {r.event_headline}
                                </div>
                                <div className="text-xs line-clamp-1 mt-0.5 font-mono-data" style={{ color: 'var(--text-muted)' }}>
                                  {r.reason || r.qwen_reasoning}
                                </div>
                              </td>
                              <td className="px-3.5 py-3 font-mono-data text-sm font-bold whitespace-nowrap">
                                <span style={{ color: Math.abs(r.z_score || 0) >= riskConfig.zScoreThreshold ? '#10B981' : 'var(--text-primary)' }}>
                                  {fmt(r.z_score, 2)}σ
                                </span>
                              </td>
                              <td className="px-3.5 py-3 whitespace-nowrap">
                                <DecisionBadge decision={r.decision} />
                              </td>
                              <td className="px-3.5 py-3 text-right font-mono-data text-sm font-bold whitespace-nowrap" style={{
                                color: (r.pnl || 0) > 0 ? '#10B981' : (r.pnl || 0) < 0 ? '#F43F5E' : 'var(--text-muted)'
                              }}>
                                {(r.pnl || 0) !== 0 ? fmtUSD(r.pnl) : '—'}
                              </td>
                            </motion.tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              </motion.div>
            )}

            {/* ─────────────────────────────────────────────────────────
                4. EVENT DETAIL SCREEN (5-Stage Mathematical Pipeline)
               ───────────────────────────────────────────────────────── */}
            {activeScreen === 'Event Detail' && (
              <motion.div
                key="detail"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.3 }}
                className="max-w-7xl mx-auto px-4 sm:px-6 py-6"
              >
                {!selectedRecord ? (
                  <div className="text-center py-20 border rounded-3xl" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}>
                    <p className="text-base font-display font-bold mb-2" style={{ color: 'var(--text-secondary)' }}>
                      No record currently selected.
                    </p>
                    <p className="text-xs mb-4" style={{ color: 'var(--text-muted)' }}>
                      Click any row in the Decision Feed or the featured card on the Dashboard to inspect its pipeline.
                    </p>
                    <button
                      onClick={() => setActiveScreen('Decision Feed')}
                      className="btn-chartreuse text-xs font-display font-bold px-4 py-2.5 rounded-xl transition-all"
                    >
                      Open Decision Feed →
                    </button>
                  </div>
                ) : (
                  <div className="space-y-6">
                    {/* Back button & Title header */}
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b" style={{ borderColor: 'var(--border-hairline)' }}>
                      <div>
                        <button
                          onClick={() => setActiveScreen('Decision Feed')}
                          className="text-xs font-display font-bold hover:underline mb-2 inline-flex items-center gap-1"
                          style={{ color: dark ? '#D4FF3F' : '#223602' }}
                        >
                          ← Return to Decision Feed
                        </button>
                        <h2 className="font-display font-black text-xl sm:text-2xl leading-tight">
                          {selectedRecord.event_headline}
                        </h2>
                      </div>
                      <div className="flex items-center gap-2">
                        <ModeBadge mode={selectedRecord.mode} isDark={dark} />
                        <SourceBadge record={selectedRecord} isDark={dark} />
                        <DecisionBadge decision={selectedRecord.decision} />
                      </div>
                    </div>

                    {/* 5-Stage Pipeline Container */}
                    <div className="space-y-4">
                      {/* Stage 1: Event Ingestion & Freshness Filtering */}
                      <PipelineStage num={1} title="Stage 1: News Catalyst Ingestion" color="#8B5CF6">
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
                          <DataRow label="Event Type" value={selectedRecord.event_type?.toUpperCase()} />
                          <DataRow label="Timestamp" value={fmtTime(selectedRecord.timestamp)} />
                          <DataRow label="Operating Mode" value={selectedRecord.mode} />
                          <DataRow label="Max Allowable Age" value={`${riskConfig.eventFreshnessHours} hours`} />
                        </div>
                        <div className="p-3 rounded-xl text-xs" style={{ background: 'var(--bg-canvas)' }}>
                          <span className="font-bold font-display" style={{ color: 'var(--text-primary)' }}>Raw Ingested Headline:</span>{' '}
                          <span style={{ color: 'var(--text-secondary)' }}>{selectedRecord.event_headline}</span>
                        </div>
                      </PipelineStage>

                      {/* Stage 2: Divergence Engine & Mathematical Derivation */}
                      <PipelineStage num={2} title="Stage 2: Deterministic Divergence Engine" color="#D4FF3F">
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
                          <DataRow label="Observed Asset Move" value={fmtPct(selectedRecord.actual_move)} />
                          <DataRow label="Benchmark Expected Move" value={fmtPct(selectedRecord.expected_move)} />
                          <DataRow label="Divergence (Residual)" value={fmtPct(selectedRecord.divergence)} />
                          <DataRow label="Volume Ratio" value={fmt(selectedRecord.volume_ratio, 4)} />
                        </div>

                        {/* Mathematical Proof calculated strictly from logged tensors */}
                        {(() => {
                          const actual = Number(selectedRecord.actual_move || 0)
                          const expected = Number(selectedRecord.expected_move || 0)
                          const residual = Number(selectedRecord.divergence || (actual - expected))
                          const z = Number(selectedRecord.z_score || 0)
                          const impliedSigma = Math.abs(z) > 0.0001 ? Math.abs(residual / z) : riskConfig.minResidualStdev
                          const volRatio = Number(selectedRecord.volume_ratio || 0)
                          const isWeakVol = volRatio < riskConfig.volumeWeakThreshold

                          return (
                            <div className="rounded-xl p-4 font-mono-data text-xs space-y-2.5 border" style={{ background: 'var(--bg-canvas)', borderColor: 'var(--border-hairline)' }}>
                              <div className="font-bold text-xs uppercase tracking-wider mb-2 font-display" style={{ color: 'var(--text-muted)' }}>
                                Mathematical Proof (Calculated from Logged Tensors):
                              </div>

                              <div className="flex flex-wrap items-center gap-1.5" style={{ color: 'var(--text-secondary)' }}>
                                <span>1. Residual:</span>
                                <span className="font-semibold text-[var(--text-primary)]">R_asset − E[R]</span>
                                <span>=</span>
                                <span>{fmtPct(actual)} − {fmtPct(expected)}</span>
                                <span>=</span>
                                <span className="font-bold text-[var(--text-primary)]">{fmtPct(residual)}</span>
                              </div>

                              <div className="flex flex-wrap items-center gap-1.5" style={{ color: 'var(--text-secondary)' }}>
                                <span>2. Standardized Z-Score:</span>
                                <span className="text-[10px] text-muted font-normal">(how unusual this price move was)</span>
                                <span className="font-semibold text-[var(--text-primary)]">residual / σ_residual</span>
                                <span>=</span>
                                <span>{fmtPct(residual)} / {fmtPct(impliedSigma)}</span>
                                <span>=</span>
                                <span className={`font-bold ${Math.abs(z) >= riskConfig.zScoreThreshold ? 'text-emerald-500' : 'text-rose-500'}`}>
                                  {fmt(z, 2)}σ
                                </span>
                                <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
                                  ({Math.abs(z) >= riskConfig.zScoreThreshold ? '≥ 2.0σ Threshold Passed ✓' : '< 2.0σ Threshold Failed ✗'})
                                </span>
                              </div>

                              <div className="flex flex-wrap items-center gap-1.5" style={{ color: 'var(--text-secondary)' }}>
                                <span>3. Volume Confirmation:</span>
                                <span className="font-semibold text-[var(--text-primary)]">Vol_AH / Vol_trailing</span>
                                <span>=</span>
                                <span className="font-bold text-[var(--text-primary)]">{fmt(volRatio, 4)}</span>
                                <span>→</span>
                                <span className={isWeakVol ? 'text-emerald-500 font-bold' : 'text-rose-500 font-bold'}>
                                  {isWeakVol ? 'WEAK VOLUME CONFIRMED (< 0.50) ✓' : 'NORMAL/HIGH VOLUME (NOT A LIQUIDITY SPIKE) ✗'}
                                </span>
                              </div>
                            </div>
                          )
                        })()}

                        <div className="mt-4">
                          <ZScoreGauge value={selectedRecord.z_score} threshold={riskConfig.zScoreThreshold} />
                        </div>
                      </PipelineStage>

                      {/* Stage 3: LLM Directional Analyst (Groq/Qwen) */}
                      <PipelineStage num={3} title="Stage 3: LLM Sentiment & Directional Analyst" color="#10B981">
                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-3">
                          <DataRow label="Directional Classification" value={selectedRecord.qwen_direction} />
                          <DataRow label="LLM Engine" value={selectedRecord.llm_source} />
                          <DataRow
                            label="Call Provenance"
                            value={
                              isLiveCall(selectedRecord)
                                ? 'Verified Live API Ping (Groq Qwen 3.8-27B)'
                                : isFallbackCall(selectedRecord)
                                  ? 'Deterministic Fallback Rules'
                                  : 'Pre-Filter Skipped (No Target Equity Ticker)'
                            }
                          />
                        </div>

                        <div className="rounded-xl p-4 border" style={{ background: 'var(--bg-canvas)', borderColor: 'var(--border-hairline)' }}>
                          <div className="text-[11px] font-display font-bold uppercase tracking-wider mb-1.5" style={{ color: 'var(--text-muted)' }}>
                            Full Un-truncated LLM Reasoning:
                          </div>
                          <p className="text-sm leading-relaxed font-mono-data" style={{ color: 'var(--text-secondary)' }}>
                            {selectedRecord.qwen_reasoning || (isSkippedCall(selectedRecord) ? 'Pre-filtered: Headline contained no target equity ticker (NVDA, TSLA, AAPL, etc.). Zero LLM tokens consumed.' : 'No LLM reasoning captured.')}
                          </p>
                        </div>
                      </PipelineStage>

                      {/* Stage 4: Strict Deterministic Risk Gate */}
                      <PipelineStage num={4} title="Stage 4: Risk Engine Verification Gate" color="#F59E0B">
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
                          <DataRow
                            label="Strategy Mode"
                            value={<StrategyBadge mode={selectedRecord?.strategy_mode} isDark={dark} />}
                          />
                          <DataRow label="3-Signal Alignment" value={selectedRecord.signals_aligned} />
                          <DataRow label="Gate Decision" value={selectedRecord.decision} />
                          <DataRow
                            label="Position Sizing Allocation"
                            value={selectedRecord.decision === 'LONG' || selectedRecord.decision === 'SHORT'
                              ? `${(riskConfig.positionSizePct * 100).toFixed(0)}% Portfolio ($${(riskConfig.defaultPortfolioBalance * riskConfig.positionSizePct).toLocaleString()})`
                              : '$0.00'
                            }
                          />
                        </div>

                        <div className="p-3.5 rounded-xl border" style={{ background: 'var(--bg-canvas)', borderColor: 'var(--border-hairline)' }}>
                          <div className="text-[11px] font-display font-bold uppercase tracking-wider mb-1" style={{ color: 'var(--text-muted)' }}>
                            Gatekeeper Verdict:
                          </div>
                          <p className="text-xs font-mono-data leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                            {selectedRecord.reason}
                          </p>
                        </div>
                      </PipelineStage>

                      {/* Stage 5: Autonomous Execution */}
                      <PipelineStage
                        num={5}
                        title="Stage 5: Bitget Agent Hub Order Execution"
                        color={selectedRecord.decision === 'LONG' || selectedRecord.decision === 'SHORT' ? '#10B981' : '#6B7280'}
                      >
                        {selectedRecord.decision === 'LONG' || selectedRecord.decision === 'SHORT' ? (
                          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                            <DataRow label="Trade Direction" value={selectedRecord.decision} />
                            <DataRow label="Position Size" value={fmtUSD(selectedRecord.position_size)} />
                            <DataRow label="Entry Execution Price" value={fmtUSD(selectedRecord.entry_price)} />
                            <DataRow label="Stop-Loss Price" value={fmtUSD(selectedRecord.stop_price)} />
                            <DataRow label="Exit Price" value={fmtUSD(selectedRecord.exit_price)} />
                            <DataRow label="Exit Catalyst" value={selectedRecord.exit_reason} />
                            <DataRow
                              label="Trade P&L"
                              value={fmtUSD(selectedRecord.pnl)}
                              accent={(selectedRecord.pnl || 0) >= 0 ? '#10B981' : '#F43F5E'}
                            />
                            <DataRow label="Client Protocol" value={selectedRecord.execution_client?.split('[')[0]?.trim()} />
                          </div>
                        ) : (
                          <div className="p-3 rounded-xl text-xs" style={{ background: 'var(--bg-canvas)', color: 'var(--text-muted)' }}>
                            No execution request dispatched — order blocked by Stage 4 risk constraints.
                          </div>
                        )}
                      </PipelineStage>
                    </div>
                  </div>
                )}
              </motion.div>
            )}

            {/* ─────────────────────────────────────────────────────────
                5. RISK CONFIG SCREEN (Read-Only Parameters from config.py)
               ───────────────────────────────────────────────────────── */}
            {activeScreen === 'Risk Config' && (
              <motion.div
                key="risk"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.3 }}
                className="max-w-7xl mx-auto px-4 sm:px-6 py-6 space-y-4"
              >
                <div>
                  <h2 className="font-display font-black text-xl sm:text-2xl tracking-tight">
                    Risk Architecture & Boundary Parameters
                  </h2>
                  <p className="text-sm mt-1" style={{ color: 'var(--text-secondary)' }}>
                    Read-only configuration loaded directly from <code className="font-mono-data text-xs px-1.5 py-0.5 rounded" style={{ background: 'var(--bg-surface-elevated)' }}>config.py</code>. These static bounds govern the Stage 4 risk gate.
                  </p>
                </div>

                <div className="rounded-2xl overflow-hidden border shadow-sm" style={{ borderColor: 'var(--border-hairline)' }}>
                  <table className="w-full text-sm">
                    <thead>
                      <tr style={{ background: 'var(--bg-surface-elevated)' }}>
                        <th className="px-4 py-3.5 text-left text-xs font-display font-bold uppercase" style={{ color: 'var(--text-muted)' }}>Parameter</th>
                        <th className="px-4 py-3.5 text-left text-xs font-display font-bold uppercase" style={{ color: 'var(--text-muted)' }}>Configured Bound</th>
                        <th className="px-4 py-3.5 text-left text-xs font-display font-bold uppercase" style={{ color: 'var(--text-muted)' }}>System Description</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[
                        ['POSITION_SIZE_PCT', `${(riskConfig.positionSizePct * 100).toFixed(0)}%`, `Fixed capital percentage of portfolio balance allocated per trade ($${(riskConfig.defaultPortfolioBalance * riskConfig.positionSizePct).toLocaleString()} baseline)`],
                        ['STOP_LOSS_PCT', `${(riskConfig.stopLossPct * 100).toFixed(1)}%`, 'Hard stop-loss distance calculated strictly from entry execution fill'],
                        ['MAX_OPEN_POSITIONS', riskConfig.maxOpenPositions, 'Concurrent open position cap across all rToken underlyings'],
                        ['DAILY_LOSS_LIMIT_PCT', `${(riskConfig.dailyLossLimitPct * 100).toFixed(0)}%`, 'Portfolio circuit breaker — halts all new trade evaluations if daily drawdown reached'],
                        ['Z_SCORE_THRESHOLD', `${riskConfig.zScoreThreshold.toFixed(1)}σ`, 'Minimum divergence residual required to trigger overreaction trade hypothesis'],
                        ['VOLUME_WEAK_THRESHOLD', riskConfig.volumeWeakThreshold.toFixed(2), 'Volume ratio ceiling; ratios above 0.50 signify structural institutional momentum and abort entry'],
                        ['MIN_RESIDUAL_STDEV', fmtPct(riskConfig.minResidualStdev), 'Numerical volatility floor to prevent division-by-zero on low-volatility weekends'],
                        ['BETA_ROLLING_WINDOW', `${riskConfig.betaRollingWindowDays} days`, 'Lookback duration for rolling ordinary least squares regression against QQQ/BTC benchmarks'],
                        ['PORTFOLIO_BALANCE', fmtUSD(riskConfig.defaultPortfolioBalance), 'Baseline simulated paper capital balance allocated to Bitget Agentic account'],
                        ['EVENT_FRESHNESS', `${riskConfig.eventFreshnessHours.toFixed(1)} hours`, 'Maximum timestamp age for news items to qualify for real-time pricing analysis'],
                      ].map(([param, val, desc]) => (
                        <tr key={param} style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-hairline)' }}>
                          <td className="px-4 py-3.5 font-mono-data text-xs font-bold">{param}</td>
                          <td className="px-4 py-3.5 font-mono-data text-xs font-bold" style={{ color: dark ? '#D4FF3F' : '#223602' }}>{val}</td>
                          <td className="px-4 py-3.5 text-xs" style={{ color: 'var(--text-secondary)' }}>{desc}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
          )}
        </main>

        {/* Minimal Bottom Line for App Screens (Landing has its own full footer) */}
        {activeScreen !== 'Home' && (
          <footer className="border-t py-4 mt-8" style={{ borderColor: 'var(--border-hairline)' }}>
            <div className="max-w-7xl mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs" style={{ color: 'var(--text-muted)' }}>
              <div className="font-display font-bold">
                AfterHours Sentinel · Autonomous rToken Event-Driven Agent
              </div>
              <div className="font-mono-data">
                Bitget Agent Hub Demo Integration
              </div>
            </div>
          </footer>
        )}
      </div>
    </div>
  )
}

// ── Shared Visual Sub-components ──
function KPI({ label, value, sublabel, accent, valueClassName }) {
  return (
    <div
      className="rounded-2xl p-4 border transition-all duration-200 hover:-translate-y-0.5 shadow-sm flex flex-col justify-between"
      style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}
    >
      <div>
        <div className="text-[10px] font-display font-bold uppercase tracking-wider mb-1.5" style={{ color: 'var(--text-muted)' }}>
          {label}
        </div>
        <div className={valueClassName || "font-mono-data text-lg sm:text-xl font-bold truncate"} style={{ color: accent || 'var(--text-primary)' }}>
          {value}
        </div>
      </div>
      {sublabel && (
        <div className="text-[10px] mt-1.5 font-display font-medium leading-tight" style={{ color: 'var(--text-muted)' }}>
          {sublabel}
        </div>
      )}
    </div>
  )
}

function DataRow({ label, value, accent }) {
  return (
    <div>
      <div className="text-[10px] uppercase font-display font-bold tracking-wider" style={{ color: 'var(--text-muted)' }}>
        {label}
      </div>
      <div className="font-mono-data text-xs font-semibold mt-0.5" style={{ color: accent || 'var(--text-primary)' }}>
        {value || '—'}
      </div>
    </div>
  )
}

function PipelineStage({ num, title, color, children }) {
  return (
    <div className="rounded-2xl p-4 sm:p-5 border shadow-sm" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-hairline)' }}>
      <div className="flex items-center gap-3 mb-3.5">
        <div
          className="w-7 h-7 rounded-xl flex items-center justify-center text-xs font-display font-black text-black shadow-sm"
          style={{ background: color === '#D4FF3F' ? 'var(--brand-chartreuse)' : color }}
        >
          {num}
        </div>
        <h3 className="font-display font-bold text-sm sm:text-base">
          {title}
        </h3>
      </div>
      {children}
    </div>
  )
}
