import type { ReactNode } from 'react'
import { Button, Checkbox, Icon, Select } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import type { PageFilters } from '../helpers'

/* One row, every control 40 px like the Select: Project and Version by name, Show (all, or warnings and errors; Debug adds the busy
   debug lines), Source, then the client controls — Search (the loaded lines only), Follow, Clear.
   The server filters reload the tail and open a new stream; the client ones only redraw. */

const ALL = 'all'   // a Radix select item cannot carry ''

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="font-mono text-label font-semibold uppercase tracking-[0.06em] text-outline">{label}</span>
      {children}
    </div>
  )
}

function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex h-10 border border-outline-variant rounded-xl overflow-hidden bg-surface-container-lowest">
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}
          className={cn('px-3 text-body whitespace-nowrap border-r border-outline-variant last:border-r-0',
            value === o.value ? 'bg-tint text-secondary font-semibold' : 'text-on-surface-variant hover:text-on-surface')}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function LogFilters({ filters, onChange, projects, versions, query, onQuery, follow, onFollow, onClear }: {
  filters: PageFilters
  onChange: (next: Partial<PageFilters>) => void
  projects: { value: string; label: string }[]
  versions: { value: string; label: string }[]
  query: string
  onQuery: (q: string) => void
  follow: boolean
  onFollow: (on: boolean) => void
  onClear: () => void
}) {
  return (
    <div className="flex flex-wrap items-end gap-3">
      <Field label="Project">
        <Select className="w-52" value={filters.project ?? ALL}
          options={[{ value: ALL, label: 'All projects' }, ...projects]}
          onValueChange={(v) => onChange({ project: v === ALL ? undefined : v, version: undefined, job: undefined })} />
      </Field>
      <Field label="Version">
        <Select className="w-36" value={filters.version ?? ALL} disabled={!filters.project}
          options={[{ value: ALL, label: filters.project ? 'All versions' : 'Pick a project' }, ...versions]}
          onValueChange={(v) => onChange({ version: v === ALL ? undefined : v, job: undefined })} />
      </Field>
      <Field label="Show">
        <div className="flex items-center gap-3 h-10">
          <Segmented label="Show" value={filters.show} onChange={(show) => onChange({ show })}
            options={[{ value: 'all', label: 'All' }, { value: 'warn', label: 'Warnings & errors' }]} />
          <Checkbox label="Debug" checked={filters.debug && filters.show === 'all'} disabled={filters.show === 'warn'}
            onCheckedChange={(v) => onChange({ debug: v === true })} />
        </div>
      </Field>
      <Field label="Source">
        <Segmented label="Source" value={filters.source ?? ALL}
          onChange={(v) => onChange({ source: v === ALL ? undefined : (v as 'server' | 'engine') })}
          options={[{ value: ALL, label: 'All' }, { value: 'server', label: 'API' }, { value: 'engine', label: 'Engine' }]} />
      </Field>
      <Field label="Search">
        <label className="relative">
          <Icon name="search" size={16} className="absolute left-2.5 top-3 text-outline" />
          <input type="search" value={query} onChange={(e) => onQuery(e.target.value)} placeholder="Search the loaded lines"
            aria-label="Search the loaded lines"
            className="h-10 w-56 pl-8 pr-2.5 border border-outline-variant rounded-xl bg-surface-container-lowest text-body text-on-surface placeholder:text-outline focus:outline-2 focus:outline-secondary" />
        </label>
      </Field>
      <div className="flex items-center gap-4 ml-auto h-10">
        <button type="button" role="switch" aria-checked={follow} onClick={() => onFollow(!follow)}
          title="Stay at the newest line" className="inline-flex items-center gap-2 text-body text-on-surface-variant">
          <span className={cn('relative w-[30px] h-[18px] rounded-full transition-colors', follow ? 'bg-secondary' : 'bg-outline-variant')}>
            <span className={cn('absolute top-0.5 left-0.5 w-3.5 h-3.5 rounded-full bg-white transition-transform', follow && 'translate-x-3')} />
          </span>
          Follow
        </button>
        <Button variant="outline" size="md" className="h-10 rounded-xl" onClick={onClear} title="Empty the list; new lines keep arriving">
          <Icon name="clear_all" size={16} />Clear
        </Button>
      </div>
    </div>
  )
}
