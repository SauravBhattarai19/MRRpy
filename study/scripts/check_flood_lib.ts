// Checks the browser HAND code (src/lib/flood/hand.ts) against MRRpy itself.
//
//   node scripts/check_flood_lib.ts          (Node ≥ 23: runs TypeScript directly)
//
// The expected arrays come from scripts/export_ch7.py (MRRpy's own functions on
// the same synthetic valley). Exits non-zero on any mismatch.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { valleyGrid, floodMap, specificQ, type ValleyData } from '../src/lib/flood/hand.ts';

const here = dirname(fileURLToPath(import.meta.url));
const valley: ValleyData = JSON.parse(readFileSync(join(here, '../src/data/ch7/valley.json'), 'utf8'));
const exp = JSON.parse(readFileSync(join(here, 'fixtures/ch7_expected.json'), 'utf8'));

let fails = 0;
function check(name: string, ok: boolean, detail = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  ' + detail : ''}`);
  if (!ok) fails++;
}
function maxDiff(a: ArrayLike<number>, b: ArrayLike<number>) {
  let m = 0;
  for (let i = 0; i < a.length; i++) m = Math.max(m, Math.abs(a[i] - b[i]));
  return m;
}
// partitions equal up to renumbering (reach ids depend on traversal order)
function samePartition(a: ArrayLike<number>, b: ArrayLike<number>) {
  const ab = new Map<number, number>(), ba = new Map<number, number>();
  for (let i = 0; i < a.length; i++) {
    if ((a[i] < 0) !== (b[i] < 0)) return false;
    if (a[i] < 0) continue;
    if (ab.has(a[i]) && ab.get(a[i]) !== b[i]) return false;
    if (ba.has(b[i]) && ba.get(b[i]) !== a[i]) return false;
    ab.set(a[i], b[i]); ba.set(b[i], a[i]);
  }
  return true;
}

const t0 = performance.now();
const g = valleyGrid(valley);
const fm = floodMap(g, specificQ(g, valley.qSpecific));
const ms = performance.now() - t0;

const d8Diff = g.d8.reduce((s, v, i) => s + (v !== exp.d8[i] ? 1 : 0), 0);
check('least-cost D8 directions identical', d8Diff === 0, `${d8Diff} cells differ`);
check('drainage area', maxDiff(g.area, exp.area) < 1e-5, `max diff ${maxDiff(g.area, exp.area).toExponential(2)} km²`);
check('reach slope', maxDiff(g.slopeReach, exp.slopeReach) < 1e-12);
check('number of levels', fm.levels.length === exp.levels.length, `${fm.levels.length} vs ${exp.levels.length}`);
fm.levels.forEach((lev, k) => {
  const e = exp.levels[k];
  const hand = Float64Array.from(lev.hand, (h) => (Number.isNaN(h) ? -1 : h));
  check(`level ${k}: HAND`, maxDiff(hand, e.hand) < 1e-4, `max diff ${maxDiff(hand, e.hand).toExponential(2)} m`);
  check(`level ${k}: reaches (${lev.nReach})`, lev.nReach === e.nReach && samePartition(lev.cellReach, e.cellReach));
  // compare per-reach values through the partition mapping (first cell of each reach)
  const map = new Map<number, number>();
  lev.cellReach.forEach((r, i) => { if (r >= 0 && !map.has(r)) map.set(r, e.cellReach[i]); });
  let dS = 0, dQ = 0, dStage = 0, dCurve = 0;
  for (const [r, re] of map) {
    dS = Math.max(dS, Math.abs(lev.S[r] - e.S[re]));
    dQ = Math.max(dQ, Math.abs(lev.qPeak[r] - e.qPeak[re]));
    dStage = Math.max(dStage, Math.abs(lev.stage[r] - e.stagePeak[re]));
    dCurve = Math.max(dCurve, maxDiff(lev.rating.Q[r], e.Q[re]) / Math.max(...e.Q[re]));
  }
  check(`level ${k}: reach slope / peak Q`, dS < 1e-12 && dQ < 1e-6, `dS ${dS.toExponential(1)}, dQ ${dQ.toExponential(1)}`);
  check(`level ${k}: rating curves`, dCurve < 1e-9 && lev.rating.y.length === e.y.length, `rel. diff ${dCurve.toExponential(1)}`);
  check(`level ${k}: stages`, dStage < 1e-9, `max diff ${dStage.toExponential(1)} m`);
});
check('flood depth map', maxDiff(fm.depth, exp.depth) < 1e-4, `max diff ${maxDiff(fm.depth, exp.depth).toExponential(2)} m`);
console.log(`(browser code: ${ms.toFixed(0)} ms for the whole map, ${g.n} cells)`);
process.exit(fails ? 1 : 0);
