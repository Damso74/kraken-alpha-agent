# Collector cache examples (`SYNTHETIC` / `EXAMPLE` only)

Fichiers **versionnés** pour valider les schémas JSON et les tests unitaires.
Ils ne contiennent **pas** de données historiques réelles Etherscan.

| Fichier | Usage |
|---------|--------|
| `etherscan_gas_history.example.json` | Schéma officiel `etherscan_gas_history.json` — 2 rows factices |

**Ne jamais** copier ces exemples vers `data/collector_cache/etherscan_gas_history.json`
pour contourner le minimum `lookback + 1` en recherche.

Pour tracker ce dossier dans git, le `.gitignore` racine doit inclure :

```gitignore
!data/collector_cache/examples/
!data/collector_cache/examples/**
```
