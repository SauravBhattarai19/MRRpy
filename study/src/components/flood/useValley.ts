'use client';

// Loads the course's synthetic valley once (a lazily loaded JSON chunk) and
// builds its HAND network with the same code MRRpy uses (src/lib/flood/hand).

import { useEffect, useState } from 'react';
import { decodeZ, valleyGrid, specificQ, type HandGrid, type ValleyData } from '@/lib/flood/hand';
import { hillshade } from './ui';

export interface Valley {
  data: ValleyData;
  z: Float64Array;
  grid: HandGrid;
  shade: Float32Array;
  /** discharge at every river cell for a flood of 1 m³/s per km² */
  q1: Float64Array;
}

let cache: Promise<Valley> | null = null;

export function loadValley(): Promise<Valley> {
  if (!cache) {
    cache = import('@/data/ch7/valley.json').then((m) => {
      const data = (m.default ?? m) as unknown as ValleyData;
      const z = decodeZ(data.z_cm, data.zmin);
      const grid = valleyGrid(data, z);
      return { data, z, grid, shade: hillshade(z, data.ny, data.nx, data.dx, 2), q1: specificQ(grid, 1) };
    });
  }
  return cache;
}

export function useValley(): Valley | null {
  const [v, setV] = useState<Valley | null>(null);
  useEffect(() => {
    let live = true;
    loadValley().then((x) => live && setV(x));
    return () => { live = false; };
  }, []);
  return v;
}
