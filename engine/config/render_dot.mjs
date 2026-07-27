// Render a Graphviz DOT file to PNG: viz-js (DOT -> SVG) + puppeteer (SVG -> PNG).
// Usage: node render_dot.mjs <dotPath> <outPng> [scale]
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { instance } from "@viz-js/viz";
import puppeteer from "puppeteer";

const [, , dotPath, outPng, scaleArg] = process.argv;
if (!dotPath || !outPng) {
  console.error("usage: node render_dot.mjs <dotPath> <outPng> [scale]");
  process.exit(2);
}
const scale = Number(scaleArg) || 2;

const dot = readFileSync(dotPath, "utf-8");
const viz = await instance();
const svg = viz.renderString(dot, { format: "svg" });

// Launch options come from puppeteer-config.json (the same file mmdc uses for
// the mermaid diagrams), so the browser is configured in ONE place. On an
// offline/air-gapped server, add an "executablePath" to that file pointing at a
// standalone Chrome/Chromium, since puppeteer's bundled Chromium is downloaded
// from the network at install time and is therefore absent there. (Avoid the
// user's interactive Edge/Chrome: single-instance hand-off makes headless launch
// fail — use a dedicated browser install.) An env var
// (PUPPETEER_EXECUTABLE_PATH / CHROME_PATH) still wins if set.
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

// A configured executablePath is a "use if present" hint: if it doesn't exist on
// this machine (e.g. the committed offline-server path on a dev box that uses the
// bundled Chromium), drop it so puppeteer falls back to its own browser instead
// of failing with ENOENT.
if (launchOpts.executablePath && !existsSync(launchOpts.executablePath)) {
  console.error(
    `render_dot: configured executablePath not found, using bundled browser: ${launchOpts.executablePath}`,
  );
  delete launchOpts.executablePath;
}

const browser = await puppeteer.launch(launchOpts);
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1200, height: 1600, deviceScaleFactor: scale });
  await page.setContent(
    `<!doctype html><body style="margin:0;background:#fff">${svg}</body>`,
    { waitUntil: "networkidle0" },
  );
  const el = await page.$("svg");
  await el.screenshot({ path: outPng });
} finally {
  await browser.close();
}
