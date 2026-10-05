import { describe, expect, it } from 'vitest'
import { allKeys, compKey, groupKeys, layerKeys, scopeOf, tickState, toggleKeys } from '../runScope'
import type { ArchLayer } from '../../types'

const g = (name: string, comps: string[]) => ({ name, components: comps.map((c) => ({ name: c })) })
const LAYERS: ArchLayer[] = [
  { name: 'Layer1', groups: [g('My Sample', ['Sample Core', 'Lib', 'Util']), g('Support', ['Math', 'App'])] },
  { name: 'Layer2', groups: [g('My Sample', ['Sample Core']), g('Platform', ['Gpio', 'Uart'])] },
  { name: 'Layer3', groups: [] },
]
const all = () => new Set(allKeys(LAYERS))
const without = (keys: string[]) => { const s = all(); keys.forEach((k) => s.delete(k)); return s }
const only = (keys: string[]) => new Set(keys)
const [L1, L2] = LAYERS

describe('scopeOf', () => {
  it('is the whole project when every component is ticked - the default run', () => {
    expect(scopeOf(LAYERS, all())).toEqual({ type: 'project', names: [] })
  })

  it('is nothing when nothing is ticked', () => {
    expect(scopeOf(LAYERS, new Set())).toBeNull()
  })

  it('sends whole layers as layers', () => {
    expect(scopeOf(LAYERS, only(layerKeys(L2)))).toEqual({ type: 'layer', names: ['Layer2'] })
  })

  it('sends whole groups as layer-qualified groups, across layers', () => {
    expect(scopeOf(LAYERS, only([...groupKeys(L1, L1.groups[1]), ...groupKeys(L2, L2.groups[1])])))
      .toEqual({ type: 'group', names: ['Layer1.Support', 'Layer2.Platform'] })
  })

  it('spells a whole layer out as its groups when a group elsewhere is ticked too', () => {
    expect(scopeOf(LAYERS, only([...layerKeys(L2), ...groupKeys(L1, L1.groups[1])])))
      .toEqual({ type: 'group', names: ['Layer1.Support', 'Layer2.My Sample', 'Layer2.Platform'] })
  })

  it('sends a part of a group as layer-qualified components', () => {
    expect(scopeOf(LAYERS, only([compKey('Layer1', 'My Sample', 'Lib')])))
      .toEqual({ type: 'component', names: ['Layer1.Lib'] })
    expect(scopeOf(LAYERS, without([compKey('Layer2', 'Platform', 'Uart')]))?.names).toEqual([
      'Layer1.Sample Core', 'Layer1.Lib', 'Layer1.Util', 'Layer1.Math', 'Layer1.App',
      'Layer2.Sample Core', 'Layer2.Gpio'])
  })
})

describe('ticking', () => {
  it('ticks a whole node, and unticks it when it is all ticked', () => {
    const lib = compKey('Layer1', 'My Sample', 'Lib')
    const some = toggleKeys(groupKeys(L1, L1.groups[0]), only([lib]))
    expect(tickState(groupKeys(L1, L1.groups[0]), some)).toBe('all')
    expect(tickState(groupKeys(L1, L1.groups[0]), toggleKeys(groupKeys(L1, L1.groups[0]), some))).toBe('none')
  })

  it('reads a node with only some components ticked as partly ticked', () => {
    expect(tickState(layerKeys(L1), only([compKey('Layer1', 'Support', 'Math')]))).toBe('some')
  })

  it('keeps a component apart from one of the same name in another layer', () => {
    expect(compKey('Layer1', 'My Sample', 'Sample Core')).not.toBe(compKey('Layer2', 'My Sample', 'Sample Core'))
  })
})
