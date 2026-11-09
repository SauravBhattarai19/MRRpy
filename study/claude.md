# PROJECT REQUIREMENTS — OPM Interactive Hydrology Course

Derived from user prompts. Follow these rules exactly when generating new modules.

---

## SYSTEM ROLE
Expert Educational Platform Developer building a **static, open-source interactive textbook**
deployed to GitHub Pages. No backend. No Python-based compute. All simulations run in the browser.

---

## TECH STACK (non-negotiable)
| Layer | Choice |
|-------|--------|
| Framework | **Next.js 14** (App Router) with `@next/mdx` |
| Content | `.mdx` files — Markdown + LaTeX via **KaTeX** (`remark-math` + `rehype-katex` + `remark-gfm`) |
| Components | **React (TSX)**, self-contained with `'use client'` |
| Visualisation | **HTML5 Canvas** for 3-D and animation; **SVG** for 2-D grids and arrows |
| Styling | **Tailwind CSS** + `@tailwindcss/typography` |
| Deploy | `output: 'export'` → static GitHub Pages |
| No D3 needed | Pure React state + Canvas/SVG is sufficient and preferred |

---

## AUDIENCE & PEDAGOGY

Dual audience — **both must be served in every module**:

| Tier | What they need |
|------|---------------|
| Undergrad | Physical analogy (2–3 sentences max), colorful interactive widget, formula in plain English |
| Grad student | Rigorous PDE / algorithm derivation, complexity analysis, failure-mode analysis |

---

## MODULE STRUCTURE (mandatory for every chapter page)

Every chapter must follow this exact sequence:

1. **Hook** — 1–3 sentence real-world analogy. No math yet.
2. **2-D Interactive Widget** — placed immediately, before any prose explanation.
3. **3-D View Widget** — drag-to-rotate Canvas rendering of the same concept.
4. **Core Math** — KaTeX equations, concise.
5. **More Interactive Calculation Widgets** — calculations revealed interactively, not in prose.
6. **Grad-level section** — algorithms, pseudocode, complexity, failure modes.
7. **Summary table** — one-liner per concept.

**Rule: widgets carry the teaching burden. Prose is framing only.**
**Rule: every prose paragraph should be replaceable by a widget. If it isn't, cut it.**

---

## WIDGET DESIGN RULES

### Interaction model
- **Left-click** on a grid cell → raise elevation (+1, max 15)
- **Right-click** on a grid cell → lower elevation (−1, min 1)
- **Drag** on a 3-D canvas → rotate view (horizontal drag = azimuth, vertical = tilt)
- **Hover** on a cell → show tooltip with coordinates and value
- All controls visible without scrolling (compact layout)

### Required tabs / modes for the DEM widget
| Tab | Behaviour |
|-----|-----------|
| 🗺 Terrain | Editable grid, elevation colormap, ± click |
| ➡ Flow Direction | D8 arrows + optional ESRI code labels + pit markers |
| 📐 Slope Calculator | Click any cell → live 8-row table (dir, code, neighbour z, distance, Δz, slope m/m, status) + 3×3 neighbourhood mini-grid. Ties highlighted amber. Winner highlighted green. |
| 💧 Raindrop | Animated flow path, step-by-step, outlet vs pit outcome |

### 3-D Widget requirements
- HTML5 Canvas, painter's-algorithm depth sort (ascending depth = far-first)
- **Correct orthographic projection**:
  - `sx = (wx·cosφ − wz·sinφ) · scale + W/2`
  - `sy = (wx·sinφ·sinθ − wy·cosθ + wz·cosφ·sinθ) · scale + H/2`
  - `depth = wx·sinφ + wz·cosφ`
  - where wx = col − (C−1)/2, wy = elev × hScale, wz = row − (R−1)/2
- Draw south and east walls where a cell is taller than its neighbour
- Hillshading: NW sun, Lambert diffuse on per-cell gradient normal
- Controls: height exaggeration slider, azimuth slider, tilt slider, flow-arrows toggle, hillshading toggle, preset buttons
- Hover shows `(row, col) z = X m` in HUD

### Flow Accumulation Widget
- Animated step-by-step: yellow = current cell, purple = downstream recipient
- FA coloring: log-scale white → sky-blue → dark navy
- Stream threshold slider reveals channel network
- Speed slider + pause + step-forward + skip-to-end controls

### Pit Fill Widget (Wang & Liu 2006)
- Side-by-side Before | After grids
- Animated heap-pop / fill steps with text log
- Low-outlet cell marked in blue
- Back / Forward step buttons (not just autoplay)
- After completion: flat-area warning

### Fail-safe rule
Every widget must catch numerical blow-up (NaN / Infinity) and display
a visible "Model Unstable" warning instead of crashing.

---

## CONTENT RULES

### Text density
- **Maximum 3 sentences of prose per section** before a widget appears.
- No long explanatory paragraphs — the widget IS the explanation.
- Callout boxes inside widgets replace sidebar text.

### Tables
- Use GFM pipe tables (`remark-gfm` is configured). Always use them for structured data.
- Never render tables as prose.

### Math
- All equations in KaTeX via `$...$` (inline) or `$$...$$` (display).
- Always show the formula first, then reference the widget for the numerical example.

### Worked examples
- Numerical worked examples belong INSIDE the widget's "Slope Calculator" or equivalent tab.
- Do NOT write static numeric examples in MDX prose.

---

## COLOUR CONVENTIONS (use consistently across all widgets)

| Meaning | Colour |
|---------|--------|
| Elevation low | `rgb(67,117,180)` — blue |
| Elevation high | `rgb(245,245,244)` — near-white/snow |
| Currently processing cell | Amber / `#fbbf24` |
| Flow path / animated raindrop | Sky blue `#93c5fd` → `#0284c7` (head) |
| Flow-to / downstream | Purple `#a78bfa` |
| Winner direction | Emerald green |
| Tie direction | Amber |
| Uphill direction | Red-tinted |
| Raised (pit-filled) cell | Orange `#fdba74` |
| Low outlet | Blue `#3b82f6` |
| Stream channel | Dark navy (high FA) |
| Flood water depth (Ch 7–9) | light blue `#DCEBF7` → navy `#0B2F5C` (`depthRGB` in `components/flood/ui.tsx`) |
| Height / HAND under flood maps | dark brown → pale yellow (YlOrBr reversed), never blue |
| Reaches, links, categories | Okabe–Ito / Tol palette (`QUAL`), always with a text legend |

Flood widgets never carry information by colour alone: wet-only-because-of, hit/miss and
similar classes also get a pattern or a text label.

---

## FILE STRUCTURE
```
study/
  src/
    app/
      layout.tsx          ← sticky nav, KaTeX CSS import
      page.tsx            ← chapter index with status badges
      chapter/
        01-dem-flow-direction/page.tsx
    components/
      dem/
        DEMFlowWidget.tsx   ← 2-D grid, 4 tabs
        DEM3DWidget.tsx     ← 3-D canvas, drag-rotate
        FlowAccumWidget.tsx ← FA animation
        PitFillWidget.tsx   ← Wang & Liu animation
    content/
      01-dem-and-flow-direction.mdx
  mdx-components.tsx        ← register all widgets here
  next.config.mjs           ← remark-math, remark-gfm, rehype-katex
  tailwind.config.ts
```

---

## CHAPTER ROADMAP

| # | Title | Status |
|---|-------|--------|
| 1 | Digital Elevation Models & Flow Direction | ✅ Done |
| 2 | Watershed Delineation | ✅ Done |
| 3 | Rainfall–Runoff (VSA + Green-Ampt) | ✅ Done |
| 3b | Interlude: The D8 Tree (grid → tree → `ds_idx` → three walks) | ✅ Done |
| 4 | Kinematic-Wave Routing | ✅ Done |
| 5 | Diffusive-Wave Routing | ✅ Done |
| 6 | Semi-Implicit Diffusive-Wave Routing | ✅ Done |
| 7 | HAND: Flood Maps from a Rating Curve | ✅ Done |
| 8 | The 2D Flood Model (local-inertial, live sandbox) | Planned |
| 9 | From a Basin Run to a Town Flood Map, and How Good It Is | Planned |

---

## FLOOD CHAPTERS (7–9): SAME NUMBERS AS THE PACKAGE

- `src/lib/flood/` is a line-by-line TypeScript port of `MRRpy/core/inundation/`
  (no relative imports, erasable TypeScript only, so Node runs it directly).
- `scripts/export_ch7.py` (run with the `mrrpy` env) writes the synthetic DEMs to
  `src/data/ch7/` and MRRpy's own results to `scripts/fixtures/`;
  `node scripts/check_flood_lib.ts` (Node ≥ 23) must print only PASS after any
  change to the port. Data JSON is loaded lazily (`import()`), never bundled into
  the page.
- Widgets live in `src/components/flood/` and share `ui.tsx` (frame, sliders,
  "look for" strip, legends, colour scales, raster canvas) and `useValley.ts`.
- Flood maps lie on the DEM as it is: never draw a channel below the DEM's
  river surface in a picture.

---

## D8-TREE INTERLUDE (3b): SAME NUMBERS AS THE PACKAGE

- `src/lib/tree/tree.ts` is a line-by-line port of the D8-tree code MRRpy runs:
  `pyflwdir.dem.fill_depressions` (D8 + fill), `upstream_area`, `terrain.topological_order`,
  `build_downstream_map`, `compute_strahler_order`, `hydraulics._mc_sweep`,
  `implicit._sweep_solve`, `implicit._build_children_csr`. Same rules as `src/lib/flood/`.
- `scripts/export_ch3b.py` (mrrpy env) writes the presets to `src/data/ch3b/presets.json`
  and MRRpy's answers to `scripts/fixtures/ch3b_expected.json`; `npm run check-tree`
  (Node ≥ 23) must print only PASS after any change to the port or the presets.
- Widgets live in `src/components/tree/` and share `shared.tsx` (grid view, tree view,
  node shapes: circle = leaf/chain, diamond = confluence, square = root).
