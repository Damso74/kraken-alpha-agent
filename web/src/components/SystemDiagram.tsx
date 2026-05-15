import {
  Bot,
  HardDrive,
  Network,
  ScrollText,
  ShieldCheck,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

type Tone = "gold" | "info" | "success" | "neutral" | "vault";

const TONE_FILL: Record<Tone, string> = {
  gold: "rgba(245, 158, 11, 0.06)",
  info: "rgba(14, 165, 233, 0.06)",
  success: "rgba(16, 185, 129, 0.06)",
  neutral: "rgba(255, 255, 255, 0.02)",
  vault: "rgba(20, 184, 166, 0.05)",
};

const TONE_STROKE: Record<Tone, string> = {
  gold: "rgba(245, 158, 11, 0.32)",
  info: "rgba(14, 165, 233, 0.32)",
  success: "rgba(16, 185, 129, 0.34)",
  neutral: "#2c2f37",
  vault: "rgba(20, 184, 166, 0.32)",
};

const TONE_ACCENT: Record<Tone, string> = {
  gold: "#f59e0b",
  info: "#0ea5e9",
  success: "#10b981",
  neutral: "#9ca3af",
  vault: "#14b8a6",
};

type Node = {
  id: string;
  label: string;
  tagline: string;
  icon: LucideIcon;
  tone: Tone;
};

const NODES: Record<string, Node> = {
  agent: { id: "agent", label: "Agent", tagline: "Strategy Loop", icon: Bot, tone: "gold" },
  kraken: { id: "kraken", label: "Kraken API", tagline: "Spot + Futures CLI 0.3.2", icon: Network, tone: "info" },
  risk: { id: "risk", label: "Risk Engine", tagline: "8 gates · 1× leverage", icon: ShieldCheck, tone: "success" },
  logger: { id: "logger", label: "Logger & Audit", tagline: "JSONL + SQLite", icon: ScrollText, tone: "neutral" },
  store: { id: "store", label: "Data Store (Encrypted)", tagline: "Audit trail · keys never logged", icon: HardDrive, tone: "vault" },
};

const ORDER_DESKTOP = ["agent", "kraken", "risk", "logger"] as const;
const ORDER_MOBILE = ["agent", "kraken", "risk", "logger", "store"] as const;

function NodeRect({
  node,
  x,
  y,
  width,
  height,
  iconSize = 32,
}: {
  node: Node;
  x: number;
  y: number;
  width: number;
  height: number;
  iconSize?: number;
}) {
  const Icon = node.icon;
  const accent = TONE_ACCENT[node.tone];
  const padX = 14;
  const iconCenterY = y + height / 2;
  const labelX = x + padX + iconSize + 12;
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        rx={10}
        ry={10}
        fill={TONE_FILL[node.tone]}
        stroke={TONE_STROKE[node.tone]}
        strokeWidth={1}
      />
      {/* Accent left bar */}
      <rect
        x={x}
        y={y + 8}
        width={3}
        height={height - 16}
        rx={1.5}
        ry={1.5}
        fill={accent}
        opacity={0.85}
      />
      {/* Icon tile */}
      <rect
        x={x + padX}
        y={iconCenterY - iconSize / 2}
        width={iconSize}
        height={iconSize}
        rx={7}
        ry={7}
        fill={accent}
        opacity={0.14}
      />
      <foreignObject
        x={x + padX}
        y={iconCenterY - iconSize / 2}
        width={iconSize}
        height={iconSize}
      >
        <div
          style={{
            width: "100%",
            height: "100%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: accent,
          }}
        >
          <Icon width={16} height={16} strokeWidth={2} />
        </div>
      </foreignObject>
      <text
        x={labelX}
        y={iconCenterY - 4}
        fill="#e6e7ea"
        fontSize={12.5}
        fontWeight={600}
        fontFamily="var(--font-sans, system-ui)"
      >
        {node.label}
      </text>
      <text
        x={labelX}
        y={iconCenterY + 12}
        fill="#6b7280"
        fontSize={10}
        fontWeight={500}
        fontFamily="var(--font-sans, system-ui)"
      >
        {node.tagline}
      </text>
    </g>
  );
}

function SvgDefs() {
  return (
    <defs>
      <marker
        id="arrowhead-emerald"
        viewBox="0 0 10 10"
        refX="8"
        refY="5"
        markerWidth="6"
        markerHeight="6"
        orient="auto-start-reverse"
      >
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#10b981" />
      </marker>
      <marker
        id="arrowhead-teal"
        viewBox="0 0 10 10"
        refX="8"
        refY="5"
        markerWidth="6"
        markerHeight="6"
        orient="auto-start-reverse"
      >
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#14b8a6" />
      </marker>
      <linearGradient id="bg-grad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor="rgba(255,255,255,0.02)" />
        <stop offset="100%" stopColor="rgba(255,255,255,0)" />
      </linearGradient>
    </defs>
  );
}

function DesktopDiagram() {
  const VB_W = 1000;
  const VB_H = 280;
  const cardW = 200;
  const cardH = 88;
  const topY = 16;
  // 4 cards spaced evenly across the viewBox.
  const startX = 15;
  const endX = VB_W - 15 - cardW;
  const gap = (endX - startX) / (ORDER_DESKTOP.length - 1);
  const positions = ORDER_DESKTOP.map((id, i) => ({
    id,
    x: startX + i * gap,
    y: topY,
  }));

  const storeW = 380;
  const storeH = 80;
  const storeX = (VB_W - storeW) / 2;
  const storeY = 178;

  const arrowOffset = 6; // gap before card edge for arrowhead clarity

  return (
    <svg
      viewBox={`0 0 ${VB_W} ${VB_H}`}
      preserveAspectRatio="xMidYMid meet"
      className="hidden md:block w-full h-auto"
      role="img"
      aria-label="Kraken Alpha Agent system architecture"
    >
      <SvgDefs />
      <rect x={0} y={0} width={VB_W} height={VB_H} fill="url(#bg-grad)" />

      {/* Top row arrows (solid emerald) */}
      {positions.slice(0, -1).map((p, i) => {
        const next = positions[i + 1];
        const y = p.y + cardH / 2;
        return (
          <line
            key={`arr-${p.id}`}
            x1={p.x + cardW + 2}
            y1={y}
            x2={next.x - arrowOffset}
            y2={y}
            stroke="#10b981"
            strokeWidth={1.6}
            markerEnd="url(#arrowhead-emerald)"
          />
        );
      })}

      {/* Dashed lines from Agent (first) and Logger (last) down to Data Store */}
      {(() => {
        const first = positions[0];
        const last = positions[positions.length - 1];
        const firstX = first.x + cardW / 2;
        const firstY = first.y + cardH;
        const lastX = last.x + cardW / 2;
        const lastY = last.y + cardH;
        const storeLeftX = storeX + 32;
        const storeRightX = storeX + storeW - 32;
        const storeTopY = storeY;

        return (
          <g
            stroke="#14b8a6"
            strokeWidth={1.4}
            strokeDasharray="5 4"
            fill="none"
            opacity={0.85}
          >
            <path
              d={`M ${firstX} ${firstY + 4} C ${firstX} ${firstY + 50}, ${storeLeftX} ${storeTopY - 40}, ${storeLeftX} ${storeTopY - arrowOffset}`}
              markerEnd="url(#arrowhead-teal)"
            />
            <path
              d={`M ${lastX} ${lastY + 4} C ${lastX} ${lastY + 50}, ${storeRightX} ${storeTopY - 40}, ${storeRightX} ${storeTopY - arrowOffset}`}
              markerEnd="url(#arrowhead-teal)"
            />
          </g>
        );
      })()}

      {/* Top row nodes */}
      {positions.map((p) => (
        <NodeRect
          key={p.id}
          node={NODES[p.id]}
          x={p.x}
          y={p.y}
          width={cardW}
          height={cardH}
        />
      ))}

      {/* Data store node (centered) */}
      <NodeRect
        node={NODES.store}
        x={storeX}
        y={storeY}
        width={storeW}
        height={storeH}
      />
    </svg>
  );
}

function MobileDiagram() {
  const VB_W = 320;
  const cardW = 290;
  const cardH = 72;
  const cardX = (VB_W - cardW) / 2;
  const arrowGap = 32;
  const startY = 8;
  const totalHeight =
    startY +
    ORDER_MOBILE.length * cardH +
    (ORDER_MOBILE.length - 1) * arrowGap +
    8;

  return (
    <svg
      viewBox={`0 0 ${VB_W} ${totalHeight}`}
      preserveAspectRatio="xMidYMid meet"
      className="md:hidden w-full h-auto"
      role="img"
      aria-label="Kraken Alpha Agent system architecture"
    >
      <SvgDefs />
      <rect x={0} y={0} width={VB_W} height={totalHeight} fill="url(#bg-grad)" />

      {ORDER_MOBILE.map((id, i) => {
        const y = startY + i * (cardH + arrowGap);
        const isLast = i === ORDER_MOBILE.length - 1;
        const node = NODES[id];
        // dashed teal arrow only for the last leg into the data store; emerald for the rest.
        const isStoreLeg = !isLast && ORDER_MOBILE[i + 1] === "store";
        return (
          <g key={id}>
            <NodeRect
              node={node}
              x={cardX}
              y={y}
              width={cardW}
              height={cardH}
            />
            {!isLast ? (
              <line
                x1={VB_W / 2}
                y1={y + cardH + 4}
                x2={VB_W / 2}
                y2={y + cardH + arrowGap - 4}
                stroke={isStoreLeg ? "#14b8a6" : "#10b981"}
                strokeWidth={1.6}
                strokeDasharray={isStoreLeg ? "5 4" : undefined}
                markerEnd={
                  isStoreLeg ? "url(#arrowhead-teal)" : "url(#arrowhead-emerald)"
                }
                opacity={isStoreLeg ? 0.85 : 1}
              />
            ) : null}
          </g>
        );
      })}
    </svg>
  );
}

export function SystemDiagram() {
  return (
    <div className="relative rounded-lg bg-[var(--surface-0)] border border-[var(--border)] p-3 sm:p-4 dot-grid">
      <DesktopDiagram />
      <MobileDiagram />

      <div className="mt-3 sm:mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-[10.5px] text-[var(--text-tertiary)]">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-[2px] w-5 bg-[var(--success)] rounded-full" />
          Real-time flow
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span
            aria-hidden
            className="inline-block h-[2px] w-5 rounded-full"
            style={{
              backgroundImage:
                "repeating-linear-gradient(90deg, #14b8a6 0 4px, transparent 4px 8px)",
            }}
          />
          Audit / persistence
        </span>
      </div>

      <p className="mt-3 text-[11px] text-[var(--text-tertiary)] leading-relaxed">
        Triple opt-in for live:{" "}
        <code className="text-[var(--text-secondary)]">TRADING_MODE=live</code>{" "}
        +{" "}
        <code className="text-[var(--text-secondary)]">LIVE_TRADING=true</code>{" "}
        +{" "}
        <code className="text-[var(--text-secondary)]">
          ALLOW_LIVE_ORDERS=true
        </code>
        . Dead-man cancel-after on every session.
      </p>
    </div>
  );
}
