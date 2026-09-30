import { useState, type ReactNode } from 'react'
import { cn } from '../../../lib/cn'
import type { RichSection, RichTable, TestSpecData, TestSummary } from '../../../types'

/*
 * The SWE.4 reader: the Unit Test Specification, section for section as its DOCX
 * (engine/swe4_exporter.py), laid out as docs/ui-mockups/documents.html draws it — per test spec
 * Table A (the DOCX's six columns turned into rows, so Test Steps gets the page's width) and
 * Table B (the eight metadata fields). Headings stay flat: four levels of numbering, no indents.
 */

/** Counts under the title: units, specs, interactions, mocks, where the tests run. */
export function Swe4Strip({ summary }: { summary: TestSummary }) {
  const plural = (n: number, one: string, many = `${one}s`) => `${n === 1 ? one : many}`
  return (
    <div className="px-8 py-2.5 border-b border-outline-variant bg-surface flex flex-wrap gap-x-[18px] gap-y-1.5 font-mono text-caption text-on-surface-variant">
      <span><b className="text-on-surface">{summary.units}</b> {plural(summary.units, 'unit')}</span>
      <span><b className="text-on-surface">{summary.functionSpecs}</b> function {plural(summary.functionSpecs, 'spec')}</span>
      <span><b className="text-on-surface">{summary.dynamicSpecs}</b> dynamic behaviour {plural(summary.dynamicSpecs, 'spec')}</span>
      <span><b className="text-on-surface">{summary.mocks}</b> {plural(summary.mocks, 'mock')}</span>
      <span>{summary.equipment} · {summary.platform}</span>
    </div>
  )
}

/** Every section of the document, flat, in DOCX order. */
export function Swe4Body({ sections }: { sections: RichSection[] }) {
  return (
    <div className="px-8 py-10 space-y-14">
      {sections.map((s) => <Swe4Section key={s.id} section={s} />)}
    </div>
  )
}

function Swe4Section({ section }: { section: RichSection }) {
  if (section.type === 'test_spec' && section.testSpec) {
    return <SpecCard section={section} spec={section.testSpec} />
  }
  const heading = section.level <= 1
    ? 'text-[20px] font-semibold mb-4'
    : section.level === 2 ? 'text-[17px] font-semibold mt-7 mb-1' : 'text-title font-semibold mt-6 mb-1'
  return (
    <section id={`sec-${section.id}`} className="scroll-mt-6">
      <h2 className={cn('flex items-baseline text-on-surface', heading)}>
        {section.number && <span className="font-mono text-xs text-outline mr-1.5">{section.number}</span>}
        {section.title}
      </h2>
      {section.type === 'table' && section.table ? (
        <TermsTable table={section.table} />
      ) : section.content ? (
        <p className="text-sm text-on-surface leading-relaxed whitespace-pre-line">{section.content}</p>
      ) : null}
      {section.id === 'test_spec' && section.children.length === 0 && (
        // The DOCX prints the bare heading; say why, so an empty chapter does not read as a failure.
        <p className="text-sm text-outline italic">
          No test specification. A spec is written for each function of a .cpp unit that another
          unit calls, and this component has none.
        </p>
      )}
      {section.children.map((c) => <Swe4Section key={c.id} section={c} />)}
    </section>
  )
}

function TermsTable({ table }: { table: RichTable }) {
  return (
    <div className="mt-2 border border-outline-variant rounded-xl overflow-hidden">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr>
            {table.headers.map((h) => (
              <th key={h} className="text-left px-3 py-2 bg-surface border-b border-surface-container font-mono text-caption font-semibold text-on-surface-variant">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((r, i) => (
            <tr key={i} className="border-b border-surface-container last:border-0">
              {r.map((c, j) => <td key={j} className={cn('px-3 py-2 align-top text-on-surface', j === 0 && 'font-mono text-caption font-medium w-40')}>{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ── One spec: heading, Table A (six rows), Table B (eight fields) ── */

function SpecCard({ section, spec }: { section: RichSection; spec: TestSpecData }) {
  // The step an expected result names, while the pointer is on it.
  const [hl, setHl] = useState<string | null>(null)
  const meta: [string, string][] = [
    ['Test Case ID', spec.testCaseId], ['Alias Test ID', '-'], ['Priority', spec.priority],
    ['Risk', '-'], ['Test Method', '-'], ['Test Environment', spec.environment],
    ['Test Case Generation Method', spec.generationMethod], ['Linked Work Items', '-'],
  ]
  return (
    <div id={`sec-${section.id}`} className="mt-6 scroll-mt-4">
      <div className="flex items-baseline mb-2.5 text-sm font-semibold text-on-surface">
        <span className="font-mono text-xs text-outline mr-1.5">{section.number}</span>
        {section.title}
      </div>
      {section.content && <p className="text-sm text-on-surface-variant leading-relaxed mb-2.5">{section.content}</p>}
      <div className="border border-outline-variant rounded-xl overflow-hidden">
        <table className="w-full border-collapse text-[12.5px]">
          <tbody>
            <Row label="Eval. Equipment Name">{spec.equipment}</Row>
            <Row label="Precondition"><Precondition pre={spec.precondition} /></Row>
            <Row label="Input">{spec.inputs.length ? <NumberedList items={spec.inputs.map((t) => <Code key={t} text={t} />)} /> : 'VOID'}</Row>
            <Row label="Test Steps"><Steps steps={spec.steps} hl={hl} /></Row>
            <Row label="Expected Results"><Expected spec={spec} onHover={setHl} /></Row>
            <Row label="Test Platform" last>{spec.platform}</Row>
          </tbody>
        </table>
      </div>
      <div className="mt-2.5 border border-outline-variant rounded-xl overflow-hidden grid grid-cols-[200px_minmax(0,1fr)] text-xs">
        {meta.map(([k, v], i) => {
          const last = i === meta.length - 1
          return [
            <div key={`k${k}`} className={cn('px-3 py-[5px] bg-surface border-r border-surface-container font-mono text-caption font-semibold text-on-surface-variant', !last && 'border-b')}>{k}</div>,
            <div key={`v${k}`} className={cn('px-3 py-[5px] border-surface-container [overflow-wrap:anywhere]', !last && 'border-b', v === '-' ? 'text-[#b0b3b8]' : 'text-on-surface')}>{v}</div>,
          ]
        })}
      </div>
    </div>
  )
}

function Row({ label, last, children }: { label: string; last?: boolean; children: ReactNode }) {
  return (
    <tr className={cn(!last && 'border-b border-surface-container')}>
      <th className="w-[148px] text-left align-top px-3 py-2.5 bg-surface border-r border-surface-container font-mono text-caption font-semibold text-on-surface-variant">{label}</th>
      <td className="align-top px-3.5 py-[9px] text-on-surface leading-[1.55]">{children}</td>
    </tr>
  )
}

function NumberedList({ items }: { items: ReactNode[] }) {
  return (
    <ol className="list-none m-0 p-0">
      {items.map((it, i) => (
        <li key={i} className="flex gap-1.5">
          <span className="flex-shrink-0 min-w-[18px] font-mono text-caption leading-[19px] text-outline">{i + 1})</span>
          <span>{it}</span>
        </li>
      ))}
    </ol>
  )
}

function Precondition({ pre }: { pre: TestSpecData['precondition'] }) {
  const items: ReactNode[] = []
  if (pre.mocks.length) items.push(<>Mock functions: <CodeList items={pre.mocks} /></>)
  if (pre.parameters.length) items.push(<>Parameters: <CodeList items={pre.parameters} /></>)
  if (pre.globals.length) items.push(<>Globals: <CodeList items={pre.globals} /></>)
  return items.length ? <NumberedList items={items} /> : <>None</>
}

function CodeList({ items }: { items: string[] }) {
  return <>{items.map((t, i) => <span key={i}>{i > 0 && ', '}<Code text={t} /></span>)}</>
}

/** Test Steps nest as the control flow does; each level indents under its parent step. */
function Steps({ steps, hl }: { steps: TestSpecData['steps']; hl: string | null }) {
  if (!steps.length) return <span className="text-outline italic">Not available (no control-flow graph for this function)</span>
  type Node = { step: TestSpecData['steps'][number]; kids: Node[] }
  const roots: Node[] = []
  const stack: Node[] = []
  for (const step of steps) {
    const depth = step.number.split('.').length - 1
    const node: Node = { step, kids: [] }
    while (stack.length > depth) stack.pop()
    ;(stack.length ? stack[stack.length - 1].kids : roots).push(node)
    stack.push(node)
  }
  const render = (nodes: Node[]): ReactNode => nodes.map((n) => (
    <div key={n.step.number}>
      <div className={cn('flex gap-2 px-1.5 -ml-1.5 rounded-lg transition-colors', hl === n.step.number && 'bg-[#fff1c7]')}>
        <span className="flex-shrink-0 font-mono text-caption font-semibold leading-[19px] text-secondary">{n.step.number})</span>
        <span><Code text={n.step.text} /></span>
      </div>
      {n.kids.length > 0 && <div className="ml-2.5 pl-3 border-l border-[#dde1e8]">{render(n.kids)}</div>}
    </div>
  ))
  return <>{render(roots)}</>
}

/** Expected Results: each names the step(s) that produce it; pointing at one lights the step. */
function Expected({ spec, onHover }: { spec: TestSpecData; onHover: (step: string | null) => void }) {
  if (!spec.expected.length) {
    const muted = !!spec.expectedNote?.startsWith('Not available')
    return <span className={cn(muted && 'text-outline italic')}><Code text={(spec.expectedNote ?? '').replace(/`/g, '')} /></span>
  }
  return (
    <NumberedList items={spec.expected.map((e, i) => (
      <span key={i}>
        <Code text={e.text} />
        {e.steps.length > 0 && <> in step{e.steps.length > 1 ? 's' : ''}</>}
        {e.steps.map((n) => (
          <span
            key={n}
            onMouseEnter={() => onHover(n)}
            onMouseLeave={() => onHover(null)}
            className="inline-flex ml-[3px] px-[5px] rounded-[3px] bg-surface-container text-secondary font-mono text-[10.5px] font-semibold leading-[17px] cursor-default hover:bg-secondary hover:text-white"
          >
            {n}
          </span>
        ))}
      </span>
    ))} />
  )
}

// `name()`, `type name[range]` and the like read as code, as the DOCX sets them apart.
// A mocked callee's return reads `int name()[range]`: the `()` belongs to the name.
const CODE_RE = /(\b[\w:.]+\(\)|\b(?:u?int\d*_t|int|char|bool|float|double|void|long|short|unsigned)\*? [\w.[\]-]+(?:\(\))?(?:\[[^\]]*\])?)/g

function Code({ text }: { text: string }) {
  const parts = text.split(CODE_RE)
  return (
    <>
      {parts.map((p, i) =>
        i % 2
          ? <code key={i} className="font-mono text-[11.5px] font-medium bg-surface-container-low px-1 rounded-[3px]">{p}</code>
          : p)}
    </>
  )
}
