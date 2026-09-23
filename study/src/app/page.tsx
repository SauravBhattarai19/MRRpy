import Link from 'next/link';

const CHAPTERS = [
  {
    num: 1,
    slug: '01-dem-flow-direction',
    title: 'Digital Elevation Models & Flow Direction',
    desc: 'What a DEM is, D8 steepest-descent routing, flow accumulation, and pit filling.',
    tags: ['DEM', 'D8', 'flow direction'],
    status: 'ready',
  },
  {
    num: 2,
    slug: '02-watershed-delineation',
    title: 'Watershed Delineation',
    desc: 'Automatically extract catchment boundaries and stream networks from any DEM.',
    tags: ['watershed', 'stream network', 'pour point'],
    status: 'ready',
  },
  {
    num: 3,
    slug: '03-rainfall-runoff',
    title: 'Rainfall–Runoff Generation',
    desc: 'The Variable Source Area model, Green-Ampt infiltration, impervious shedding, and the satellite pipeline that derives every parameter.',
    tags: ['VSA', 'Green-Ampt', 'SERVES/GEE'],
    status: 'ready',
  },
  {
    num: 4,
    slug: '04-kinematic-wave',
    title: 'Kinematic-Wave Routing',
    desc: 'The shallow-water equations simplified: route floods through a river network.',
    tags: ['routing', 'kinematic wave', 'Saint-Venant'],
    status: 'ready',
  },
  {
    num: 5,
    slug: '05-diffusive-wave',
    title: 'Diffusive-Wave Routing',
    desc: 'Where kinematic wave fails, the GSSHA-style conveyance depth in OPM’s real code, and what one global timestep costs on flat terrain.',
    tags: ['diffusive wave', 'backwater', 'GSSHA'],
    status: 'ready',
  },
  {
    num: 6,
    slug: '06-semi-implicit-routing',
    title: 'Semi-Implicit Diffusive-Wave Routing',
    desc: 'Correcting Chapter 5: a D8 network is a tree, not a general graph, so an exact O(n) implicit solve exists after all — built, verified, and tested on a real Himalayan flood, stable and unstable results both shown.',
    tags: ['implicit', 'HEC-RAS', 'tree solve', 'real watershed'],
    status: 'ready',
  },
];

export default function HomePage() {
  return (
    <div className="max-w-4xl mx-auto">
      {/* Hero */}
      <div className="mb-14">
        <div className="inline-block bg-sky-100 text-sky-700 text-xs font-semibold uppercase tracking-widest px-3 py-1 rounded-full mb-4">
          Open Hydrology Course
        </div>
        <h1 className="text-5xl font-extrabold tracking-tight text-slate-900 leading-tight mb-4">
          From Mountains<br />to Streamflow
        </h1>
        <p className="text-xl text-slate-500 max-w-2xl leading-relaxed">
          An interactive, open-source textbook covering watershed hydrology and
          physics-based rainfall–runoff modelling — with browser-native simulations,
          no installation required.
        </p>
      </div>

      {/* Chapter cards */}
      <div className="space-y-4">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3">
          Chapters
        </h2>
        {CHAPTERS.map(ch => (
          <div key={ch.num}
            className={`group rounded-2xl border p-6 transition-all ${
              ch.status === 'ready'
                ? 'bg-white border-slate-200 hover:border-sky-300 hover:shadow-md cursor-pointer'
                : 'bg-slate-50 border-slate-100 opacity-60'
            }`}
          >
            {ch.status === 'ready' ? (
              <Link href={`/chapter/${ch.slug}`} className="block">
                <ChapterCard ch={ch} />
              </Link>
            ) : (
              <ChapterCard ch={ch} />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function ChapterCard({ ch }: { ch: typeof CHAPTERS[0] }) {
  return (
    <div className="flex items-start gap-5">
      <div className="flex-shrink-0 w-12 h-12 rounded-xl bg-sky-600 text-white flex items-center justify-center font-bold text-lg">
        {ch.num}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-3 mb-1">
          <h3 className="font-semibold text-slate-900 text-lg leading-tight">{ch.title}</h3>
          {ch.status === 'coming-soon' && (
            <span className="text-xs bg-slate-200 text-slate-500 px-2 py-0.5 rounded-full font-medium">
              Soon
            </span>
          )}
          {ch.status === 'ready' && (
            <span className="text-xs bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-full font-medium">
              Ready
            </span>
          )}
        </div>
        <p className="text-slate-500 text-sm leading-relaxed mb-3">{ch.desc}</p>
        <div className="flex gap-2 flex-wrap">
          {ch.tags.map(t => (
            <span key={t} className="text-xs bg-sky-50 text-sky-700 border border-sky-100 px-2 py-0.5 rounded-full">
              {t}
            </span>
          ))}
        </div>
      </div>
      {ch.status === 'ready' && (
        <div className="flex-shrink-0 text-sky-400 group-hover:text-sky-600 group-hover:translate-x-1 transition-all text-xl">
          →
        </div>
      )}
    </div>
  );
}
