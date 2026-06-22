import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

const STEPS = [
  { label: 'Project & Repo', icon: 'folder_open' },
  { label: 'Build Config', icon: 'build' },
  { label: 'Architecture', icon: 'account_tree' },
  { label: 'Team & Access', icon: 'group' },
  { label: 'Review & Init', icon: 'checklist' },
]

export function ProjectsEmptyPage() {
  const [step, setStep] = useState(0)
  const navigate = useNavigate()

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* Topbar */}
      <header className="h-14 flex-shrink-0 flex items-center justify-between px-6 bg-white border-b border-outline-variant z-40">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-secondary flex items-center justify-center flex-shrink-0" style={{ borderRadius: 8 }}>
            <span className="material-symbols-outlined sym-fill text-on-primary" style={{ fontSize: 18 }}>account_tree</span>
          </div>
          <h1 className="text-primary font-bold tracking-tight" style={{ fontFamily: 'Inter', fontSize: 15 }}>[PRODUCT NAME]</h1>
        </div>
        <button onClick={() => navigate('/projects')} className="flex items-center gap-1.5 text-sm text-on-surface-variant hover:text-on-surface transition-colors">
          <span className="material-symbols-outlined" style={{ fontSize: 18 }}>arrow_back</span>
          Back to Projects
        </button>
      </header>

      <div className="flex-1 overflow-hidden flex">
        {/* Left step rail */}
        <div className="w-64 flex-shrink-0 border-r border-outline-variant bg-surface-container-lowest p-6">
          <h2 className="text-xs font-semibold text-on-surface-variant uppercase tracking-[0.08em] mb-5">New Project</h2>
          <div className="space-y-1">
            {STEPS.map((s, i) => {
              const done = i < step
              const active = i === step
              return (
                <button
                  key={i}
                  onClick={() => i <= step && setStep(i)}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors ${
                    active ? 'bg-secondary/10 text-secondary' : done ? 'text-on-tertiary-container hover:bg-surface-container-low' : 'text-on-surface-variant'
                  }`}
                >
                  <div className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 text-xs font-bold ${
                    done ? 'bg-on-tertiary-container text-white' : active ? 'bg-secondary text-on-secondary' : 'bg-surface-container border border-outline-variant text-on-surface-variant'
                  }`}>
                    {done ? <span className="material-symbols-outlined" style={{ fontSize: 14 }}>check</span> : i + 1}
                  </div>
                  <span className="text-sm font-medium">{s.label}</span>
                </button>
              )
            })}
          </div>
        </div>

        {/* Main content */}
        <div className="flex-1 overflow-y-auto">
          <div className="px-10 py-8 max-w-2xl">
            <div className="mb-8">
              <p className="font-mono text-[11px] text-secondary uppercase tracking-[0.12em] mb-2">Step {step + 1} of {STEPS.length}</p>
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
                      <span className="material-symbols-outlined" style={{ fontSize: 16 }}>folder_open</span>
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
                        <span className="material-symbols-outlined" style={{ fontSize: 14 }}>upload</span>
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
                    <div className="flex items-center gap-3 px-3 py-2 bg-surface-container rounded-lg text-sm text-on-surface">
                      <span className="material-symbols-outlined text-secondary" style={{ fontSize: 16 }}>folder</span>
                      Sample / Core
                    </div>
                    <div className="flex items-center gap-3 px-3 py-2 bg-surface-container rounded-lg text-sm text-on-surface">
                      <span className="material-symbols-outlined text-secondary" style={{ fontSize: 16 }}>folder</span>
                      Sample / Lib
                    </div>
                    <button className="flex items-center gap-2 px-3 py-2 text-xs text-secondary hover:bg-surface-container-low rounded-lg transition-colors w-full">
                      <span className="material-symbols-outlined" style={{ fontSize: 14 }}>add</span>
                      Add Component
                    </button>
                  </div>
                </div>
                <button className="flex items-center gap-2 px-4 py-2 border border-dashed border-outline-variant rounded-xl text-sm text-on-surface-variant hover:bg-surface-container-low transition-colors w-full justify-center">
                  <span className="material-symbols-outlined" style={{ fontSize: 16 }}>add</span>
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
                  <div className="flex items-center justify-between px-4 py-2.5 bg-surface-container-low border-b border-outline-variant">
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
                    <span style={{ fontFamily: 'JetBrains Mono', fontSize: 9, fontWeight: 700, background: '#e5eeff', color: '#0058be', padding: '2px 8px', borderRadius: 99 }}>ADMIN</span>
                  </div>
                </div>
              </div>
            )}

            {step === 4 && (
              <div className="space-y-4">
                <div className="border border-outline-variant rounded-xl p-5 bg-surface-container-lowest space-y-3">
                  {[
                    { label: 'Project Name', value: 'VCU Engine Firmware' },
                    { label: 'Standard', value: 'ASPICE L3' },
                    { label: 'Repository', value: '/projects/vcu-firmware' },
                    { label: 'Layers', value: '1 layer · 2 groups · 3 components' },
                    { label: 'Team', value: '1 member (Admin)' },
                  ].map(row => (
                    <div key={row.label} className="flex items-center justify-between py-2 border-b border-outline-variant last:border-0">
                      <span className="text-xs text-on-surface-variant font-mono uppercase tracking-[0.06em]">{row.label}</span>
                      <span className="text-sm text-on-surface font-medium">{row.value}</span>
                    </div>
                  ))}
                </div>
                <div className="flex items-start gap-3 p-4 bg-secondary/5 border border-secondary/20 rounded-xl">
                  <span className="material-symbols-outlined text-secondary" style={{ fontSize: 18 }}>info</span>
                  <p className="text-xs text-on-surface-variant">Initializing will run Phase 1 (C++ parse) and Phase 2 (model derivation). This may take several minutes for large codebases.</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Action bar */}
      <div className="h-16 flex-shrink-0 border-t border-outline-variant bg-white flex items-center justify-between px-10">
        <button
          onClick={() => step > 0 ? setStep(step - 1) : navigate('/projects')}
          className="flex items-center gap-1.5 px-4 h-9 border border-outline-variant rounded-lg text-sm text-on-surface hover:bg-surface-container transition-colors"
        >
          <span className="material-symbols-outlined" style={{ fontSize: 16 }}>arrow_back</span>
          {step === 0 ? 'Cancel' : 'Back'}
        </button>
        <button
          onClick={() => step < STEPS.length - 1 ? setStep(step + 1) : navigate('/projects/vcu-engine/overview')}
          className="flex items-center gap-1.5 px-5 h-9 bg-secondary text-on-secondary rounded-lg text-sm font-semibold hover:bg-secondary-container transition-colors"
        >
          {step < STEPS.length - 1 ? 'Continue' : 'Initialize Project'}
          <span className="material-symbols-outlined" style={{ fontSize: 16 }}>{step < STEPS.length - 1 ? 'arrow_forward' : 'rocket_launch'}</span>
        </button>
      </div>
    </div>
  )
}
