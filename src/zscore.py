"""Z-score glissant partage — source unique de verite.

Pourquoi un module a part
-------------------------
Le meme z-score glissant est calcule par l'overlay de crowding
(:mod:`src.bot.crowding_overlay`) et par le collecteur de basis
(:mod:`src.data.collectors.binance_basis_public`). Tant qu'il existait une
copie par module, corriger ``sd = pstdev(buf) or 1e-12`` dans l'une laissait
le defaut intact dans les autres — c'est exactement ce qui est arrive.

Le module vit a la racine de ``src`` et n'importe que la stdlib: ``src.bot``
depend de ``src.data``, jamais l'inverse, donc placer l'helper dans l'une des
deux couches aurait inverse ce sens (un collecteur important le moteur de
paper-trading) et rendu le graphe d'imports cyclique au niveau paquet.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from typing import Literal

# Statut d'un z-score: distinguer "pas de donnee" d'un "z-score nul" est le
# coeur du defaut #12 — les deux valaient 0.0 et se lisaient "neutral".
ZStatus = Literal["ok", "no_data", "warmup", "flat"]

# Un ecart-type sous ce seuil signale une serie degeneree (constante), pas une
# faible volatilite: le z-score n'y est pas defini.
FLAT_SD_ABS_EPS = 1e-15
FLAT_SD_REL_EPS = 1e-9


def min_window_samples(window: int) -> int:
    """Nombre d'echantillons requis avant de sortir du warmup."""
    return max(10, window // 2)


def rolling_z_status(
    values: Sequence[float | None],
    window: int,
) -> list[tuple[float | None, ZStatus]]:
    """Z-score glissant accompagne de son statut, un element par entree.

    Le statut ``flat`` remplace l'ancien ``pstdev(buf) or 1e-12``: sur une
    serie devenue constante l'ecart-type est nul, le z-score valait donc
    exactement 0.0 et etait indiscernable d'un vrai "proche de la moyenne".
    Le plancher a 1e-12 etait de surcroit numeriquement dangereux: sur une
    serie quasi-constante il divisait un bruit flottant par 1e-12 et pouvait
    fabriquer des z-scores extremes a partir de rien.
    """
    out: list[tuple[float | None, ZStatus]] = []
    buf: list[float] = []
    need = min_window_samples(window)
    for v in values:
        if v is None:
            out.append((None, "no_data"))
            continue
        buf.append(v)
        if len(buf) > window:
            buf.pop(0)
        if len(buf) < need:
            out.append((None, "warmup"))
            continue
        mu = statistics.mean(buf)
        sd = statistics.pstdev(buf)
        if sd <= max(FLAT_SD_ABS_EPS, FLAT_SD_REL_EPS * abs(mu)):
            out.append((0.0, "flat"))
            continue
        out.append(((v - mu) / sd, "ok"))
    return out


def rolling_z(values: Sequence[float | None], window: int) -> list[float | None]:
    """Z-scores seuls (compat); voir :func:`rolling_z_status` pour le statut."""
    return [z for z, _ in rolling_z_status(values, window)]
