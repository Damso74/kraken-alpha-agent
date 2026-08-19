# Phase 24 — Data backbone audit

Source de verite : `reports/phase24_data_backbone/data_quality.json`
(genere le 2026-05-20T17:13:22Z au commit `ed3aa7b`).

> **Provenance.** Ce markdown est regenere depuis le JSON ci-dessus, qui est
> l'artefact produit par le run reel du 2026-05-20. La version precedente de ce
> fichier documentait par erreur un cache **synthetique BTC/XRP de 2020** : le
> script ecrivait son markdown dans un chemin repo en dur, si bien que
> `tests/test_data_backbone_audit_phase24.py` — qui seme une fixture — ecrasait
> le rapport versionne a chaque `pytest`. Corrige : le markdown suit desormais
> `--report-dir`, et la CI verifie par `git diff --exit-code` qu'aucun test ne
> reecrit un fichier suivi.

## Summary

- Required pairs (BTC/ETH/SOL x 1d/4h) : **6/6** data_ok
- Required complete : **True**
- Entries audited : **6**
- data_ok : **6**
- ideal bars (1d>=1000, 4h>=2000) : **6**
- Longer than Phase 23 `--max-bars 500` cap : **6**

## Criteria

- data_ok : 1d >=500 bars, 4h >=1000 bars
- ideal : 1d >=1000, 4h >=2000
- Phase 23 factory used last **500** bars by default

## Inventory

| asset | tf | bars | data_ok | ideal | first | last | gaps | dup | sha256 |
|-------|----|------|---------|-------|-------|------|------|-----|--------|
| BTC | 1d | 1831 | True | True | 2021-05-16 | 2026-05-20 | 0 | 0 | `2a3799bf39c3` |
| BTC | 4h | 6603 | True | True | 2023-05-16 | 2026-05-20 | 0 | 0 | `647b181cfd63` |
| ETH | 1d | 1831 | True | True | 2021-05-16 | 2026-05-20 | 0 | 0 | `8beaed4940d3` |
| ETH | 4h | 6603 | True | True | 2023-05-16 | 2026-05-20 | 0 | 0 | `72a8ad0ae1a2` |
| SOL | 1d | 1831 | True | True | 2021-05-16 | 2026-05-20 | 0 | 0 | `efb7af818c85` |
| SOL | 4h | 6603 | True | True | 2023-05-16 | 2026-05-20 | 0 | 0 | `2af3184811ae` |

## Reproduction

Les caches OHLCV ne sont pas versionnes (`.gitignore`). Pour reconstruire
l'etat audite ci-dessus puis verifier les sha256 :

```bash
python scripts/reseed_collector_cache.py --manifest reports/phase24_data_backbone/data_quality.json
python scripts/audit_data_backbone_phase24.py
```
