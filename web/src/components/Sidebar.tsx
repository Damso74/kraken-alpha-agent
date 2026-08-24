"use client";

import { useCallback, useEffect, useState } from "react";
import {
  BarChart3,
  FileSearch,
  GitMerge,
  LayoutDashboard,
  ListChecks,
  Menu,
  ShieldCheck,
  Terminal,
  Waves,
  X,
} from "lucide-react";
import { GithubIcon } from "@/components/GithubIcon";
import { cn } from "@/lib/cn";
import { data, fmtUsd } from "@/lib/data";

type NavItem = {
  id: string;
  label: string;
  icon: typeof LayoutDashboard;
};

const NAV_ITEMS: NavItem[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "performance", label: "Performance", icon: BarChart3 },
  { id: "trades", label: "Trades", icon: ListChecks },
  { id: "risk", label: "Risk", icon: ShieldCheck },
  { id: "logs", label: "Logs", icon: Terminal },
  { id: "system", label: "System", icon: GitMerge },
];

function SnapshotStatusCard() {
  const { summary } = data;
  const positive = summary.total_pnl_usd >= 0;
  const winRatePct = (summary.win_rate * 100).toFixed(0);
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--surface-1)] px-3 py-2.5">
      <div className="flex items-center gap-2">
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[var(--gold)] opacity-60" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-[var(--gold)]" />
        </span>
        <span className="text-[11.5px] font-medium text-[var(--gold)]">
          Snapshot ready
        </span>
      </div>
      <div className="mt-1.5 text-[10.5px] text-[var(--text-tertiary)] leading-tight">
        Backtest mode · hackathon window
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-2 text-[10.5px] tabular">
        <span
          className={cn(
            "font-semibold",
            positive ? "text-[var(--success)]" : "text-[var(--warning)]",
          )}
        >
          {fmtUsd(summary.total_pnl_usd, { signed: true })}
        </span>
        <span className="text-[var(--text-tertiary)]">{winRatePct}% win rate</span>
      </div>
    </div>
  );
}

function SidebarContent({
  activeId,
  onNavClick,
}: {
  activeId: string;
  onNavClick?: (id: string) => void;
}) {
  return (
    <>
      <div className="px-5 pt-6 pb-5 border-b border-[var(--border)]">
        <div className="flex items-center gap-3">
          <div className="relative h-10 w-10 rounded-xl bg-gradient-to-br from-[var(--accent-teal)] via-[var(--accent-emerald)] to-[var(--gold)] grid place-items-center shadow-[0_8px_28px_-12px_rgba(245,158,11,0.55)]">
            <Waves className="h-4.5 w-4.5 text-black" strokeWidth={2.5} />
          </div>
          <div className="min-w-0">
            <div className="text-[10.5px] font-semibold uppercase tracking-[0.18em] text-[var(--text-tertiary)] leading-none">
              Kraken{" "}
              <span className="text-[var(--accent-emerald)]">Alpha</span>{" "}
              Agent
            </div>
            <div className="mt-1 text-[11px] text-[var(--text-tertiary)] leading-none">
              Read-only inspection
            </div>
          </div>
        </div>
      </div>

      <nav
        aria-label="Page sections"
        className="flex-1 px-3 py-4 flex flex-col gap-0.5 overflow-y-auto"
      >
        <div className="px-2 pb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--text-tertiary)]">
          Workspace
        </div>
        {NAV_ITEMS.map(({ id, label, icon: Icon }) => {
          const active = activeId === id;
          return (
            <a
              key={id}
              href={`#${id}`}
              aria-current={active ? "true" : undefined}
              onClick={() => onNavClick?.(id)}
              className={cn(
                "group relative flex items-center gap-3 px-3 py-2 rounded-md text-[13px] transition-colors text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-emerald)]",
                active
                  ? "bg-[color:var(--success)]/[0.06] text-[var(--text-primary)]"
                  : "text-[var(--text-secondary)] hover:bg-[var(--surface-1)] hover:text-[var(--text-primary)]",
              )}
            >
              {active ? (
                <span
                  aria-hidden
                  className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-r-full bg-[var(--accent-emerald)] shadow-[0_0_10px_rgba(16,185,129,0.55)]"
                />
              ) : null}
              <Icon
                className={cn(
                  "h-4 w-4 shrink-0 transition-colors",
                  active
                    ? "text-[var(--accent-emerald)]"
                    : "text-[var(--text-tertiary)] group-hover:text-[var(--text-secondary)]",
                )}
                strokeWidth={1.8}
              />
              <span className="font-medium">{label}</span>
            </a>
          );
        })}
      </nav>

      <div className="border-t border-[var(--border)] px-4 py-4 flex flex-col gap-3">
        <a
          href="/audit"
          className="flex items-center gap-2.5 rounded-md border border-[color:var(--success)]/20 bg-[color:var(--success)]/[0.05] px-2.5 py-2 text-[12px] font-medium text-[var(--accent-emerald)] transition-colors hover:bg-[color:var(--success)]/[0.1]"
        >
          <FileSearch className="h-3.5 w-3.5" strokeWidth={1.9} />
          <span>Faire auditer une stratégie</span>
        </a>
        <a
          href="https://github.com/Damso74/kraken-alpha-agent"
          target="_blank"
          rel="noreferrer noopener"
          className="flex items-center gap-2.5 px-2 py-1.5 rounded-md text-[12px] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-1)] transition-colors"
        >
          <GithubIcon className="h-3.5 w-3.5" strokeWidth={1.8} />
          <span className="truncate">Damso74/kraken-alpha-agent</span>
        </a>
        <SnapshotStatusCard />
      </div>
    </>
  );
}

function useActiveSection(ids: string[]): string {
  const [activeId, setActiveId] = useState<string>(ids[0] ?? "");

  useEffect(() => {
    if (typeof window === "undefined") return;
    const elements = ids
      .map((id) => document.getElementById(id))
      .filter((el): el is HTMLElement => el !== null);
    if (elements.length === 0) return;

    const visibility = new Map<string, number>();

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          visibility.set(entry.target.id, entry.intersectionRatio);
        }
        let bestId = "";
        let bestRatio = -1;
        for (const [id, ratio] of visibility) {
          if (ratio > bestRatio) {
            bestRatio = ratio;
            bestId = id;
          }
        }
        if (bestId && bestRatio > 0) {
          setActiveId(bestId);
        }
      },
      {
        rootMargin: "-20% 0px -55% 0px",
        threshold: [0, 0.1, 0.25, 0.5, 0.75, 1],
      },
    );

    for (const el of elements) {
      observer.observe(el);
    }
    return () => observer.disconnect();
  }, [ids]);

  return activeId;
}

export function Sidebar() {
  const [open, setOpen] = useState(false);
  const activeId = useActiveSection(NAV_ITEMS.map((item) => item.id));

  useEffect(() => {
    if (open) {
      const previous = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      return () => {
        document.body.style.overflow = previous;
      };
    }
  }, [open]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const handleMobileNavClick = useCallback(() => {
    setOpen(false);
  }, []);

  return (
    <>
      {/* Mobile hamburger button */}
      <button
        type="button"
        aria-label="Open navigation"
        onClick={() => setOpen(true)}
        className="lg:hidden fixed top-3 left-3 z-40 inline-flex h-10 w-10 items-center justify-center rounded-md border border-[var(--border)] bg-[var(--surface-1)]/95 backdrop-blur text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-2)] transition-colors shadow-[0_4px_16px_-6px_rgba(0,0,0,0.6)]"
      >
        <Menu className="h-5 w-5" strokeWidth={2} />
      </button>

      {/* Desktop sidebar (sticky) */}
      <aside className="hidden lg:flex w-[240px] shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface-0)] sticky top-0 h-screen">
        <SidebarContent activeId={activeId} />
      </aside>

      {/* Mobile drawer */}
      <div
        aria-hidden={!open}
        className={cn(
          "lg:hidden fixed inset-0 z-50 transition-opacity duration-200",
          open ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none",
        )}
      >
        {/* Backdrop */}
        <button
          type="button"
          aria-label="Close navigation"
          onClick={() => setOpen(false)}
          className="absolute inset-0 bg-black/65 backdrop-blur-[2px]"
        />
        {/* Drawer panel */}
        <aside
          role="dialog"
          aria-modal="true"
          aria-label="Navigation"
          className={cn(
            "absolute left-0 top-0 bottom-0 w-[280px] max-w-[85vw] flex flex-col border-r border-[var(--border)] bg-[var(--surface-0)] shadow-[0_24px_60px_-12px_rgba(0,0,0,0.7)] transition-transform duration-300 ease-out",
            open ? "translate-x-0" : "-translate-x-full",
          )}
        >
          <button
            type="button"
            aria-label="Close navigation"
            onClick={() => setOpen(false)}
            className="absolute top-3 right-3 z-10 inline-flex h-8 w-8 items-center justify-center rounded-md border border-[var(--border)] bg-[var(--surface-1)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-2)] transition-colors"
          >
            <X className="h-4 w-4" strokeWidth={2} />
          </button>
          <SidebarContent activeId={activeId} onNavClick={handleMobileNavClick} />
        </aside>
      </div>
    </>
  );
}
