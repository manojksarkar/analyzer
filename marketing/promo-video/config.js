// Everything a person may want to change before re-rendering. Edit, then: node render.js
window.PROMO = {
  product: "ArtiFex",
  tagline: "Your code, documented to ASPICE.",
  // Effort card (scene 9b). Replace with measured numbers before release.
  manualLabel: "By hand",
  manualValue: "[X] days",
  autoValue: "[Y] min",
  effortTask: "SWE.3 + SWE.4 for one component",
  contact: "contact@yourcompany.com",
  // Lower-third captions, one clip each (out/captions/NN.mov|webm).
  captions: [
    "Connect your repo",
    "Parse. Model. Document.",
    "SWE.3 — generated",
    "SWE.4 — from the same model",
    "You review. It rewrites.",
    "Word file updated in ~20 s",
    "Review. Approve. Trace.",
    "Only what changed",
  ],
  // Placeholder slates for the screen-recorded scenes (animatic only).
  slates: [
    { n: 3, secs: 20, title: "Sign in → new project", text: "Record: sign in, Projects, wizard: Remote repo, branch, cores, config import, Readiness check." },
    { n: 4, secs: 12, title: "Run & progress", text: "Record: Run dialog → Generate → Overview progress (speed-ramp)." },
    { n: 5, secs: 25, title: "SWE.3 in the reader", text: "Record: Documents page → reader: diagrams, tables, flowchart, sequence diagram." },
    { n: 6, secs: 15, title: "SWE.4 + Word files", text: "Record: SWE.4 Table A/B, download .docx, open in Word." },
    { n: 7, secs: 25, title: "Review & update", text: "Record: edit mode, correct a description and a label, Update Word files." },
    { n: 8, secs: 20, title: "Review & approval", text: "Record: assign reviewer, submit, approve, approval gauge fills." },
    { n: 9, secs: 12, title: "Next release", text: "Record: Run dialog with baseline, changed components only, Compare page." },
  ],
};
