import { describe, expect, it } from 'vitest'
import {
  assignmentsOf, coreInput, coreProblems, draftToCores, draftToLayers, fitsCoreFile, followBranch, indexTree, newCore,
  nextCoreName, ownerOf, pathProblems, settingsSummary,
} from '../helpers'
import type { DraftCore } from '../../../types'

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

describe('cores', () => {
  const file = (fileId: string, fileName = `${fileId}.json`) => ({ fileId, fileName, size: 2 })
  const draft = (over: Partial<DraftCore> = {}): DraftCore =>
    ({ name: 'Core1', macros: null, dataDictionary: null, compileCommands: null, ...over })

  it('reads a config\'s cores, and each layer takes the core its config names', () => {
    let n = 0
    const newId = () => `c${++n}`
    const cores = draftToCores([
      draft({ macros: { kind: 'file', file: file('m') } }),
      draft({ name: 'Core2', macros: { kind: 'typed', defines: ['A=1', 'B'] } }),
    ], newId)
    expect(cores.map((c) => [c.name, c.macroMode, c.macroFile?.fileId ?? null, c.macroText, c.from])).toEqual([
      ['Core1', 'file', 'm', '', 'Core1'], ['Core2', 'typed', null, 'A=1\nB', 'Core2']])
    // a renamed core keeps its layers: the config's name is `from`
    cores[1].name = 'Renamed'
    const layers = draftToLayers([
      { name: 'L1', groups: [], core: 'Core2' }, { name: 'L2', groups: [], core: null }, { name: 'L3', groups: [], core: 'Nope' },
    ], newId, cores)
    expect(layers.map((l) => l.coreId)).toEqual([cores[1].id, null, null])
  })

  it('lets the files the import filled in follow the branch, and never touches the user\'s', () => {
    const imported = { ...newCore('c1', 'Core1'), from: 'Core1', macroFile: file('m-main'), dataDictionary: file('mine', 'dd.csv') }
    const was = draft({ macros: { kind: 'file', file: file('m-main') }, dataDictionary: file('dd-main', 'dd.csv') })
    const now = draft({ macros: null, compileCommands: file('cc-dev') })
    const next = followBranch(imported, was, now)
    expect(next.macroFile).toBeNull()                     // the import's: this branch has none
    expect(next.dataDictionary?.fileId).toBe('mine')      // the user's own
    expect(next.compileCommands?.fileId).toBe('cc-dev')   // this branch's
  })

  it('names a core with no name, and two cores with one name', () => {
    expect(coreProblems([newCore('a', 'Core1'), newCore('b', ' core1 '), newCore('c', ' ')]))
      .toEqual(['Two cores are called core1', 'Core 3 has no name'])
    expect(coreProblems([newCore('a', 'Core1'), newCore('b', 'Core2')])).toEqual([])
  })

  it('picks the first free CoreN', () => {
    expect(nextCoreName([newCore('a', 'Core1'), newCore('b', 'core3')])).toBe('Core2')
    expect(nextCoreName([])).toBe('Core1')
  })

  it('sends typed macros only when typing is chosen', () => {
    const c = { ...newCore('a', ' Core1 '), macroFile: file('m'), macroText: 'A=1\n\n B ', dataDictionary: file('d', 'dd.csv') }
    expect(coreInput(c)).toEqual({
      name: 'Core1', macros: { mode: 'upload', file_id: 'm', file_name: 'm.json' },
      data_dictionary: { file_id: 'd', file_name: 'dd.csv' }, compile_commands: null })
    expect(coreInput({ ...c, macroMode: 'typed' }).macros).toEqual({ mode: 'manual', defines: ['A=1', 'B'] })
    expect(coreInput({ ...c, macroMode: 'typed', macroText: ' ' }).macros).toBeNull()
  })

  it('takes only the files the engine reads for each input', () => {
    expect(fitsCoreFile('dataDictionary', 'DD.CSV')).toBe(true)
    expect(fitsCoreFile('dataDictionary', 'dd.xlsx')).toBe(false)
    expect(fitsCoreFile('compileCommands', 'compile_commands.json')).toBe(true)
    expect(fitsCoreFile('macroFile', 'macros.txt')).toBe(false)
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
    id: 'L', name: 'Layer1', path, libPaths, coreId: null, collapsed: false,
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
