import { Icon } from '../../../components/ui'
import type { DocMeta } from '../../../types'

/* ── Meta banner: pipeline/model availability + model counts ── */
export function MetaBanner({ meta }: { meta: DocMeta }) {
  const stats: [string, number][] = [
    ['Units', meta.unitsTotal],
    ['Functions', meta.functionsTotal],
    ['Globals', meta.globalsTotal],
    ['Components', meta.components.length],
    ['Layers', meta.layers.length],
  ]
  return (
    <div className="px-5 2xl:px-8 py-2.5 border-b border-outline-variant bg-surface flex flex-wrap items-center gap-x-[18px] gap-y-1.5">
      <span className="flex items-center gap-1.5 font-mono text-caption uppercase tracking-[0.06em] text-on-surface-variant">
        <Icon
          name={meta.source === 'pipeline' ? 'bolt' : 'dataset'}
          size={13}
          className={meta.pipelineDataAvailable ? 'text-[#00a572]' : 'text-outline'}
        />
        Source: {meta.source}
      </span>
      {stats.map(([label, value]) => (
        <span key={label} className="font-mono text-caption text-on-surface-variant">
          <span className="text-on-surface font-semibold">{value}</span> {label}
        </span>
      ))}
    </div>
  )
}
