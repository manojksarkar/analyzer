// Many flowcharts, one browser: `node render_dot_batch.mjs <jobs.json>`.
//
// render_dot.mjs launches a browser for every chart; a document has hundreds. This does each job
// exactly as render_dot.mjs does it -- viz-js DOT -> SVG, a page sized to the SVG, the 100M-pixel
// and 16384-side budget, two frames before the capture -- on a new page of ONE browser launched once.
//
// jobs.json: [{"dot": "a.dot", "out": "a.png", "scale": 2}, ...]. Writes <jobs.json>.results.json:
// [{"out", "ok", "ms", "error"?}] in job order. A failed job does not stop the others.
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { instance } from "@viz-js/viz";
import puppeteer from "puppeteer";

const [, , jobsPath] = process.argv;
const jobs = JSON.parse(readFileSync(jobsPath, "utf-8"));

// Launch options as render_dot.mjs resolves them: puppeteer-config.json, an env override, and a
// configured executablePath used only when it exists.
const _here = dirname(fileURLToPath(import.meta.url));
let launchOpts = { headless: "new", args: ["--no-sandbox"] };
try {
  const cfg = JSON.parse(readFileSync(join(_here, "puppeteer-config.json"), "utf-8"));
  launchOpts = { ...launchOpts, ...cfg };
} catch {
  // no config file -> defaults above
}
const envExe = process.env.PUPPETEER_EXECUTABLE_PATH || process.env.CHROME_PATH;
if (envExe) launchOpts.executablePath = envExe;
if (launchOpts.executablePath && !existsSync(launchOpts.executablePath)) delete launchOpts.executablePath;

const MAX_PIXELS = 100e6;    // as render_dot.mjs: the budget that keeps a big chart fully painted
const MAX_SIDE = 16384;

async function draw(browser, viz, job) {
  const scale = Number(job.scale) || 2;
  const svg = viz.renderString(readFileSync(job.dot, "utf-8"), { format: "svg" });
  const page = await browser.newPage();
  try {
    await page.setViewport({ width: 1200, height: 1600, deviceScaleFactor: scale });
    await page.setContent(`<!doctype html><body style="margin:0;background:#fff">${svg}</body>`,
                          { waitUntil: "load" });
    const box = await page.evaluate(() => {
      const r = document.querySelector("svg").getBoundingClientRect();
      return { w: Math.ceil(r.width), h: Math.ceil(r.height) };
    });
    let eff = scale;
    if (box.w > 0 && box.h > 0) {
      eff = Math.min(scale, MAX_SIDE / box.w, MAX_SIDE / box.h, Math.sqrt(MAX_PIXELS / (box.w * box.h)));
      eff = Math.max(0.5, eff);
    }
    await page.setViewport({ width: Math.min(box.w || 1200, MAX_SIDE), height: Math.min(box.h || 1600, MAX_SIDE),
                             deviceScaleFactor: eff });
    await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
    const el = await page.$("svg");
    // Into memory, then to disk only if the job was not given up on: a timed-out chart that
    // finishes late must not overwrite the picture render_dot.mjs drew for it meanwhile.
    const png = await el.screenshot();
    if (!job.abandoned) writeFileSync(job.out, png);
  } finally {
    await page.close();
  }
}

// Each chart has its own time limit (render_dot.mjs's limit per chart): a stuck chart fails alone
// and is drawn by render_dot.mjs afterwards, instead of holding the whole batch until the batch's
// own timeout.
const JOB_MS = 180000;
function withTimeout(promise, ms) {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`timed out after ${ms} ms`)), ms); })])
    .finally(() => clearTimeout(timer));
}

const viz = await instance();
const results = [];
let browser = await puppeteer.launch(launchOpts);
// A browser that dies mid-batch (one huge chart, out of memory) is launched again -- at most
// twice -- and the chart it died under is tried once more on the new one. Without this every
// chart left would fail at once and go back to render_dot.mjs one by one: right pictures,
// today's speed.
let relaunches = 0;
const isUp = (b) => (typeof b.isConnected === "function" ? b.isConnected() : b.connected);
async function liveBrowser() {
  if (isUp(browser)) return browser;
  if (relaunches >= 2) throw new Error("the browser died again after two relaunches");
  relaunches++;
  try { browser.process()?.kill("SIGKILL"); } catch {}
  browser = await puppeteer.launch(launchOpts);
  return browser;
}
try {
  for (const job of jobs) {
    const t0 = Date.now();
    try {
      for (let attempt = 0; ; attempt++) {
        const b = await liveBrowser();
        try {
          await withTimeout(draw(b, viz, job), JOB_MS).catch((e) => { job.abandoned = true; throw e; });
          break;
        } catch (e) {
          if (attempt === 0 && !isUp(b)) { job.abandoned = false; continue; }  // died under it: once more
          throw e;
        }
      }
      results.push({ out: job.out, ok: true, ms: Date.now() - t0 });
    } catch (e) {
      results.push({ out: job.out, ok: false, ms: Date.now() - t0, error: String((e && e.message) || e) });
    }
  }
} finally {
  await browser.close().catch(() => {});
}
writeFileSync(jobsPath + ".results.json", JSON.stringify(results));
