import type { Metadata } from "next";
import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import {
  ArrowRight,
  BadgeCheck,
  BarChart3,
  Check,
  CircleAlert,
  Database,
  ExternalLink,
  FileSearch,
  GitBranch,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";

export const metadata: Metadata = {
  title: "Audit de stratégie de trading — Alpha Reality Check",
  description:
    "Audit indépendant de backtests et stratégies quantitatives : reproductibilité, biais, frais, walk-forward et verdict exploitable.",
  openGraph: {
    title: "Alpha Reality Check — votre backtest résiste-t-il au réel ?",
    description:
      "Un audit indépendant, reproductible et sans promesse de rendement. Résultat attendu : go, retravailler ou arrêter.",
  },
};

const REPO_URL = "https://github.com/Damso74/kraken-alpha-agent";
const VERDICT_URL = `${REPO_URL}/blob/phase30/observation-ops-ux/reports/PHASE31_FINAL_VERDICT.md`;
const CONTACT_URL = "https://www.linkedin.com/in/damien-credoz/";
const SAMPLE_REPORT_URL = "/alpha-reality-check-sample-report.pdf";
const AUDIT_HOME = process.env.SITE_MODE === "audit" ? "/" : "/audit";

const proof = [
  { value: "1 058", label: "tests automatisés", detail: "Suite déterministe et CI verte" },
  { value: "872", label: "configurations OOS", detail: "Walk-forward, pas de cherry-picking" },
  { value: "0 / 4", label: "overlays retenus", detail: "Après reconstruction des données" },
  { value: "2 190", label: "points funding réels", detail: "Contre 1 000 tronqués au départ" },
];

const deliverables = [
  "Reproduction du backtest dans un environnement isolé",
  "Audit des données, timestamps, look-ahead et survivorship bias",
  "Frais, slippage, turnover et capacité économique",
  "Walk-forward strict et séparation train / validation / test",
  "Placebos, puissance statistique et correction multi-tests",
  "Verdict écrit : continuer, retravailler ou arrêter",
];

const offers = [
  {
    name: "Signal Check",
    price: "190 € HT",
    lead: "3 jours ouvrés",
    summary: "Tarif fondateur limité aux trois premières missions, puis 290 € HT.",
    items: [
      "1 stratégie, 1 marché",
      "Analyse des exports fournis",
      "Contrôle des biais majeurs",
      "Note de verdict 5–8 pages, sans reproduction du code",
    ],
  },
  {
    name: "Research Audit",
    price: "790 € HT",
    lead: "7–10 jours",
    summary: "Tarif de lancement, puis 990 € HT après les trois audits fondateurs.",
    items: [
      "Reproduction complète",
      "Walk-forward + stress tests",
      "Coûts et analyse statistique",
      "Rapport technique + restitution 60 min",
    ],
    featured: true,
  },
  {
    name: "Team Review",
    price: "1 900 € HT",
    lead: "2 semaines",
    summary: "Pour un moteur, un portefeuille ou une équipe quant.",
    items: ["Jusqu'à 3 stratégies", "Revue code et exécution", "Priorités de remédiation", "2 restitutions équipe"],
  },
];

const processSteps = [
  { step: "01", title: "Cadrage privé", text: "20 minutes pour fixer la décision, les données disponibles et les critères d'arrêt." },
  { step: "02", title: "Périmètre écrit", text: "Vous validez les contrôles, le prix, le délai et les exclusions avant tout transfert." },
  { step: "03", title: "Audit reproductible", text: "Je rejoue, falsifie et documente. Aucun paramètre n'est retouché pour sauver le résultat." },
  { step: "04", title: "Verdict exploitable", text: "Rapport, priorités et restitution : continuer, corriger ou arrêter avec des raisons vérifiables." },
];

const faqs = [
  { question: "Que faut-il fournir ?", answer: "Au minimum un export de trades ou un rapport de backtest. Le code et les données sources augmentent le niveau d'assurance, mais aucune clé API n'est acceptée." },
  { question: "Pouvez-vous garantir qu'une stratégie gagnera ?", answer: "Non. L'audit mesure la solidité de la preuve disponible et les risques d'illusion. Il ne prédit pas les marchés et ne garantit aucun rendement." },
  { question: "Et si le verdict est négatif ?", answer: "Le rapport explique précisément ce qui casse, ce qui reste valable et les conditions minimales d'un nouveau test. Arrêter peut être le meilleur résultat économique." },
  { question: "Mon code restera-t-il confidentiel ?", answer: "Oui : échange privé, NDA possible, environnement isolé, aucune réutilisation pour entraîner un modèle et suppression sous 30 jours sauf accord écrit contraire." },
];

export default function AuditPage() {
  return (
    <main lang="fr" className="min-h-screen overflow-hidden bg-[#070807] text-[#f3f4ef]">
      <div aria-hidden className="pointer-events-none fixed inset-0 dot-grid opacity-60" />
      <div aria-hidden className="pointer-events-none fixed left-1/2 top-[-18rem] h-[34rem] w-[52rem] -translate-x-1/2 rounded-full bg-emerald-500/[0.08] blur-[120px]" />

      <nav className="relative z-10 mx-auto flex max-w-7xl items-center justify-between px-5 py-5 sm:px-8 lg:px-10">
        <Link href={AUDIT_HOME} className="flex items-center gap-3" aria-label="Alpha Reality Check — accueil">
          <span className="grid h-9 w-9 place-items-center rounded-lg border border-emerald-300/25 bg-emerald-300/10 text-emerald-300">
            <FileSearch className="h-4.5 w-4.5" />
          </span>
          <span>
            <span className="block text-[11px] font-semibold uppercase tracking-[0.22em] text-emerald-300">Alpha Reality Check</span>
            <span className="block text-[10px] text-zinc-500">par Damien Credoz</span>
          </span>
        </Link>
        <div className="flex items-center gap-2">
          <a href="#methode" className="hidden rounded-lg px-3 py-2 text-xs text-zinc-400 transition hover:bg-white/5 hover:text-white sm:inline-flex">Méthode</a>
          <a href={SAMPLE_REPORT_URL} target="_blank" rel="noreferrer" className="hidden rounded-lg px-3 py-2 text-xs text-zinc-400 transition hover:bg-white/5 hover:text-white md:inline-flex">Rapport exemple</a>
          <a href={CONTACT_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-lg bg-emerald-300 px-3.5 py-2 text-xs font-semibold text-emerald-950 transition hover:bg-emerald-200">
            Écrire en privé <ArrowRight className="h-3.5 w-3.5" />
          </a>
        </div>
      </nav>

      <section className="relative mx-auto grid max-w-7xl gap-12 px-5 pb-20 pt-16 sm:px-8 sm:pt-24 lg:grid-cols-[1.1fr_0.9fr] lg:px-10 lg:pb-28 lg:pt-28">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-emerald-300/20 bg-emerald-300/[0.06] px-3 py-1.5 text-[11px] font-medium text-emerald-200">
            <BadgeCheck className="h-3.5 w-3.5" /> Audit indépendant · sans promesse de rendement
          </div>
          <h1 className="mt-7 max-w-4xl text-5xl font-semibold leading-[0.96] tracking-[-0.045em] sm:text-6xl lg:text-7xl">
            Votre backtest est-il un actif… ou une histoire bien racontée ?
          </h1>
          <p className="mt-7 max-w-2xl text-base leading-7 text-zinc-400 sm:text-lg">
            Je reproduis votre stratégie, cherche ce qui gonfle ses performances et rends un verdict que vous pouvez utiliser avant de risquer du capital : <strong className="font-medium text-zinc-100">continuer, corriger ou arrêter.</strong>
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <a href={CONTACT_URL} target="_blank" rel="noreferrer" className="inline-flex items-center justify-center gap-2 rounded-xl bg-emerald-300 px-5 py-3.5 text-sm font-semibold text-emerald-950 transition hover:-translate-y-0.5 hover:bg-emerald-200">
              Demander un cadrage privé <ArrowRight className="h-4 w-4" />
            </a>
            <a href={SAMPLE_REPORT_URL} target="_blank" rel="noreferrer" className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-5 py-3.5 text-sm font-medium text-zinc-200 transition hover:border-white/20 hover:bg-white/[0.06]">
              Télécharger le rapport exemple <ExternalLink className="h-4 w-4" />
            </a>
          </div>
          <p className="mt-4 max-w-xl text-[11px] leading-5 text-zinc-600">
            Premier échange par message privé LinkedIn. Aucun secret, identifiant d&apos;exchange ou code privé n&apos;est demandé au cadrage.
          </p>
        </div>

        <div className="relative self-end rounded-2xl border border-white/10 bg-[#10120f]/90 p-5 shadow-2xl shadow-black/40 sm:p-7">
          <div className="flex items-center justify-between border-b border-white/8 pb-4">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-zinc-500">Rapport de réalité</p>
              <p className="mt-1 text-sm font-medium">Kraken Alpha Agent · clôture</p>
            </div>
            <span className="rounded-full border border-red-400/20 bg-red-400/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-red-300">No edge</span>
          </div>
          <div className="mt-5 space-y-3">
            <AuditFinding icon={Database} label="Données" before="1 000 points" after="2 190 points" tone="warning" />
            <AuditFinding icon={GitBranch} label="Pipeline" before="4/4 passent" after="0/4 passent" tone="warning" />
            <AuditFinding icon={ShieldCheck} label="Risque" before="sorties bloquées" after="5 gates corrigés" tone="warning" />
            <AuditFinding icon={BarChart3} label="Signal ETH" before="+0,786 pp" after="−0,177 pp" tone="danger" />
          </div>
          <div className="mt-5 rounded-xl border border-emerald-300/15 bg-emerald-300/[0.05] p-4">
            <div className="flex items-start gap-3">
              <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />
              <div>
                <p className="text-xs font-semibold text-emerald-200">La bonne décision a été d&apos;arrêter.</p>
                <p className="mt-1 text-[11px] leading-5 text-zinc-400">Éviter une mauvaise mise en production est un retour sur investissement mesurable.</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="relative mx-auto max-w-7xl px-5 pb-20 sm:px-8 lg:px-10 lg:pb-28">
        <div className="grid gap-4 rounded-2xl border border-white/[0.08] bg-white/[0.025] p-6 sm:grid-cols-[1fr_auto] sm:items-center sm:p-8">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-emerald-300">Confidentialité par défaut</p>
            <h2 className="mt-3 text-2xl font-semibold tracking-tight">Votre logique reste privée.</h2>
            <p className="mt-3 max-w-3xl text-xs leading-6 text-zinc-400">
              NDA possible avant transfert. Les clés API et identifiants d&apos;exchange sont refusés. Les fichiers de mission sont isolés, non réutilisés pour entraîner un modèle et supprimés au plus tard 30 jours après la restitution, sauf demande écrite contraire.
            </p>
          </div>
          <a href={VERDICT_URL} target="_blank" rel="noreferrer" className="inline-flex items-center justify-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-4 py-3 text-xs font-semibold text-zinc-100 transition hover:bg-white/[0.08]">
            Vérifier les sources publiques <ExternalLink className="h-3.5 w-3.5" />
          </a>
        </div>
      </section>

      <section className="relative border-y border-white/[0.07] bg-white/[0.015]">
        <div className="mx-auto grid max-w-7xl grid-cols-2 divide-x divide-y divide-white/[0.07] px-5 sm:px-8 lg:grid-cols-4 lg:divide-y-0 lg:px-10">
          {proof.map((item) => (
            <div key={item.label} className="px-4 py-7 first:pl-0 sm:py-8 lg:px-7 lg:first:pl-0">
              <div className="text-3xl font-semibold tracking-tight text-emerald-200">{item.value}</div>
              <div className="mt-1 text-xs font-medium text-zinc-200">{item.label}</div>
              <div className="mt-1 text-[10px] leading-4 text-zinc-600">{item.detail}</div>
            </div>
          ))}
        </div>
      </section>

      <section id="methode" className="relative mx-auto max-w-7xl scroll-mt-8 px-5 py-20 sm:px-8 lg:px-10 lg:py-28">
        <div className="grid gap-12 lg:grid-cols-[0.85fr_1.15fr]">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-emerald-300">Ce que vous achetez</p>
            <h2 className="mt-4 text-3xl font-semibold tracking-tight sm:text-4xl">Une décision documentée, pas un nouveau graphique.</h2>
            <p className="mt-5 text-sm leading-7 text-zinc-400">L&apos;audit cherche activement les raisons pour lesquelles la performance pourrait ne pas exister. Si la stratégie tient, vous saurez pourquoi. Si elle casse, vous saurez où et combien cela vous aurait coûté.</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {deliverables.map((item, index) => (
              <div key={item} className="flex gap-3 rounded-xl border border-white/[0.08] bg-white/[0.025] p-4">
                <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-emerald-300/10 text-[10px] font-semibold text-emerald-300">{index + 1}</span>
                <p className="text-xs leading-5 text-zinc-300">{item}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="relative mx-auto max-w-7xl px-5 pb-24 sm:px-8 lg:px-10 lg:pb-32">
        <div className="mb-9 max-w-3xl">
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-emerald-300">Déroulé</p>
          <h2 className="mt-4 text-3xl font-semibold tracking-tight sm:text-4xl">Simple à acheter. Difficile à biaiser.</h2>
          <p className="mt-4 text-sm leading-7 text-zinc-400">La décision, le périmètre et les critères d&apos;arrêt sont fixés avant l&apos;analyse. Le rapport montre aussi les échecs, les limites et les contrôles non réalisables.</p>
        </div>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          {processSteps.map((item) => (
            <article key={item.step} className="rounded-2xl border border-white/[0.08] bg-white/[0.02] p-5">
              <span className="text-[10px] font-semibold tracking-[0.18em] text-emerald-300">{item.step}</span>
              <h3 className="mt-5 text-sm font-semibold text-zinc-100">{item.title}</h3>
              <p className="mt-3 text-xs leading-5 text-zinc-500">{item.text}</p>
            </article>
          ))}
        </div>
      </section>

      <section id="offres" className="relative mx-auto max-w-7xl px-5 pb-24 sm:px-8 lg:px-10 lg:pb-32">
        <div className="mb-9 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-emerald-300">Offres de lancement</p>
            <h2 className="mt-4 text-3xl font-semibold tracking-tight sm:text-4xl">Un périmètre et un prix avant de commencer.</h2>
          </div>
          <p className="max-w-md text-xs leading-5 text-zinc-500">Toute mission commence par un échange de cadrage. Si les données ou le périmètre ne permettent pas un verdict honnête, je refuse la mission.</p>
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          {offers.map((offer) => (
            <article key={offer.name} className={`relative rounded-2xl border p-6 ${offer.featured ? "border-emerald-300/30 bg-emerald-300/[0.055]" : "border-white/[0.08] bg-white/[0.02]"}`}>
              {offer.featured ? <span className="absolute right-5 top-5 rounded-full bg-emerald-300 px-2.5 py-1 text-[9px] font-bold uppercase tracking-wider text-emerald-950">Le plus utile</span> : null}
              <p className="text-sm font-semibold text-zinc-100">{offer.name}</p>
              <p className="mt-4 text-3xl font-semibold tracking-tight">{offer.price}</p>
              <p className="mt-1 text-[11px] text-emerald-300">Livraison indicative : {offer.lead}</p>
              <p className="mt-5 min-h-10 text-xs leading-5 text-zinc-400">{offer.summary}</p>
              <ul className="mt-5 space-y-2.5 border-t border-white/[0.08] pt-5">
                {offer.items.map((item) => <li key={item} className="flex items-center gap-2 text-xs text-zinc-300"><Check className="h-3.5 w-3.5 shrink-0 text-emerald-300" />{item}</li>)}
              </ul>
              <a href={CONTACT_URL} target="_blank" rel="noreferrer" className={`mt-7 inline-flex w-full items-center justify-center gap-2 rounded-lg px-4 py-3 text-xs font-semibold transition ${offer.featured ? "bg-emerald-300 text-emerald-950 hover:bg-emerald-200" : "border border-white/10 bg-white/[0.04] text-zinc-100 hover:bg-white/[0.08]"}`}>Choisir cette formule <ArrowRight className="h-3.5 w-3.5" /></a>
            </article>
          ))}
        </div>
      </section>

      <section className="relative mx-auto max-w-7xl px-5 pb-24 sm:px-8 lg:px-10 lg:pb-32">
        <div className="grid gap-10 lg:grid-cols-[0.7fr_1.3fr]">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-emerald-300">Questions fréquentes</p>
            <h2 className="mt-4 text-3xl font-semibold tracking-tight">Avant de confier votre backtest.</h2>
          </div>
          <div className="divide-y divide-white/[0.08] border-y border-white/[0.08]">
            {faqs.map((item) => (
              <article key={item.question} className="py-5 first:pt-0 lg:first:pt-5">
                <h3 className="text-sm font-semibold text-zinc-100">{item.question}</h3>
                <p className="mt-2 text-xs leading-6 text-zinc-500">{item.answer}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="relative border-t border-white/[0.07] bg-[#0c0e0b]">
        <div className="mx-auto grid max-w-7xl gap-10 px-5 py-16 sm:px-8 lg:grid-cols-[1fr_auto] lg:items-center lg:px-10 lg:py-20">
          <div>
            <div className="flex items-center gap-2 text-xs font-medium text-amber-200"><CircleAlert className="h-4 w-4" />Ce service ne vend pas de performance.</div>
            <h2 className="mt-4 max-w-3xl text-3xl font-semibold tracking-tight">Le livrable peut être « arrêtez ici ». C&apos;est souvent celui qui rapporte le plus.</h2>
            <p className="mt-4 max-w-2xl text-sm leading-6 text-zinc-400">Audit technique et méthodologique, pas conseil financier. Aucun rendement n&apos;est garanti. Vos secrets restent hors des échanges publics.</p>
          </div>
          <a href={CONTACT_URL} target="_blank" rel="noreferrer" className="inline-flex items-center justify-center gap-2 rounded-xl bg-emerald-300 px-5 py-3.5 text-sm font-semibold text-emerald-950 transition hover:bg-emerald-200">Demander le cadrage <ArrowRight className="h-4 w-4" /></a>
        </div>
      </section>

      <footer className="relative mx-auto flex max-w-7xl flex-col gap-4 px-5 py-8 text-[11px] text-zinc-600 sm:flex-row sm:items-center sm:justify-between sm:px-8 lg:px-10">
        <span>© 2026 Alpha Reality Check · Damien Credoz</span>
        <div className="flex flex-wrap items-center gap-4"><a href={SAMPLE_REPORT_URL} target="_blank" rel="noreferrer" className="transition hover:text-zinc-300">Rapport exemple</a><a href={VERDICT_URL} target="_blank" rel="noreferrer" className="transition hover:text-zinc-300">Preuve technique</a><a href={CONTACT_URL} target="_blank" rel="noreferrer" className="transition hover:text-zinc-300">LinkedIn</a></div>
      </footer>
    </main>
  );
}

function AuditFinding({ icon: Icon, label, before, after, tone }: { icon: LucideIcon; label: string; before: string; after: string; tone: "warning" | "danger" }) {
  return (
    <div className="grid grid-cols-[1fr_auto_auto] items-center gap-3 rounded-xl border border-white/[0.07] bg-black/20 px-3.5 py-3">
      <div className="flex min-w-0 items-center gap-2.5"><Icon className="h-3.5 w-3.5 shrink-0 text-zinc-500" /><span className="truncate text-xs text-zinc-300">{label}</span></div>
      <span className="hidden items-center gap-1 text-[10px] text-zinc-600 sm:inline-flex"><X className="h-3 w-3" />{before}</span>
      <span className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium ${tone === "danger" ? "bg-red-400/10 text-red-300" : "bg-amber-300/10 text-amber-200"}`}><Check className="h-3 w-3" />{after}</span>
    </div>
  );
}
