# SampleCppProject — Test Repo for the C++ Analyzer

Sample C++ tree used to test the analyzer's **incremental document generation**
(baseline / nearest-ancestor selection + git-diff narrowed parse).

## Branch & commit structure

```
main      C1 ── C2 ── C3 ── C4 ── C5
          │     │            │
feature2 ─┘     │            │     off C1   (F2a ── F2b)
feature1 ───────┘            │     off C2   (F1a ── F1b)
feature3 ────────────────────┘     off C4   (F3a ── F3b)
```

| Commit | SHA | Change |
|---|---|---|
| C1 | `08d2f56` | 1st version of code |
| C2 | `da8a13e` | some changes |
| C3 | `3433fd6` | few more changes |
| C4 | `e26c506` | math: `multiply` + `clampPositive` |
| C5 | `d60947e` | core: `coreReset` |
| feature1 | `401f69b` → `1a78ac3` | direction + flow helpers (off C2) |
| feature2 | `1f85997` → `bf7dec2` | hub + math helpers (off C1) |
| feature3 | `59b0785` → `afa3bb6` | util + core helpers (off C4) |

## Why these fork points

Different branch points give nearest / far / divergent ancestors for one target:

- **feature3** → nearest `C4`, far `C1`, divergent `C5`
- **feature1** → nearest `C2`, far `C1`, divergent `C3/C4/C5`
- **feature2** → only ancestor `C1` (everything after diverges)
