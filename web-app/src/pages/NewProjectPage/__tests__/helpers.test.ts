import { describe, expect, it } from 'vitest'
import { assignmentsOf, draftToLayers, ownerOf, settingsSummary } from '../helpers'

describe('draftToLayers', () => {
  it('builds the wizard tree with fresh ids and imported components collapsed', () => {
    let n = 0
    const layers = draftToLayers([{
      name: 'Layer1', path: 'Layer1', libPaths: [],
      groups: [{ name: 'G', components: [{ name: 'Core', files: ['Layer1/Sample/Core'] }] }],
    }], () => `id${++n}`)
    expect(layers[0].id).toBe('id1')
    expect(layers[0].groups[0].comps[0]).toEqual({ id: 'id3', name: 'Core', files: ['Layer1/Sample/Core'], collapsed: true })
  })
})

describe('ownerOf', () => {
  const owners = { 'Layer1/Sample/Core': 'Core', 'Layer1/Math/Utils.cpp': 'Math' }

  it('finds the component that lists the path itself', () => {
    expect(ownerOf('Layer1/Math/Utils.cpp', owners)).toBe('Math')
  })

  it('finds the component that lists a folder above the path — an imported config names folders', () => {
    expect(ownerOf('Layer1/Sample/Core/Core.cpp', owners)).toBe('Core')
    expect(ownerOf('Layer1/Sample/Core/sub/x.h', owners)).toBe('Core')
  })

  it('does not match a folder that only shares a name prefix', () => {
    expect(ownerOf('Layer1/Sample/CoreExtra/a.cpp', owners)).toBeUndefined()
  })

  it('reads the assignments off a tree', () => {
    let n = 0
    const layers = draftToLayers([{ name: 'L', path: 'L', libPaths: [], groups: [
      { name: 'G', components: [{ name: 'A', files: ['L/a'] }, { name: 'B', files: ['L/b', 'L/c'] }] }] }], () => `i${++n}`)
    expect(assignmentsOf(layers)).toEqual({ 'L/a': 'A', 'L/b': 'B', 'L/c': 'B' })
  })
})

describe('settingsSummary', () => {
  it('says what the imported settings change', () => {
    expect(settingsSummary({ clang: { clangArgs: ['--target=arm-none-eabi'] }, views: { flowcharts: true } }))
      .toBe('compiler: --target=arm-none-eabi · flowcharts on · behaviour diagrams off')
  })

  it('is empty when nothing was imported', () => {
    expect(settingsSummary({})).toBe('')
  })
})
