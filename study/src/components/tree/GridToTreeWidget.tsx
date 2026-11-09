'use client';

import React, { useMemo, useState } from 'react';
import { buildModel, childrenOf } from '@/lib/tree/tree';
import { WidgetFrame, Toggle, LookFor, Stat, Legend } from '../flood/ui';
import {
  PRESETS, GridView, TreeView, PresetButtons, RoleLegend, roles, ROLE_TEXT, cellName,
  pathToOutlet, upstreamOf, d8Label, T,
} from './shared';

type Mode = 'watershed' | 'whole';

export default function GridToTreeWidget() {
  const [preset, setPreset] = useState('tributaries');
  const [z, setZ] = useState<number[]>(() => [...PRESETS.tributaries.z]);
  const [mode, setMode] = useState<Mode>('watershed');
  const [edit, setEdit] = useState(false);
  const [sel, setSel] = useState<number | null>(null);
  const [showUp, setShowUp] = useState(true);
  const { ny, nx } = PRESETS[preset];

  const m = useMemo(() => buildModel(z, ny, nx, mode === 'whole'), [z, ny, nx, mode]);
  const rl = useMemo(() => roles(m), [m]);
  const kids = useMemo(() => childrenOf(m.dsIdx), [m]);

  const selActive = sel !== null && m.pos[sel] >= 0;
  const path = useMemo(() => (selActive ? pathToOutlet(m, sel!) : undefined), [m, sel, selActive]);
  const up = useMemo(() => (selActive && showUp ? upstreamOf(m, sel!) : undefined), [m, sel, selActive, showUp]);

  const choose = (k: string) => { setPreset(k); setZ([...PRESETS[k].z]); setSel(null); setMode(k === 'ridge' ? 'whole' : 'watershed'); };
  const onCell = (f: number, button: number) => {
    if (edit) {
      setZ((old) => old.map((v, i) => (i === f ? Math.min(15, Math.max(0, v + (button === 2 ? -1 : 1))) : v)));
    }
    setSel(f);
  };

  const nAct = m.order.length;
  const count = (r: string) => rl.filter((x) => x === r).length;
  const p = selActive ? m.pos[sel!] : -1;
  const raised = m.filled.filter((v, i) => v > m.z[i] + 1e-9).length;

  return (
    <WidgetFrame
      title="From arrows to a tree"
      idea="Every cell sends its water to exactly one neighbour. Draw those arrows as a family tree and the outlet is the root that every cell shares."
    >
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <PresetButtons value={preset} onChange={choose} />
        <Toggle label="Area" value={mode} onChange={(v) => { setMode(v); setSel(null); }}
          options={[{ value: 'watershed', label: 'One watershed' }, { value: 'whole', label: 'Whole DEM' }]} />
        <label className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-600 cursor-pointer">
          <input type="checkbox" checked={edit} onChange={(e) => setEdit(e.target.checked)} className="accent-sky-600" />
          ✏️ Edit terrain (click +1 m, right-click −1 m)
        </label>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] items-start">
        <div>
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1.5">The map (D8 arrows)</p>
          <GridView m={m} selected={sel} onCell={onCell} path={path} subtree={up} />
          <p className="text-[11px] text-slate-500 mt-1">
            Letter = cell name · number = elevation (m){raised ? ' · ↑ and orange frame = raised by pit filling' : ''} · hatched = outside the area
          </p>
        </div>
        <div>
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1.5">The same cells as a tree</p>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-2">
            <TreeView m={m} selected={sel} onNode={setSel} path={path} subtree={up} />
          </div>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <RoleLegend />
            <label className="inline-flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer">
              <input type="checkbox" checked={showUp} onChange={(e) => setShowUp(e.target.checked)} className="accent-sky-600" />
              shade everything upstream of the picked cell
            </label>
          </div>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-slate-200 p-4 text-sm text-slate-700 min-h-[120px]">
          {p < 0 ? (
            <p className="text-slate-500">
              {sel !== null ? `Cell ${cellName(sel)} is outside the area, so it is not in the tree. ` : ''}
              Pick a cell on the map or in the tree to see where its water goes.
            </p>
          ) : (
            <>
              <p className="font-semibold text-slate-900 mb-1">
                Cell {cellName(sel!)} <span className="font-normal text-slate-500">(row {Math.floor(sel! / nx)}, col {sel! % nx})</span>
              </p>
              <ul className="space-y-0.5 text-[13px]">
                <li>Role: <b>{ROLE_TEXT[rl[p]]}</b></li>
                <li>Flow direction: <span className="font-mono">{m.dsIdx[p] < 0 ? 'none: the water leaves the area here' : d8Label(m.d8[sel!])}</span></li>
                <li>Sends water to: <b>{m.dsIdx[p] < 0 ? '—' : cellName(m.order[m.dsIdx[p]])}</b> (always exactly one cell, or none at a root)</li>
                <li>Receives water from: <b>{kids[p].length ? kids[p].map((k) => cellName(m.order[k])).join(', ') : 'nobody'}</b></li>
                <li>Cells draining through it (flow accumulation): <b>{m.fa[sel!]}</b></li>
                <li>Hops to the outlet: <b>{(path?.size ?? 1) - 1}</b></li>
              </ul>
            </>
          )}
        </div>
        <div className="grid grid-cols-3 gap-2 content-start">
          <Stat label="cells" value={nAct} />
          <Stat label="arrows" value={nAct - m.roots.length} tone="sky" />
          <Stat label="roots" value={m.roots.length} tone={m.roots.length > 1 ? 'red' : 'slate'} />
          <Stat label="leaves" value={count('leaf')} />
          <Stat label="confluences" value={count('confluence')} />
          <Stat label="trees" value={m.roots.length === 1 ? '1 tree' : `${m.roots.length} (a forest)`} />
        </div>
      </div>

      <div className="mt-3">
        <Legend items={[
          { swatch: T.edge, label: 'arrow = "flows to"' },
          { swatch: T.path, label: 'path of the picked cell to the outlet' },
          { swatch: T.subtree, label: 'upstream of the picked cell (its watershed)' },
        ]} />
      </div>

      <LookFor items={[
        <>Count the arrows leaving any cell: always <b>one</b>, or zero at a root. That is all it takes to be a tree. <b>arrows = cells − roots</b>, every time.</>,
        <>Arrows can <b>merge</b> (a confluence ◇) but never split, and they never loop back, so there is exactly one way down from every cell.</>,
        <>Switch to <b>Whole DEM</b> on the ridge: every edge cell that water leaves from is its own root, giving several trees side by side (a <b>forest</b>). Edit the terrain and the tree rebuilds.</>,
      ]} />
    </WidgetFrame>
  );
}
