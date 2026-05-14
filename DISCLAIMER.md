# Disclaimer

This project is for **hackathon and educational purposes only**. It is **not**
financial advice. Trading — and especially live, automated trading — carries
substantial risk of loss. Tokenised equities (xStocks) carry additional risks
described in Kraken's official xStocks Risk Disclosure
(https://www.kraken.com/legal/xstocks) and the related Final Terms
(https://assets.backed.fi/legal-documentation).

xStocks are not available to U.S. persons or in several other jurisdictions.
Always check eligibility before trading.

The default operating mode of this agent is `dry_run`. No order is ever sent
to a venue unless three independent flags are set simultaneously
(`TRADING_MODE=live`, `LIVE_TRADING=true`, `ALLOW_LIVE_ORDERS=true`) and a
Kraken CLI with trading permissions is installed locally.

Locally computed PnL is labelled `source = "local_estimate"`. The official,
audit-grade PnL comes from Kraken (via the read-only API key submitted to the
hackathon organisers). The two may differ because of fees, partial fills, and
quote refresh timing.

The authors of this project accept **no liability** for any loss incurred from
its use.
