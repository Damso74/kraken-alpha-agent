"""One-shot inspector for data/walk_forward_crypto_results.json (operator-local)."""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
path = ROOT / "data" / "walk_forward_crypto_results.json"
d = json.loads(path.read_text(encoding="utf-8"))
print(f"evaluated={d['evaluated_count']} survivors={d['survivors_count']}")

evaluated = d["evaluated"]
if not evaluated:
    sys.exit(0)

best_train = max(evaluated, key=lambda c: c["train"]["net_pnl_usd"])
best_test = max(evaluated, key=lambda c: c["test"]["net_pnl_usd"])
print(
    "BEST_TRAIN:", best_train["params"],
    f"train_pnl={best_train['train']['net_pnl_usd']:+.2f}",
    f"train_wr={best_train['train']['win_rate'] * 100:.1f}%",
    f"trades={best_train['train']['trades_count']}",
)
print(
    "BEST_TEST :", best_test["params"],
    f"test_pnl={best_test['test']['net_pnl_usd']:+.2f}",
    f"test_wr={best_test['test']['win_rate'] * 100:.1f}%",
    f"trades={best_test['test']['trades_count']}",
)

tpnl = [c["test"]["net_pnl_usd"] for c in evaluated]
twr = [c["test"]["win_rate"] for c in evaluated]
trpnl = [c["train"]["net_pnl_usd"] for c in evaluated]
trwr = [c["train"]["win_rate"] for c in evaluated]
print(f"train PnL: min={min(trpnl):+.2f} med={statistics.median(trpnl):+.2f} max={max(trpnl):+.2f}")
print(f"train WR : min={min(trwr) * 100:.2f}% med={statistics.median(trwr) * 100:.2f}% max={max(trwr) * 100:.2f}%")
print(f"test  PnL: min={min(tpnl):+.2f} med={statistics.median(tpnl):+.2f} max={max(tpnl):+.2f}")
print(f"test  WR : min={min(twr) * 100:.2f}% med={statistics.median(twr) * 100:.2f}% max={max(twr) * 100:.2f}%")

pos = [c for c in evaluated if c["test"]["net_pnl_usd"] > 0]
print(f"combos with positive test PnL: {len(pos)}/{len(evaluated)}")
for c in pos[:10]:
    print(
        "  ", c["params"],
        f"pnl={c['test']['net_pnl_usd']:+.2f}",
        f"wr={c['test']['win_rate'] * 100:.1f}%",
        f"trades={c['test']['trades_count']}",
        f"mdd={c['test']['max_drawdown_pct']:.2f}%",
    )

print("WINNER:", d.get("winner", {}).get("params") if d.get("winner") else "(none)")
sys.exit(0)
