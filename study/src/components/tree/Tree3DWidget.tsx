'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { buildModel } from '@/lib/tree/tree';
import { PRESETS, PresetButtons, elevRGB, cellName } from './shared';

// Same orthographic camera as the Ch 1 3-D viewer (DEM3DWidget):
// wx = col, wy = elev × hScale, wz = row; azimuth φ, tilt θ.
function makeProjector(az: number, tilt: number, scale: number, hScale: number, offX: number, offY: number, R: number, C: number) {
  const phi = (az * Math.PI) / 180, th = (tilt * Math.PI) / 180;
  const cP = Math.cos(phi), sP = Math.sin(phi), cT = Math.cos(th), sT = Math.sin(th);
  return (col: number, row: number, elev: number) => {
    const wx = col - (C - 1) / 2, wz = row - (R - 1) / 2, wy = elev * hScale;
    return {
      sx: (wx * cP - wz * sP) * scale + offX,
      sy: (wx * sP * sT - wy * cT + wz * cP * sT) * scale + offY,
      depth: wx * sP + wz * cP,
    };
  };
}
const LDIR = [-1 / Math.sqrt(3), 1 / Math.sqrt(3), 1 / Math.sqrt(3)];
function shadeAt(z: number[], ny: number, nx: number, r: number, c: number, h: number) {
  const g = (rr: number, cc: number) => z[Math.min(ny - 1, Math.max(0, rr)) * nx + Math.min(nx - 1, Math.max(0, cc))];
  const dzdx = (g(r, c + 1) - g(r, c - 1)) / 2, dzdy = (g(r + 1, c) - g(r - 1, c)) / 2;
  const n = [-dzdx * h, dzdy * h, 1], len = Math.hypot(...n);
  return 0.3 + 0.7 * Math.max(0, (n[0] * LDIR[0] + n[1] * LDIR[1] + n[2] * LDIR[2]) / len);
}

const CW = 560, CH = 380;
const WIDTH = [0, 2, 4.5, 7.5, 10];

export default function Tree3DWidget() {
  const ref = useRef<HTMLCanvasElement>(null);
  const [preset, setPreset] = useState('tributaries');
  const [az, setAz] = useState(205);
  const [tilt, setTilt] = useState(55);
  const [hScale, setHScale] = useState(0.45);
  const [showTree, setShowTree] = useState(true);
  const [showNames, setShowNames] = useState(true);
  const drag = useRef<{ x: number; y: number; az: number; tilt: number } | null>(null);

  const P = PRESETS[preset];
  const m = useMemo(() => buildModel(P.z, P.ny, P.nx, preset === 'ridge'), [P, preset]);

  const render = useCallback(() => {
    const cv = ref.current; if (!cv) return;
    const ctx = cv.getContext('2d'); if (!ctx) return;
    const { ny: R, nx: C } = m, z = m.filled;
    const lo = Math.min(...z), hi = Math.max(...z);
    const raw = makeProjector(az, tilt, 1, hScale, 0, 0, R, C);
    const pts = [0, C].flatMap((c) => [0, R].flatMap((r) => [lo, hi].map((e) => raw(c - 0.5, r - 0.5, e))));
    const xs = pts.map((p) => p.sx), ys = pts.map((p) => p.sy);
    const S = Math.min((CW * 0.84) / (Math.max(...xs) - Math.min(...xs) || 1), (CH * 0.8) / (Math.max(...ys) - Math.min(...ys) || 1));
    const offX = CW / 2 - ((Math.max(...xs) + Math.min(...xs)) / 2) * S;
    const offY = CH / 2 - ((Math.max(...ys) + Math.min(...ys)) / 2) * S;
    const pr = makeProjector(az, tilt, S, hScale, offX, offY, R, C);

    const bg = ctx.createLinearGradient(0, 0, 0, CH);
    bg.addColorStop(0, '#1e293b'); bg.addColorStop(1, '#0f172a');
    ctx.fillStyle = bg; ctx.fillRect(0, 0, CW, CH);

    const cells: { r: number; c: number; d: number }[] = [];
    for (let r = 0; r < R; r++) for (let c = 0; c < C; c++) cells.push({ r, c, d: pr(c + 0.5, r + 0.5, z[r * C + c]).depth });
    cells.sort((a, b) => a.d - b.d);
    const fill = (rgb: number[], k: number, a = 1) => `rgba(${rgb.map((v) => Math.round(v * k)).join(',')},${a})`;
    for (const { r, c } of cells) {
      const f = r * C + c, e = z[f], rgb = elevRGB(e, lo, hi);
      const sh = shadeAt(z, R, C, r, c, 0.6), a = m.mask[f] ? 1 : 0.45;
      const q = (cc: number, rr: number, ee: number) => pr(cc, rr, ee);
      const wall = (pts2: { sx: number; sy: number }[], k: number) => {
        ctx.beginPath(); pts2.forEach((p, i) => (i ? ctx.lineTo(p.sx, p.sy) : ctx.moveTo(p.sx, p.sy)));
        ctx.closePath(); ctx.fillStyle = fill(rgb, sh * k, a); ctx.fill();
      };
      const base = lo - 0.5;
      // all four sides, so the blocks read from any azimuth
      const zS = r < R - 1 ? z[f + C] : base, zN = r > 0 ? z[f - C] : base;
      const zE = c < C - 1 ? z[f + 1] : base, zW = c > 0 ? z[f - 1] : base;
      if (e > zS) wall([q(c, r + 1, e), q(c + 1, r + 1, e), q(c + 1, r + 1, zS), q(c, r + 1, zS)], 0.55);
      if (e > zN) wall([q(c, r, e), q(c + 1, r, e), q(c + 1, r, zN), q(c, r, zN)], 0.55);
      if (e > zE) wall([q(c + 1, r, e), q(c + 1, r + 1, e), q(c + 1, r + 1, zE), q(c + 1, r, zE)], 0.7);
      if (e > zW) wall([q(c, r, e), q(c, r + 1, e), q(c, r + 1, zW), q(c, r, zW)], 0.7);
      ctx.beginPath();
      [q(c, r, e), q(c + 1, r, e), q(c + 1, r + 1, e), q(c, r + 1, e)].forEach((p, i) => (i ? ctx.lineTo(p.sx, p.sy) : ctx.moveTo(p.sx, p.sy)));
      ctx.closePath(); ctx.fillStyle = fill(rgb, sh, a); ctx.fill();
      ctx.strokeStyle = 'rgba(0,0,0,0.2)'; ctx.lineWidth = 0.6; ctx.stroke();
    }

    if (showTree) {
      const lift = 0.15;
      const at = (f: number) => pr((f % C) + 0.5, Math.floor(f / C) + 0.5, z[f] + lift);
      // thin first so thick main stems sit on top
      const idx = m.order.map((_, i) => i).sort((a, b) => m.strahler[a] - m.strahler[b]);
      ctx.lineCap = 'round';
      for (const i of idx) {
        const d = m.dsIdx[i]; if (d < 0) continue;
        const a = at(m.order[i]), b = at(m.order[d]);
        ctx.strokeStyle = 'rgba(15,23,42,0.85)'; ctx.lineWidth = WIDTH[Math.min(m.strahler[i], 4)] + 2.5;
        ctx.beginPath(); ctx.moveTo(a.sx, a.sy); ctx.lineTo(b.sx, b.sy); ctx.stroke();
        ctx.strokeStyle = '#93c5fd'; ctx.lineWidth = WIDTH[Math.min(m.strahler[i], 4)];
        ctx.beginPath(); ctx.moveTo(a.sx, a.sy); ctx.lineTo(b.sx, b.sy); ctx.stroke();
        // arrowhead at 70 % of the way
        const mx = a.sx + (b.sx - a.sx) * 0.7, my = a.sy + (b.sy - a.sy) * 0.7;
        const L = Math.hypot(b.sx - a.sx, b.sy - a.sy) || 1, ux = (b.sx - a.sx) / L, uy = (b.sy - a.sy) / L, h = 6 + m.strahler[i];
        ctx.beginPath(); ctx.moveTo(mx + ux * h, my + uy * h);
        ctx.lineTo(mx - uy * h * 0.6, my + ux * h * 0.6); ctx.lineTo(mx + uy * h * 0.6, my - ux * h * 0.6);
        ctx.closePath(); ctx.fillStyle = '#e0f2fe'; ctx.fill();
      }
      for (const p of m.roots) {
        const a = at(m.order[p]);
        ctx.fillStyle = '#fff'; ctx.strokeStyle = '#0f172a'; ctx.lineWidth = 2;
        ctx.fillRect(a.sx - 8, a.sy - 8, 16, 16); ctx.strokeRect(a.sx - 8, a.sy - 8, 16, 16);
        ctx.fillStyle = '#0f172a'; ctx.font = 'bold 9px sans-serif'; ctx.textAlign = 'center'; ctx.fillText('out', a.sx, a.sy + 3);
      }
      if (showNames) {
        ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'center';
        m.order.forEach((f, i) => {
          if (m.dsIdx[i] < 0) return;
          const a = at(f);
          ctx.fillStyle = 'rgba(15,23,42,0.75)'; ctx.fillRect(a.sx - 13, a.sy - 20, 26, 13);
          ctx.fillStyle = '#fff'; ctx.fillText(`${cellName(f)}${m.strahler[i] > 1 ? ' ' + m.strahler[i] : ''}`, a.sx, a.sy - 10);
        });
      }
    }
    ctx.fillStyle = 'rgba(255,255,255,0.55)'; ctx.font = '11px monospace'; ctx.textAlign = 'left';
    ctx.fillText('Drag to rotate', 10, CH - 10);
  }, [m, az, tilt, hScale, showTree, showNames]);

  useEffect(() => { render(); }, [render]);

  const start = (x: number, y: number) => { drag.current = { x, y, az, tilt }; };
  const move = (x: number, y: number) => {
    if (!drag.current) return;
    setAz((((drag.current.az + (x - drag.current.x) * 0.5) % 360) + 360) % 360);
    setTilt(Math.max(12, Math.min(80, drag.current.tilt + (y - drag.current.y) * 0.25)));
  };
  const maxOrder = Math.max(...m.strahler);

  return (
    <div className="not-prose my-8 rounded-2xl border border-slate-200 bg-slate-900 shadow-xl overflow-hidden font-sans">
      <div className="bg-gradient-to-r from-slate-800 to-slate-900 px-6 py-3 border-b border-slate-700">
        <h3 className="text-white font-bold tracking-tight">The tree, lying on the terrain</h3>
        <p className="text-slate-400 text-xs mt-0.5">
          Each line is one D8 arrow. Thicker line and the number after the letter = higher Strahler order, so the main stem stands out.
        </p>
      </div>
      <div className="flex flex-col lg:flex-row">
        <canvas ref={ref} width={CW} height={CH} role="img"
          aria-label={`3-D terrain of the ${P.label} preset with its D8 tree drawn on it; highest Strahler order ${maxOrder}`}
          className="cursor-grab active:cursor-grabbing block flex-shrink-0 touch-none" style={{ width: '100%', maxWidth: CW, height: 'auto' }}
          onMouseDown={(e) => start(e.clientX, e.clientY)} onMouseMove={(e) => move(e.clientX, e.clientY)}
          onMouseUp={() => { drag.current = null; }} onMouseLeave={() => { drag.current = null; }}
          onTouchStart={(e) => start(e.touches[0].clientX, e.touches[0].clientY)}
          onTouchMove={(e) => move(e.touches[0].clientX, e.touches[0].clientY)}
          onTouchEnd={() => { drag.current = null; }} />
        <div className="flex flex-col gap-4 p-5 lg:flex-1 lg:min-w-[15rem] bg-slate-800/60 text-slate-300">
          <div className="[&_button]:!text-[11px]">
            <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2">Terrain</p>
            <PresetButtons value={preset} onChange={setPreset} />
          </div>
          {([
            ['Height ×', hScale, 0.1, 1.5, 0.05, setHScale, hScale.toFixed(2)],
            ['Azimuth', az, 0, 359, 1, setAz, `${Math.round(az)}°`],
            ['Tilt', tilt, 12, 80, 1, setTilt, `${Math.round(tilt)}°`],
          ] as const).map(([label, v, min, max, step, set, shown]) => (
            <label key={label} className="block">
              <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">{label} {shown}</span>
              <input type="range" min={min} max={max} step={step} value={v}
                onChange={(e) => (set as (x: number) => void)(Number(e.target.value))} className="w-full accent-sky-500" />
            </label>
          ))}
          <div className="space-y-2 text-sm">
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={showTree} onChange={(e) => setShowTree(e.target.checked)} className="accent-sky-500" /> Tree lines
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={showNames} onChange={(e) => setShowNames(e.target.checked)} className="accent-sky-500" /> Cell names + order
            </label>
          </div>
          <div className="text-[11px] text-slate-400 space-y-1">
            <p className="font-semibold uppercase tracking-wider">Line width = Strahler order</p>
            {[1, 2, 3].map((o) => (
              <div key={o} className="flex items-center gap-2">
                <span className="inline-block rounded-full bg-sky-300" style={{ width: 40, height: WIDTH[o] }} /> order {o}{o === 1 ? ' (headwater)' : ''}
              </div>
            ))}
            <p>Faded blocks lie outside the watershed. ▢ out = root.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
