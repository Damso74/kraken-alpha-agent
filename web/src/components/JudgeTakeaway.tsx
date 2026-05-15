import { Sparkles } from "lucide-react";

export function JudgeTakeaway({ message }: { message: string }) {
  return (
    <div className="relative rounded-2xl gradient-border p-[1px]">
      <div className="rounded-2xl bg-[linear-gradient(180deg,rgba(245,158,11,0.06),rgba(20,184,166,0.04))] border border-transparent px-6 py-5 flex items-start gap-4">
        <div className="h-10 w-10 rounded-lg bg-[color:var(--gold)]/15 text-[var(--gold)] grid place-items-center shrink-0">
          <Sparkles className="h-4.5 w-4.5" strokeWidth={2} />
        </div>
        <div className="min-w-0">
          <div className="text-[10.5px] font-semibold uppercase tracking-[0.16em] text-[var(--gold)] mb-1.5">
            Judge takeaway
          </div>
          <p className="text-[14.5px] leading-relaxed text-[var(--text-primary)] tracking-tight">
            {message}
          </p>
        </div>
      </div>
    </div>
  );
}
