import { Bot, Database, FileBox, Lock, ShieldCheck, Waves } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";

function Node({
  title,
  subtitle,
  icon: Icon,
  tone = "neutral",
}: {
  title: string;
  subtitle: string;
  icon: LucideIcon;
  tone?: "neutral" | "success" | "info" | "gold" | "warning";
}) {
  const toneClasses = {
    neutral: "border-[var(--border-strong)] bg-[var(--surface-2)]",
    success: "border-[color:var(--success)]/30 bg-[color:var(--success)]/[0.06]",
    info: "border-[color:var(--info)]/30 bg-[color:var(--info)]/[0.06]",
    gold: "border-[color:var(--gold)]/30 bg-[color:var(--gold)]/[0.06]",
    warning: "border-[color:var(--warning)]/30 bg-[color:var(--warning)]/[0.06]",
  } as const;

  const iconTone = {
    neutral: "text-[var(--text-secondary)] bg-[var(--surface-1)]",
    success: "text-[var(--success)] bg-[color:var(--success)]/10",
    info: "text-[var(--info)] bg-[color:var(--info)]/10",
    gold: "text-[var(--gold)] bg-[color:var(--gold)]/10",
    warning: "text-[var(--warning)] bg-[color:var(--warning)]/10",
  } as const;

  return (
    <div
      className={cn(
        "rounded-lg border px-3.5 py-3 flex items-center gap-3 shadow-[0_2px_12px_-8px_rgba(0,0,0,0.6)]",
        toneClasses[tone],
      )}
    >
      <div className={cn("h-9 w-9 rounded-md grid place-items-center", iconTone[tone])}>
        <Icon className="h-4 w-4" strokeWidth={2} />
      </div>
      <div className="min-w-0">
        <div className="text-[12.5px] font-semibold text-[var(--text-primary)] tracking-tight">
          {title}
        </div>
        <div className="text-[11px] text-[var(--text-tertiary)] truncate">{subtitle}</div>
      </div>
    </div>
  );
}

function Arrow({ direction = "right" }: { direction?: "right" | "down" }) {
  if (direction === "down") {
    return (
      <div className="flex justify-center" aria-hidden>
        <span className="text-[var(--text-tertiary)] text-base leading-none">↓</span>
      </div>
    );
  }
  return (
    <div className="flex items-center justify-center" aria-hidden>
      <span className="text-[var(--text-tertiary)] text-base leading-none">→</span>
    </div>
  );
}

export function SystemDiagram() {
  return (
    <div className="relative rounded-lg bg-[var(--surface-0)] border border-[var(--border)] p-4 dot-grid">
      <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr] items-center gap-3 md:gap-2">
        <Node
          title="Agent Loop"
          subtitle="features → ensemble → risk"
          icon={Bot}
          tone="gold"
        />
        <Arrow />
        <Node
          title="Kraken API"
          subtitle="CLI 0.3.2 · spot + futures"
          icon={Waves}
          tone="info"
        />
        <Arrow />
        <Node
          title="Risk Engine"
          subtitle="leverage 1x · shorting=off"
          icon={ShieldCheck}
          tone="success"
        />
        <Arrow />
        <Node
          title="Logger & Audit"
          subtitle="structured JSONL + rotated"
          icon={FileBox}
          tone="neutral"
        />
      </div>

      <div className="mt-4 grid grid-cols-1 md:grid-cols-[1fr_auto_1fr] items-center gap-3 md:gap-2">
        <Node
          title="Data Store"
          subtitle="SQLite · positions · orders"
          icon={Database}
          tone="info"
        />
        <Arrow />
        <Node
          title="Encrypted .env"
          subtitle="Kraken keys · never logged"
          icon={Lock}
          tone="warning"
        />
      </div>

      <div className="mt-4 text-[11px] text-[var(--text-tertiary)] leading-relaxed">
        Triple opt-in for live: <code className="text-[var(--text-secondary)]">TRADING_MODE=live</code> +
        <code className="text-[var(--text-secondary)] mx-1">LIVE_TRADING=true</code> +
        <code className="text-[var(--text-secondary)] ml-1">ALLOW_LIVE_ORDERS=true</code>. Dead-man cancel-after on every session.
      </div>
    </div>
  );
}
