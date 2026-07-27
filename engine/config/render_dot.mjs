// Render a Graphviz DOT file to PNG: viz-js (DOT -> SVG) + puppeteer (SVG -> PNG).
// Usage: node render_dot.mjs <dotPath> <outPng> [scale]
// Uses the full `puppeteer` package so the bundled Chromium is located
// automatically (no hardcoded browser path).
import { readFileSync } from "node:fs";
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

const browser = await puppeteer.launch({ headless: "new", args: ["--no-sandbox"] });
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
