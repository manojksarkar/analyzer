// Many Mermaid diagrams, one browser: `node render_mmd_batch.mjs <jobs.json> [puppeteer-config.json]`.
//
// mmdc starts a Chromium for every diagram (~2-8 s each, before any drawing); a run draws hundreds.
// This draws each job with mermaid-cli's own renderMermaid() and the options mmdc uses by default
// (theme "default", white background, an 800x600 viewport, --scale as a whole number), so a picture
// comes out as mmdc draws it -- in one browser launched once.
//
// jobs.json: [{"in": "a.mmd", "out": "a.png", "scale": 2}, ...]. Writes <jobs.json>.results.json:
// [{"out", "ok", "ms", "error"?}], in job order -- a file, not stdout, which mermaid's plugins log to.
// A failed job does not stop the others.
import fs from 'node:fs'
import puppeteer from 'puppeteer'
import { renderMermaid } from '@mermaid-js/mermaid-cli'

const [jobsPath, pupConfigPath] = process.argv.slice(2)
const jobs = JSON.parse(fs.readFileSync(jobsPath, 'utf8'))
const launch = { headless: 1 }                          // as mmdc launches it
if (pupConfigPath && fs.existsSync(pupConfigPath)) {
  Object.assign(launch, JSON.parse(fs.readFileSync(pupConfigPath, 'utf8')))
}

// Pages at once in the one browser: each diagram gets its own page, as with mmdc, so they cannot
// affect one another.
const pages = 3
// Each job has its own time limit (mmdc's per-diagram limit at export): a stuck diagram fails
// alone and goes back to mmdc, instead of holding the whole batch until the batch's own (much
// longer) timeout.
const JOB_MS = 90000
function withTimeout (promise, ms) {
  let timer
  return Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`timed out after ${ms} ms`)), ms) })])
    .finally(() => clearTimeout(timer))
}
const results = new Array(jobs.length)
let browser = await puppeteer.launch(launch)
// A browser that dies mid-batch (one huge diagram, out of memory) is launched again -- at most
// twice -- and the job it died under is tried once more on the new one. Without this every job
// left would fail at once and go back to mmdc one by one: right pictures, today's speed.
let relaunches = 0
let relaunching = null
const isUp = (b) => (typeof b.isConnected === 'function' ? b.isConnected() : b.connected)
async function liveBrowser () {
  if (isUp(browser)) return browser
  if (!relaunching) {
    if (relaunches >= 2) throw new Error('the browser died again after two relaunches')
    relaunches++
    try { browser.process()?.kill('SIGKILL') } catch {}
    relaunching = puppeteer.launch(launch).then((b) => { browser = b; return b })
      .finally(() => { relaunching = null })
  }
  return relaunching
}
let next = 0
async function worker () {
  while (next < jobs.length) {
    const i = next++
    const job = jobs[i]
    const t0 = Date.now()
    try {
      const definition = fs.readFileSync(job.in, 'utf8')
      const scale = parseInt(job.scale ?? 1, 10) || 1    // mmdc parses --scale with parseInt
      let data
      for (let attempt = 0; ; attempt++) {
        const b = await liveBrowser()
        try {
          ({ data } = await withTimeout(renderMermaid(b, definition, 'png', {
            mermaidConfig: { theme: 'default' },
            backgroundColor: 'white',
            viewport: { width: 800, height: 600, deviceScaleFactor: scale },
          }), JOB_MS))
          break
        } catch (e) {
          if (attempt === 0 && !isUp(b)) continue          // the browser died under it: once more
          throw e
        }
      }
      fs.writeFileSync(job.out, data)
      results[i] = { out: job.out, ok: true, ms: Date.now() - t0 }
    } catch (e) {
      results[i] = { out: job.out, ok: false, ms: Date.now() - t0, error: String(e && e.message || e) }
    }
  }
}
try {
  await Promise.all(Array.from({ length: Math.min(pages, jobs.length) }, worker))
} finally {
  await browser.close().catch(() => {})
}
fs.writeFileSync(jobsPath + '.results.json', JSON.stringify(results))
