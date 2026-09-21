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

// Past roughly 120 megapixels Chromium stops painting the lower part of a large
// element and screenshots it anyway: the PNG comes out the full size, with the
// bottom half flat white, and the exit code is 0. A 13768x12598 test graph came
// back 50% painted; a real 11966x13810 flowchart came back 40% painted and shipped
// into a document that way.
//
// Measured on that test graph: 173M px -> 50% painted, 110M -> whole, 85M -> whole,
// 64M -> whole. So the raster is held under MAX_PIXELS by lowering the device scale,
// which costs resolution nobody sees (these are embedded 4in wide) and keeps the
// diagram complete, which is the whole point of drawing it.
//
// The waits are secondary but real: `networkidle0` waits for the network, and inline
// SVG has none, so it returned before the rasterizer had finished. Adding the frame
// waits alone took the same graph from 50% to 75% - better, still broken. The budget
// is what fixes it.
const MAX_PIXELS = 100e6;    // below the 110M that rendered whole, well under the 173M that did not
const MAX_SIDE = 16384;      // Chromium's per-side texture limit

const browser = await puppeteer.launch(launchOpts);
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1200, height: 1600, deviceScaleFactor: scale });
  await page.setContent(
    `<!doctype html><body style="margin:0;background:#fff">${svg}</body>`,
    { waitUntil: "load" },
  );

  const box = await page.evaluate(() => {
    const r = document.querySelector("svg").getBoundingClientRect();
    return { w: Math.ceil(r.width), h: Math.ceil(r.height) };
  });

  let eff = scale;
  if (box.w > 0 && box.h > 0) {
    eff = Math.min(scale, MAX_SIDE / box.w, MAX_SIDE / box.h,
                   Math.sqrt(MAX_PIXELS / (box.w * box.h)));
    eff = Math.max(0.5, eff);            // never shrink past half: illegible is its own failure
    if (eff < scale) {
      console.error(
        `render_dot: ${box.w}x${box.h} css -> scale ${scale} would be ` +
        `${Math.round(box.w * scale * box.h * scale / 1e6)}M px; using scale ${eff.toFixed(2)}`,
      );
    }
  }

  // The whole element in view, then two frames, so the capture cannot outrun the paint.
  await page.setViewport({
    width: Math.min(box.w || 1200, MAX_SIDE),
    height: Math.min(box.h || 1600, MAX_SIDE),
    deviceScaleFactor: eff,
  });
  await page.evaluate(
    () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))),
  );

  const el = await page.$("svg");
  await el.screenshot({ path: outPng });
} finally {
  await browser.close();
}
