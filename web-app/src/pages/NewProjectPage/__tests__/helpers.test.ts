import { describe, expect, it } from 'vitest'
import { assignmentsOf, draftToLayers, indexTree, ownerOf, pathProblems, settingsSummary } from '../helpers'

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

describe('pathProblems', () => {
  // Layer1/Sample/Core/Core.cpp, Layer1/Math/Utils.cpp, include/ — the branch's tree.
  const tree = indexTree([
    { type: 'folder', name: 'Layer1', path: 'Layer1', children: [
      { type: 'folder', name: 'Sample', path: 'Layer1/Sample', children: [
        { type: 'folder', name: 'Core', path: 'Layer1/Sample/Core', children: [
          { type: 'file', name: 'Core.cpp', path: 'Layer1/Sample/Core/Core.cpp' }] }] },
      { type: 'folder', name: 'Math', path: 'Layer1/Math', children: [
        { type: 'file', name: 'Utils.cpp', path: 'Layer1/Math/Utils.cpp' }] }] },
    { type: 'folder', name: 'include', path: 'include', children: [] },
  ])
  const layer = (path: string, comps: { name: string; files: string[] }[], libPaths: string[] = []) => ({
    id: 'L', name: 'Layer1', path, libPaths, collapsed: false,
    groups: [{ id: 'G', name: 'G', collapsed: false, comps: comps.map((c, i) => ({ id: `c${i}`, collapsed: true, ...c })) }],
  })
  const texts = (layers: ReturnType<typeof layer>[]) => pathProblems(layers, tree, 'main').map((p) => p.text)

  it('passes a project whose every path is on the branch', () => {
    expect(texts([layer('Layer1', [{ name: 'Core', files: ['Layer1/Sample/Core'] },
      { name: 'Math', files: ['Layer1/Math/Utils.cpp'] }], ['include', '/opt/sdk/include', ''])])).toEqual([])
  })

  it('names a path the branch does not have — the run would skip it and the document come out empty', () => {
    expect(texts([layer('Layer1', [{ name: 'Ghost', files: ['Layer1/Gone'] }])]))
      .toEqual(['Layer1 / G / Ghost: `Layer1/Gone` is not on branch `main`'])
  })

  it('names a layer with no root folder, or one that is not there', () => {
    expect(texts([layer('', [{ name: 'Core', files: ['Layer1/Sample/Core'] }])]))
      .toEqual(["Layer1: no root folder — pick the layer's folder"])
    expect(texts([layer('Layer9', [{ name: 'Core', files: ['Layer1/Sample/Core'] }])])).toEqual([
      'Layer1: `Layer9` is not a folder on branch `main`',
      "Layer1 / G / Core: `Layer1/Sample/Core` is outside the layer's folder `Layer9`",
    ])
  })

  it('names a component with no files, a relative lib path that is not there, and a project with no component', () => {
    expect(texts([layer('Layer1', [{ name: 'Empty', files: [] }], ['libs/missing'])])).toEqual([
      'Layer1 / G / Empty: no files — a run would stop on it',
      'Layer1: lib path `libs/missing` is not a folder on branch `main`',
    ])
    expect(texts([])).toEqual(['No component yet — a run needs at least one'])
  })

  it('takes the repository root as a layer folder', () => {
    expect(texts([layer('.', [{ name: 'Core', files: ['Layer1/Sample/Core'] }])])).toEqual([])
  })
})
