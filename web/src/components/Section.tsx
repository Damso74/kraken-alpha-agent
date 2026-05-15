import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";

type Tone = "neutral" | "success" | "warning" | "info" | "gold";

const TONE_DOT: Record<Tone, string> = {
  neutral: "bg-[var(--text-tertiary)]",
  success: "bg-[var(--success)] shadow-[0_0_12px_rgba(16,185,129,0.6)]",
  warning: "bg-[var(--warning)] shadow-[0_0_12px_rgba(239,68,68,0.6)]",
  info: "bg-[var(--info)] shadow-[0_0_12px_rgba(14,165,233,0.6)]",
  gold: "bg-[var(--gold)] shadow-[0_0_12px_rgba(245,158,11,0.6)]",
};

const TONE_ICON: Record<Tone, string> = {
  neutral: "text-[var(--text-secondary)] bg-[var(--surface-2)]",
  success: "text-[var(--success)] bg-[color:var(--success)]/10",
  warning: "text-[var(--warning)] bg-[color:var(--warning)]/10",
  info: "text-[var(--info)] bg-[color:var(--info)]/10",
  gold: "text-[var(--gold)] bg-[color:var(--gold)]/10",
};

export function Section({
  title,
  description,
  tone = "neutral",
  icon: Icon,
  children,
  className,
  contentClassName,
}: {
  title: string;
  description?: string;
  tone?: Tone;
  icon?: LucideIcon;
  children: React.ReactNode;
  className?: string;
  contentClassName?: string;
}) {
  return (
    <section
      className={cn(
        "rounded-xl bg-[var(--surface-1)] border border-[var(--border)] overflow-hidden",
        className,
      )}
    >
      <header className="flex items-start gap-3 px-5 pt-5 pb-3">
        {Icon ? (
          <div
            className={cn(
              "h-9 w-9 rounded-lg grid place-items-center shrink-0",
              TONE_ICON[tone],
            )}
          >
            <Icon className="h-4 w-4" strokeWidth={2} />
          </div>
        ) : (
          <span
            className={cn(
              "mt-2 h-2 w-2 rounded-full shrink-0",
              TONE_DOT[tone],
            )}
            aria-hidden
          />
        )}
        <div className="min-w-0">
          <h3 className="text-[14px] font-semibold tracking-tight text-[var(--text-primary)]">
            {title}
          </h3>
          {description ? (
            <p className="mt-1 text-[12px] leading-relaxed text-[var(--text-secondary)]">
              {description}
            </p>
          ) : null}
        </div>
      </header>
      <div className={cn("px-5 pb-5 pt-1", contentClassName)}>{children}</div>
    </section>
  );
}

export function CheckRow({
  tone = "success",
  children,
}: {
  tone?: Tone;
  children: React.ReactNode;
}) {
  return (
    <li className="flex items-start gap-3 py-1.5">
      <span
        className={cn(
          "mt-1.5 h-1.5 w-1.5 rounded-full shrink-0",
          TONE_DOT[tone],
        )}
        aria-hidden
      />
      <span className="text-[13px] leading-relaxed text-[var(--text-primary)]">
        {children}
      </span>
    </li>
  );
}
