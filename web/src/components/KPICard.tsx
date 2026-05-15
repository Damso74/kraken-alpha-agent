import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";

type Tone = "neutral" | "success" | "warning" | "info" | "gold";

const TONE_RING: Record<Tone, string> = {
  neutral: "ring-[var(--border-strong)]",
  success: "ring-[color:var(--success)]/30",
  warning: "ring-[color:var(--warning)]/30",
  info: "ring-[color:var(--info)]/30",
  gold: "ring-[color:var(--gold)]/30",
};

const TONE_ICON: Record<Tone, string> = {
  neutral: "text-[var(--text-secondary)] bg-[var(--surface-2)]",
  success: "text-[var(--success)] bg-[color:var(--success)]/10",
  warning: "text-[var(--warning)] bg-[color:var(--warning)]/10",
  info: "text-[var(--info)] bg-[color:var(--info)]/10",
  gold: "text-[var(--gold)] bg-[color:var(--gold)]/10",
};

const TONE_VALUE: Record<Tone, string> = {
  neutral: "text-[var(--text-primary)]",
  success: "text-[var(--success)]",
  warning: "text-[var(--warning)]",
  info: "text-[var(--info)]",
  gold: "text-[var(--gold)]",
};

export function KPICard({
  label,
  value,
  hint,
  tone = "neutral",
  icon: Icon,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: Tone;
  icon?: LucideIcon;
}) {
  return (
    <div
      className={cn(
        "relative rounded-xl bg-[var(--surface-1)] border border-[var(--border)] p-4 ring-1 ring-inset",
        TONE_RING[tone],
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
          {label}
        </div>
        {Icon ? (
          <div
            className={cn(
              "h-8 w-8 rounded-lg grid place-items-center",
              TONE_ICON[tone],
            )}
          >
            <Icon className="h-4 w-4" strokeWidth={2} />
          </div>
        ) : null}
      </div>
      <div className={cn("mt-3 text-2xl font-semibold tabular tracking-tight", TONE_VALUE[tone])}>
        {value}
      </div>
      {hint ? (
        <div className="mt-1.5 text-[12px] text-[var(--text-secondary)]">{hint}</div>
      ) : null}
    </div>
  );
}
