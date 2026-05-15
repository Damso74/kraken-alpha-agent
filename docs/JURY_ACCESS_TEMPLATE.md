# Jury Access — Read-Only Audit Protocol

> This file is a **template** describing the secure handoff protocol used
> to share Kraken read-only credentials with the hackathon jury. It
> contains **no real keys** and is safe to commit to a public repository.
> The actual key material lives in `data/jury_readonly_credentials.md`
> which is `.gitignore`'d (see [`.gitignore`](../.gitignore)) and is
> delivered to the jury through an out-of-band secure channel only.

## What the jury receives

A separate secure channel (out-of-band, **NOT** this repository, **NOT**
email, **NOT** Slack/Discord public channels) contains:

- Kraken **Read-Only** API key + secret (Spot).
- Kraken **Read-Only** API key + secret (Futures), if applicable.
- Kraken account public ID (last 4 chars of account UUID).
- Optional: VPS read-only SSH key for log inspection.

The bot's live keys (with `Trades` + `Positions` permissions) are
**never** shared with the jury and are never written to this repository.

## Recommended Kraken API key permissions for the jury read-only key

### Spot read-only

- Query Funds / Balances : enabled
- Query Ledger Entries : enabled
- Query Open Orders & Trades : enabled
- Query Closed Orders & Trades : enabled
- Place Orders : DISABLED
- Cancel Orders : DISABLED
- Withdraw Funds : DISABLED
- Modify Account Settings : DISABLED

### Futures read-only

- Query positions : enabled
- Query trades / fills : enabled
- Query account / balances : enabled
- Place orders : DISABLED
- Cancel orders : DISABLED
- Withdraw / transfer : DISABLED

A read-only key with the wrong scope (e.g. `Withdraw Funds` accidentally
left on) is a security incident. Double-check the permission set in the
Kraken Pro UI **before** generating the key.

## How the jury verifies live PnL

1. Install Kraken CLI 0.3.2 (Linux/WSL):

   ```bash
   curl -sSf https://krakencli.netlify.app/install.sh | bash
   kraken auth set --profile jury
   ```

   Paste the read-only key/secret when prompted. The credentials are
   stored locally on the jury workstation and are never sent to a
   third-party service.

2. Pull live account state via the read-only key:

   ```bash
   kraken balance -o json
   kraken trades-history -o json
   kraken futures positions -o json
   kraken futures fills -o json
   kraken futures accounts -o json
   ```

3. Cross-check timestamps and order IDs against the agent's local audit
   log (also provided out-of-band on request):

   - `data/trades.jsonl` — append-only trade ledger.
   - `data/agent.sqlite` — SQLite audit DB with `decisions`, `orders`,
     `positions`, `pnl_snapshots`, `errors`, `cycles` tables.
   - `export/<timestamp>/` — secret-redacted audit bundles produced by
     `python scripts/export_audit_bundle.py`.

## Security guarantees

- This repository **never** contains live API keys.
- `data/jury_readonly_credentials.md` is `.gitignore`'d and never
  committed; any attempt to `git add` it surfaces a warning in the
  wrap-up protocol.
- The jury read-only key is rotated immediately after the audit window
  closes; the live write key is rotated post-hackathon.
- The bot's live key is restricted to the VPS IP allowlist (the VPS is
  not enumerated publicly in this repository).
- Secret masking is enforced in `src/logger.py` (regex + env-var
  comparison); `tests/test_storage.py` and friends assert masked output.

## Out-of-band handoff template

When sharing the read-only credentials with the jury, use the following
template (paste into a secure channel — Signal, age-encrypted file,
1Password share link, etc.):

```
Kraken Alpha Agent — Read-only audit credentials
================================================

Account public ID (last 4): xxxx
Window: <start ISO timestamp UTC> to <end ISO timestamp UTC>

Spot READ-ONLY key:
  key:    <redacted-in-template>
  secret: <redacted-in-template>

Futures READ-ONLY key:
  key:    <redacted-in-template>
  secret: <redacted-in-template>

Verification commands:
  kraken balance -o json
  kraken trades-history -o json --start <start_epoch> --end <end_epoch>
  kraken futures fills -o json --start <start_iso> --end <end_iso>

Local audit bundle (delivered separately):
  export/<timestamp>/orders.json
  export/<timestamp>/decisions.json
  export/<timestamp>/pnl.json
```

The template values above are **placeholders**. The actual credentials
go on the secure channel only, never into this repository.
