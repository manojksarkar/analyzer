import { describe, expect, it } from 'vitest'
import type { RichSection, Slot } from '../../../types'
import {
  ancestorsOf, buildOutline, defaultExpanded, docCorrections, filterOutline, outlineIds, slotWhere,
  unitCorrectionCounts,
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
  const all = [
    slot('description', `${U}|libAdd|int`, { isOverridden: true }),
    slot('structDescription', 'Acc', { isOverridden: true }),
    slot('description', 'Other|X|f|', { isOverridden: true }),
    slot('description', `${U}|gone|`, { isOrphaned: true }),
  ]
  it('keeps the ones it prints, and its component’s orphans', () => {
    const { inForce, orphans } = docCorrections(all, doc, 'C')
    expect(inForce.map((s) => s.key)).toEqual([`${U}|libAdd|int`, 'Acc'])
    expect(orphans.map((s) => s.key)).toEqual([`${U}|gone|`])
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
