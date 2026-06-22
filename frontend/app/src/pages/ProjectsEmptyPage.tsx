import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

type View = 'empty' | 'wizard'

const STEPS = [
  { label: 'Project & Repo', icon: 'folder_open' },
  { label: 'Build Config',   icon: 'build' },
  { label: 'Architecture',   icon: 'account_tree' },
  { label: 'Team & Access',  icon: 'group' },
  { label: 'Review & Init',  icon: 'checklist' },
]

/* ─── Shared header ─────────────────────────────────────────────────── */
function PageHeader({ onBack, backLabel }: { onBack: () => void; backLabel: string }) {
  return (
    <header className="h-14 flex-shrink-0 flex items-center justify-between px-6 bg-white border-b border-outline-variant z-40">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 bg-secondary rounded-lg flex items-center justify-center flex-shrink-0">
          <span className="material-symbols-outlined sym-fill text-white" style={{ fontSize: 18 }} aria-hidden>account_tree</span>
        </div>
        <div>
          <h1 className="text-primary font-bold tracking-tight" style={{ fontFamily: 'Inter', fontSize: 15, lineHeight: 1.2 }}>[PRODUCT NAME]</h1>
          <p className="text-on-surface-variant uppercase mt-0.5" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 500, letterSpacing: '0.08em' }}>Automotive Tier 1</p>
        </div>
      </div>
      <button
        onClick={onBack}
        className="flex items-center gap-1.5 text-sm text-on-surface-variant hover:text-on-surface transition-colors"
      >
        <span className="material-symbols-outlined" style={{ fontSize: 18 }} aria-hidden>arrow_back</span>
        {backLabel}
      </button>
    </header>
  )
}

/* ─── Empty state ───────────────────────────────────────────────────── */
function EmptyView({ onNewProject }: { onNewProject: () => void }) {
  return (
    <div className="flex-1 flex items-center justify-center">
      <div className="text-center" style={{ maxWidth: 520 }}>
        {/* Icon */}
        <div className="w-16 h-16 rounded-2xl bg-secondary-container flex items-center justify-center mx-auto mb-6">
          <span className="material-symbols-outlined sym-fill text-secondary" style={{ fontSize: 32 }} aria-hidden>folder_open</span>
        </div>

        <h2 className="text-on-surface mb-2" style={{ fontSize: 22, fontWeight: 600, letterSpacing: '-0.01em' }}>
          No projects yet
        </h2>
        <p className="text-on-surface-variant mb-8" style={{ fontSize: 14, lineHeight: 1.6 }}>
          Create a new project to start generating compliance documentation, or request access to an existing workspace.
        </p>

        {/* Choice cards */}
        <div className="grid grid-cols-2 gap-4">
          {/* New Project */}
          <button
            onClick={onNewProject}
            className="group flex flex-col items-center gap-3 p-6 bg-white border-2 border-secondary rounded-xl hover:bg-secondary/5 transition-colors text-left"
          >
            <div className="w-10 h-10 rounded-xl bg-secondary flex items-center justify-center">
              <span className="material-symbols-outlined text-white" style={{ fontSize: 20 }} aria-hidden>add</span>
            </div>
            <div>
              <p className="font-semibold text-on-surface mb-1" style={{ fontSize: 14 }}>New Project</p>
              <p className="text-on-surface-variant" style={{ fontSize: 12, lineHeight: 1.5 }}>
                Connect a C++ repository and generate your first compliance artifacts.
              </p>
            </div>
            <span className="mt-auto flex items-center gap-1 text-secondary text-xs font-semibold">
              Get started
              <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>arrow_forward</span>
            </span>
          </button>

          {/* Request Access */}
          <button
            className="group flex flex-col items-center gap-3 p-6 bg-white border border-outline-variant rounded-xl hover:bg-surface-container-low transition-colors text-left"
          >
            <div className="w-10 h-10 rounded-xl bg-surface-container flex items-center justify-center">
              <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 20 }} aria-hidden>lock</span>
            </div>
            <div>
              <p className="font-semibold text-on-surface mb-1" style={{ fontSize: 14 }}>Request Access</p>
              <p className="text-on-surface-variant" style={{ fontSize: 12, lineHeight: 1.5 }}>
                Ask an admin to add you to an existing project workspace.
              </p>
            </div>
            <span className="mt-auto flex items-center gap-1 text-on-surface-variant text-xs font-semibold">
              Send request
              <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>arrow_forward</span>
            </span>
          </button>
        </div>
      </div>
    </div>
  )
}

/* ─── Wizard ────────────────────────────────────────────────────────── */
function WizardView({ onCancel, onComplete }: { onCancel: () => void; onComplete: () => void }) {
  const [step, setStep] = useState(0)

  return (
    <div className="flex-1 overflow-hidden flex">
      {/* Step rail */}
      <div className="w-64 flex-shrink-0 border-r border-outline-variant bg-surface-container-lowest p-6">
        <h2 className="text-xs font-semibold text-on-surface-variant uppercase tracking-[0.08em] mb-5">New Project</h2>
        <div className="space-y-1">
          {STEPS.map((s, i) => {
            const done   = i < step
            const active = i === step
            return (
              <button
                key={i}
                onClick={() => i <= step && setStep(i)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors ${
                  active ? 'bg-secondary/10 text-secondary' : done ? 'text-on-tertiary-container hover:bg-surface-container-low' : 'text-on-surface-variant'
                }`}
              >
                <div
                  className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 text-xs font-bold ${
                    done  ? 'bg-on-tertiary-container text-white'
                    : active ? 'bg-secondary text-on-secondary'
                    : 'bg-surface-container border border-outline-variant text-on-surface-variant'
                  }`}
                >
                  {done
                    ? <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>check</span>
                    : i + 1
                  }
                </div>
                <span className="text-sm font-medium">{s.label}</span>
              </button>
            )
          })}
        </div>
      </div>

      {/* Step content */}
      <div className="flex-1 overflow-y-auto">
        <div className="px-10 py-8 max-w-2xl">
          <div className="mb-8">
            <p className="font-mono text-[11px] text-secondary uppercase tracking-[0.12em] mb-2">
              Step {step + 1} of {STEPS.length}
            </p>
            <h2 className="text-2xl font-semibold text-on-surface">{STEPS[step].label}</h2>
          </div>

          {step === 0 && (
            <div className="space-y-5">
              <div>
                <label className="block font-mono text-[11px] text-on-surface-variant uppercase tracking-[0.08em] mb-1.5">Project Name</label>
                <input type="text" placeholder="e.g. VCU Engine Firmware" className="w-full h-11 px-3 border border-outline-variant rounded-xl text-sm text-on-surface bg-white focus:outline-none focus:border-secondary" />
              </div>
              <div>
                <label className="block font-mono text-[11px] text-on-surface-variant uppercase tracking-[0.08em] mb-1.5">Standard</label>
                <select className="w-full h-11 px-3 border border-outline-variant rounded-xl text-sm text-on-surface bg-white focus:outline-none">
                  <option>ASPICE L2</option>
                  <option>ASPICE L3</option>
                  <option>ISO 26262 ASIL-A</option>
                  <option>ISO 26262 ASIL-B</option>
                </select>
              </div>
              <div>
                <label className="block font-mono text-[11px] text-on-surface-variant uppercase tracking-[0.08em] mb-1.5">Repository Path</label>
                <div className="flex gap-2">
                  <input type="text" placeholder="/path/to/project" className="flex-1 h-11 px-3 border border-outline-variant rounded-xl text-sm text-on-surface bg-white focus:outline-none focus:border-secondary" />
                  <button className="flex items-center gap-1.5 px-4 h-11 border border-outline-variant rounded-xl text-sm text-on-surface-variant hover:bg-surface-container transition-colors">
                    <span className="material-symbols-outlined" style={{ fontSize: 16 }} aria-hidden>folder_open</span>
                    Browse
                  </button>
                </div>
              </div>
            </div>
          )}

          {step === 1 && (
            <div className="space-y-5">
              <div>
                <label className="block font-mono text-[11px] text-on-surface-variant uppercase tracking-[0.08em] mb-1.5">LLVM Library Path</label>
                <input type="text" placeholder="C:\Program Files\LLVM\bin\libclang.dll" className="w-full h-11 px-3 border border-outline-variant rounded-xl text-sm font-mono text-on-surface bg-white focus:outline-none focus:border-secondary" />
              </div>
              <div>
                <label className="block font-mono text-[11px] text-on-surface-variant uppercase tracking-[0.08em] mb-2">Preprocessor Definitions</label>
                <div className="border border-outline-variant rounded-xl p-4 bg-surface-container-low">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs text-on-surface-variant">Upload Makefile or CSV</span>
                    <button className="flex items-center gap-1 px-3 h-8 border border-outline-variant rounded-lg text-xs text-on-surface hover:bg-surface-container transition-colors">
                      <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>upload</span>
                      Upload
                    </button>
                  </div>
                  <p className="text-xs text-on-surface-variant">2-column CSV: Name, Value — or drag a Makefile to extract -D flags automatically.</p>
                </div>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <p className="text-sm text-on-surface-variant">Define your layers → groups → components architecture.</p>
              <div className="border border-outline-variant rounded-xl overflow-hidden">
                <div className="flex items-center justify-between px-4 py-3 bg-surface-container-low border-b border-outline-variant">
                  <span className="text-xs font-semibold text-on-surface">Layer 1</span>
                  <button className="text-xs text-secondary hover:underline">+ Add Group</button>
                </div>
                <div className="p-4 space-y-2">
                  {['Sample / Core', 'Sample / Lib'].map((c) => (
                    <div key={c} className="flex items-center gap-3 px-3 py-2 bg-surface-container rounded-lg text-sm text-on-surface">
                      <span className="material-symbols-outlined text-secondary" style={{ fontSize: 16 }} aria-hidden>folder</span>
                      {c}
                    </div>
                  ))}
                  <button className="flex items-center gap-2 px-3 py-2 text-xs text-secondary hover:bg-surface-container-low rounded-lg transition-colors w-full">
                    <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>add</span>
                    Add Component
                  </button>
                </div>
              </div>
              <button className="flex items-center gap-2 px-4 py-2 border border-dashed border-outline-variant rounded-xl text-sm text-on-surface-variant hover:bg-surface-container-low transition-colors w-full justify-center">
                <span className="material-symbols-outlined" style={{ fontSize: 16 }} aria-hidden>add</span>
                Add Layer
              </button>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-4">
              <div>
                <label className="block font-mono text-[11px] text-on-surface-variant uppercase tracking-[0.08em] mb-1.5">Invite Team Members</label>
                <div className="flex gap-2">
                  <input type="email" placeholder="colleague@company.com" className="flex-1 h-11 px-3 border border-outline-variant rounded-xl text-sm text-on-surface bg-white focus:outline-none focus:border-secondary" />
                  <select className="h-11 px-3 border border-outline-variant rounded-xl text-sm text-on-surface bg-white focus:outline-none">
                    <option>Developer</option>
                    <option>Admin</option>
                  </select>
                  <button className="px-4 h-11 bg-secondary text-on-secondary rounded-xl text-sm font-semibold hover:bg-secondary-container transition-colors">Invite</button>
                </div>
              </div>
              <div className="border border-outline-variant rounded-xl overflow-hidden">
                <div className="px-4 py-2.5 bg-surface-container-low border-b border-outline-variant">
                  <span className="text-xs font-mono text-on-surface-variant uppercase tracking-[0.06em]">Team (1)</span>
                </div>
                <div className="px-4 py-3 flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-secondary flex items-center justify-center">
                    <span className="text-on-secondary font-bold text-xs">MS</span>
                  </div>
                  <div className="flex-1">
                    <p className="text-sm font-medium text-on-surface">Manoj Sarkar</p>
                    <p className="text-xs text-on-surface-variant">manoj@example.com</p>
                  </div>
                  <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 9, fontWeight: 700, background: '#e5eeff', color: '#0058be', padding: '2px 8px', borderRadius: 99 }}>ADMIN</span>
                </div>
              </div>
            </div>
          )}

          {step === 4 && (
            <div className="space-y-4">
              <div className="border border-outline-variant rounded-xl p-5 bg-surface-container-lowest space-y-3">
                {[
                  { label: 'Project Name', value: 'VCU Engine Firmware' },
                  { label: 'Standard',     value: 'ASPICE L3' },
                  { label: 'Repository',   value: '/projects/vcu-firmware' },
                  { label: 'Layers',       value: '1 layer · 2 groups · 3 components' },
                  { label: 'Team',         value: '1 member (Admin)' },
                ].map((row) => (
                  <div key={row.label} className="flex items-center justify-between py-2 border-b border-outline-variant last:border-0">
                    <span className="text-xs text-on-surface-variant font-mono uppercase tracking-[0.06em]">{row.label}</span>
                    <span className="text-sm text-on-surface font-medium">{row.value}</span>
                  </div>
                ))}
              </div>
              <div className="flex items-start gap-3 p-4 bg-secondary/5 border border-secondary/20 rounded-xl">
                <span className="material-symbols-outlined text-secondary" style={{ fontSize: 18 }} aria-hidden>info</span>
                <p className="text-xs text-on-surface-variant">Initializing will run Phase 1 (C++ parse) and Phase 2 (model derivation). This may take several minutes for large codebases.</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Action bar */}
      <div className="absolute bottom-0 left-64 right-0 h-16 border-t border-outline-variant bg-white flex items-center justify-between px-10">
        <button
          onClick={() => step > 0 ? setStep(step - 1) : onCancel()}
          className="flex items-center gap-1.5 px-4 h-9 border border-outline-variant rounded-lg text-sm text-on-surface hover:bg-surface-container transition-colors"
        >
          <span className="material-symbols-outlined" style={{ fontSize: 16 }} aria-hidden>arrow_back</span>
          {step === 0 ? 'Cancel' : 'Back'}
        </button>
        <button
          onClick={() => step < STEPS.length - 1 ? setStep(step + 1) : onComplete()}
          className="flex items-center gap-1.5 px-5 h-9 bg-secondary text-on-secondary rounded-lg text-sm font-semibold hover:bg-secondary-container transition-colors"
        >
          {step < STEPS.length - 1 ? 'Continue' : 'Initialize Project'}
          <span className="material-symbols-outlined" style={{ fontSize: 16 }} aria-hidden>
            {step < STEPS.length - 1 ? 'arrow_forward' : 'rocket_launch'}
          </span>
        </button>
      </div>
    </div>
  )
}

/* ─── Page ──────────────────────────────────────────────────────────── */
export function ProjectsEmptyPage() {
  const [view, setView] = useState<View>('empty')
  const navigate = useNavigate()

  return (
    <div className="h-screen flex flex-col overflow-hidden relative">
      {view === 'empty' ? (
        <>
          <PageHeader onBack={() => navigate('/projects')} backLabel="Back to Projects" />
          <EmptyView onNewProject={() => setView('wizard')} />
        </>
      ) : (
        <>
          <PageHeader onBack={() => setView('empty')} backLabel="Back" />
          <WizardView
            onCancel={() => setView('empty')}
            onComplete={() => navigate('/projects/vcu-engine/overview')}
          />
        </>
      )}
    </div>
  )
}
