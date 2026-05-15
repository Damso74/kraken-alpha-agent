import {
  Activity,
  BarChart3,
  LayoutDashboard,
  ListChecks,
  Settings as SettingsIcon,
  ShieldCheck,
  Terminal,
  Waves,
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

export function Sidebar() {
  return (
    <aside className="hidden lg:flex w-[240px] shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface-0)] sticky top-0 h-screen">
      <div className="px-5 pt-6 pb-5 border-b border-[var(--border)]">
        <div className="flex items-center gap-3">
          <div className="relative h-9 w-9 rounded-lg bg-gradient-to-br from-[var(--accent-teal)] to-[var(--gold)] grid place-items-center shadow-[0_4px_24px_-8px_rgba(245,158,11,0.5)]">
            <Waves className="h-4 w-4 text-black" strokeWidth={2.5} />
          </div>
          <div>
            <div className="text-[13px] font-semibold tracking-tight text-[var(--text-primary)]">
              Kraken Alpha
            </div>
            <div className="text-[11px] text-[var(--text-tertiary)] -mt-0.5">
              Agent v1.0.0
            </div>
          </div>
        </div>
      </div>

      <nav className="flex-1 px-3 py-4 flex flex-col gap-0.5">
        <div className="px-2 pb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--text-tertiary)]">
          Workspace
        </div>
        {NAV_ITEMS.map(({ label, icon: Icon, active }) => (
          <div
            key={label}
            className={cn(
              "flex items-center gap-3 px-3 py-2 rounded-md text-[13px] transition-colors cursor-default select-none",
              active
                ? "bg-[var(--surface-2)] text-[var(--text-primary)] border border-[var(--border-strong)]"
                : "text-[var(--text-secondary)] hover:bg-[var(--surface-1)] hover:text-[var(--text-primary)] border border-transparent",
            )}
          >
            <Icon className="h-4 w-4 shrink-0" strokeWidth={1.8} />
            <span className="font-medium">{label}</span>
          </div>
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
        <div className="flex items-center gap-2 px-2 text-[11px] text-[var(--text-tertiary)]">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[var(--success)] opacity-60" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-[var(--success)]" />
          </span>
          <Activity className="h-3 w-3" strokeWidth={2} />
          <span>Agent online</span>
        </div>
      </div>
    </aside>
  );
}
