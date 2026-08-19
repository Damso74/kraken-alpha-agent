#!/usr/bin/env python3
"""Reconstruit ``data/collector_cache/`` a partir des manifests versionnes.

Pourquoi
--------
Les phases 21 a 30 ont ete produites a partir de caches collectors qui sont
gitignores : un clone frais ne contient que ce README et les exemples. Aucun
resultat n'etait donc reproductible sans savoir *quels* fichiers manquent.

Les manifests versionnes sous ``reports/`` portent en revanche l'inventaire
exact (actif, timeframe, nombre de barres, bornes temporelles, sha256, chemin
du cache). Cet outil lit ces manifests, en deduit la liste des caches a
reconstruire, appelle les collectors publics existants
(``src/data/collectors/binance_*.py``) et compare le sha256 obtenu a celui du
manifest.

Limite honnete sur le sha256
----------------------------
Les fichiers de cache embarquent leur propre horodatage de generation
(``generated_at`` / ``fetched_at`` ecrits par ``save_*_cache``) et sont
fetches sur une fenetre qui se termine *aujourd'hui*. Un re-fetch ne peut donc
**jamais** reproduire le fichier octet pour octet : un sha256 ``mismatch``
apres reconstruction est attendu, pas un bug. Le sha256 du manifest sert a
repondre a une seule question : « ai-je exactement le fichier d'origine ? ».
Pour juger un cache reconstruit, l'outil rapporte aussi le nombre de lignes et
la fenetre temporelle obtenus face a ceux du manifest.

Les manifests derivatives (phases 26/27) ne portent **aucun** sha256 :
8 cibles sur 17 (funding BTC/ETH, open interest BTC/ETH 4h et 1d, basis
BTC/ETH 4h) ne sont donc pas verifiables par empreinte. Un fichier present
pour l'une d'elles n'est pas declare ``match`` : il est ouvert, son nombre de
lignes et sa fenetre temporelle sont compares au manifest, et il ressort
``present_unverified`` (coherent, identite non prouvable) ou ``mismatch``
(illisible, tronque, ou fenetre plus courte que le manifest).

Garde-fous
----------
- Un cache existant qui differe du manifest n'est **jamais** ecrase
  silencieusement : statut ``mismatch`` et sortie 2, sauf ``--force``.
- ``--force`` reconstruit tout cache present, y compris un
  ``present_unverified``. Seule exception : un fichier dont le sha256 est
  identique au manifest est l'original exact, jamais recuperable une fois
  ecrase — il reste ``match`` et intact.
- L'ecriture est refusee partout dans le depot en dehors de
  ``data/collector_cache/`` (jamais ``reports/``).
- Le fetcher HTTP est injectable, comme dans les collectors : les tests
  tournent sans reseau.

Codes de sortie : 0 = rien d'anormal, 1 = erreur de fetch/parse/IO,
2 = divergence (cache present mais different) ou cache toujours absent. La
regle vaut aussi en ``--dry-run`` : un inventaire hors ligne qui trouve des
caches manquants sort 2, ce qui en fait un controle CI utilisable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.data.collectors._common import default_http_fetcher  # noqa: E402
from src.data.collectors.binance_basis_public import (  # noqa: E402
    default_basis_cache_path,
    fetch_basis_history,
    save_basis_cache,
)
from src.data.collectors.binance_derivatives_public import (  # noqa: E402
    LIQUIDATIONS_BLOCKED_REASON,
    default_funding_cache_path,
    default_oi_cache_path,
    fetch_funding_rate_history,
    fetch_open_interest_history,
    save_funding_cache,
    save_oi_cache,
)
from src.data.collectors.binance_public import (  # noqa: E402
    TIMEFRAME_COVERAGE_DAYS,
    default_ohlc_cache_path,
    fetch_binance_klines,
    save_ohlc_cache,
)

DEFAULT_CACHE_ROOT = REPO_ROOT / "data" / "collector_cache"

# Manifests versionnes qui decrivent les caches attendus (phases 21 a 27).
DEFAULT_MANIFESTS: tuple[Path, ...] = (
    REPO_ROOT / "reports" / "data_manifests_phase21" / "ohlcv_backbone_manifest.json",
    REPO_ROOT / "reports" / "phase24_data_backbone" / "data_quality.json",
    REPO_ROOT / "reports" / "data_manifests_phase26" / "derivatives_readiness.json",
    REPO_ROOT / "reports" / "data_manifests_phase27" / "basis_readiness.json",
    REPO_ROOT / "reports" / "data_manifests_phase27" / "derivatives_depth.json",
)

KIND_OHLCV = "ohlcv"
KIND_FUNDING = "funding"
KIND_OPEN_INTEREST = "open_interest"
KIND_BASIS = "basis"

# Les manifests derivatives ne portent aucune borne temporelle : on retombe sur
# les memes profondeurs que les scripts de build d'origine (phases 26/27).
DEFAULT_FUNDING_DAYS = 730
DEFAULT_OI_DAYS = 30

STATUS_MATCH = "match"
STATUS_PRESENT_UNVERIFIED = "present_unverified"
STATUS_MISMATCH = "mismatch"
STATUS_ABSENT = "absent"
STATUS_REBUILT = "rebuilt"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"

TMP_SUFFIX = ".reseed-tmp"

# Tolerance de manque de lignes face au manifest. Un re-fetch se termine
# *aujourd'hui* et peut perdre la bougie partielle de bord ; au-dela de 2 %
# ce n'est plus un effet de bord, c'est une autre serie (ou un fichier tronque).
ROW_COUNT_SHORTFALL_TOLERANCE = 0.02

# Meme logique pour les bornes : une journee d'ecart n'est pas une divergence.
WINDOW_TOLERANCE_SECONDS = 86_400

# Les caches du depot rangent leurs lignes sous l'une de ces cles.
CACHE_ROW_KEYS: tuple[str, ...] = ("candles", "rows")

FetcherFn = Callable[[str, Mapping[str, Any]], Any]


class ReseedError(RuntimeError):
    """Erreur de configuration de l'outil (manifest illisible, racine interdite)."""


# --------------------------------------------------------------------------
# Manifests -> cibles
# --------------------------------------------------------------------------


@dataclass
class CacheTarget:
    """Un fichier de cache attendu, deduit d'un ou plusieurs manifests."""

    kind: str
    asset: str
    filename: str
    timeframe: str | None = None
    sha256: str | None = None
    row_count: int | None = None
    first_timestamp: int | None = None
    last_timestamp: int | None = None
    sources: list[str] = field(default_factory=list)
    skip_reason: str | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "filename": self.filename,
            "sha256_expected": self.sha256,
            "row_count_expected": self.row_count,
            "first_timestamp_expected": self.first_timestamp,
            "last_timestamp_expected": self.last_timestamp,
            "sources": list(self.sources),
            "skip_reason": self.skip_reason,
            "warnings": list(self.warnings),
        }


def manifest_basename(raw_path: Any) -> str:
    """Nom de fichier seul d'un chemin manifest.

    Les manifests versionnes portent des chemins absolus de la machine
    d'origine (``C:\\Users\\credo\\...``) : ``Path(...).name`` ne les decoupe
    pas sous POSIX. On normalise donc les deux separateurs a la main.
    """
    if not raw_path:
        return ""
    text = str(raw_path).replace("\\", "/").rstrip("/")
    return text.rsplit("/", 1)[-1]


def classify_filename(name: str) -> tuple[str, str | None] | None:
    """(kind, timeframe) deduit du nom de fichier de cache, sinon ``None``."""
    if not name.endswith(".json"):
        return None
    stem = name[: -len(".json")]
    if stem.startswith("ohlc_daily_"):
        return (KIND_OHLCV, "1d")
    if stem.startswith("ohlc_4h_"):
        return (KIND_OHLCV, "4h")
    if stem.startswith("ohlc_1h_"):
        return (KIND_OHLCV, "1h")
    if stem.startswith("funding_"):
        return (KIND_FUNDING, None)
    if stem.startswith("oi_"):
        return (KIND_OPEN_INTEREST, stem.rsplit("_", 1)[-1].lower())
    if stem.startswith("basis_"):
        return (KIND_BASIS, stem.rsplit("_", 1)[-1].lower())
    return None


def classify_series(series: str, timeframe: str | None) -> tuple[str, str | None] | None:
    """(kind, timeframe) deduit du champ ``series`` d'un manifest readiness."""
    s = (series or "").strip().lower()
    if not s:
        return None
    if s == "funding":
        return (KIND_FUNDING, None)
    if s.startswith("open_interest"):
        tail = s.rsplit("_", 1)[-1]
        return (KIND_OPEN_INTEREST, timeframe or (tail if tail != "interest" else None))
    if s.startswith("basis"):
        tail = s.rsplit("_", 1)[-1]
        return (KIND_BASIS, timeframe or (tail if tail != "basis" else None))
    return None


def expected_filename(kind: str, asset: str, timeframe: str | None) -> str:
    """Nom de fichier canonique tel que les collectors du depot l'ecriraient."""
    if kind == KIND_OHLCV:
        return default_ohlc_cache_path(asset, timeframe or "1d").name
    if kind == KIND_FUNDING:
        return default_funding_cache_path(asset).name
    if kind == KIND_OPEN_INTEREST:
        return default_oi_cache_path(asset, timeframe or "4h").name
    if kind == KIND_BASIS:
        return default_basis_cache_path(asset, timeframe or "4h").name
    raise ReseedError(f"kind inconnu: {kind}")


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def target_from_entry(entry: Mapping[str, Any], *, source: str) -> CacheTarget | None:
    """Traduit une entree de manifest en cible de cache, ou ``None``."""
    if not isinstance(entry, Mapping):
        return None

    asset = str(entry.get("asset") or "").strip().upper().partition("/")[0]
    series = str(entry.get("series") or "").strip().lower()
    raw_timeframe = entry.get("timeframe") or entry.get("period")
    timeframe = str(raw_timeframe).strip().lower() if raw_timeframe else None
    filename = manifest_basename(entry.get("cache_path") or entry.get("path"))

    if series == "liquidations" or asset in ("", "*"):
        # Entree pseudo-serie du manifest phase 26 : aucun cache a reconstruire.
        return CacheTarget(
            kind=series or "unknown",
            asset=asset or "*",
            filename=filename or f"{series or 'unknown'}",
            timeframe=timeframe,
            sources=[source],
            skip_reason=(
                LIQUIDATIONS_BLOCKED_REASON
                if series == "liquidations"
                else "entree sans actif identifiable"
            ),
        )

    classified = classify_filename(filename) or classify_series(series, timeframe)
    if classified is None:
        return None
    kind, tf = classified
    tf = tf or timeframe

    canonical = expected_filename(kind, asset, tf)
    warnings: list[str] = []
    if not filename:
        filename = canonical
    elif filename != canonical:
        warnings.append(
            f"nom de fichier manifest {filename!r} != nom canonique {canonical!r}"
        )

    row_count = _as_int(entry.get("bar_count"))
    if row_count is None:
        row_count = _as_int(entry.get("row_count"))
    first_ts = _as_int(entry.get("first_timestamp"))
    if first_ts is None:
        first_ts = _as_int(entry.get("coverage_start"))
    last_ts = _as_int(entry.get("last_timestamp"))
    if last_ts is None:
        last_ts = _as_int(entry.get("coverage_end"))

    sha = entry.get("sha256")
    sha_str = str(sha).strip().lower() if isinstance(sha, str) and sha.strip() else None

    skip_reason = None
    status = str(entry.get("status") or entry.get("gate_status") or "").strip().lower()
    if status and status != "available" and not row_count:
        # Le manifest lui-meme declare la serie indisponible a l'origine :
        # on l'expose sans pretendre pouvoir la reconstruire a l'identique.
        reason = entry.get("blocked_reason") or f"status={status}"
        skip_reason = f"jamais collecte a l'origine ({reason})"

    return CacheTarget(
        kind=kind,
        asset=asset,
        filename=filename,
        timeframe=tf,
        sha256=sha_str,
        row_count=row_count,
        first_timestamp=first_ts,
        last_timestamp=last_ts,
        sources=[source],
        skip_reason=skip_reason,
        warnings=warnings,
    )


def parse_manifest_payload(payload: Any, *, source: str) -> list[CacheTarget]:
    """Extrait les cibles d'un manifest, y compris ses sous-sections."""
    if not isinstance(payload, Mapping):
        raise ReseedError(f"manifest {source}: racine JSON non-objet")

    targets: list[CacheTarget] = []
    entries = payload.get("entries")
    if isinstance(entries, list):
        for entry in entries:
            target = target_from_entry(entry, source=source)
            if target is not None:
                targets.append(target)

    # ``derivatives_depth.json`` empile plusieurs manifests (oi_depth,
    # derivatives, basis) sous des cles de premier niveau.
    for key, value in payload.items():
        if key == "entries" or not isinstance(value, Mapping):
            continue
        if isinstance(value.get("entries"), list):
            targets.extend(parse_manifest_payload(value, source=f"{source}#{key}"))
    return targets


def load_manifest(path: Path) -> list[CacheTarget]:
    """Lit un manifest JSON versionne et en deduit les cibles."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReseedError(f"manifest illisible {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ReseedError(f"manifest JSON invalide {path}: {exc}") from exc
    return parse_manifest_payload(payload, source=path.name)


def merge_targets(targets: Iterable[CacheTarget]) -> list[CacheTarget]:
    """Fusionne les cibles par nom de fichier (un cache peut etre cite 2x)."""
    merged: dict[str, CacheTarget] = {}
    for target in targets:
        existing = merged.get(target.filename)
        if existing is None:
            merged[target.filename] = CacheTarget(
                kind=target.kind,
                asset=target.asset,
                filename=target.filename,
                timeframe=target.timeframe,
                sha256=target.sha256,
                row_count=target.row_count,
                first_timestamp=target.first_timestamp,
                last_timestamp=target.last_timestamp,
                sources=list(target.sources),
                skip_reason=target.skip_reason,
                warnings=list(target.warnings),
            )
            continue
        for source in target.sources:
            if source not in existing.sources:
                existing.sources.append(source)
        for warning in target.warnings:
            if warning not in existing.warnings:
                existing.warnings.append(warning)
        if existing.sha256 is None:
            existing.sha256 = target.sha256
        elif target.sha256 and target.sha256 != existing.sha256:
            existing.warnings.append(
                f"sha256 divergent entre manifests: {existing.sha256} vs {target.sha256}"
            )
        # On garde l'exigence la plus large quand deux manifests different.
        if target.row_count is not None:
            existing.row_count = max(existing.row_count or 0, target.row_count)
        if target.first_timestamp is not None:
            existing.first_timestamp = min(
                existing.first_timestamp or target.first_timestamp, target.first_timestamp
            )
        if target.last_timestamp is not None:
            existing.last_timestamp = max(
                existing.last_timestamp or target.last_timestamp, target.last_timestamp
            )
        if existing.skip_reason and not target.skip_reason and (target.row_count or 0) > 0:
            # Un autre manifest a bien vu des lignes pour cette serie : elle est
            # reconstructible malgre le blocage constate ailleurs.
            existing.skip_reason = None
    return sorted(merged.values(), key=lambda t: (t.kind, t.asset, t.filename))


def load_targets(manifest_paths: Sequence[Path]) -> list[CacheTarget]:
    collected: list[CacheTarget] = []
    for path in manifest_paths:
        collected.extend(load_manifest(path))
    return merge_targets(collected)


# --------------------------------------------------------------------------
# Reconstruction
# --------------------------------------------------------------------------


def resolve_cache_root(cache_root: Path) -> Path:
    """Refuse toute racine d'ecriture interne au depot hors collector_cache."""
    resolved = Path(cache_root).resolve()
    allowed = DEFAULT_CACHE_ROOT.resolve()
    if resolved == allowed:
        return resolved
    if allowed in resolved.parents:
        return resolved
    repo = REPO_ROOT.resolve()
    if resolved == repo or repo in resolved.parents:
        raise ReseedError(
            f"racine de cache interdite: {resolved} (seul {allowed} est ecrivable "
            "dans le depot)"
        )
    # Hors du depot (tmp_path des tests, cache externe) : autorise.
    return resolved


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def coverage_days_for(target: CacheTarget, *, now: datetime) -> int | None:
    """Profondeur de fetch pour couvrir au moins la fenetre du manifest."""
    default = TIMEFRAME_COVERAGE_DAYS.get(target.timeframe or "")
    if target.first_timestamp is None:
        return default
    span = math.ceil((now.timestamp() - float(target.first_timestamp)) / 86400.0) + 5
    span = max(span, 1)
    return max(span, default) if default else span


def _normalized_stamp(value: Any) -> int | None:
    """Timestamp en secondes, ou ``None``. Meme convention ms->s que les collectors."""
    if isinstance(value, bool):
        return None
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return None
    if ts > 10_000_000_000:
        ts //= 1000
    return ts


def _window_of(rows: Sequence[Any]) -> tuple[int | None, int | None]:
    stamps = [
        stamp
        for stamp in (
            _normalized_stamp(row.get("timestamp"))
            for row in rows
            if isinstance(row, Mapping)
        )
        if stamp is not None
    ]
    if not stamps:
        return (None, None)
    return (min(stamps), max(stamps))


def inspect_cache_file(path: Path) -> dict[str, Any]:
    """Nombre de lignes et fenetre temporelle d'un cache deja present.

    Lecture volontairement tolerante : un fichier illisible, non-JSON ou de
    structure inconnue n'est pas une exception a propager mais un *constat*
    (``unreadable``), et ce constat vaut divergence. C'est le seul moyen de
    juger les 8 cibles dont le manifest ne porte aucun sha256.
    """
    out: dict[str, Any] = {
        "row_count": None,
        "first_timestamp": None,
        "last_timestamp": None,
        "unreadable": None,
    }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        out["unreadable"] = f"illisible ({exc})"
        return out
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        out["unreadable"] = f"JSON invalide ({exc})"
        return out

    rows: Any = None
    if isinstance(payload, Mapping):
        entries = payload.get("entries")
        if isinstance(entries, Mapping):
            for key in CACHE_ROW_KEYS:
                if isinstance(entries.get(key), list):
                    rows = entries[key]
                    break
        if rows is None and isinstance(payload.get("rows"), list):
            rows = payload["rows"]
    if rows is None:
        out["unreadable"] = "structure inconnue (ni entries.candles, ni entries.rows)"
        return out

    out["row_count"] = len(rows)
    first_ts, last_ts = _window_of(rows)
    out["first_timestamp"] = first_ts
    out["last_timestamp"] = last_ts
    return out


def content_divergences(
    target: CacheTarget, observed: Mapping[str, Any]
) -> list[str]:
    """Ecarts entre le contenu observe d'un cache et ce que le manifest annonce.

    Liste vide = rien de verifiable ne cloche. Ne signale que les manques
    (moins de lignes, fenetre plus courte) : un cache *plus* riche que le
    manifest est normal, la fenetre de re-fetch se termine aujourd'hui.
    """
    unreadable = observed.get("unreadable")
    if unreadable:
        return [f"contenu {unreadable}"]

    diffs: list[str] = []
    expected_rows = target.row_count
    actual_rows = observed.get("row_count")
    if expected_rows and actual_rows is not None:
        floor = int(expected_rows * (1.0 - ROW_COUNT_SHORTFALL_TOLERANCE))
        if actual_rows < floor:
            diffs.append(
                f"row_count {actual_rows} < {expected_rows} attendu (plancher {floor})"
            )

    first_actual = observed.get("first_timestamp")
    if target.first_timestamp is not None and first_actual is not None:
        if first_actual > target.first_timestamp + WINDOW_TOLERANCE_SECONDS:
            diffs.append(
                f"debut {first_actual} posterieur au manifest {target.first_timestamp}"
            )

    last_actual = observed.get("last_timestamp")
    if target.last_timestamp is not None and last_actual is not None:
        if last_actual < target.last_timestamp - WINDOW_TOLERANCE_SECONDS:
            diffs.append(
                f"fin {last_actual} anterieure au manifest {target.last_timestamp}"
            )
    return diffs


def fetch_and_save(
    target: CacheTarget,
    destination: Path,
    *,
    fetcher: FetcherFn,
    now: datetime,
    funding_days: int = DEFAULT_FUNDING_DAYS,
    oi_days: int = DEFAULT_OI_DAYS,
    coverage_days_override: int | None = None,
) -> list[dict[str, Any]]:
    """Appelle le collector adapte et ecrit ``destination``. Retourne les rows."""
    coverage = coverage_days_override or coverage_days_for(target, now=now)
    end_ms = int(now.timestamp() * 1000)

    if target.kind == KIND_OHLCV:
        timeframe = target.timeframe or "1d"
        rows = fetch_binance_klines(
            target.asset, timeframe, coverage_days=coverage, fetcher=fetcher
        )
        save_ohlc_cache(
            destination, ticker=target.asset, timeframe=timeframe, rows=rows
        )
        return rows

    if target.kind == KIND_FUNDING:
        start_ms = end_ms - funding_days * 86400 * 1000
        rows = fetch_funding_rate_history(
            target.asset, start_ms=start_ms, end_ms=end_ms, fetcher=fetcher
        )
        save_funding_cache(destination, ticker=target.asset, rows=rows)
        return rows

    if target.kind == KIND_OPEN_INTEREST:
        period = target.timeframe or "4h"
        start_ms = end_ms - oi_days * 86400 * 1000
        rows = fetch_open_interest_history(
            target.asset, period, start_ms=start_ms, end_ms=end_ms, fetcher=fetcher
        )
        save_oi_cache(destination, ticker=target.asset, period=period, rows=rows)
        return rows

    if target.kind == KIND_BASIS:
        timeframe = target.timeframe or "4h"
        rows = fetch_basis_history(
            target.asset, timeframe, coverage_days=coverage, fetcher=fetcher
        )
        save_basis_cache(
            destination, ticker=target.asset, timeframe=timeframe, rows=rows
        )
        return rows

    raise ReseedError(f"kind non reconstructible: {target.kind}")


def _rebuild(
    target: CacheTarget,
    path: Path,
    *,
    fetcher: FetcherFn,
    now: datetime,
    funding_days: int,
    oi_days: int,
    coverage_days_override: int | None,
) -> dict[str, Any]:
    """Fetch vers un fichier temporaire puis remplacement atomique."""
    tmp = path.with_name(path.name + TMP_SUFFIX)
    try:
        rows = fetch_and_save(
            target,
            tmp,
            fetcher=fetcher,
            now=now,
            funding_days=funding_days,
            oi_days=oi_days,
            coverage_days_override=coverage_days_override,
        )
        if not tmp.is_file():
            raise ReseedError(f"ecriture du cache temporaire impossible: {tmp}")
        digest = sha256_file(tmp)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()

    first_ts, last_ts = _window_of(rows)
    return {
        "status": STATUS_REBUILT,
        "sha256_actual": digest,
        "row_count_actual": len(rows),
        "first_timestamp_actual": first_ts,
        "last_timestamp_actual": last_ts,
    }


def reseed_target(
    target: CacheTarget,
    *,
    cache_root: Path,
    fetcher: FetcherFn,
    dry_run: bool = False,
    force: bool = False,
    now: datetime | None = None,
    funding_days: int = DEFAULT_FUNDING_DAYS,
    oi_days: int = DEFAULT_OI_DAYS,
    coverage_days_override: int | None = None,
) -> dict[str, Any]:
    """Verifie puis, si besoin, reconstruit un cache. N'ecrase jamais en silence."""
    moment = now or datetime.now(UTC)
    path = cache_root / target.filename
    result = target.as_dict()
    result.update(
        {
            "path": str(path),
            "sha256_actual": None,
            "row_count_actual": None,
            "first_timestamp_actual": None,
            "last_timestamp_actual": None,
            "action": "none",
            "note": None,
        }
    )

    if target.skip_reason:
        result["status"] = STATUS_SKIPPED
        result["note"] = target.skip_reason
        return result

    actual_sha = sha256_file(path)
    result["sha256_actual"] = actual_sha

    if actual_sha is not None:
        observed = inspect_cache_file(path)
        result["row_count_actual"] = observed["row_count"]
        result["first_timestamp_actual"] = observed["first_timestamp"]
        result["last_timestamp_actual"] = observed["last_timestamp"]

        if target.sha256 and actual_sha == target.sha256:
            # Fichier d'origine exact : --force ne l'ecrase pas, un re-fetch ne
            # saurait pas le reproduire (horodatage embarque).
            result["status"] = STATUS_MATCH
            return result

        diffs = content_divergences(target, observed)
        if target.sha256:
            result["status"] = STATUS_MISMATCH
            reason = "cache present mais sha256 different du manifest"
            if diffs:
                reason += "; " + "; ".join(diffs)
        elif diffs:
            result["status"] = STATUS_MISMATCH
            reason = (
                "aucun sha256 dans le manifest, mais le contenu diverge: "
                + "; ".join(diffs)
            )
        else:
            result["status"] = STATUS_PRESENT_UNVERIFIED
            reason = (
                "aucun sha256 dans le manifest: identite non prouvable; "
                f"row_count={observed['row_count']} et bornes coherents "
                "avec le manifest"
            )
        result["note"] = reason
        if not force:
            suffix = (
                "non ecrase (utiliser --force pour reconstruire)"
                if result["status"] == STATUS_MISMATCH
                else "conserve tel quel (--force pour re-fetcher quand meme)"
            )
            result["note"] = f"{reason}; {suffix}"
            return result

    if dry_run:
        if actual_sha is None:
            result["status"] = STATUS_ABSENT
        result["action"] = "would_fetch"
        prefix = f"{result['note']}; " if result.get("note") else ""
        result["note"] = f"{prefix}dry-run: aucun appel reseau, aucune ecriture"
        return result

    try:
        rebuilt = _rebuild(
            target,
            path,
            fetcher=fetcher,
            now=moment,
            funding_days=funding_days,
            oi_days=oi_days,
            coverage_days_override=coverage_days_override,
        )
    except Exception as exc:  # noqa: BLE001 - on rapporte, on n'interrompt pas le lot
        result["status"] = STATUS_ERROR
        result["action"] = "fetch"
        result["note"] = f"{type(exc).__name__}: {exc}"
        return result

    result.update(rebuilt)
    result["action"] = "fetch"

    notes: list[str] = []
    if target.sha256 and rebuilt["sha256_actual"] != target.sha256:
        notes.append(
            "reconstruit mais sha256 different du manifest: le cache embarque son "
            "horodatage de generation, la reproduction octet-a-octet est impossible"
        )
    # Le sha ne pouvant pas trancher, c'est le volume et la fenetre qui disent
    # si le cache reconstruit vaut celui des phases 21-30. Sans cela un OHLC 1h
    # a 12 000 barres au lieu de 17 650 sortirait 'rebuilt' et exit 0, alors
    # qu'il echouerait le gate data_ok.
    diffs = content_divergences(
        target,
        {
            "row_count": rebuilt["row_count_actual"],
            "first_timestamp": rebuilt["first_timestamp_actual"],
            "last_timestamp": rebuilt["last_timestamp_actual"],
        },
    )
    if diffs:
        result["status"] = STATUS_MISMATCH
        notes.append("reconstruit mais divergent du manifest: " + "; ".join(diffs))
    result["note"] = "; ".join(notes) or None
    return result


def reseed(
    targets: Sequence[CacheTarget],
    *,
    cache_root: Path,
    fetcher: FetcherFn = default_http_fetcher,
    dry_run: bool = False,
    force: bool = False,
    now: datetime | None = None,
    funding_days: int = DEFAULT_FUNDING_DAYS,
    oi_days: int = DEFAULT_OI_DAYS,
    coverage_days_override: int | None = None,
) -> dict[str, Any]:
    """Traite toutes les cibles et retourne un rapport JSON-serialisable."""
    root = resolve_cache_root(cache_root)
    if not dry_run:
        root.mkdir(parents=True, exist_ok=True)

    moment = now or datetime.now(UTC)
    results = [
        reseed_target(
            target,
            cache_root=root,
            fetcher=fetcher,
            dry_run=dry_run,
            force=force,
            now=moment,
            funding_days=funding_days,
            oi_days=oi_days,
            coverage_days_override=coverage_days_override,
        )
        for target in targets
    ]

    counts: dict[str, int] = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1

    return {
        "generated_at": moment.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "cache_root": str(root),
        "dry_run": bool(dry_run),
        "force": bool(force),
        "targets_total": len(results),
        "counts": counts,
        "results": results,
    }


def exit_code_for(report: Mapping[str, Any]) -> int:
    """1 si erreur, 2 si divergence ou cache absent, 0 sinon.

    La regle ne depend **pas** de ``--dry-run`` : un inventaire hors ligne qui
    trouve 17 caches manquants doit sortir 2, sinon ``--dry-run`` ne peut pas
    servir de controle CI (« les caches attendus sont-ils la ? »).

    ``present_unverified`` ne vaut pas 2 : le fichier est la et coherent avec
    tout ce que le manifest permet de verifier ; seule son *identite* reste
    non prouvable, ce qui est un defaut du manifest, pas du cache.
    """
    counts = report.get("counts") or {}
    if counts.get(STATUS_ERROR):
        return 1
    if counts.get(STATUS_MISMATCH) or counts.get(STATUS_ABSENT):
        return 2
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def format_report(report: Mapping[str, Any]) -> str:
    lines: list[str] = []
    mode = "dry-run" if report.get("dry_run") else "reseed"
    lines.append(f"[{mode}] cache_root={report['cache_root']}")
    for item in report["results"]:
        head = f"  {item['status']:<18} {item['filename']}"
        detail: list[str] = []
        if item.get("row_count_expected"):
            got = item.get("row_count_actual")
            detail.append(
                f"rows={got if got is not None else '?'}/{item['row_count_expected']}"
            )
        if item.get("sha256_expected"):
            detail.append(f"sha_manifest={item['sha256_expected'][:12]}")
        if item.get("sha256_actual"):
            detail.append(f"sha_local={item['sha256_actual'][:12]}")
        if detail:
            head += "  " + " ".join(detail)
        lines.append(head)
        if item.get("note"):
            lines.append(f"            note: {item['note']}")
        for warning in item.get("warnings") or []:
            lines.append(f"            warn: {warning}")
    counts = ", ".join(f"{k}={v}" for k, v in sorted(report["counts"].items()))
    lines.append(f"  total={report['targets_total']} ({counts})")
    return "\n".join(lines)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reconstruit data/collector_cache/ depuis les manifests versionnes "
            "et verifie les sha256"
        )
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        action="append",
        default=None,
        help="Manifest explicite (repetable). Defaut: les 5 manifests phases 21-27.",
    )
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Liste ce qui serait fait, sans reseau ni ecriture. Sort 2 si des "
            "caches manquent ou divergent (utilisable en controle CI)."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Reconstruit tout cache present divergent ou non verifiable. Un "
            "cache dont le sha256 est identique au manifest reste intact."
        ),
    )
    parser.add_argument(
        "--only",
        nargs="+",
        default=None,
        metavar="ASSET",
        help="Restreint aux actifs listes (ex: BTC ETH)",
    )
    parser.add_argument("--funding-days", type=int, default=DEFAULT_FUNDING_DAYS)
    parser.add_argument("--oi-days", type=int, default=DEFAULT_OI_DAYS)
    parser.add_argument(
        "--coverage-days",
        type=int,
        default=None,
        help="Force la profondeur OHLCV/basis (defaut: fenetre du manifest)",
    )
    parser.add_argument("--json", action="store_true", help="Rapport JSON complet")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    manifests = [Path(p) for p in (args.manifest or DEFAULT_MANIFESTS)]

    try:
        targets = load_targets(manifests)
        if args.only:
            wanted = {a.strip().upper() for a in args.only}
            targets = [t for t in targets if t.asset in wanted]
        report = reseed(
            targets,
            cache_root=args.cache_root,
            dry_run=args.dry_run,
            force=args.force,
            funding_days=args.funding_days,
            oi_days=args.oi_days,
            coverage_days_override=args.coverage_days,
        )
    except ReseedError as exc:
        print(f"erreur: {exc}", file=sys.stderr)
        return 1

    report["manifests"] = [str(p) for p in manifests]
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_report(report))
    return exit_code_for(report)


if __name__ == "__main__":
    raise SystemExit(main())
