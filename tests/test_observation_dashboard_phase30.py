"""Phase 30.2 — observation dashboard generator tests."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from scripts.generate_observation_dashboard_phase30 import build_dashboard_html, write_dashboard


def _minimal_summary() -> dict:
    return {
        "generated_at_utc": "2026-05-21T12:00:00+00:00",
        "summary": {
            "target_count": 1,
            "total_decisions": 1,
            "total_trades": 0,
            "any_kill_triggered": False,
        },
        "targets": [
            {
                "target": "trend_following_baseline",
                "decision_count": 1,
                "trade_count": 0,
                "block_rate_on_signals": 0.0,
                "stale_data_count": 0,
                "error_count": 0,
                "overlay_decisions": {"allow": 1, "block": 0, "reduce": 0, "neutral": 0},
                "equity": {"overlay_usd": 1000.0, "overlay_return_pct_from_1k": 0.0},
                "shadow_proxies": {"blocks": 0, "reductions": 0, "missed_upside_bars": 0},
                "kill_criteria": {"should_kill": False, "reasons": []},
            }
        ],
    }


# Attributs par lesquels un navigateur va *charger* quelque chose au rendu.
# ``<a href>`` en est volontairement absent : un lien hypertexte ne declenche
# aucune requete tant que le lecteur ne clique pas, et n'empeche donc pas la
# lecture hors-ligne du dashboard.
_LOADING_ATTRS: dict[str, tuple[str, ...]] = {
    "link": ("href",),
    "script": ("src",),
    "img": ("src", "srcset"),
    "iframe": ("src",),
    "frame": ("src",),
    "embed": ("src",),
    "object": ("data",),
    "source": ("src", "srcset"),
    "track": ("src",),
    "video": ("src", "poster"),
    "audio": ("src",),
    "input": ("src",),
    "use": ("href", "xlink:href"),
    "image": ("href", "xlink:href"),
}
# ``url(...)`` et ``@import`` dans une feuille de style inline ou un attribut
# ``style`` : le navigateur les charge aussi.
_CSS_REF_RE = re.compile(
    r"""(?:\burl\(\s*|@import\s+(?:url\(\s*)?)(?:'([^']*)'|"([^"]*)"|([^'")\s;]+))""",
    re.IGNORECASE,
)
# Tout ce qui designe un hote distant : un schema explicite (https:, ftp:) ou
# une URL protocol-relative (//cdn/...). ``data:`` est traite a part : il porte
# la ressource dans le document, donc il reste autonome.
_REMOTE_REF_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//)", re.IGNORECASE)


class _ResourceRefCollector(HTMLParser):
    """Collecte les URL que le rendu de la page irait chercher."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[tuple[str, str]] = []
        self._in_style = False

    def _collect(self, origin: str, value: str | None) -> None:
        if value:
            self.refs.append((origin, value))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        mapping = {k.lower(): v for k, v in attrs}
        for attr in _LOADING_ATTRS.get(tag, ()):
            value = mapping.get(attr)
            if attr == "srcset" and value:
                for candidate in value.split(","):
                    self._collect(f"<{tag} {attr}>", candidate.strip().split(" ")[0])
            else:
                self._collect(f"<{tag} {attr}>", value)
        style = mapping.get("style")
        if style:
            for match in _CSS_REF_RE.findall(style):
                self._collect(f"<{tag} style>", next((m for m in match if m), ""))
        if tag == "style":
            self._in_style = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if not self._in_style:
            return
        for match in _CSS_REF_RE.findall(data):
            self._collect("<style>", next((m for m in match if m), ""))


def _assert_no_external_resource(html_doc: str) -> None:
    """Le dashboard doit rester lisible hors-ligne : aucune ressource distante.

    "Ressource" au sens strict : ce que le navigateur telecharge tout seul pour
    afficher la page (feuille de style, script, image, iframe, police, url()
    CSS). Sont explicitement autorises, parce qu'ils n'entrainent aucune
    requete au rendu :

    * les ancres internes et les liens hypertexte ``<a href="...">``, y compris
      vers un hote distant — cliquer est un acte du lecteur, pas du rendu ;
    * les ``data:`` URI, qui embarquent la ressource dans le document.

    L'assertion d'origine (``"external" not in doc or "no external" in doc``)
    etait une disjonction toujours vraie : elle testait la presence d'un mot
    dans la prose, jamais les URL reellement referencees.
    """
    collector = _ResourceRefCollector()
    collector.feed(html_doc)
    collector.close()
    for origin, ref in collector.refs:
        target = ref.strip()
        if not target or target.startswith("#") or target.lower().startswith("data:"):
            continue
        assert not _REMOTE_REF_RE.match(target), f"ressource externe chargee par {origin}: {target}"


def test_build_dashboard_contains_expected_sections(tmp_path: Path) -> None:
    obs = tmp_path / "obs"
    obs.mkdir()
    summary_dir = tmp_path / "metrics"
    summary_dir.mkdir()
    summary_path = summary_dir / "summary.json"
    summary_path.write_text(json.dumps(_minimal_summary()), encoding="utf-8")

    html_doc = build_dashboard_html(observation_base=obs, summary_path=summary_path)
    for section_id in (
        "status",
        "stop",
        "freshness",
        "targets",
        "equity",
        "overlay",
        "risk",
        "decisions",
        "kill",
        "next",
    ):
        assert f'id="{section_id}"' in html_doc
    _assert_no_external_resource(html_doc)
    assert "<script" not in html_doc


def test_write_dashboard_minimal_data_no_crash(tmp_path: Path) -> None:
    obs = tmp_path / "obs"
    obs.mkdir()
    summary_path = tmp_path / "summary.json"
    summary_path.write_text("{}", encoding="utf-8")
    out = obs / "dashboard.html"
    write_dashboard(out, observation_base=obs, summary_path=summary_path)
    content = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert "Observation Ops Dashboard" in content


# ---------------------------------------------------------------------------
# Frontiere de ``_assert_no_external_resource`` : elle doit interdire les
# ressources chargees depuis un hote distant, et rien d'autre.
# ---------------------------------------------------------------------------

_ACCEPTED = [
    # un lien hypertexte ne declenche aucune requete au rendu
    '<html><body><a href="https://example.invalid/doc">doc</a></body></html>',
    '<html><body><a href="#status">aller au statut</a></body></html>',
    # une ressource embarquee reste autonome
    '<html><body><img src="data:image/png;base64,iVBORw0KGgo="></body></html>',
    '<html><head><style>body{background:url(data:image/gif;base64,R0lGOD)}</style></head></html>',
    # un chemin relatif n'est pas un hote distant
    '<html><body><img src="chart.png"></body></html>',
    # pas de ressource du tout
    "<html><body><p>rien a charger</p></body></html>",
]

_REJECTED = [
    '<html><head><link rel="stylesheet" href="https://cdn.invalid/x.css"></head></html>',
    '<html><head><script src="//cdn.invalid/x.js"></script></head></html>',
    '<html><body><img src="https://cdn.invalid/x.png"></body></html>',
    '<html><body><iframe src="http://example.invalid/"></iframe></body></html>',
    '<html><head><style>@import url("https://fonts.invalid/f.css");</style></head></html>',
    "<html><head><style>@font-face{src:url(https://fonts.invalid/f.woff2)}</style></head></html>",
    '<html><body><div style="background:url(https://cdn.invalid/bg.png)">x</div></body></html>',
    '<html><body><img srcset="a.png 1x, https://cdn.invalid/b.png 2x"></body></html>',
]


@pytest.mark.parametrize("doc", _ACCEPTED)
def test_no_external_resource_accepts_self_contained_documents(doc: str) -> None:
    _assert_no_external_resource(doc)


@pytest.mark.parametrize("doc", _REJECTED)
def test_no_external_resource_rejects_remote_loads(doc: str) -> None:
    with pytest.raises(AssertionError):
        _assert_no_external_resource(doc)
