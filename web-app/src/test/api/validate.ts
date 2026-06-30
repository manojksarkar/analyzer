import type { ZodType } from 'zod'

export interface FieldProblem {
  /** Dotted path to the offending field, e.g. `projects[0].team_count`. */
  path: string
  code: string
  message: string
}

export interface ValidationResult {
  /** False = a required field is missing or has the wrong type (a breaking change). */
  ok: boolean
  problems: FieldProblem[]
  /** Fields the API returns that the UI's types don't model (non-breaking — a warning). */
  extra: string[]
}

/**
 * Validate a raw API response against the zod schema the UI expects.
 *
 * - `problems` (hard) come from `safeParse`: missing required fields or type
 *   mismatches — these would break the UI and fail the API-test suite.
 * - `extra` (soft) are keys the server returned that the schema strips. zod
 *   removes unknown keys on a successful parse, so diffing the raw payload
 *   against the parsed result surfaces additions the API made — a heads-up,
 *   not a failure.
 */
export function validateResponse(schema: ZodType, data: unknown): ValidationResult {
  const res = schema.safeParse(data)
  if (!res.success) {
    return {
      ok: false,
      problems: res.error.issues.map((i) => ({
        path: i.path.length ? i.path.map(String).join('.') : '(root)',
        code: i.code,
        message: i.message,
      })),
      extra: [],
    }
  }
  return { ok: true, problems: [], extra: diffExtraKeys(data, res.data) }
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/** Keys present in `orig` but stripped from `clean`, as dotted paths. */
export function diffExtraKeys(orig: unknown, clean: unknown, path = ''): string[] {
  if (Array.isArray(orig) && Array.isArray(clean)) {
    const out: string[] = []
    for (let i = 0; i < clean.length; i++) {
      out.push(...diffExtraKeys(orig[i], clean[i], `${path}[${i}]`))
    }
    return out
  }
  if (isPlainObject(orig) && isPlainObject(clean)) {
    const out: string[] = []
    for (const key of Object.keys(orig)) {
      const child = path ? `${path}.${key}` : key
      if (!(key in clean)) out.push(child)
      else out.push(...diffExtraKeys(orig[key], clean[key], child))
    }
    return out
  }
  return []
}

export interface ReportRow {
  name: string
  status: number | string
  result: ValidationResult | null
  note?: string
}

/** Render the per-endpoint report as a plain-text block for the console. */
export function formatReport(rows: ReportRow[], base: string): string {
  const lines: string[] = []
  lines.push(`API test report — ${base}`)
  lines.push('─'.repeat(64))
  for (const r of rows) {
    const mark = r.result ? (r.result.ok ? '✓' : '✗') : '•'
    lines.push(`${mark} [${String(r.status)}] ${r.name}${r.note ? `  (${r.note})` : ''}`)
    if (r.result) {
      for (const p of r.result.problems) lines.push(`    ✗ ${p.path}: ${p.message}`)
      for (const e of r.result.extra) lines.push(`    + extra field: ${e}`)
    }
  }
  const hard = rows.filter((r) => r.result && !r.result.ok).length
  const extra = rows.reduce((n, r) => n + (r.result?.extra.length ?? 0), 0)
  lines.push('─'.repeat(64))
  lines.push(`${rows.length} endpoints · ${hard} mismatch(es) · ${extra} new field(s)`)
  return lines.join('\n')
}
