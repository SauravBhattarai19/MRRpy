'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { buildModel, levelsOf, treeLayout, childrenCsr, childrenOf, type TreeModel } from '@/lib/tree/tree';
import { WidgetFrame, LookFor, Stat, Slider } from '../flood/ui';
import { PRESETS, PresetButtons, NodeShape, roles, cellName, Btn, T } from './shared';

// A synthetic basin of any size: a tilted surface with seeded bumps, filled and
// routed exactly like the small presets.
function bigBasin(N: number) {
  let s = 12345;
  const rnd = () => { s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648; };
  const bumps = Array.from({ length: 12 }, () => [rnd() * N, rnd() * N, (rnd() - 0.4) * N * 0.15, 2 + rnd() * N * 0.2]);
  const z: number[] = [];
  for (let r = 0; r < N; r++) for (let c = 0; c < N; c++) {
    let v = (N - r) * 0.6 + Math.abs(c - N / 2) * 0.4 + rnd() * 0.8;
    for (const [br, bc, h, w] of bumps) v += h * Math.exp(-((r - br) ** 2 + (c - bc) ** 2) / (2 * w * w));
    z.push(Math.round(v * 10) / 10);
  }
  return buildModel(z, N, N);
}

function LevelTree({ m, lev, upto }: { m: TreeModel; lev: number[]; upto: number }) {
  const lay = treeLayout(m.dsIdx, (p) => m.order[p] % m.nx);
  const L = Math.max(...lev);
  const slotW = 32, rowH = 46, r = 11, padL = 58, pad = 18;
  const W = padL + lay.slots * slotW + pad, H = (L + 1) * rowH + 2 * pad;
  const px = (p: number) => padL + lay.x[p] * slotW + slotW / 2;
  const py = (p: number) => pad + lev[p] * rowH + rowH / 2;
  const rl = roles(m);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img"
      aria-label={`Tree drawn by level: ${L + 1} levels for ${m.order.length} cells`}>
      {Array.from({ length: L + 1 }, (_, l) => (
        <g key={l}>
          <rect x={0} y={pad + l * rowH} width={W} height={rowH} fill={l % 2 ? '#f8fafc' : '#fff'} />
          <text x={6} y={pad + l * rowH + rowH / 2 + 4} fontSize={11} fontWeight={700} fill={l < upto ? T.good : '#475569'}>
            level {l}{l < upto ? ' ✓' : ''}
          </text>
        </g>
      ))}
      {m.dsIdx.map((d, p) => d < 0 ? null : (
        <line key={`e${p}`} x1={px(p)} y1={py(p) + r} x2={px(d)} y2={py(d) - r} stroke={T.edgeSoft} strokeWidth={1.6} />
      ))}
      {m.order.map((f, p) => {
        const done = lev[p] < upto, now = lev[p] === upto - 1;
        return (
          <g key={f}>
            <NodeShape role={rl[p]} x={px(p)} y={py(p)} r={r} fill={now ? '#fef3c7' : done ? '#dcfce7' : '#fff'}
              stroke={now ? T.current : '#334155'} strokeWidth={now ? 3 : 1.5} />
            <text x={px(p)} y={py(p) + 4} fontSize={10.5} fontWeight={700} textAnchor="middle" fill="#0f172a">{cellName(f)}</text>
          </g>
        );
      })}
    </svg>
  );
}

export default function LevelScheduleWidget() {
  const [preset, setPreset] = useState('tributaries');
  const [upto, setUpto] = useState(0);
  const [N, setN] = useState(60);
  const P = PRESETS[preset];
  const m = useMemo(() => buildModel(P.z, P.ny, P.nx, preset === 'ridge'), [P, preset]);
  const lev = useMemo(() => levelsOf(m.dsIdx), [m]);
  const L = Math.max(...lev) + 1;
  useEffect(() => setUpto(0), [preset]);

  const big = useMemo(() => {
    const bm = bigBasin(N), bl = levelsOf(bm.dsIdx);
    const per = new Array(Math.max(...bl) + 1).fill(0);
    bl.forEach((l) => per[l]++);
    return { n: bm.order.length, L: per.length, widest: Math.max(...per), last10: per.slice(-10).reduce((a, b) => a + b, 0) };
  }, [N]);

  // the confluence with the most children, for the "who writes where" panel
  const kids = childrenOf(m.dsIdx);
  let cp = 0;
  kids.forEach((k, p) => { if (k.length > kids[cp].length) cp = p; });
  const csr = childrenCsr(m.dsIdx);

  return (
    <WidgetFrame tone="slate"
      title="Could the tree sweep run in parallel?"
      idea="A cell can be folded as soon as all of its children are. Group the cells by that, and each group (a level) could be folded all at once."
    >
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <PresetButtons value={preset} onChange={setPreset} />
        <Btn onClick={() => setUpto((u) => Math.min(L, u + 1))} disabled={upto >= L}>Fold next level ▶</Btn>
        <Btn onClick={() => setUpto(0)}>⏮ Reset</Btn>
      </div>
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] items-start">
        <div className="rounded-xl border border-slate-200 overflow-hidden"><LevelTree m={m} lev={lev} upto={upto} /></div>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <Stat label="folds one at a time" value={m.order.length - m.roots.length} />
            <Stat label="rounds by level" value={L} tone="sky" />
          </div>
          <div className="rounded-xl border border-slate-200 p-3 text-[12.5px] text-slate-700 space-y-2">
            <p className="font-semibold text-slate-900">Who writes where at confluence {cellName(m.order[cp])}?</p>
            <p><b>scatter_add</b> (explicit schemes): {kids[cp].map((c) => cellName(m.order[c])).join(', ')} each <i>write</i> into {cellName(m.order[cp])} at the same moment. On a GPU that needs atomic adds.</p>
            <p><b>children list</b> (implicit assembly, <code>_build_children_csr</code>): {cellName(m.order[cp])} <i>reads</i> its own children and adds them itself, so each cell has one writer and no locks are needed.</p>
            <pre className="text-[11px] bg-slate-900 text-slate-100 rounded-lg p-2 whitespace-pre-wrap break-all">{`child_off = [${csr.childOff.join(', ')}]
child_idx = [${csr.childIdx.join(', ')}]
children of ${cellName(m.order[cp])} (position ${cp}) = child_idx[${csr.childOff[cp]}:${csr.childOff[cp + 1]}] = [${csr.childIdx.slice(csr.childOff[cp], csr.childOff[cp + 1]).join(', ')}]`}</pre>
          </div>
        </div>
      </div>

      <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <p className="text-sm font-semibold text-slate-900 mb-2">On a bigger basin</p>
        <Slider label="Synthetic basin size" value={N} min={20} max={160} step={10} display={`${N} × ${N} grid`} onChange={setN}
          hint="A tilted surface with random hills, pit-filled and routed like the presets above. The watershed of the main outlet is used." />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3">
          <Stat label="cells in the watershed" value={big.n.toLocaleString()} />
          <Stat label="levels (rounds)" value={big.L.toLocaleString()} tone="sky" />
          <Stat label="widest level" value={big.widest.toLocaleString()} />
          <Stat label="cells in the last 10 levels" value={big.last10.toLocaleString()} tone="red" />
        </div>
        <p className="text-[12.5px] text-slate-600 mt-2">
          The number of rounds is set by the longest flow path, not by the number of cells. Leaves are plentiful,
          but the levels near the outlet hold only a few cells (often just the main stem), so the last rounds have one cell each.
          MRRpy&apos;s sweep is sequential today (Ch 6 §6.8). Level scheduling is the natural next step, and this is its limit.
        </p>
      </div>

      <LookFor items={[
        <>Fold level by level: every cell of a level has all its children done already, so the whole level could go at once.</>,
        <>Rounds = levels = the longest chain of arrows, plus one. A long main stem is a long queue that no number of cores can shorten.</>,
        <>Explicit schemes <i>push</i> water to the parent (needs atomic adds at confluences); the implicit assembly lets each parent <i>pull</i> from its children.</>,
      ]} />
    </WidgetFrame>
  );
}
