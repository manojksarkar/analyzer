# Promo video — graphics

The non-recorded parts of the promo video, made as HTML animations and rendered to video. The script
is the Claude Doc "ASPICE Analyzer — Promo Video Script".

| File | What it is | Length |
|---|---|---|
| `out/scenes/s01_problem.mp4` | Scene 1: writing an interface table by hand, weeks ticking, "Weeks of documents. Every release." | 15 s |
| `out/scenes/s02_title.mp4` | Scene 2: "What if your code could document itself — to ASPICE?" → logo and name | 10 s |
| `out/scenes/s04_pipeline.mp4` | Scene 4 insert: C++ code → one model → SWE.3 / SWE.4, Parse → Derive → Views → Export | 9 s |
| `out/scenes/s09b_effort.mp4` | Effort card: by hand vs. with the product, per component | 8 s |
| `out/scenes/s10_endcard.mp4` | End card: tagline, features, Book a demo | 12 s |
| `out/captions/NN.mov` / `.webm` | Lower-third captions with a transparent background (ProRes 4444 / VP9) | 4 s each |
| `out/slates/sNN.mp4` | Placeholders where a screen recording goes | per scene |
| `out/vo/sNN.wav` | Scratch voice-over (Windows text-to-speech), for timing only | — |
| `out/animatic.mp4` | Everything above joined into the 3-minute cut | ~3:03 |

## Change and re-render

1. Edit `config.js`: product name, tagline, contact, captions, and the effort numbers —
   `manualValue` / `autoValue` still read `[X] days` / `[Y] min` until measured.
2. `node render.js` (all) or `node render.js s09b captions` (only those). Check one frame with
   `node render.js --still s01 12`.
3. `powershell -File make_vo.ps1`, then `python build_animatic.py`.

`render.js` uses puppeteer from the repo root and ffmpeg from `PATH` or the `FFMPEG` variable. Any scene
also plays live in a browser (open the HTML file without `?render`), so it can be screen-recorded instead.

## In the editor

Lay out the animatic, then replace each slate with its recording. Captions go on a track above the
recording; the `.mov` files keep their transparency in Premiere, DaVinci Resolve and Final Cut, and the
`.webm` files in browser-based editors. Replace the scratch voice-over with a real voice before release.
