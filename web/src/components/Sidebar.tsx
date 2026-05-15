"use client";

import { useEffect, useState } from "react";
import {
  Activity,
  BarChart3,
  LayoutDashboard,
  ListChecks,
  Menu,
  Settings as SettingsIcon,
  ShieldCheck,
  Terminal,
  Waves,
  X,
} from "lucide-react";
import { GithubIcon } from "@/components/GithubIcon";
import { cn } from "@/lib/cn";

type NavItem = {
  label: string;
  icon: typeof LayoutDashboard;
  active?: boolean;
};

const NAV_ITEMS: NavItem[] = [
  { label: "Overview", icon: LayoutDashboard, active: true },
  { label: "Performance", icon: BarChart3 },
  { label: "Trades", icon: ListChecks },
  { label: "Risk", icon: ShieldCheck },
  { label: "Logs", icon: Terminal },
  { label: "Settings", icon: SettingsIcon },
];

function SidebarContent({ onNavClick }: { onNavClick?: () => void }) {
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
              v1.0.0
            </div>
          </div>
        </div>
      </div>

      <nav className="flex-1 px-3 py-4 flex flex-col gap-0.5 overflow-y-auto">
        <div className="px-2 pb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--text-tertiary)]">
          Workspace
        </div>
        {NAV_ITEMS.map(({ label, icon: Icon, active }) => (
          <button
            type="button"
            key={label}
            onClick={onNavClick}
            className={cn(
              "group relative flex items-center gap-3 px-3 py-2 rounded-md text-[13px] transition-colors text-left",
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
                active ? "text-[var(--accent-emerald)]" : "text-[var(--text-tertiary)] group-hover:text-[var(--text-secondary)]",
              )}
              strokeWidth={1.8}
            />
            <span className="font-medium">{label}</span>
          </button>
        ))}
      </nav>

      <div className="border-t border-[var(--border)] px-4 py-4 flex flex-col gap-3">
        <a
          href="https://github.com/Damso74/kraken-alpha-agent"
          target="_blank"
          rel="noreferrer noopener"
          className="flex items-center gap-2.5 px-2 py-1.5 rounded-md text-[12px] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-1)] transition-colors"
        >
          <GithubIcon className="h-3.5 w-3.5" strokeWidth={1.8} />
          <span className="truncate">Damso74/kraken-alpha-agent</span>
        </a>
        <div className="rounded-md border border-[var(--border)] bg-[var(--surface-1)] px-3 py-2.5">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[var(--success)] opacity-60" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-[var(--success)]" />
            </span>
            <span className="text-[11.5px] font-medium text-[var(--success)]">
              Agent Online
            </span>
          </div>
          <div className="mt-1.5 flex items-center justify-between gap-2 text-[10.5px] text-[var(--text-tertiary)] tabular">
            <span className="inline-flex items-center gap-1">
              <Activity className="h-2.5 w-2.5" strokeWidth={2} />
              <span>Uptime 02h 14m</span>
            </span>
            <span>v1.0.0</span>
          </div>
        </div>
      </div>
    </>
  );
}

export function Sidebar() {
  const [open, setOpen] = useState(false);

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
        <SidebarContent />
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
          <SidebarContent onNavClick={() => setOpen(false)} />
        </aside>
      </div>
    </>
  );
}
