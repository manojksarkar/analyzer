/** A failed run's error, as the runner writes it: a headline, then (when the engine stopped
 *  before the parse) its other reasons as `- ` lines, then the log's tail. The reasons carry
 *  backticked paths and keys; the tail is a log, shown as one. */
export function failureParts(message: string | null | undefined): { headline: string; reasons: string[]; log: string } {
  const lines = (message ?? '').trim().split('\n')
  const headline = lines[0]?.trim() || 'The analysis stopped with an error.'
  let i = 1
  const reasons: string[] = []
  while (i < lines.length && lines[i].startsWith('- ')) reasons.push(lines[i++].slice(2).trim())
  return { headline, reasons, log: lines.slice(i).join('\n').trim() }
}
