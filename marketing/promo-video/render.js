// Renders the promo video's graphics frame by frame: seeks every animation to the frame's time,
// screenshots it, and pipes the frames to ffmpeg.
//   node render.js                 everything
//   node render.js s01 captions    only jobs whose name contains one of the words
//   node render.js --still s01 4.5 one PNG at 4.5 s, to check a frame
// Needs ffmpeg on PATH or in the FFMPEG environment variable; puppeteer from the repo root.
const path = require("path");
const fs = require("fs");
const { spawn } = require("child_process");
const puppeteer = require(path.join(__dirname, "..", "..", "node_modules", "puppeteer"));

const FFMPEG = process.env.FFMPEG || "ffmpeg";
const FPS = 30;
const OUT = path.join(__dirname, "out");
const url = (file, query = "") => "file:///" + path.join(__dirname, file).replace(/\\/g, "/") + "?render" + query;

function promo() {
  const window = {};
  eval(fs.readFileSync(path.join(__dirname, "config.js"), "utf8"));
  return window.PROMO;
}

function jobs() {
  const P = promo();
  const list = [
    { name: "s01_problem", file: "scenes/s01_problem.html", secs: 15 },
    { name: "s02_title", file: "scenes/s02_title.html", secs: 10 },
    { name: "s04_pipeline", file: "scenes/s04_pipeline.html", secs: 9 },
    { name: "s09b_effort", file: "scenes/s09b_effort.html", secs: 8 },
    { name: "s10_endcard", file: "scenes/s10_endcard.html", secs: 12 },
  ].map((j) => ({ ...j, out: path.join(OUT, "scenes", j.name + ".mp4") }));
  P.captions.forEach((_, i) => {
    const n = String(i + 1).padStart(2, "0");
    list.push({ name: "captions_" + n, file: "scenes/lower_third.html", query: "&i=" + i, secs: 4, alpha: true,
                out: path.join(OUT, "captions", n) });
  });
  P.slates.forEach((s, i) => {
    list.push({ name: "slates_s" + String(s.n).padStart(2, "0"), file: "scenes/slate.html", query: "&i=" + i,
                secs: s.secs, still: true, out: path.join(OUT, "slates", "s" + String(s.n).padStart(2, "0") + ".mp4") });
  });
  return list;
}

function ffmpeg(args) {
  const p = spawn(FFMPEG, ["-y", "-loglevel", "error", ...args], { stdio: ["pipe", "inherit", "inherit"] });
  const done = new Promise((res, rej) => p.on("close", (c) => (c === 0 ? res() : rej(new Error("ffmpeg exit " + c)))));
  return { stdin: p.stdin, done };
}

async function open(browser, job) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 1 });
  await page.goto(url(job.file, job.query || ""), { waitUntil: "networkidle0" });
  await page.evaluate(() => window.__ready);
  return page;
}

async function shot(page, ms, alpha) {
  await page.evaluate((t) => window.__seek(t), ms);
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  return page.screenshot(alpha ? { type: "png", omitBackground: true } : { type: "jpeg", quality: 95 });
}

async function render(browser, job) {
  fs.mkdirSync(path.dirname(job.out), { recursive: true });
  const page = await open(browser, job);
  const frames = Math.round(job.secs * FPS);
  if (job.still) {
    const png = job.out.replace(/\.mp4$/, ".png");
    fs.writeFileSync(png, await shot(page, 0, false));
    await ffmpeg(["-loop", "1", "-framerate", String(FPS), "-i", png, "-t", String(job.secs),
                  "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", job.out]).done;
    fs.unlinkSync(png);
  } else if (job.alpha) {
    // Frames to a temp folder, then two encodes with alpha: ProRes 4444 (.mov) and VP9 (.webm).
    const tmp = job.out + "_frames";
    fs.mkdirSync(tmp, { recursive: true });
    for (let f = 0; f < frames; f++) {
      fs.writeFileSync(path.join(tmp, String(f).padStart(5, "0") + ".png"), await shot(page, (f * 1000) / FPS, true));
    }
    const input = ["-framerate", String(FPS), "-i", path.join(tmp, "%05d.png")];
    await ffmpeg([...input, "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", job.out + ".mov"]).done;
    await ffmpeg([...input, "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "4M", job.out + ".webm"]).done;
    fs.rmSync(tmp, { recursive: true, force: true });
  } else {
    const enc = ffmpeg(["-f", "image2pipe", "-framerate", String(FPS), "-c:v", "mjpeg", "-i", "-",
                        "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", job.out]);
    for (let f = 0; f < frames; f++) {
      const buf = await shot(page, (f * 1000) / FPS, false);
      if (!enc.stdin.write(buf)) await new Promise((r) => enc.stdin.once("drain", r));
    }
    enc.stdin.end();
    await enc.done;
  }
  await page.close();
}

(async () => {
  const args = process.argv.slice(2);
  const browser = await puppeteer.launch({ headless: "new", args: ["--allow-file-access-from-files", "--hide-scrollbars"] });
  try {
    if (args[0] === "--still") {
      const job = jobs().find((j) => j.name.includes(args[1]));
      const page = await open(browser, job);
      const file = path.join(OUT, "stills", `${job.name}_${args[2]}s.png`);
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(file, await shot(page, parseFloat(args[2]) * 1000, !!job.alpha));
      console.log(file);
      return;
    }
    const todo = jobs().filter((j) => !args.length || args.some((a) => j.name.includes(a)));
    for (const job of todo) {
      const t = Date.now();
      await render(browser, job);
      console.log(`${job.name}  ${((Date.now() - t) / 1000).toFixed(0)} s  → ${path.relative(__dirname, job.out)}`);
    }
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e); process.exit(1); });
