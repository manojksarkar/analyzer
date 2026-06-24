/**
 * Minimal markdown-section parser for document bodies.
 *
 * Document/compare section content is plain markdown: interface sections are
 * GitHub-style pipe tables, everything else is prose. The rich `/render`
 * endpoint parses tables server-side, but the flat document + compare detail
 * endpoints return raw strings — so we parse the pipe tables here to render
 * them as real tables (reusing the inspector's table styling) and fall back to
 * paragraphs for everything else.
 */

export interface TableBlock {
  type: 'table'
  headers: string[]
  rows: string[][]
}

export interface TextBlock {
  type: 'text'
  text: string
}

export type SectionBlock = TableBlock | TextBlock

/** Split a pipe-delimited row into trimmed cells (tolerates optional edge pipes). */
function splitRow(line: string): string[] {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim())
}

/** A `| --- | :--: |` style separator row that follows a table header. */
function isSeparator(line: string): boolean {
  return /^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$/.test(line)
}

/**
 * Parse markdown `content` into a flat list of text/table blocks. A table is a
 * header line containing `|` immediately followed by a `---` separator row.
 */
export function parseSectionBody(content: string): SectionBlock[] {
  const lines = (content ?? '').split('\n')
  const blocks: SectionBlock[] = []
  let textBuf: string[] = []

  const flushText = () => {
    const t = textBuf.join('\n').trim()
    if (t) blocks.push({ type: 'text', text: t })
    textBuf = []
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const next = lines[i + 1]
    if (line.includes('|') && next !== undefined && isSeparator(next)) {
      flushText()
      const headers = splitRow(line)
      const rows: string[][] = []
      i += 2
      while (i < lines.length && lines[i].includes('|')) {
        rows.push(splitRow(lines[i]))
        i++
      }
      i-- // the for-loop will re-increment
      blocks.push({ type: 'table', headers, rows })
    } else {
      textBuf.push(line)
    }
  }
  flushText()
  return blocks
}
