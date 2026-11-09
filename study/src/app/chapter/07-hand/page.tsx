import ChapterContent from '../../../content/07-hand.mdx';
import Link from 'next/link';

export const metadata = {
  title: 'Ch.7 — HAND: Flood Maps from a Rating Curve | OPM Hydrology',
};

export default function Chapter07() {
  return (
    <article className="chapter-body">
      <div className="not-prose flex items-center gap-2 text-sm text-slate-400 mb-8">
        <Link href="/" className="hover:text-sky-600 transition-colors">Chapters</Link>
        <span>›</span>
        <span className="text-slate-600">Chapter 7</span>
      </div>

      <ChapterContent />

      <div className="not-prose mt-16 pt-8 border-t border-slate-200 flex justify-between">
        <Link
          href="/chapter/06-semi-implicit-routing"
          className="flex items-center gap-2 rounded-xl border border-slate-200 hover:border-sky-300 text-slate-600 hover:text-sky-600 px-5 py-3 text-sm font-semibold transition-colors"
        >
          ← Chapter 6 — Semi-Implicit Routing
        </Link>
        <div />
      </div>
    </article>
  );
}
