import type { ReactNode } from 'react'
import { useDownloadProjectConfig } from '../../../hooks/useProjects'
import { Icon, RoleBadge, Text } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import type { Project, TeamMember } from '../../../types'

/* ─── Team member row ─── */
export function TeamRow({ member }: { member: TeamMember }) {
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 hover:bg-surface-container-low transition-colors">
      <div
        className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0"
        // eslint-disable-next-line no-restricted-syntax -- avatar colours are data-driven
        style={{ background: member.avatarColor, color: member.avatarTextColor }}
        aria-hidden
      >
        <span className="font-sans text-label font-bold">{member.initials}</span>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-on-surface truncate font-mono text-xs font-medium">{member.name}</p>
      </div>
      <RoleBadge role={member.role} />
    </div>
  )
}

/* ─── Config info row ─── */
function InfoRow({ label, value, mono }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-start gap-4 px-5 py-3">
      <span className="flex-shrink-0 text-on-surface-variant uppercase w-[116px] font-mono text-label font-medium tracking-[0.07em] pt-0.5">
        {label}
      </span>
      <span className={cn('flex-1 min-w-0 text-on-surface text-body break-words', mono && 'font-mono')}>
        {value}
      </span>
    </div>
  )
}

/* ─── Project configuration overview (shown before any analysis run) ─── */
export function ConfigOverview({ project, team, teamLoading }: { project: Project; team?: TeamMember[]; teamLoading: boolean }) {
  const layers = project.architectureLayers
  const groupCount = layers.reduce((a, l) => a + l.groups.length, 0)
  const compCount = layers.reduce((a, l) => a + l.groups.reduce((b, g) => b + g.components.length, 0), 0)
  const cores = project.buildConfig.cores
  const plural = (n: number, w: string) => `${n} ${w}${n !== 1 ? 's' : ''}`
  const downloadConfig = useDownloadProjectConfig(project.id)
  return (
    <div className="flex gap-6 items-stretch">
      {/* Left — configuration + architecture */}
      <div className="flex-1 min-w-0 flex flex-col gap-4">
        <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
          <div className="px-5 py-3.5 border-b border-outline-variant flex items-start justify-between gap-3">
            <div>
              <Text as="h2" variant="heading" className="text-on-surface">Project Configuration</Text>
              <Text as="p" variant="caption" className="font-mono mt-0.5">Captured at setup · analysis not run yet</Text>
            </div>
            <button
              onClick={() => { void downloadConfig(project.name) }}
              title="The project as a config file — the command line and the New Project wizard read it"
              className="flex items-center gap-1 px-3 py-1.5 border border-outline-variant rounded-lg hover:bg-surface-container transition-colors text-secondary font-mono text-caption flex-shrink-0"
            >
              <Icon name="download" size={14} />Download config
            </button>
          </div>
          <div className="divide-y divide-outline-variant">
            <InfoRow label="Repository" mono value={project.repoPath || '—'} />
            <InfoRow label="Branch" mono value={project.defaultBranch || '—'} />
            <InfoRow label="Standard" value={project.standard || '—'} />
            {project.client && <InfoRow label="Client" value={project.client} />}
            <InfoRow
              label="Cores"
              value={cores.length ? (
                <div className="space-y-1.5">
                  {cores.map((c) => (
                    <div key={c.name}>
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <Icon name="memory" size={14} className="text-secondary" />
                        <span className="font-mono text-xs font-semibold">{c.name}</span>
                        <span className={cn('font-mono text-label', c.layers.length ? 'text-on-surface-variant' : 'text-[#b45309]')}>
                          {c.layers.length ? `used by ${c.layers.join(', ')}` : 'no layer uses it'}
                        </span>
                      </div>
                      <div className="ml-5 text-on-surface-variant font-mono text-label">
                        {[c.macros ?? 'no macros', c.dataDictionary ?? 'no dictionary', c.compileCommands ?? 'no compile commands'].join(' · ')}
                      </div>
                    </div>
                  ))}
                </div>
              ) : 'None: every layer is parsed without macros or a data dictionary'}
            />
          </div>
        </div>

        <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
          <div className="px-5 py-3.5 border-b border-outline-variant flex items-center justify-between">
            <Text as="h2" variant="heading" className="text-on-surface">Architecture</Text>
            <Text variant="caption" className="font-mono">
              {plural(layers.length, 'layer')} · {plural(groupCount, 'group')} · {plural(compCount, 'component')}
            </Text>
          </div>
          {layers.length === 0 ? (
            <p className="px-5 py-5 text-on-surface-variant text-xs">No architecture mapped during setup.</p>
          ) : (
            <div className="divide-y divide-outline-variant">
              {layers.map((layer, li) => (
                <div key={li} className="px-5 py-3">
                  <div className="flex items-center gap-2">
                    <Icon name="layers" size={15} className="text-secondary" />
                    <span className="text-on-surface font-mono text-xs font-bold">{layer.name}</span>
                    {layer.path && <span className="text-on-surface-variant font-mono text-label">{layer.path}</span>}
                    {layer.core && (
                      <span className="ml-auto flex items-center gap-1 text-secondary font-mono text-label" title="The core this layer is built for">
                        <Icon name="memory" size={12} />{layer.core}
                      </span>
                    )}
                  </div>
                  {layer.groups.length === 0 ? (
                    <p className="text-on-surface-variant ml-[23px] mt-0.5 font-mono text-caption">No groups</p>
                  ) : layer.groups.map((g, gi) => (
                    <div key={gi} className="ml-[23px] mt-1">
                      <div className="flex items-center gap-1.5">
                        <Icon name="folder_open" size={13} className="text-secondary" />
                        <span className="text-on-surface font-mono text-caption font-semibold">{g.name}</span>
                        <span className="text-on-surface-variant font-mono text-label">{plural(g.components.length, 'comp')}</span>
                      </div>
                      {g.components.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 ml-5 mt-[3px]">
                          {g.components.map((c, ci) => (
                            <span key={ci} className="font-mono text-label bg-surface-container text-secondary px-[7px] py-0.5 rounded-lg">
                              {c.name}{c.files && c.files.length > 0 ? ` · ${c.files.length}` : ''}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Right — team */}
      <div className="w-[300px] flex-shrink-0">
        <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
          <div className="px-4 py-3.5 border-b border-outline-variant">
            <Text as="h2" variant="heading" className="text-on-surface">Team</Text>
            <Text as="p" variant="caption" className="font-mono mt-0.5">{plural(team?.length ?? 0, 'member')}</Text>
          </div>
          {teamLoading ? (
            <div className="divide-y divide-outline-variant">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="flex items-center gap-3 px-4 py-2.5">
                  <div className="w-7 h-7 rounded-full bg-surface-container animate-pulse flex-shrink-0" />
                  <div className="flex-1 h-3 bg-surface-container animate-pulse rounded" />
                </div>
              ))}
            </div>
          ) : team && team.length > 0 ? (
            <div className="divide-y divide-outline-variant">
              {team.map((m) => <TeamRow key={m.id} member={m} />)}
            </div>
          ) : (
            <p className="px-4 py-4 text-on-surface-variant text-xs">No members yet.</p>
          )}
        </div>
      </div>
    </div>
  )
}
