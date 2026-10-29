import type { ReactNode } from 'react'
import { useRunSettings } from '../../hooks/useVersionComponents'
import { formatDateTime } from '../../lib/format'
import { Drawer, Icon, Skeleton, Text } from '../ui'
import type { RunSetting } from '../../types'

/* How a version was made, run by run (docs/ui-mockups/versions.html, Runs drawer): this server's
   settings when each run started -- they change in config.local.json, a version keeps them. Read
   only, newest first; while a run is at work on the version, its entry is the first and is read
   again every 10 s. No secret is ever in the record. */

export function RunsDrawer({ projectId, versionId, versionTag, onClose }: {
  projectId: string
  versionId: string
  versionTag: string
  onClose: () => void
}) {
  const { data, isLoading, isError } = useRunSettings(projectId, versionId, true)
  const runs = data?.runs ?? []
  const count = isLoading ? '' : runs.length ? `${runs.length} run${runs.length === 1 ? '' : 's'}` : 'no runs recorded'
  return (
    <Drawer
      open
      onClose={onClose}
      title="Runs"
      description={<><span className="font-mono">{versionTag}</span>{count && ` · ${count}`}</>}
      footer={
        <p className="flex items-center gap-1.5 text-caption text-outline">
          <Icon name="lock" size={14} aria-hidden />
          Keys and header values are never recorded.
        </p>
      }
      className="w-[min(560px,100%)]"
    >
      {isLoading ? (
        <div className="p-6 space-y-3">{[0, 1].map((i) => <Skeleton key={i} className="h-40" />)}</div>
      ) : isError ? (
        <Text as="p" className="px-6 py-5">The runs could not be read. Try again in a moment.</Text>
      ) : runs.length === 0 ? (
        <Text as="p" className="px-6 py-5">Made before runs were recorded (28 Oct 2026).</Text>
      ) : (
        runs.map((run, i) => <RunSection key={`${run.at}-${i}`} run={run} now={i === 0 && !!data?.running} />)
      )}
    </Drawer>
  )
}

function RunSection({ run, now }: { run: RunSetting; now: boolean }) {
  return (
    <section className="px-6 py-3.5 border-b border-hairline">
      <div className="flex items-baseline justify-between gap-3 mb-1.5">
        <h3 className="flex items-center gap-2 text-body font-semibold text-on-surface">
          {run.what}
          {now && (
            <span className="text-caption font-medium text-secondary bg-surface-container px-1.5 rounded-full">Running now</span>
          )}
        </h3>
        <Text variant="caption" className="text-outline whitespace-nowrap">{formatDateTime(run.at)}</Text>
      </div>
      <dl>
        <Row label="Components">{run.components}</Row>
        <Row label="LLM">{run.llm}</Row>
        {run.endpoint && <Row label="Endpoint"><span className="font-mono text-caption">{run.endpoint}</span></Row>}
        <Row label="Lanes">
          {run.lanes.length ? run.lanes.map((l) => `${l.name} (${l.atOnce} at once)`).join(', ') : 'none — one call at a time'}
        </Row>
        <Row label="Credentials">{run.credentials}</Row>
        {run.pacing && <Row label="Pacing">{run.pacing}</Row>}
        <Row label="Parsing">{run.parsing}</Row>
        {run.llvm && <Row label="LLVM">{run.llvm}</Row>}
        {(run.host || run.code) && (
          <Row label="Machine">
            {run.host ?? '?'}
            {run.code && <> · code <span className="font-mono text-caption">{run.code}</span></>}
          </Row>
        )}
      </dl>
    </section>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3 py-0.5">
      <dt className="w-[92px] flex-shrink-0 text-xs text-outline">{label}</dt>
      <dd className="flex-1 min-w-0 text-xs text-on-surface break-words">{children}</dd>
    </div>
  )
}
