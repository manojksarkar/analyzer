import { useState } from 'react'

type Decision = 'accepted' | 'declined' | null
type TreeMode = 'diff' | 'all'

const TREE_DOCS = [
  { id: 'brake',     label: 'Brake Controller', changed: true,  active: true  },
  { id: 'abs',       label: 'ABS Unit',         changed: true,  active: false },
  { id: 'stability', label: 'Stability Control', changed: true, active: false },
  { id: 'throttle',  label: 'Throttle Controller', changed: false, active: false },
  { id: 'fuel',      label: 'Fuel Injector',    changed: false, active: false },
  { id: 'gpio',      label: 'GPIO Driver',      changed: false, active: false },
  { id: 'can',       label: 'CAN Driver',       changed: false, active: false },
]

const CHANGED_SECTIONS = ['c-interfaces', 'c-dynamic'] as const

/* ─── Document tree (left) ─── */
function DocTree({ mode, setMode, active, setActive }: {
  mode: TreeMode; setMode: (m: TreeMode) => void; active: string; setActive: (id: string) => void
}) {
  const visible = mode === 'diff' ? TREE_DOCS.filter((d) => d.changed) : TREE_DOCS
  const changedCount = TREE_DOCS.filter((d) => d.changed).length
  return (
    <aside className="w-60 flex-shrink-0 bg-white border-r border-outline-variant flex flex-col overflow-hidden">
      <div className="px-3 py-2.5 border-b border-outline-variant flex-shrink-0 flex items-center justify-between">
        <span className="text-on-surface-variant uppercase" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 500, letterSpacing: '0.1em' }}>Documents</span>
        <div className="flex items-center rounded-lg border border-outline-variant overflow-hidden" style={{ fontFamily: "'JetBrains Mono'", fontSize: 10, fontWeight: 600 }}>
          <button
            onClick={() => setMode('diff')}
            className="px-2 py-1 transition-colors"
            style={{ background: mode === 'diff' ? '#041627' : 'transparent', color: mode === 'diff' ? '#fff' : '#44474c' }}
          >
            Diff
          </button>
          <button
            onClick={() => setMode('all')}
            className="px-2 py-1 transition-colors"
            style={{ background: mode === 'all' ? '#041627' : 'transparent', color: mode === 'all' ? '#fff' : '#44474c' }}
          >
            All
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto py-2">
        {visible.map((d) => {
          const isActive = active === d.id
          return (
            <button
              key={d.id}
              onClick={() => setActive(d.id)}
              className="w-full flex items-center gap-1.5 transition-colors"
              style={{
                padding: isActive ? '5px 10px 5px 8px' : '5px 10px',
                fontFamily: "'JetBrains Mono'", fontSize: 11,
                background: isActive ? '#e5eeff' : 'transparent',
                color: isActive ? '#0058be' : '#44474c',
                borderLeft: isActive ? '2px solid #0058be' : '2px solid transparent',
                textAlign: 'left',
              }}
            >
              <span style={{ width: 6, height: 6, borderRadius: '50%', flexShrink: 0, background: isActive ? '#0058be' : '#c4c6cd' }} aria-hidden />
              <span style={{ opacity: !d.changed && !isActive ? 0.4 : 1 }}>{d.label}</span>
            </button>
          )
        })}
      </div>
      <div className="px-3 py-2 border-t border-outline-variant flex-shrink-0">
        <span className="text-on-surface-variant" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>{changedCount} changed of {TREE_DOCS.length}</span>
      </div>
    </aside>
  )
}

/* ─── Section header in current pane (with review controls) ─── */
function SectionHead({ title, id, decision, onDecide }: {
  title: string; id: string; decision?: Decision; onDecide?: (d: Decision) => void
}) {
  const hasControls = (CHANGED_SECTIONS as readonly string[]).includes(id)
  return (
    <div className="flex items-start justify-between gap-3 mb-3">
      <h2 className="text-primary font-semibold" style={{ fontFamily: 'Inter', fontSize: 18 }}>{title}</h2>
      {hasControls && onDecide && (
        <div className="flex-shrink-0 flex items-center gap-1.5 mt-0.5">
          {decision && (
            <span
              className="inline-flex items-center gap-1"
              style={{
                padding: '2px 8px', borderRadius: 9999, fontSize: 10, fontFamily: "'JetBrains Mono'", fontWeight: 600,
                background: decision === 'accepted' ? 'rgba(0,165,114,.1)' : '#fef2f2',
                color: decision === 'accepted' ? '#00a572' : '#ba1a1a',
                border: `1px solid ${decision === 'accepted' ? '#86efac' : '#fecaca'}`,
              }}
            >
              {decision === 'accepted' ? 'Accepted' : 'Declined'}
            </span>
          )}
          <button
            onClick={() => onDecide(decision === 'accepted' ? null : 'accepted')}
            className="flex items-center gap-1 px-2 py-0.5 rounded border border-outline-variant hover:bg-on-tertiary-container hover:text-white hover:border-on-tertiary-container text-on-surface-variant transition-colors"
            style={{ fontSize: 10, fontFamily: "'JetBrains Mono'" }}
          >
            <span className="material-symbols-outlined" style={{ fontSize: 11 }} aria-hidden>check</span>Accept
          </button>
          <button
            onClick={() => onDecide(decision === 'declined' ? null : 'declined')}
            className="flex items-center gap-1 px-2 py-0.5 rounded border border-outline-variant hover:bg-surface-container-high text-on-surface-variant transition-colors"
            style={{ fontSize: 10, fontFamily: "'JetBrains Mono'" }}
          >
            <span className="material-symbols-outlined" style={{ fontSize: 11 }} aria-hidden>remove</span>Decline
          </button>
          <button
            className="flex items-center gap-1 px-2 py-0.5 rounded border border-outline-variant hover:bg-surface-container text-on-surface-variant transition-colors"
            style={{ fontSize: 10, fontFamily: "'JetBrains Mono'" }}
          >
            <span className="material-symbols-outlined" style={{ fontSize: 11 }} aria-hidden>edit</span>Edit
          </button>
        </div>
      )}
    </div>
  )
}

const IFACE_ROWS = [
  ['IF_BrakeReq', 'Input', 'Target deceleration from VCU'],
  ['IF_WheelSpeed[4]', 'Input', 'Raw encoder pulse counts'],
  ['IF_ValveCmd', 'Output', 'PWM duty cycle for valves'],
]

function IntroProse() {
  return (
    <p className="text-on-surface leading-relaxed" style={{ fontSize: 14 }}>
      The <strong>Brake Controller</strong> unit implements the core logic for the Electronic Braking System (EBS).
      It processes wheel speed sensor data and driver brake requests to modulate hydraulic valve actuators
      via high-frequency PWM signals.
    </p>
  )
}

function IfaceTable({ side }: { side: 'current' | 'reference' }) {
  return (
    <div className="overflow-hidden border border-outline-variant rounded-lg">
      <table className="w-full text-left" style={{ fontSize: 12 }}>
        <thead className="bg-surface-container text-on-surface-variant">
          <tr>
            <th className="px-3 py-2.5 border-b border-outline-variant font-semibold">Interface ID</th>
            <th className="px-3 py-2.5 border-b border-outline-variant font-semibold">Dir</th>
            <th className="px-3 py-2.5 border-b border-outline-variant font-semibold">Description</th>
          </tr>
        </thead>
        <tbody>
          {IFACE_ROWS.map(([id, dir, desc]) => (
            <tr key={id} style={{ borderBottom: '1px solid rgba(196,198,205,.6)' }}>
              <td className="px-3 py-2 text-secondary" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>{id}</td>
              <td className="px-3 py-2 text-on-surface-variant">{dir}</td>
              <td className="px-3 py-2 text-on-surface-variant">{desc}</td>
            </tr>
          ))}
          {side === 'current' ? (
            <tr style={{ borderLeft: '3px solid #00a572', background: 'rgba(0,165,114,.06)' }}>
              <td className="px-3 py-2 text-secondary" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>IF_DiagStatus</td>
              <td className="px-3 py-2 text-on-surface-variant">Output</td>
              <td className="px-3 py-2 text-on-surface-variant">
                Diagnostic trouble code bitmask
                <span className="ml-1.5 px-1.5 py-0.5 rounded text-on-tertiary-container" style={{ background: 'rgba(0,165,114,.1)', fontFamily: "'JetBrains Mono'", fontSize: 11 }}>+ added</span>
              </td>
            </tr>
          ) : (
            <tr className="opacity-40" style={{ borderLeft: '3px solid #ba1a1a', background: 'rgba(186,26,26,.06)' }}>
              <td className="px-3 py-2 text-on-surface-variant line-through" colSpan={3} style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>— IF_DiagStatus not in this version</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function DynamicDesign({ cfg }: { cfg: string }) {
  return (
    <>
      <div className="mb-6">
        <h3 className="text-on-surface mb-2 uppercase" style={{ fontFamily: "'JetBrains Mono'", fontSize: 12, letterSpacing: '0.06em' }}>4.1 Control Flow Graphs</h3>
        <div className="rounded-lg p-4 flex flex-col items-center justify-center text-center gap-2 border border-secondary/20" style={{ borderLeft: '3px solid #0058be', background: '#eff4ff', paddingTop: 40, paddingBottom: 40 }}>
          <span className="material-symbols-outlined text-secondary" style={{ fontSize: 36 }} aria-hidden>account_tree</span>
          <p className="text-on-surface-variant" style={{ fontFamily: "'JetBrains Mono'", fontSize: 12 }}>{cfg}</p>
          <span className="px-2 py-0.5 rounded text-secondary bg-secondary/10" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>~ changed</span>
        </div>
      </div>
      <div>
        <h3 className="text-on-surface mb-2 uppercase" style={{ fontFamily: "'JetBrains Mono'", fontSize: 12, letterSpacing: '0.06em' }}>4.2 State Machine</h3>
        <div className="bg-surface-container-low border border-outline-variant rounded-lg flex flex-col items-center justify-center text-center gap-2" style={{ paddingTop: 40, paddingBottom: 40 }}>
          <span className="material-symbols-outlined text-outline-variant" style={{ fontSize: 36 }} aria-hidden>alt_route</span>
          <p className="text-on-surface-variant" style={{ fontFamily: "'JetBrains Mono'", fontSize: 12 }}>State machine · INIT → STANDBY → ACTIVE → FAULT</p>
        </div>
      </div>
    </>
  )
}

function StaticPlaceholder({ label }: { label: string }) {
  return (
    <div className="bg-surface-container-low border border-outline-variant rounded-lg flex flex-col items-center justify-center text-center gap-2" style={{ paddingTop: 40, paddingBottom: 40 }}>
      <span className="material-symbols-outlined text-outline-variant" style={{ fontSize: 36 }} aria-hidden>schema</span>
      <p className="text-on-surface-variant" style={{ fontFamily: "'JetBrains Mono'", fontSize: 12 }}>{label}</p>
    </div>
  )
}

/* ─── Document card (shared shell for both panes) ─── */
function DocCard({ hash, children }: { hash: string; children: React.ReactNode }) {
  return (
    <div className="max-w-2xl mx-auto px-5 py-6">
      <div className="bg-white rounded-xl border border-outline-variant overflow-hidden" style={{ boxShadow: '0 1px 4px rgba(4,22,39,.06)' }}>
        <div className="px-8 pt-8 pb-6 border-b border-outline-variant">
          <p className="text-on-surface-variant uppercase mb-1" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, letterSpacing: '0.1em' }}>{hash}</p>
          <h1 className="text-primary font-semibold" style={{ fontFamily: 'Inter', fontSize: 24 }}>Brake Controller</h1>
          <p className="text-on-surface-variant mt-0.5" style={{ fontSize: 12 }}>Software Detailed Design Specification</p>
        </div>
        <div className="px-8 py-8 space-y-10">{children}</div>
      </div>
    </div>
  )
}

export function ComparePage() {
  const [treeMode, setTreeMode] = useState<TreeMode>('diff')
  const [activeDoc, setActiveDoc] = useState('brake')
  const [decisions, setDecisions] = useState<Record<string, Decision>>({})

  const decide = (id: string, d: Decision) => setDecisions((p) => ({ ...p, [id]: d }))
  const resolved = CHANGED_SECTIONS.filter((id) => decisions[id]).length
  const total = CHANGED_SECTIONS.length

  return (
    <div className="flex h-full overflow-hidden">
      <DocTree mode={treeMode} setMode={setTreeMode} active={activeDoc} setActive={setActiveDoc} />

      {/* Compare area */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        <div className="flex-1 flex overflow-hidden">

          {/* Reference (left) */}
          <div className="flex-1 flex flex-col overflow-hidden border-r border-outline-variant min-w-0">
            <div className="flex-shrink-0 px-4 py-2 bg-white border-b border-outline-variant flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-outline-variant flex-shrink-0" aria-hidden />
              <span className="text-on-surface" style={{ fontFamily: "'JetBrains Mono'", fontSize: 12, fontWeight: 500 }}>Reference</span>
              <span className="px-2 py-0.5 rounded bg-surface-container text-on-surface-variant border border-outline-variant uppercase" style={{ fontFamily: "'JetBrains Mono'", fontSize: 9, fontWeight: 700 }}>a3f9c12</span>
              <div className="flex items-center gap-2 ml-auto">
                <span className="flex items-center gap-1 text-on-tertiary-container" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>
                  <span className="w-1.5 h-1.5 rounded-sm bg-on-tertiary-container inline-block" aria-hidden />1 added
                </span>
                <span className="flex items-center gap-1 text-secondary" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>
                  <span className="w-1.5 h-1.5 rounded-sm bg-secondary inline-block" aria-hidden />1 changed
                </span>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto bg-surface-container-low">
              <DocCard hash="a3f9c12">
                <section><h2 className="text-primary font-semibold mb-3" style={{ fontFamily: 'Inter', fontSize: 18 }}>1. Introduction</h2><IntroProse /></section>
                <section><h2 className="text-primary font-semibold mb-3" style={{ fontFamily: 'Inter', fontSize: 18 }}>2. Interfaces</h2><IfaceTable side="reference" /></section>
                <section><h2 className="text-primary font-semibold mb-3" style={{ fontFamily: 'Inter', fontSize: 18 }}>3. Static Design</h2><StaticPlaceholder label="Include dependency diagram" /></section>
                <section><h2 className="text-primary font-semibold mb-3" style={{ fontFamily: 'Inter', fontSize: 18 }}>4. Dynamic Design</h2><DynamicDesign cfg="CFG · 3 functions · 42 nodes" /></section>
              </DocCard>
            </div>
          </div>

          {/* Current (right) */}
          <div className="flex-1 flex flex-col overflow-hidden min-w-0">
            <div className="flex-shrink-0 px-4 py-2 bg-white border-b border-outline-variant flex items-center gap-2">
              <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: '#00a572' }} aria-hidden />
              <span className="text-on-surface" style={{ fontFamily: "'JetBrains Mono'", fontSize: 12, fontWeight: 500 }}>Current</span>
              <span className="px-2 py-0.5 rounded uppercase" style={{ fontFamily: "'JetBrains Mono'", fontSize: 9, fontWeight: 700, background: '#00a572', color: '#fff' }}>Latest</span>
              <span className="text-on-surface-variant" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>main @ b2e8d45</span>
              <span className="ml-auto flex items-center gap-0.5" style={{ padding: '2px 6px', borderRadius: 4, fontSize: 10, fontFamily: "'JetBrains Mono'", background: '#fff8e6', color: '#b45309', border: '1px solid #f59e0b' }}>
                <span className="material-symbols-outlined" style={{ fontSize: 10 }} aria-hidden>rate_review</span>In Review
              </span>
            </div>
            <div className="flex-1 overflow-y-auto bg-surface-container-low">
              <DocCard hash="b2e8d45">
                <section><SectionHead title="1. Introduction" id="c-intro" /><IntroProse /></section>
                <section><SectionHead title="2. Interfaces" id="c-interfaces" decision={decisions['c-interfaces'] ?? null} onDecide={(d) => decide('c-interfaces', d)} /><IfaceTable side="current" /></section>
                <section><SectionHead title="3. Static Design" id="c-static" /><StaticPlaceholder label="Include dependency diagram" /></section>
                <section><SectionHead title="4. Dynamic Design" id="c-dynamic" decision={decisions['c-dynamic'] ?? null} onDecide={(d) => decide('c-dynamic', d)} /><DynamicDesign cfg="CFG · 4 functions · 51 nodes" /></section>
              </DocCard>
            </div>
          </div>
        </div>

        {/* Review footer */}
        <footer className="flex-shrink-0 border-t border-outline-variant bg-white px-5 py-2.5 flex items-center justify-between" style={{ minHeight: 44 }}>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1" role="progressbar" aria-valuenow={resolved} aria-valuemax={total} aria-label={`${resolved} of ${total} changes resolved`}>
              {CHANGED_SECTIONS.map((id) => {
                const d = decisions[id]
                return (
                  <div key={id} className="w-3 h-3 rounded-full transition-colors"
                    style={{ background: d === 'accepted' ? '#00a572' : d === 'declined' ? '#ba1a1a' : '#c4c6cd' }} />
                )
              })}
            </div>
            <span className="text-on-surface-variant" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>{resolved}/{total} changes resolved</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              className="flex items-center gap-1.5 px-3 py-1.5 border border-outline-variant rounded-lg hover:bg-surface-container-low transition-colors text-on-surface"
              style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 500 }}
            >
              Submit Review
            </button>
            <button
              disabled={resolved < total}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-secondary hover:bg-secondary-container text-on-secondary rounded-lg transition-colors disabled:opacity-50"
              style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 700, letterSpacing: '0.04em' }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>check</span>
              Approve Document
            </button>
          </div>
        </footer>
      </div>
    </div>
  )
}
