'use client';

import React from 'react';

type Node = { id: string; x: number; y: number; confluence?: boolean };
type Edge = { from: string; to: string };

const CHANNEL_NODES: Node[] = [
  { id: '1', x: 30, y: 80 },
  { id: '2', x: 90, y: 80 },
  { id: '3', x: 150, y: 80 },
  { id: '4', x: 210, y: 80 },
  { id: '5', x: 270, y: 80 },
];
const CHANNEL_EDGES: Edge[] = [
  { from: '1', to: '2' },
  { from: '2', to: '3' },
  { from: '3', to: '4' },
  { from: '4', to: '5' },
];

const DAG_NODES: Node[] = [
  { id: '1a', x: 50, y: 30 },
  { id: '1b', x: 50, y: 130 },
  { id: '2', x: 140, y: 80, confluence: true },
  { id: '3', x: 220, y: 80 },
  { id: '4', x: 290, y: 80 },
];
const DAG_EDGES: Edge[] = [
  { from: '1a', to: '2' },
  { from: '1b', to: '2' },
  { from: '2', to: '3' },
  { from: '3', to: '4' },
];

const NODE_R = 16;
const SVG_W = 320;
const SVG_H = 170;

function nodeById(nodes: Node[], id: string): Node {
  const n = nodes.find((x) => x.id === id);
  if (!n) throw new Error(`unknown node ${id}`);
  return n;
}

function Arrow({
  nodes,
  edge,
  color = '#64748b',
}: {
  nodes: Node[];
  edge: Edge;
  color?: string;
}) {
  const a = nodeById(nodes, edge.from);
  const b = nodeById(nodes, edge.to);
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.sqrt(dx * dx + dy * dy);
  const ux = dx / len;
  const uy = dy / len;
  // start/end offset by node radius so the line doesn't run under the circles
  const x1 = a.x + ux * NODE_R;
  const y1 = a.y + uy * NODE_R;
  const x2 = b.x - ux * NODE_R;
  const y2 = b.y - uy * NODE_R;
  // arrowhead triangle at (x2, y2)
  const headLen = 9;
  const headWidth = 6;
  const bx = x2 - ux * headLen;
  const by = y2 - uy * headLen;
  const px = -uy;
  const py = ux;
  const p1 = `${x2},${y2}`;
  const p2 = `${bx + px * headWidth},${by + py * headWidth}`;
  const p3 = `${bx - px * headWidth},${by - py * headWidth}`;
  return (
    <g>
      <line x1={x1} y1={y1} x2={bx} y2={by} stroke={color} strokeWidth={2} />
      <polygon points={`${p1} ${p2} ${p3}`} fill={color} />
    </g>
  );
}

function NodeCircle({ node, color }: { node: Node; color: string }) {
  const r = node.confluence ? NODE_R + 4 : NODE_R;
  return (
    <g>
      <circle
        cx={node.x}
        cy={node.y}
        r={r}
        fill={node.confluence ? '#fef3c7' : 'white'}
        stroke={color}
        strokeWidth={node.confluence ? 3 : 2}
      />
      <text
        x={node.x}
        y={node.y + 4}
        textAnchor="middle"
        fontSize={node.confluence ? 12 : 11}
        fontWeight={node.confluence ? 700 : 600}
        fill="#1e293b"
      >
        {node.id}
      </text>
    </g>
  );
}

export default function DagVsChannelDiagram() {
  return (
    <div className="not-prose my-8 rounded-2xl border border-slate-200 bg-white shadow-xl overflow-hidden font-sans">
      <div className="bg-gradient-to-r from-indigo-700 to-violet-900 px-6 py-4">
        <h3 className="text-white font-bold text-lg tracking-tight">
          One Channel vs. a Watershed Tree
        </h3>
        <p className="text-indigo-200 text-sm mt-0.5">
          A confluence breaks the tridiagonal Thomas algorithm — but not the O(n) exact solve.
          See Chapter 6.
        </p>
      </div>

      <div className="p-6 flex flex-col lg:flex-row gap-8 items-start">
        {/* LEFT: single channel */}
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
            Single Channel (what Preissmann / Thomas assumes)
          </p>
          <svg
            width={SVG_W}
            height={SVG_H}
            viewBox={`0 0 ${SVG_W} ${SVG_H}`}
            className="block overflow-visible"
            style={{ maxWidth: '100%' }}
          >
            {CHANNEL_EDGES.map((e) => (
              <Arrow key={`${e.from}-${e.to}`} nodes={CHANNEL_NODES} edge={e} color="#4338ca" />
            ))}
            {CHANNEL_NODES.map((n) => (
              <NodeCircle key={n.id} node={n} color="#4338ca" />
            ))}
            <text x={SVG_W / 2} y={SVG_H - 8} textAnchor="middle" fontSize={10} fill="#64748b">
              each cell: exactly 1 upstream, 1 downstream neighbor
            </text>
          </svg>
          <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-3 text-xs text-indigo-800 mt-2">
            A straight chain of unknowns → the implicit system is a clean{' '}
            <strong>tridiagonal matrix</strong>, solved in one forward sweep + one
            back-substitution sweep (the Thomas algorithm from Ch. 4 §4.4). This is
            a <em>special case</em> of the tree on the right — a chain with no
            confluences.
          </div>
        </div>

        {/* RIGHT: D8 tree */}
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
            OPM&apos;s Real Domain: a D8 Flow-Direction Tree
          </p>
          <svg
            width={SVG_W}
            height={SVG_H}
            viewBox={`0 0 ${SVG_W} ${SVG_H}`}
            className="block overflow-visible"
            style={{ maxWidth: '100%' }}
          >
            {DAG_EDGES.map((e) => (
              <Arrow key={`${e.from}-${e.to}`} nodes={DAG_NODES} edge={e} color="#b45309" />
            ))}
            {DAG_NODES.map((n) => (
              <NodeCircle key={n.id} node={n} color={n.confluence ? '#b45309' : '#4338ca'} />
            ))}
            <text x={SVG_W / 2} y={SVG_H - 8} textAnchor="middle" fontSize={10} fill="#64748b">
              cell 2 is a confluence: 2 upstream neighbors, 1 downstream
            </text>
          </svg>
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-900 mt-2">
            A watershed-wide <strong>directed acyclic graph (DAG)</strong> built from D8
            steepest-descent directions. Confluences — two or more upstream cells draining
            into one downstream cell — are everywhere, not the exception.
          </div>
        </div>
      </div>

      {/* Caption */}
      <div className="px-6 pb-6">
        <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 text-sm text-slate-700">
          <strong>Why this breaks the tridiagonal trick — but not an exact O(n) solve:</strong>{' '}
          a tridiagonal solve assumes every unknown has exactly one neighbor on each side — a
          single line of cells, as in the left panel. The confluence at cell &ldquo;2&rdquo; in
          the right panel violates that: it has <em>two</em> upstream neighbors feeding it, not
          one, so its row in the system matrix has an extra nonzero entry off the main
          diagonal. Stack that across a whole watershed and the matrix is no longer
          tridiagonal.
        </div>
        <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-4 text-sm text-emerald-900 mt-3">
          <strong>Correction (this course originally said this needed a &ldquo;general sparse
          solver&rdquo; — that overstated the cost):</strong> every cell in a D8 network still
          has <em>exactly one downstream neighbor</em> — flow direction is a function, not a
          relation. That makes the whole watershed a <strong>tree</strong> (technically a
          forest, rooted at the outlet(s)), not a general graph. A tree still has a perfect
          elimination ordering (fold every leaf into its unique parent, repeat), so a{' '}
          <strong>generalized Thomas algorithm</strong> solves it exactly in O(n) with{' '}
          <em>zero fill-in</em> — a confluence just means that parent&apos;s elimination step
          sums more than one child&apos;s contribution, not that the algorithm changes
          character. Chapter 6 builds exactly this solver and runs it on a real 768,000-cell
          Himalayan watershed in under five minutes on one CPU core.
        </div>
      </div>
    </div>
  );
}
