// Draw many Graphviz DOT flowcharts to SVG in ONE process: viz-js, no browser.
// Usage: node render_svg.mjs <jobs.json>
//   jobs.json = [{"dot": "<DOT text>", "svg": "<output path>", "key": "<content key>"}, ...]
// Prints one JSON line on stdout: {"ok": <count>, "failed": [{"svg": ..., "error": ...}]}.
//
// This is the cheap half of render_dot.mjs. Graphviz's layout and SVG take about a millisecond
// for a typical flowchart; the PNG then costs a headless browser per chart (~12 s each). The SVG
// is what the web reader shows, so it is drawn on every run; the PNG stays Word's alone.
//
// `key` goes into the file as a comment (<!-- dot-key: ... -->) so the caller can tell a
// current picture from a stale one without drawing it again (utils.svg_file_key).
//
// A graph can abort the WASM module outright -- seen on a synthetic 1,000-node flowchart, an
// assertion in gv_list_get_. An aborted module is dead, so after ANY failure a fresh instance is
// made and the next chart goes on; only the one chart fails.
import { readFileSync, writeFileSync, renameSync, mkdirSync, rmSync } from "node:fs";
import { dirname } from "node:path";
import { instance } from "@viz-js/viz";

const [, , jobsPath] = process.argv;
if (!jobsPath) {
  console.error("usage: node render_svg.mjs <jobs.json>");
  process.exit(2);
}

const jobs = JSON.parse(readFileSync(jobsPath, "utf-8"));

// After the XML declaration: a comment is allowed anywhere in the prolog.
function withKey(svg, key) {
  const mark = `<!-- dot-key: ${key} -->\n`;
  if (svg.startsWith("<?xml")) {
    const end = svg.indexOf("?>") + 2;
    return svg.slice(0, end) + "\n" + mark + svg.slice(end).replace(/^\r?\n/, "");
  }
  return mark + svg;
}

let viz = await instance();
let ok = 0;
const failed = [];

for (const job of jobs) {
  try {
    const svg = withKey(viz.renderString(job.dot, { format: "svg" }), job.key);
    mkdirSync(dirname(job.svg), { recursive: true });
    // Written aside and renamed in: the web app serves these files, and must never be handed
    // half of one.
    const tmp = `${job.svg}.${process.pid}.tmp`;
    writeFileSync(tmp, svg, "utf-8");
    try {
      renameSync(tmp, job.svg);
    } catch (e) {
      rmSync(tmp, { force: true });
      throw e;
    }
    ok += 1;
  } catch (e) {
    failed.push({ svg: job.svg, error: String((e && e.message) || e).split("\n")[0].slice(0, 300) });
    viz = await instance();
  }
}

process.stdout.write(JSON.stringify({ ok, failed }) + "\n");
