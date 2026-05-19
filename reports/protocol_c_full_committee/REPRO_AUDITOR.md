# Committee — Reproducibility Auditor

- Git SHA dans JSON : **oui** (`a066001f4a3f93e7f4dea1643451c7b469c3ecf3`).  
- CLI :
  ```powershell
  python scripts/event_study_volume_shock.py --run-all-variants --days 365 `
    --ohlc-source cache --use-cache-only --enable-holdout --holdout-fraction 0.5 `
    --embargo-days 7 --assets BTC,ETH,SOL --output-dir reports/research_runs_phase13 --protocol protocol_a
  ```
- Seed : 20260519.  
- Cache paths + SHA256 par actif dans `data_provenance`.  
- **Score rôle :** 9/10.
