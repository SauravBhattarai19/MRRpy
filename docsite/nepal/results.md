# Reading the results

A study gives one table: a row per method, a column per return period. Next to
it come the **official range**, the **warnings**, a **chart** and a **report**.
This page explains every part, and every rule that decides a method's status.

## The table

| Column | Meaning |
|---|---|
| `method` | the method's name (the index) |
| `key` | its short key (`wecs_dhm`, `rational`, …) |
| `group` | `regional`, `rainfall`, `gauge` or `comparison` |
| `status` | whether the method can be used here (below) |
| `Q2`, `Q5`, … | the flood in m³/s, to 4 significant figures; empty where the method gives nothing |
| `flags` | which values are interpolated or extrapolated, e.g. `Q10 interpolated; Q500 extrapolated` |
| `notes` | the validity notes, the assumptions and the intermediate values (e.g. $t_c$ and $C$ for Rational, $p$ for Modified Dickens) |

Floods are rounded to 4 significant figures because they are not known better
than that.

### Status

| Status | Meaning | In the official range? |
|---|---|---|
| *ok* | inside the method's stated range | yes, for regional peak methods |
| *use with caution* | usable, with a caveat in the notes | yes, for regional peak methods |
| *outside its range* | computed, but outside the range the method was made for | no |
| *needs input* | something is missing or unusable; the notes say what | no |
| *not run* | the physics model, when it was not run | no |
| *comparison only* | Dickens, Ryves, Inglis | never |

A method never stops the study with an error: a missing rainfall or a bad
input becomes *needs input* with a plain note, and the other methods still run.

### The validity rules

| Method | *outside its range* when | *use with caution* when |
|---|---|---|
| WECS/DHM 1990 | — | $A$ < 100 km² (AEPC); a Chure/Terai stream (class III) |
| DHM 2004 | $A_{3000}$ = 0 | a Chure/Terai stream |
| MHSP 1997 | — | $A$ < 100 km², or a Chure/Terai stream |
| Modified Dickens | $p \ge 1185$ (about $A$ < 0.5 km² without snow) | no snow and $A$ < 100 km² |
| Specific discharge | $A$ < 12 km² | — |
| Rational | $A$ > 50 km² (WECS 2019) | 12 < $A$ ≤ 50 km² |
| Area ratio | — | $A_{site}/A_{donor}$ outside 0.5–2 |
| Frequency analysis | — (fewer than 10 years: *needs input*) | notes for fewer than 20 years |
| WECS/DHM daily, physics | — | — |

The river class (I, II, III) is explained under
[catchment numbers](catchment.md#river-class).

### Flags: `≈` and `*`

| Flag | Shown as | When |
|---|---|---|
| interpolated | `≈` | MHSP and specific discharge between their tabulated return periods ([how](regional-formulas.md#tabulated)) |
| rain interpolated | `≈` | Rational, at a return period between two typed rainfalls ([how](rainfall-methods.md#typed-rainfall)) |
| extrapolated | `*` | WECS/DHM, DHM 2004 and WECS/DHM daily beyond 100 years; frequency analysis and fitted rainfall beyond twice the record length |
| not tabulated | – | MHSP or specific discharge outside its tabulated span: no value |
| no rainfall for this T | – | Rational beyond the typed rainfalls: no value |
| no donor flood for this T | – | area ratio at a return period with no typed donor flood: no value |

In the CSV the numbers stay numbers and the `flags` column says which are
marked. In the Markdown table and the report they carry `≈` or `*`.

## The official range {#official-range}

The **official range** collects, for each return period, the methods that
count as official evidence:

* in the *regional* group (WECS/DHM, DHM 2004, MHSP, Modified Dickens, specific
  discharge);
* giving an instantaneous **peak** (WECS/DHM daily is left out);
* with status *ok* or *use with caution*;
* with a value at that return period.

For those values it gives:

| Column | Meaning |
|---|---|
| `n_methods` | how many methods contribute |
| `min`, `median`, `max` | the range and its middle |
| `spread` | max ÷ min (when at least 2 methods contribute) |
| `methods` | which ones |

The Rational method, the physics model, frequency analysis and the area ratio
are *compared* with the range, not part of it. They use other information
(rainfall, a gauge), so they are the independent check the range is measured
against.

**Where a method sits.** `estimates.compare("physics")` (or any other key) gives,
for each return period, the method's value, the range, its position (`inside`,
`above` or `below`) and its ratio to the official median. The report writes this
out for the physics model:

```text
It is below the official range (4.169–15.77 m³/s), 0.3196× the official median.
```

**A wide range.** When max ÷ min is more than 3, the methods disagree enough
that the choice must be explained, and the result carries a warning.

## Warnings

`result.warnings()` (and the report's *Warnings* section) lists, in order:

1. a Chure/Terai stream (class III): "the national regional formulas use area
   only here and were fitted to few such catchments; rainfall-based methods,
   the physics model and local flood marks deserve more weight";
2. each method *outside its range*, with the reason;
3. the return periods where the official methods differ by more than a factor
   of 3.

## The recommendation

`result.recommendation` is the compendium's quick guide (§7) applied to this
catchment and the data you gave. It is written whatever methods you chose, so it
works as a check. See [manuals and recommendations](guidelines.md#recommend).

## The chart

`result.plot()` draws flood against return period on a log scale:

* each official method as a thin grey line;
* the official range shaded, with the median as a blue line;
* the methods that carry the story in their own colours, always the same for
  each method: the physics model (orange, with its values labelled), frequency
  analysis (green, with its confidence band), the Rational method and the
  donor gauge;
* observed floods (flood marks) as horizontal reference lines.

The chart is saved next to the table, which is its accessible twin, so the
chart labels sparingly. `result.plot(theme="dark")` draws it for a dark
background.

## The report

`result.report()` returns the whole study as Markdown (saved as
`nepal_report.md`):

1. **Catchment**: every number, with what was assumed;
2. **Design basis**: the manual and its methods (and those not yet in
   MRRpy-Nepal), the structure with its design flood and freeboard, the return
   periods;
3. **Flood estimates**: the table with `≈` and `*`;
4. **Official range**: per return period, the number of methods, min, median,
   max and spread;
5. **Physics model**: one line per design storm, with its place against the
   range and the folder of its files;
6. **Notes by method**: status, notes, formula, who uses it and the source
   caveat of the compendium;
7. **Warnings**, **What the compendium recommends**, **Observed floods** and
   **Files**.

It is a starting point for the hydrology chapter of a design report, not a
replacement for it.

## Files

`result.save(folder)` (done for you by `study.run()` when the site has a folder,
default `<results>/nepal/`, or with `-o` on the command line) writes:

| File | Content |
|---|---|
| `nepal_flood_estimates.csv` | the table |
| `nepal_flood_estimates.png` | the chart |
| `nepal_report.md` | the report |
| `catchment.csv` | the catchment numbers |
| `design_T<T>/` | one folder per physics run ([contents](design-floods.md#result)) |

## In code

```python
result = study.run()
result.table                       # the DataFrame above
result.envelope                    # the official range
result.estimates.compare("physics")
result.estimates.flags             # per value: '', 'interpolated', 'extrapolated', …
result.estimates.values("wecs_dhm")      # {T: Q}
result.warnings()
result.recommendation
result.plot()
print(result.report())
result.save("my_folder/")
```

A table built directly with `estimate_floods(site, methods, T, **inputs)` has
the same `table`, `envelope`, `compare`, `warnings()`, `to_csv` and
`to_markdown`.
