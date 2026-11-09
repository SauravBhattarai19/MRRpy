// Checks the browser D8-tree code (src/lib/tree/tree.ts) against MRRpy itself.
//
//   node scripts/check_tree_lib.ts          (Node ≥ 23: runs TypeScript directly)
//
// The expected arrays come from scripts/export_ch3b.py (MRRpy's own functions on
// the same small DEMs). Exits non-zero on any mismatch.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import {
  fillDepressions, upstreamArea, basinMask, topologicalOrder, buildDownstreamMap,
  strahlerOrder, mcSweep, sweepSolve, scatterAdd, buildModel, eliminationFill, childrenCsr,
} from '../src/lib/tree/tree.ts';

const here = dirname(fileURLToPath(import.meta.url));
const presets = JSON.parse(readFileSync(join(here, '../src/data/ch3b/presets.json'), 'utf8'));
const exp = JSON.parse(readFileSync(join(here, 'fixtures/ch3b_expected.json'), 'utf8'));

let fails = 0;
function check(name: string, ok: boolean, detail = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  ' + detail : ''}`);
  if (!ok) fails++;
}
const same = (a: ArrayLike<number>, b: ArrayLike<number>) =>
  a.length === b.length && Array.from(a).every((v, i) => v === b[i]);
function maxDiff(a: ArrayLike<number>, b: ArrayLike<number>) {
  let m = 0;
  for (let i = 0; i < a.length; i++) m = Math.max(m, Math.abs(a[i] - b[i]));
  return m;
}
// Topological orders may differ among cells with equal accumulation (NumPy's
// argsort is not stable); require the same accumulation at every position and
// that every cell's downstream cell comes later.
function sameOrderUpToTies(a: number[], b: number[], fa: number[]) {
  return a.length === b.length && a.every((c, i) => fa[c] === fa[b[i]]) &&
    new Set(a).size === a.length && b.every((c) => a.includes(c));
}

for (const [name, p] of Object.entries<any>(presets)) {
  const e = exp[name];
  const { ny, nx, z } = p;
  const { filled, d8 } = fillDepressions(z, ny, nx);
  check(`${name}: filled DEM`, maxDiff(filled, e.filled) === 0);
  check(`${name}: D8 codes`, same(d8, e.d8));
  const fa = upstreamArea(d8, ny, nx);
  check(`${name}: flow accumulation`, same(fa, e.fa));
  const mask = basinMask(d8, ny, nx, e.outlet);
  check(`${name}: watershed mask`, same(mask.map(Number), e.mask));

  const order = topologicalOrder(fa, mask);
  check(`${name}: topological order`, sameOrderUpToTies(order, e.order, fa));
  const ds = buildDownstreamMap(order, d8, mask, ny, nx);
  const dsFlat = order.map((_, i) => (ds[i] >= 0 ? order[ds[i]] : -1));
  check(`${name}: downstream map`, order.every((c, i) => dsFlat[i] === e.ds_flat[c]));
  check(`${name}: ds_idx[i] > i`, ds.every((d, i) => d < 0 || d > i));
  const st = strahlerOrder(ds);
  check(`${name}: Strahler order`, order.every((c, i) => st[i] === e.strahler[c]));

  const wmask = new Array(ny * nx).fill(true);
  const word = topologicalOrder(fa, wmask);
  const wds = buildDownstreamMap(word, d8, wmask, ny, nx);
  const wflat = word.map((_, i) => (wds[i] >= 0 ? word[wds[i]] : -1));
  const ewflat: Record<number, number> = {};
  (e.whole_order as number[]).forEach((c, i) => { ewflat[c] = e.whole_ds_flat[i]; });
  check(`${name}: whole-DEM forest`, sameOrderUpToTies(word, e.whole_order, fa) &&
    word.every((c, i) => wflat[i] === ewflat[c]));

  const m = buildModel(z, ny, nx);
  check(`${name}: buildModel agrees`, same(m.order, order) && same(m.dsIdx, ds));

  const mc = e.mc;
  const r = mcSweep(mc.C0, mc.C1, mc.C2, mc.C3, mc.I1, mc.O1, mc.QL, mc.ds_idx);
  check(`${name}: Muskingum–Cunge sweep`, maxDiff(r.O2, mc.O2) < 1e-12 && maxDiff(r.I2, mc.I2) < 1e-12 && r.neg === mc.neg,
    `max diff ${maxDiff(r.O2, mc.O2).toExponential(1)}`);
  const csr = childrenCsr(mc.ds_idx);
  check(`${name}: children CSR`, same(csr.childOff, mc.child_off) && same(csr.childIdx, mc.child_idx));
}

(exp._random as any[]).forEach((e, k) => {
  const { filled, d8 } = fillDepressions(e.z, 7, 7);
  const raised = filled.filter((v, i) => v > e.z[i]).length;
  check(`random DEM ${k}: fill, D8, accumulation (${raised} cells raised)`,
    maxDiff(filled, e.filled) === 0 && same(d8, e.d8) && same(upstreamArea(d8, 7, 7), e.fa));
});

const s = exp._solve;
const isRoot = s.parent.map((p: number) => p < 0);
const zz = sweepSolve(s.diag, s.off, s.parent, isRoot, s.rhs);
check('tree solve vs MRRpy', maxDiff(zz, s.z) < 1e-12, `max diff ${maxDiff(zz, s.z).toExponential(1)}`);
const n = s.diag.length;
let resid = 0;
for (let i = 0; i < n; i++) {
  let row = s.diag[i] * zz[i];
  if (!isRoot[i]) row += s.off[i] * zz[s.parent[i]];
  for (let j = 0; j < n; j++) if (s.parent[j] === i) row += s.off[j] * zz[j];
  resid = Math.max(resid, Math.abs(row - s.rhs[i]));
}
check('tree solve residual', resid < 1e-12, `max |Mz − b| ${resid.toExponential(1)}`);

const dst = [0, 0, 0];
scatterAdd(dst, [2, 2, 1], [1, 2, 4]);
check('scatter_add adds at a confluence', same(dst, [0, 4, 3]));

const tree = s.parent.flatMap((p: number, i: number) => (p >= 0 ? [[i, p]] : []));
check('no fill-in on a tree', eliminationFill(n, tree).length === 0);
check('fill-in once a cell has two downstream links', eliminationFill(4, [[0, 2], [0, 3], [1, 3]]).length === 1);

if (fails) { console.log(`${fails} check(s) failed`); process.exit(1); }
