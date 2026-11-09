import ChapterContent from '../../../content/03b-d8-tree.mdx';
import Link from 'next/link';

export const metadata = {
  title: 'Interlude — The D8 Tree | OPM Hydrology',
};

export default function Chapter03b() {
  return (
    <article className="chapter-body">
      <div className="not-prose flex items-center gap-2 text-sm text-slate-400 mb-8">
        <Link href="/" className="hover:text-sky-600 transition-colors">Chapters</Link>
        <span>›</span>
        <span className="text-slate-600">Interlude 3b</span>
      </div>

      <ChapterContent />

      <div className="not-prose mt-16 pt-8 border-t border-slate-200 flex justify-between">
        <Link
          href="/chapter/03-rainfall-runoff"
          className="flex items-center gap-2 rounded-xl border border-slate-200 hover:border-sky-300 text-slate-600 hover:text-sky-600 px-5 py-3 text-sm font-semibold transition-colors"
        >
          ← Chapter 3 — Rainfall–Runoff
        </Link>
        <Link
          href="/chapter/04-kinematic-wave"
          className="flex items-center gap-2 rounded-xl bg-sky-600 hover:bg-sky-700 text-white px-5 py-3 text-sm font-semibold transition-colors"
        >
          Chapter 4 — Kinematic-Wave Routing →
        </Link>
      </div>
    </article>
  );
}
