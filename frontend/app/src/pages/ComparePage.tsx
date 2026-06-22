import { useState } from 'react'
import { Button, Badge } from '../components/ui'
import { cn } from '../lib/cn'

type Decision = 'accepted' | 'declined' | null

interface Section {
  id: string
  title: string
  ref: string
  current: string
}

const SECTIONS: Section[] = [
  {
    id: 'overview',
    title: '1. Overview',
    ref: 'The ThermalModel component monitors engine temperature and triggers protective actions when thresholds are exceeded. It reads from three NTC sensors and applies a Kalman filter for noise reduction.',
    current: 'The ThermalModel component monitors engine temperature and triggers protective actions when thresholds are exceeded. It reads from four NTC sensors and applies an extended Kalman filter for improved noise reduction and sensor fusion.',
  },
  {
    id: 'interfaces',
    title: '2. Interfaces',
    ref: 'Public interfaces:\n- ThermalModel_Init(cfg: ThermalConfig*) → void\n- ThermalModel_Step(dt: float32) → ThermalState\n- ThermalModel_GetTemp(sensor: uint8) → float32',
    current: 'Public interfaces:\n- ThermalModel_Init(cfg: ThermalConfig*) → void\n- ThermalModel_Step(dt: float32) → ThermalState\n- ThermalModel_GetTemp(sensor: uint8) → float32\n- ThermalModel_Calibrate(offset: float32[4]) → void  ← NEW',
  },
  {
    id: 'behavior',
    title: '3. Behavior',
    ref: 'State machine with 3 states: NORMAL, WARNING, CRITICAL. Transitions triggered by temperature crossing configured thresholds (T_warn, T_crit).',
    current: 'State machine with 3 states: NORMAL, WARNING, CRITICAL. Transitions triggered by temperature crossing configured thresholds (T_warn, T_crit). Hysteresis of 2°C applied on all transitions to prevent oscillation.',
  },
]

const TREE_COMPONENTS = [
  { id: 'thermal', label: 'ThermalModel', active: true },
  { id: 'kalman',  label: 'KalmanFilter', active: false },
  { id: 'can',     label: 'CANInterface', active: false },
  { id: 'diag',    label: 'Diagnostics',  active: false },
  { id: 'pwm',     label: 'PWMControl',   active: false },
]

function DiffPanel({ refLines, curLines }: { refLines: string[]; curLines: string[] }) {
  const maxLen = Math.max(refLines.length, curLines.length)
  return (
    <>
      {Array.from({ length: maxLen }, (_, i) => {
        const r = refLines[i] ?? ''
        const c = curLines[i] ?? ''
        const changed = r !== c
        return (
          <div
            key={i}
            className={cn(
              'px-4 py-0.5 font-mono text-xs leading-5',
              changed ? 'bg-amber-50 border-l-2 border-amber-400 text-on-surface' : 'text-on-surface-variant',
            )}
          >
            {c || <span className="opacity-0">—</span>}
          </div>
        )
      })}
    </>
  )
}

export function ComparePage() {
  const [decisions, setDecisions] = useState<Record<string, Decision>>({})
  const [activeComponent, setActiveComponent] = useState('thermal')

  function decide(id: string, d: Decision) {
    setDecisions((prev) => ({ ...prev, [id]: d }))
  }

  const resolved = Object.values(decisions).filter(Boolean).length
  const total = SECTIONS.length

  return (
    <div className="flex h-full overflow-hidden">
      {/* Component tree panel */}
      <nav
        aria-label="Component tree"
        className="flex-shrink-0 border-r border-outline-variant bg-white flex flex-col"
        style={{ width: 200 }}
      >
        <div className="px-3 py-3 border-b border-outline-variant">
          <p
            className="text-on-surface-variant uppercase"
            style={{ fontFamily: "'JetBrains Mono'", fontSize: 10, fontWeight: 600, letterSpacing: '0.1em' }}
          >
            SWE.3
          </p>
        </div>
        <div className="flex-1 overflow-y-auto py-2">
          {TREE_COMPONENTS.map((comp) => {
            const isActive = activeComponent === comp.id
            return (
              <button
                key={comp.id}
                onClick={() => setActiveComponent(comp.id)}
                className="w-full flex items-center gap-1.5 transition-colors"
                style={{
                  padding: isActive ? '5px 10px 5px 8px' : '5px 10px',
                  borderRadius: 4,
                  background: isActive ? '#e5eeff' : 'transparent',
                  color: isActive ? '#0058be' : '#44474c',
                  borderLeft: isActive ? '2px solid #0058be' : '2px solid transparent',
                  fontFamily: "'JetBrains Mono'",
                  fontSize: 11,
                  fontWeight: isActive ? 600 : 400,
                  textAlign: 'left',
                }}
              >
                <span
                  style={{
                    width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
                    background: isActive ? '#0058be' : '#c4c6cd',
                  }}
                  aria-hidden
                />
                {comp.label}
              </button>
            )
          })}
        </div>
      </nav>

      {/* Compare content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Panel headers */}
        <div className="flex border-b border-outline-variant bg-white flex-shrink-0" aria-label="Compare versions">
          <div className="flex-1 flex items-center gap-3 px-5 py-3 border-r border-outline-variant">
            <span className="font-mono text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.08em]">Reference</span>
            <Badge variant="mono">v1.1.0 · a1b2c3d</Badge>
          </div>
          <div className="flex-1 flex items-center gap-3 px-5 py-3">
            <span className="font-mono text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.08em]">Current</span>
            <Badge variant="primary">v1.2.0 · d9a0c55</Badge>
            <Badge variant="warning">In Review</Badge>
          </div>
        </div>

        {/* Sections */}
        <div className="flex-1 overflow-y-auto" role="list" aria-label="Document sections">
          {SECTIONS.map((section) => {
            const decision = decisions[section.id] ?? null
            const refLines = section.ref.split('\n')
            const curLines = section.current.split('\n')

            return (
              <div
                key={section.id}
                role="listitem"
                className={cn(
                  'border-b border-outline-variant',
                  decision === 'accepted' && 'bg-on-tertiary-container/5',
                  decision === 'declined' && 'bg-error/5',
                )}
              >
                {/* Section header */}
                <div className="flex items-center justify-between px-5 py-3 bg-surface-container-low border-b border-outline-variant">
                  <div className="flex items-center gap-2.5">
                    {decision === 'accepted' && (
                      <span className="material-symbols-outlined sym-fill text-on-tertiary-container" style={{ fontSize: 16 }} aria-hidden>check_circle</span>
                    )}
                    {decision === 'declined' && (
                      <span className="material-symbols-outlined sym-fill text-error" style={{ fontSize: 16 }} aria-hidden>cancel</span>
                    )}
                    <h3 className="text-sm font-semibold text-on-surface">{section.title}</h3>
                  </div>
                  <div className="flex items-center gap-2" role="group" aria-label={`Actions for ${section.title}`}>
                    <Button
                      size="sm"
                      variant={decision === 'accepted' ? 'primary' : 'ghost'}
                      onClick={() => decide(section.id, decision === 'accepted' ? null : 'accepted')}
                      aria-pressed={decision === 'accepted'}
                      className={decision === 'accepted' ? '' : 'text-on-tertiary-container border border-on-tertiary-container/30 hover:bg-on-tertiary-container/10'}
                    >
                      <span className="material-symbols-outlined" style={{ fontSize: 13 }} aria-hidden>check</span>
                      Accept
                    </Button>
                    <Button
                      size="sm"
                      variant={decision === 'declined' ? 'danger' : 'ghost'}
                      onClick={() => decide(section.id, decision === 'declined' ? null : 'declined')}
                      aria-pressed={decision === 'declined'}
                      className={decision === 'declined' ? '' : 'text-error border border-error/30 hover:bg-error/10'}
                    >
                      <span className="material-symbols-outlined" style={{ fontSize: 13 }} aria-hidden>close</span>
                      Decline
                    </Button>
                    <Button size="sm" variant="ghost">
                      <span className="material-symbols-outlined" style={{ fontSize: 13 }} aria-hidden>edit</span>
                      Edit
                    </Button>
                  </div>
                </div>

                {/* Split diff */}
                <div className="flex" aria-label={`Diff for ${section.title}`}>
                  <div className="flex-1 border-r border-outline-variant py-2" aria-label="Reference">
                    {refLines.map((line, i) => (
                      <div key={i} className="px-4 py-0.5 font-mono text-xs text-on-surface-variant leading-5">{line}</div>
                    ))}
                  </div>
                  <div className="flex-1 py-2" aria-label="Current">
                    <DiffPanel refLines={refLines} curLines={curLines} />
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        {/* Review footer */}
        <footer className="flex-shrink-0 border-t border-outline-variant bg-white px-5 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1" role="progressbar" aria-valuenow={resolved} aria-valuemax={total} aria-label={`${resolved} of ${total} sections resolved`}>
              {SECTIONS.map((s) => {
                const d = decisions[s.id]
                return (
                  <div
                    key={s.id}
                    className={cn(
                      'w-3 h-3 rounded-full transition-colors',
                      d === 'accepted' ? 'bg-on-tertiary-container' : d === 'declined' ? 'bg-error' : 'bg-outline-variant',
                    )}
                  />
                )
              })}
            </div>
            <span className="text-xs text-on-surface-variant">{resolved}/{total} sections resolved</span>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm">Submit Review</Button>
            <Button
              size="sm"
              disabled={resolved < total}
              aria-disabled={resolved < total}
              title={resolved < total ? 'Resolve all sections first' : undefined}
            >
              <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>check</span>
              Approve Document
            </Button>
          </div>
        </footer>
      </div>
    </div>
  )
}
