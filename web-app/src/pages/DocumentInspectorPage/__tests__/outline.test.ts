import { describe, expect, it } from 'vitest'
import type { RichSection, Slot } from '../../../types'
import {
  ancestorsOf, buildOutline, defaultExpanded, docCorrections, filterOutline, flowOrder, isCorrected, outlineIds,
  slotWhere, undoneInWordFile, unitCorrectionCounts,
} from '../outline'

function sec(id: string, number: string, title: string, level: number, children: RichSection[] = [],
  extra: Partial<RichSection> = {}): RichSection {
  return { id, number, title, level, type: 'richtext', content: null, table: null, imageUrl: null, mermaid: null,
    children, ...extra }
}

function slot(kind: Slot['kind'], key: string, extra: Partial<Slot> = {}): Slot {
  return { kind, key, text: 't', llmText: 't', humanText: null, isOverridden: false, isOrphaned: false,
    canUndo: false, updatedBy: null, updatedAt: null, ...extra }
}

const U = 'C|Lib'
const doc: RichSection[] = [
  sec('intro', '1', 'Introduction', 1, [sec('intro-purpose', '1.1', 'Purpose', 2)]),
  sec('comp-C', '2', 'C', 1, [
    sec('C-static', '2.1', 'Static Design', 2, [
      sec('C-unit-table', '', 'Component/Unit Table', 2, [], { type: 'table',
        table: { headers: [], rows: [], cellSlots: [[null, null, slot('unitDescription', U), null]] } }),
      sec('C-unit-1', '2.1.1', 'Lib', 3, [
        sec(`${U}-header`, '2.1.1.1', 'unit header', 4, [], { type: 'table',
          table: { headers: [], rows: [], cellSlots: [[null, slot('structDescription', 'Acc')]] } }),
        sec(`${U}-iface`, '2.1.1.2', 'unit interface', 4),
        sec(`${U}-fn-libAdd`, '2.1.1.3', 'Lib-libAdd', 4, [], { contentSlot: slot('description', `${U}|libAdd|int`) }),
        sec(`${U}-fn-libSub`, '2.1.1.4', 'Lib-libSub', 4),
      ]),
    ]),
    sec('C-dynamic', '2.2', 'Dynamic Behaviour', 2),
  ]),
]

describe('buildOutline', () => {
  const tree = buildOutline(doc)
  it('lists units with their functions, not their header and interface tables', () => {
    const unit = tree[1].children[0].children[0]
    expect(unit.title).toBe('Lib')
    expect(unit.unitKey).toBe(U)
    expect(unit.children.map((c) => c.title)).toEqual(['Lib-libAdd', 'Lib-libSub'])
  })
  it('keeps document order and nests by depth', () => {
    expect(outlineIds(tree)).toEqual(['intro', 'intro-purpose', 'comp-C', 'C-static', 'C-unit-1',
      `${U}-fn-libAdd`, `${U}-fn-libSub`, 'C-dynamic'])
    expect(ancestorsOf(tree, `${U}-fn-libSub`)).toEqual(['comp-C', 'C-static', 'C-unit-1'])
  })
  it('opens chapters and their parts, not units', () => {
    const open = defaultExpanded(tree)
    expect(open.has('comp-C')).toBe(true)
    expect(open.has('C-static')).toBe(true)
    expect(open.has('C-unit-1')).toBe(false)
  })
  it('stops at a level', () => {
    expect(outlineIds(buildOutline(doc, 3))).not.toContain(`${U}-fn-libAdd`)
  })
})

describe('filterOutline', () => {
  const tree = buildOutline(doc)
  it('keeps the matches and their ancestors, and counts them', () => {
    const { nodes, hits } = filterOutline(tree, 'SUB')
    expect(hits).toBe(1)
    expect(outlineIds(nodes)).toEqual(['comp-C', 'C-static', 'C-unit-1', `${U}-fn-libSub`])
  })
  it('shows a matching unit with all its functions', () => {
    const { nodes } = filterOutline(tree, 'lib')
    expect(outlineIds(nodes)).toContain(`${U}-fn-libAdd`)
  })
})

describe('corrections of this document', () => {
  // A correction in force (API spec §5): the human's text printed, the LLM's kept, Undo possible.
  const fixed = { isOverridden: true, canUndo: true, text: 'new', humanText: 'new' }
  const all = [
    slot('description', `${U}|libAdd|int`, fixed),
    slot('structDescription', 'Acc', fixed),
    slot('description', 'Other|X|f|', fixed),
    slot('description', `${U}|gone|`, { isOrphaned: true, humanText: 'old words' }),
    // Undone (R4): the record stays, isOverridden too, but the page prints the LLM's text again.
    slot('unitDescription', U, { isOverridden: true, canUndo: false, humanText: 't' }),
  ]
  it('keeps the ones it prints, and its component’s orphans — an undone one apart', () => {
    const { inForce, undone, orphans } = docCorrections(all, doc, 'C')
    expect(inForce.map((s) => s.key)).toEqual([`${U}|libAdd|int`, 'Acc'])
    // Undone: not in force on the page, but the Word file has it until a re-export (R9 counts it).
    expect(undone.map((s) => s.key)).toEqual([U])
    expect(orphans.map((s) => s.key)).toEqual([`${U}|gone|`])
  })
  it('tells a correction in force from an undone one, an orphan and a never-corrected text', () => {
    expect(isCorrected(slot('description', 'k', fixed))).toBe(true)
    expect(isCorrected(slot('description', 'k', { isOverridden: true, canUndo: false, humanText: 't' }))).toBe(false)
    expect(isCorrected(slot('description', 'k', { isOrphaned: true, humanText: 'old' }))).toBe(false)
    expect(isCorrected(slot('description', 'k'))).toBe(false)
    // A slot that was empty before its first correction has no original to undo to: still corrected.
    expect(isCorrected(slot('description', 'k', { isOverridden: true, canUndo: false, llmText: null, text: 'new' })))
      .toBe(true)
  })
  it('counts them per unit, a struct by its header row', () => {
    const { inForce } = docCorrections(all, doc, 'C')
    expect(unitCorrectionCounts(inForce, doc).get(U)).toBe(2)
  })
  it('says where a correction is', () => {
    expect(slotWhere(slot('description', `${U}|libAdd|int`))).toBe('libAdd')
    expect(slotWhere(slot('unitDescription', U))).toBe('unit Lib')
    expect(slotWhere(slot('nodeLabel', `${U}|libAdd|int\u0001n3`, { nodeId: 'n3' }))).toBe('libAdd · box n3')
  })
})

describe('flowOrder (a flowchart’s boxes as its arrows run)', () => {
  it('follows the arrows, not the node numbers', () => {
    const dot = [
      'digraph G {',
      '  N1 [shape=ellipse, label="Start"];',
      '  N2 [shape=ellipse, label="End"];',
      '  N3 [shape=box, label="Return x"];',
      '  N1 -> N3;',
      '  N3 -> N2;',
      '}',
    ].join('\n')
    const o = flowOrder(dot)
    expect([...o.entries()].sort((a, b) => a[1] - b[1]).map((e) => e[0])).toEqual(['N1', 'N3', 'N2'])
  })
  it('is empty without a DOT', () => {
    expect(flowOrder('').size).toBe(0)
  })
})

/* "Undone — not in the Word file yet": cut off at the last re-export's end (or the version's oldest
   derivation), it hid undos a partial re-export never wrote. Every undone correction of the
   document is listed while its Word file is stale. */
describe('undone corrections the Word file may still carry', () => {
  const undo = (key: string, updatedAt: string | null) =>
    slot('description', key, { isOverridden: true, updatedAt })
  it('lists every one while the Word file is stale, however long ago it was undone', () => {
    const old = undo('a', '2026-09-01T09:00:00Z')
    const recent = undo('b', '2026-10-05T09:00:00Z')
    const unknown = undo('c', null)
    expect(undoneInWordFile([old, recent, unknown], true).map((s) => s.key)).toEqual(['a', 'b', 'c'])
  })
  it('lists none once the Word file is up to date', () => {
    expect(undoneInWordFile([undo('a', '2026-09-01T09:00:00Z')], false)).toEqual([])
  })
})
