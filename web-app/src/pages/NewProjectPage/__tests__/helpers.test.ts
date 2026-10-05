import { describe, expect, it } from 'vitest'
import {
  assignmentsOf, baseName, browseStart, cleanPath, coreInput, coreProblems, draftToCores, draftToLayers, fitsCoreFile,
  folderCrumbs, indexTree, looksLocal, matchFolder, newCore, nextCoreName, openWants, ownerOf, pathProblems,
  settingsSummary, type WantedFile,
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

describe('matchFolder', () => {
  const want = (coreId: string, path: string, slot: WantedFile['slot'] = 'macroFile'): WantedFile => ({ coreId, slot, path })
  const picked = (...paths: string[]) => paths.map((path) => ({ path }))

  it('tells same-named files apart by the folders at the end of the config\'s path', () => {
    const m = matchFolder(
      [want('c1', 'D:/fw-inputs/core1/macros.json'), want('c2', '/home/u/fw-inputs/core2/macros.json')],
      picked('fw-inputs/core1/macros.json', 'fw-inputs/core2/macros.json', 'fw-inputs/notes.txt'))
    expect(m.found.map((f) => [f.want.coreId, f.file.path])).toEqual([
      ['c1', 'fw-inputs/core1/macros.json'], ['c2', 'fw-inputs/core2/macros.json']])
    expect([m.missing, m.unsure]).toEqual([[], []])
  })

  it('prefers the longer match over a stray copy, case aside', () => {
    const m = matchFolder([want('c1', 'C:\\Inputs\\Core1\\DD.csv', 'dataDictionary')],
      picked('inputs/old/core1/dd.csv', 'inputs/core1/dd.csv'))
    expect(m.found[0].file.path).toBe('inputs/core1/dd.csv')
  })

  it('never guesses a tie, and names a file the folder does not have', () => {
    // a downloaded config names files by name alone
    const m = matchFolder([want('c1', 'macros.json'), want('c1', 'cc.json', 'compileCommands')],
      picked('in/core1/macros.json', 'in/core2/macros.json'))
    expect(m.found).toEqual([])
    expect(m.unsure.map((w) => w.path)).toEqual(['macros.json'])
    expect(m.missing.map((w) => w.path)).toEqual(['cc.json'])
  })

  it('never takes another core\'s file for a folder the pick does not have', () => {
    const cc = want('c3', 'D:/in/core3/compile_commands.json', 'compileCommands')
    for (const pick of [picked('in/core1/compile_commands.json', 'in/core2/compile_commands.json'),
      picked('in/core1/compile_commands.json')]) {
      const m = matchFolder([cc], pick)
      expect([m.found, m.unsure, m.missing]).toEqual([[], [], [cc]])
    }
  })

  it('takes a copy of the inputs under another folder name, or a flat one', () => {
    const cc = want('c3', '/home/u/in/core3/compile_commands.json', 'compileCommands')
    expect(matchFolder([cc], picked('in-copy/core1/compile_commands.json', 'in-copy/core3/compile_commands.json'))
      .found.map((f) => f.file.path)).toEqual(['in-copy/core3/compile_commands.json'])
    expect(matchFolder([cc], picked('flat/compile_commands.json')).found).toHaveLength(1)
  })

  it('fills only the core whose folder was picked', () => {
    const m = matchFolder([want('c1', 'D:/in/core1/macros.json'), want('c2', 'D:/in/core2/macros.json')],
      picked('core1/macros.json'))
    expect(m.found.map((f) => f.want.coreId)).toEqual(['c1'])
    expect(m.missing.map((w) => w.coreId)).toEqual(['c2'])
    // a flat folder that two cores' paths fit equally well is not guessed
    const flat = matchFolder([want('c1', 'D:/in/core1/macros.json'), want('c2', 'D:/in/core2/macros.json')],
      picked('flat/macros.json'))
    expect(flat.unsure.map((w) => w.coreId)).toEqual(['c1', 'c2'])
  })

  it('lets one file fill every core that names it', () => {
    const m = matchFolder([want('c1', 'D:/shared/dd.csv', 'dataDictionary'), want('c2', 'D:/shared/dd.csv', 'dataDictionary')],
      picked('shared/dd.csv'))
    expect(m.found.map((f) => f.want.coreId)).toEqual(['c1', 'c2'])
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

  it('asks only for the files a core still lacks - macros only while they are a file', () => {
    const want = { macros: 'D:/in/core1/macros.json', dataDictionary: 'D:/in/core1/dd.csv', compileCommands: null }
    const c = { ...newCore('c1', 'Core1'), dataDictionary: file('mine', 'dd.csv') }
    expect(openWants(c, want)).toEqual([{ coreId: 'c1', slot: 'macroFile', path: 'D:/in/core1/macros.json' }])
    expect(openWants({ ...c, macroMode: 'typed' }, want)).toEqual([])
    expect(openWants(c, undefined)).toEqual([])
    expect(baseName('C:\\work\\dd.csv')).toBe('dd.csv')
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

/* Step 1's repository is a Git URL or a local path: a git repository's folder on the server. */
describe('cleanPath', () => {
  it('drops blanks and the quotes of Explorer\'s "Copy as path"', () => {
    expect(cleanPath('  "D:\\src\\vcu-firmware"  ')).toBe('D:\\src\\vcu-firmware')
    expect(cleanPath("'/home/build/vcu'")).toBe('/home/build/vcu')
    expect(cleanPath('D:/src/vcu')).toBe('D:/src/vcu')
    expect(cleanPath('')).toBe('')
  })
})

describe('looksLocal', () => {
  it('a drive, a root, a share or a file:// link is a local path', () => {
    for (const p of ['D:/src/vcu', 'd:\\src\\vcu', '/home/build/vcu', '\\\\server\\share\\vcu', 'file:///D:/src/vcu', ' "D:\\src" ']) {
      expect(looksLocal(p)).toBe(true)
    }
  })
  it('a URL, an ssh remote, a relative path or nothing is not', () => {
    for (const p of ['https://github.com/org/repo.git', 'git@github.com:org/repo.git', 'src/vcu', 'D:', '', '  ']) {
      expect(looksLocal(p)).toBe(false)
    }
  })
})

describe('browseStart', () => {
  it('opens the folder above the path the field names, to pick that path there', () => {
    expect(browseStart('D:/src/vcu-firmware')).toEqual({ folder: 'D:/src', pick: 'D:/src/vcu-firmware' })
    expect(browseStart('"D:\\src\\vcu-firmware\\"')).toEqual({ folder: 'D:/src', pick: 'D:/src/vcu-firmware' })
    expect(browseStart('D:/vcu')).toEqual({ folder: 'D:/', pick: 'D:/vcu' })
    expect(browseStart('/home/build')).toEqual({ folder: '/home', pick: '/home/build' })
    expect(browseStart('/vcu')).toEqual({ folder: '/', pick: '/vcu' })
    expect(browseStart('file:///D:/src/vcu')).toEqual({ folder: 'D:/src', pick: 'D:/src/vcu' })
  })
  it('a drive or the root opens the top list; no full path, nothing', () => {
    expect(browseStart('D:\\')).toEqual({ folder: '', pick: 'D:/' })
    expect(browseStart('/')).toEqual({ folder: '', pick: '/' })
    expect(browseStart('src/vcu')).toBeNull()
    expect(browseStart('https://github.com/org/repo.git')).toBeNull()
  })
})

describe('folderCrumbs', () => {
  it('one part per folder from the drive or the root down', () => {
    expect(folderCrumbs('D:/src/docs', null)).toEqual([
      { name: 'D:', path: 'D:/' }, { name: 'src', path: 'D:/src' }, { name: 'docs', path: 'D:/src/docs' }])
    expect(folderCrumbs('/home/build', null)).toEqual([
      { name: '/', path: '/' }, { name: 'home', path: '/home' }, { name: 'build', path: '/home/build' }])
    expect(folderCrumbs('', null)).toEqual([])
  })
  it('a folder the server limits the picker to is the first part, by its full path', () => {
    const roots = [{ name: 'D:/src', path: 'D:/src' }, { name: 'E:/builds', path: 'E:/builds' }]
    expect(folderCrumbs('D:/src/third_party/lwip', roots)).toEqual([
      { name: 'D:/src', path: 'D:/src' }, { name: 'third_party', path: 'D:/src/third_party' },
      { name: 'lwip', path: 'D:/src/third_party/lwip' }])
    expect(folderCrumbs('D:/srcx', roots)).toEqual([{ name: 'D:', path: 'D:/' }, { name: 'srcx', path: 'D:/srcx' }])
    expect(folderCrumbs('d:/SRC/lwip', roots)).toEqual([{ name: 'D:/src', path: 'D:/src' }, { name: 'lwip', path: 'D:/src/lwip' }])
  })
})
