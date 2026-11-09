'use client';

import React, { useMemo, useState } from 'react';
import { buildModel, topologicalOrder, buildDownstreamMap, type TreeModel } from '@/lib/tree/tree';
import { WidgetFrame, Toggle, LookFor, Stat } from '../flood/ui';
import { PRESETS, GridView, PresetButtons, cellName, T } from './shared';

type Key = 'fa' | 'elev';

/** Cells sorted by elevation, highest first (Ch 1 §1.4); ties stay in map order. */
function elevationOrder(m: TreeModel) {
  return topologicalOrder(m.filled.map((z) => -z), m.mask);
}

/** One pass of flow accumulation in the given order (each cell passes its count on once). */
function onePassFa(m: TreeModel, order: number[], ds: number[]) {
  const fa = order.map(() => 1);
  for (let i = 0; i < order.length; i++) if (ds[i] >= 0) fa[ds[i]] += fa[i];
  return fa;
}

export default function FlattenOrderWidget() {
  const [preset, setPreset] = useState('flat');
  const [key, setKey] = useState<Key>('fa');
  const [hover, setHover] = useState<number | null>(null); // position
  const P = PRESETS[preset];
  const m = useMemo(() => buildModel(P.z, P.ny, P.nx), [P]);

  const order = useMemo(() => (key === 'fa' ? m.order : elevationOrder(m)), [m, key]);
  const ds = useMemo(() => buildDownstreamMap(order, m.d8, m.mask, m.ny, m.nx), [order, m]);
  const n = order.length;
  const backward = ds.map((d, i) => d >= 0 && d < i);
  const nBack = backward.filter(Boolean).length;
  const fa1 = useMemo(() => onePassFa(m, order, ds), [m, order, ds]);
  const wrong = order.map((f, i) => fa1[i] !== m.fa[f]);
  const nWrong = wrong.filter(Boolean).length;
  const posOf = new Map(order.map((f, i) => [f, i]));

  // ── strip geometry ──
  const bw = 34, gap = 4, pad = 12;
  const W = pad * 2 + n * (bw + gap) - gap;
  const span = (a: number, b: number) => Math.abs(b - a);
  const maxSpan = Math.max(1, ...ds.map((d, i) => (d >= 0 ? span(i, d) : 0)));
  const arcH = Math.min(120, 22 + maxSpan * 9);
  const H = arcH + 120;
  const by = arcH + 10;
  const cx = (i: number) => pad + i * (bw + gap) + bw / 2;

  return (
    <WidgetFrame
      title="From a map to one line of cells"
      idea={<>MRRpy keeps the cells in one list, sorted so every cell comes <b>before</b> the cell it drains to. Then <code>ds_idx[i]</code>, the position of cell i&apos;s downstream cell, is always larger than i.</>}
    >
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <PresetButtons value={preset} onChange={(k) => { setPreset(k); setHover(null); }} keys={['valley', 'tributaries', 'flat']} />
        <Toggle label="Sort the cells by" value={key} onChange={setKey}
          options={[{ value: 'fa', label: 'Flow accumulation, small first (MRRpy)' }, { value: 'elev', label: 'Elevation, high first (Ch 1)' }]} />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,5fr)] items-start">
        <div>
          <GridView m={m} size={46} showFa={key === 'fa'} selected={hover !== null ? order[hover] : null}
            label={(f) => (m.mask[f] ? `${cellName(f)} ·${posOf.get(f)}` : cellName(f))}
            onCell={(f) => setHover(posOf.has(f) ? posOf.get(f)! : null)} />
          <p className="text-[11px] text-slate-500 mt-1">Letter ·position in the list. Bottom number = the sort key ({key === 'fa' ? 'flow accumulation' : 'elevation, m'}).</p>
        </div>
        <div className="min-w-0">
          <div className="overflow-x-auto rounded-xl border border-slate-200 bg-slate-50">
            <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" className="block"
              aria-label={`The ${n} cells in one row in sort order, with an arc from each cell to its downstream cell. ${nBack} arcs point backwards.`}>
              {ds.map((d, i) => {
                if (d < 0) return null;
                const x1 = cx(i), x2 = cx(d), back = backward[i];
                const h = 14 + (span(i, d) / maxSpan) * (arcH - 22);
                const hl = hover === i || hover === d;
                const col = back ? T.backward : hl ? T.path : T.edgeSoft;
                const mid = (x1 + x2) / 2;
                return (
                  <g key={i} opacity={hover === null || hl ? 1 : 0.25}>
                    <path d={`M ${x1} ${by} C ${x1} ${by - h}, ${x2} ${by - h}, ${x2} ${by}`} fill="none"
                      stroke={col} strokeWidth={back || hl ? 2.5 : 1.6} strokeDasharray={back ? '5 3' : undefined} />
                    <polygon points={`${x2},${by} ${x2 - 4},${by - 8} ${x2 + 4},${by - 8}`} fill={col} />
                    {back && <text x={mid} y={by - h * 0.75 - 4} fontSize={12} fontWeight={700} textAnchor="middle" fill={T.backward}>✗</text>}
                  </g>
                );
              })}
              {order.map((f, i) => (
                <g key={f} onMouseEnter={() => setHover(i)} onClick={() => setHover(i)} style={{ cursor: 'pointer' }}>
                  <rect x={cx(i) - bw / 2} y={by + 2} width={bw} height={30} rx={4}
                    fill={hover === i ? '#fef3c7' : '#fff'} stroke={backward[i] ? T.backward : '#475569'} strokeWidth={backward[i] ? 2 : 1} />
                  <text x={cx(i)} y={by + 21} fontSize={13} fontWeight={700} textAnchor="middle" fill="#0f172a">{cellName(f)}</text>
                  {[`${i}`, `${Math.floor(f / m.nx)}`, `${f % m.nx}`, ds[i] < 0 ? '−1' : `${ds[i]}`, `${key === 'fa' ? m.fa[f] : +m.filled[f].toFixed(1)}`].map((t, k) => (
                    <text key={k} x={cx(i)} y={by + 48 + k * 14} fontSize={10.5} textAnchor="middle" fontFamily="monospace"
                      fill={k === 3 && backward[i] ? T.backward : '#334155'} fontWeight={k === 3 && backward[i] ? 700 : 400}>{t}</text>
                  ))}
                </g>
              ))}
            </svg>
          </div>
          <div className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 text-[11px] font-mono text-slate-600">
            <span>row 1</span><span>i: position in the list</span>
            <span>row 2–3</span><span>sorted_rows, sorted_cols: where the cell sits on the map</span>
            <span>row 4</span><span>ds_idx: position of its downstream cell (−1 = water leaves)</span>
            <span>row 5</span><span>the sort key: {key === 'fa' ? 'flow accumulation' : 'elevation'}</span>
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <Stat label="arcs pointing backwards" value={nBack === 0 ? '0 ✓' : `${nBack} ✗`} tone={nBack ? 'red' : 'green'} />
        <Stat label="flow accumulation in one pass" value={nWrong === 0 ? 'all right ✓' : `${nWrong} cells wrong ✗`} tone={nWrong ? 'red' : 'green'} />
        <Stat label="ds_idx[i] > i for every cell?" value={nBack ? 'no' : 'yes'} tone={nBack ? 'red' : 'green'} />
      </div>
      {nBack > 0 && (
        <p className="mt-2 text-[13px] text-red-800 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          ✗ On the flat, neighbours have the <b>same</b> elevation, so sorting by height cannot tell which one is upstream.
          A downstream cell landed earlier in the list than a cell that feeds it, so one pass in this order hands its water on
          before all of its water has arrived.
        </p>
      )}

      <LookFor items={[
        <>With <b>flow accumulation</b> every arc points right on every terrain. A cell always drains to a cell with a larger count, because that cell counts it plus itself.</>,
        <>Switch the flat plateau to <b>elevation</b>: dashed ✗ arcs point left. Those are the cells whose one-pass accumulation comes out wrong.</>,
        <>The map is gone: routing only needs the three rows <code>sorted_rows</code>, <code>sorted_cols</code> and <code>ds_idx</code>. Hover a box to light up its arcs.</>,
      ]} />
    </WidgetFrame>
  );
}
