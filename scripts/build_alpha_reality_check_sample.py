"""Build the public Alpha Reality Check sample audit report.

The report is deliberately generated from the final, versioned research verdict.
It is a commercial sample, not a new research result.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

PAGE_W, PAGE_H = A4
INK = colors.HexColor("#12201B")
MUTED = colors.HexColor("#66736D")
EMERALD = colors.HexColor("#059669")
EMERALD_DARK = colors.HexColor("#065F46")
EMERALD_PALE = colors.HexColor("#E8F7F0")
RED = colors.HexColor("#B42318")
RED_PALE = colors.HexColor("#FDECEA")
AMBER = colors.HexColor("#B45309")
AMBER_PALE = colors.HexColor("#FFF4E5")
LINE = colors.HexColor("#DDE5E1")
PAPER = colors.HexColor("#FAFCFB")
NAVY = colors.HexColor("#0B1713")


def register_fonts() -> tuple[str, str]:
    candidates = [
        (Path("C:/Windows/Fonts/segoeui.ttf"), Path("C:/Windows/Fonts/seguisb.ttf")),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
    ]
    for regular, bold in candidates:
        if regular.exists() and bold.exists():
            pdfmetrics.registerFont(TTFont("ARC-Regular", str(regular)))
            pdfmetrics.registerFont(TTFont("ARC-Bold", str(bold)))
            return "ARC-Regular", "ARC-Bold"
    return "Helvetica", "Helvetica-Bold"


REGULAR, BOLD = register_fonts()


class Rule(Flowable):
    def __init__(self, color: colors.Color = LINE, thickness: float = 0.6, width: float = 170 * mm):
        super().__init__()
        self.color = color
        self.thickness = thickness
        self.width = width
        self.height = 4 * mm

    def draw(self) -> None:
        self.canv.setStrokeColor(self.color)
        self.canv.setLineWidth(self.thickness)
        self.canv.line(0, self.height / 2, self.width, self.height / 2)


class VerdictBand(Flowable):
    def __init__(self, label: str, title: str, body: str, color: colors.Color = RED):
        super().__init__()
        self.label = label
        self.title = title
        self.body = body
        self.color = color
        self.width = 170 * mm
        self.height = 34 * mm

    def draw(self) -> None:
        c = self.canv
        c.setFillColor(RED_PALE if self.color == RED else EMERALD_PALE)
        c.roundRect(0, 0, self.width, self.height, 4 * mm, fill=1, stroke=0)
        c.setFillColor(self.color)
        c.setFont(BOLD, 7.5)
        c.drawString(6 * mm, 25.5 * mm, self.label.upper())
        c.setFillColor(INK)
        c.setFont(BOLD, 19)
        c.drawString(6 * mm, 16.2 * mm, self.title)
        c.setFillColor(MUTED)
        c.setFont(REGULAR, 8.5)
        c.drawString(6 * mm, 7.5 * mm, self.body)


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "eyebrow": ParagraphStyle(
            "eyebrow",
            parent=base["Normal"],
            fontName=BOLD,
            fontSize=7.5,
            leading=10,
            textColor=EMERALD_DARK,
            spaceAfter=3 * mm,
            uppercase=True,
        ),
        "title": ParagraphStyle(
            "title",
            parent=base["Title"],
            fontName=BOLD,
            fontSize=30,
            leading=32,
            textColor=INK,
            alignment=TA_LEFT,
            spaceAfter=5 * mm,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontName=BOLD,
            fontSize=22,
            leading=26,
            textColor=INK,
            spaceBefore=1 * mm,
            spaceAfter=5 * mm,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName=BOLD,
            fontSize=13,
            leading=17,
            textColor=INK,
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName=REGULAR,
            fontSize=9.1,
            leading=14,
            textColor=INK,
            spaceAfter=3 * mm,
        ),
        "small": ParagraphStyle(
            "small",
            parent=base["BodyText"],
            fontName=REGULAR,
            fontSize=7.5,
            leading=10.5,
            textColor=MUTED,
            spaceAfter=2 * mm,
        ),
        "callout": ParagraphStyle(
            "callout",
            parent=base["BodyText"],
            fontName=BOLD,
            fontSize=11,
            leading=16,
            textColor=EMERALD_DARK,
            borderColor=EMERALD,
            borderWidth=0,
            leftIndent=5 * mm,
            rightIndent=5 * mm,
            spaceBefore=2 * mm,
            spaceAfter=4 * mm,
        ),
        "table": ParagraphStyle(
            "table",
            parent=base["BodyText"],
            fontName=REGULAR,
            fontSize=7.6,
            leading=10,
            textColor=INK,
        ),
        "table_bold": ParagraphStyle(
            "table_bold",
            parent=base["BodyText"],
            fontName=BOLD,
            fontSize=7.6,
            leading=10,
            textColor=INK,
        ),
        "metric": ParagraphStyle(
            "metric",
            parent=base["BodyText"],
            fontName=BOLD,
            fontSize=20,
            leading=22,
            alignment=TA_CENTER,
            textColor=EMERALD_DARK,
        ),
        "metric_label": ParagraphStyle(
            "metric_label",
            parent=base["BodyText"],
            fontName=REGULAR,
            fontSize=7.2,
            leading=9.5,
            alignment=TA_CENTER,
            textColor=MUTED,
        ),
    }


S = styles()


def p(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, S[style])


def bullet(text: str) -> Paragraph:
    return Paragraph(f"<font color='#059669'>●</font>&nbsp;&nbsp;{text}", S["body"])


def section(label: str, title: str) -> list[Flowable]:
    return [p(label.upper(), "eyebrow"), p(title, "h1")]


def styled_table(data: list[list[object]], widths: list[float], header: bool = True) -> Table:
    table = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("FONTNAME", (0, 0), (-1, -1), REGULAR),
        ("FONTSIZE", (0, 0), (-1, -1), 7.6),
        ("LEADING", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
    ]
    if header:
        commands.extend(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), BOLD),
                ("TOPPADDING", (0, 0), (-1, 0), 3.2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 3.2 * mm),
            ]
        )
    for row in range(1 if header else 0, len(data)):
        if row % 2 == 0:
            commands.append(("BACKGROUND", (0, row), (-1, row), PAPER))
    table.setStyle(TableStyle(commands))
    return table


def card(title: str, body: str, tone: str = "green") -> Table:
    bg = EMERALD_PALE if tone == "green" else (RED_PALE if tone == "red" else AMBER_PALE)
    fg = EMERALD_DARK if tone == "green" else (RED if tone == "red" else AMBER)
    data = [[Paragraph(title, ParagraphStyle("card-title", parent=S["body"], fontName=BOLD, fontSize=9, textColor=fg, spaceAfter=1.5 * mm)), Paragraph(body, S["small"])]]
    table = Table(data, colWidths=[42 * mm, 120 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("BOX", (0, 0), (-1, -1), 0.5, fg),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 4 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
    ]))
    return table


def cover(canvas, _doc) -> None:
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#123F31"))
    canvas.circle(PAGE_W - 12 * mm, PAGE_H - 18 * mm, 58 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#0E2A22"))
    canvas.circle(PAGE_W - 10 * mm, 0, 72 * mm, fill=1, stroke=0)
    canvas.setFillColor(EMERALD)
    canvas.rect(20 * mm, PAGE_H - 30 * mm, 8 * mm, 2 * mm, fill=1, stroke=0)
    canvas.setFont(BOLD, 8)
    canvas.setFillColor(colors.HexColor("#A7F3D0"))
    canvas.drawString(32 * mm, PAGE_H - 31 * mm, "ALPHA REALITY CHECK")
    canvas.setFont(REGULAR, 7)
    canvas.setFillColor(colors.HexColor("#9AA8A2"))
    canvas.drawRightString(PAGE_W - 20 * mm, 15 * mm, "RAPPORT EXEMPLE · 25 AOÛT 2026")
    canvas.restoreState()


def body_page(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFillColor(colors.white)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(20 * mm, PAGE_H - 17 * mm, PAGE_W - 20 * mm, PAGE_H - 17 * mm)
    canvas.setFont(BOLD, 6.7)
    canvas.setFillColor(EMERALD_DARK)
    canvas.drawString(20 * mm, PAGE_H - 13 * mm, "ALPHA REALITY CHECK")
    canvas.setFont(REGULAR, 6.7)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(PAGE_W - 20 * mm, PAGE_H - 13 * mm, "RAPPORT EXEMPLE · KRAKEN ALPHA AGENT")
    canvas.line(20 * mm, 15 * mm, PAGE_W - 20 * mm, 15 * mm)
    canvas.setFont(REGULAR, 6.7)
    canvas.drawString(20 * mm, 10 * mm, "Audit technique et méthodologique · pas un conseil financier")
    canvas.drawRightString(PAGE_W - 20 * mm, 10 * mm, f"{doc.page - 1:02d}")
    canvas.restoreState()


def build_report(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=24 * mm,
        bottomMargin=21 * mm,
        title="Alpha Reality Check - Rapport exemple Kraken Alpha Agent",
        author="Damien Credoz",
        subject="Exemple public d'audit indépendant de stratégie quantitative",
    )
    body_frame = Frame(20 * mm, 21 * mm, 170 * mm, PAGE_H - 45 * mm, id="body")
    cover_frame = Frame(20 * mm, 20 * mm, 170 * mm, PAGE_H - 40 * mm, id="cover")
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[cover_frame], onPage=cover),
        PageTemplate(id="body", frames=[body_frame], onPage=body_page),
    ])

    story: list[Flowable] = []
    story.extend([
        Spacer(1, 54 * mm),
        p("RAPPORT EXEMPLE · AUDIT INDÉPENDANT", "eyebrow"),
        Paragraph("Un backtest prometteur.<br/>Une décision qui résiste au réel.", ParagraphStyle("cover-title", parent=S["title"], fontSize=32, leading=36, textColor=colors.white)),
        Spacer(1, 5 * mm),
        Paragraph("Cas public : Kraken Alpha Agent", ParagraphStyle("cover-sub", parent=S["body"], fontName=BOLD, fontSize=13, leading=18, textColor=colors.HexColor("#A7F3D0"))),
        Spacer(1, 6 * mm),
        Paragraph("Reproduction · qualité des données · biais d'exécution · walk-forward · inférence · décision", ParagraphStyle("cover-body", parent=S["body"], fontSize=10, leading=15, textColor=colors.HexColor("#C9D3CF"), rightIndent=40 * mm)),
        Spacer(1, 34 * mm),
        Table([
            [p("VERDICT", "small"), Paragraph("RESEARCH_CLOSED", ParagraphStyle("cover-verdict", parent=S["body"], fontName=BOLD, fontSize=14, textColor=colors.HexColor("#FCA5A5")))],
            [p("SIGNAL TRADABLE", "small"), Paragraph("0", ParagraphStyle("cover-number", parent=S["body"], fontName=BOLD, fontSize=14, textColor=colors.white))],
            [p("OVERLAY RETENU", "small"), Paragraph("0 / 4", ParagraphStyle("cover-number2", parent=S["body"], fontName=BOLD, fontSize=14, textColor=colors.white))],
        ], colWidths=[48 * mm, 70 * mm], style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#10231C")),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#315347")),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#315347")),
            ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])),
        NextPageTemplate("body"),
        PageBreak(),
    ])

    story.extend(section("01 · Décision", "Synthèse exécutive"))
    story.extend([
        p("Le dépôt présentait encore un overlay de risque funding + basis comme piste utile après trente phases de recherche. L'audit a reconstruit les données, rejoué le pipeline et vérifié le moteur d'exécution. Le résultat positif disparaît."),
        Spacer(1, 2 * mm),
        VerdictBand("Décision", "Arrêter la recherche sur cet univers", "Aucun signal tradable, aucun candidat OOS, aucun overlay supporté."),
        Spacer(1, 6 * mm),
    ])
    metrics = [
        [p("1 058", "metric"), p("872", "metric"), p("0 / 4", "metric"), p("2 190", "metric")],
        [p("tests automatisés", "metric_label"), p("configurations OOS", "metric_label"), p("overlays retenus", "metric_label"), p("points funding reconstruits", "metric_label")],
    ]
    metric_table = Table(metrics, colWidths=[42.5 * mm] * 4)
    metric_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PAPER),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, 0), 4 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 1 * mm),
        ("TOPPADDING", (0, 1), (-1, 1), 1 * mm),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 4 * mm),
    ]))
    story.extend([metric_table, Spacer(1, 6 * mm)])
    story.extend([
        p("Pourquoi cette décision est utile", "h2"),
        bullet("Elle évite de transformer un artefact de données en règle de risque mise en production."),
        bullet("Elle clôt un budget de recherche déjà supérieur à 2 600 configurations sur le même univers."),
        bullet("Elle distingue ce qui reste démontré - l'absence d'edge brut - des métriques historiques devenues caduques."),
        p("Périmètre et niveau d'assurance", "h2"),
        p("Revue du code Python, des caches publics Binance, des rapports versionnés, des règles de risque, des tests et de la CI. Aucun ordre réel n'a été envoyé. Les caches reconstruits ne sont pas versionnés ; leur manifeste de volume et de provenance est conservé."),
        PageBreak(),
    ])

    story.extend(section("02 · Point de départ", "Ce que le backtest semblait raconter"))
    story.extend([
        p("Avant audit, quatre bundles dérivés sur quatre franchissaient le gate <b>proceed_to_overlay</b>. L'overlay ETH 4h était classé <b>useful_overlay</b>, avec un signal funding dont l'excès à 72 h paraissait positif et monotone."),
        styled_table([
            ["Objet", "Résultat publié", "Lecture apparente"],
            ["ETH 4h funding z-score", "+0,786 point à 72 h (n=142)", "Signal directionnel cohérent"],
            ["BTC 4h funding z-score", "+0,931 point à 72 h (n=126)", "Confirmation inter-actifs"],
            ["Gate dérivés", "4 bundles sur 4 passent", "Overlay à observer en forward"],
            ["Observation", "114 trades, block rate 0 %", "Harnais opérationnel"],
        ], [45 * mm, 58 * mm, 67 * mm]),
        Spacer(1, 6 * mm),
        card("Alerte méthodologique", "Les chiffres étaient présents, mais la chaîne de preuve n'était pas complète : pagination de données, fraîcheur, tests d'inférence, définition du baseline et possibilité réelle de solder une position n'avaient pas été vérifiés ensemble.", "amber"),
        Spacer(1, 5 * mm),
        p("Question d'audit", "h2"),
        p("L'effet survit-il à une reconstruction complète des données et à des gates pré-enregistrés de puissance, direction, inférence, robustesse économique et out-of-sample ?"),
        p("Standard de décision", "h2"),
        bullet("Un résultat positif ne suffit pas : il doit être alimenté par des données complètes et fraîches."),
        bullet("Un signal doit survivre au placebo et à la correction Benjamini-Hochberg sur toute sa famille de tests."),
        bullet("Une stratégie doit pouvoir exécuter ses sorties, y compris après le déclenchement d'un stop de risque."),
        PageBreak(),
    ])

    story.extend(section("03 · Diagnostic", "Quatre défauts qui changent la décision"))
    findings = [
        ("1. Données tronquées", "Le cache funding s'arrêtait exactement à 1 000 lignes, la limite d'une page. Il ne couvrait qu'environ 30 % de la fenêtre de backtest."),
        ("2. Valeur gelée", "Un forward-fill non borné propageait la dernière valeur connue. Le z-score devenait 0,0 et le composant funding se neutralisait silencieusement."),
        ("3. Gate permissif", "Aucune p-value, aucun placebo et aucune correction multi-tests. Un excès négatif pris en valeur absolue pouvait être compté comme preuve favorable."),
        ("4. Sorties refusées", "Cinq garde-fous du risk manager bloquaient aussi les ventes exit-only. Une position pouvait rester piégée après un stop ou un dépassement de plafond."),
    ]
    for title, body in findings:
        story.extend([card(title, body, "red" if title.startswith("4") else "amber"), Spacer(1, 3 * mm)])
    story.extend([
        p("Ampleur observée dans les artefacts", "h2"),
        styled_table([
            ["Règle de risque", "Déclenchements historiques", "Effet avant correction"],
            ["max_drawdown_pct", "966", "Sortie refusée après stop"],
            ["max_position_fraction", "874", "Allègement refusé au-dessus du plafond"],
            ["max_daily_loss_pct", "150", "Position bloquée après perte journalière"],
            ["max_trades_per_day", "41", "Sortie refusée après quota"],
            ["risk_denial_rate = 1,0", "216 runs", "Signature d'une position refusée à chaque barre"],
        ], [58 * mm, 48 * mm, 64 * mm]),
        Spacer(1, 4 * mm),
        p("Le biais n'était pas simplement pessimiste. En hausse, une position impossible à solder pouvait embellir l'equity latente ; après retournement, elle pouvait amplifier la perte. Les métriques par run des phases concernées ne sont donc pas utilisables telles quelles."),
        PageBreak(),
    ])

    story.extend(section("04 · Rejeu", "Après reconstruction, l'effet disparaît"))
    story.extend([
        p("Les caches ont été reconstruits depuis les endpoints publics, puis le pipeline a été rejoué avec un plancher de puissance, une direction attendue pré-enregistrée, un bootstrap placebo et une correction BH-FDR."),
        styled_table([
            ["Signal", "n publié", "n réel", "72 h publié", "72 h réel", "p", "q (BH)"],
            ["ETH 4h", "142", "266", "+0,786 pp", "-0,177 pp", "0,647", "0,826"],
            ["BTC 4h", "126", "243", "+0,931 pp", "+0,222 pp", "0,428", "0,965"],
        ], [31 * mm, 19 * mm, 19 * mm, 27 * mm, 27 * mm, 22 * mm, 25 * mm]),
        Spacer(1, 5 * mm),
        card("Résultat statistique", "Aucune cellule ne survit à Benjamini-Hochberg. L'effet ETH change de signe ; l'effet BTC est divisé par quatre. Le verdict devient not supported avant même l'analyse des coûts.", "red"),
        Spacer(1, 6 * mm),
        p("Effet sur les quatre bundles", "h2"),
        styled_table([
            ["Bundle", "Publié", "Rejeu complet"],
            ["BTC 4h", "non_trivial=4 · proceed=true · overlay_only", "non_trivial=0 · proceed=false · weak"],
            ["ETH 4h", "non_trivial=3 · proceed=true · overlay_only", "non_trivial=0 · proceed=false · weak"],
            ["BTC 1d", "non_trivial=2 · proceed=true · blocked_data", "non_trivial=0 · proceed=false · blocked_data"],
            ["ETH 1d", "non_trivial=2 · proceed=true · blocked_data", "non_trivial=0 · proceed=false · blocked_data"],
        ], [30 * mm, 70 * mm, 70 * mm]),
        Spacer(1, 6 * mm),
        p("La conclusion ne repose pas sur un seul backtest", "h2"),
        p("Trois pipelines indépendants convergent vers zéro : 872 configurations moteur/walk-forward pour 0 survivant OOS ; 18 hypothèses event-study pour 0 candidat OOS et 0 rejet BH-FDR ; environ 600 runs de tournois/walk-forward bot pour 0 candidat papier."),
        PageBreak(),
    ])

    story.extend(section("05 · Observation", "Pourquoi le forward test a été archivé"))
    story.extend([
        p("Le cron 4 h annoncé comme prêt n'a jamais été installé : une seule barre datée du 21 mai 2026, aucune donnée nouvelle trois mois plus tard, healthcheck en échec. Les 114 trades rapportés étaient un replay historique, pas une observation forward."),
        card("Baseline incorrect", "Une boucle de replay au corps vide laissait le portefeuille standalone sans position. Le baseline ne pouvait jamais vendre et pouvait répéter les achats au lieu de n'agir qu'aux croisements.", "red"),
        Spacer(1, 3 * mm),
        card("Critère d'arrêt inerte", "La comparaison d'equity face au standalone n'était jamais alimentée. Un critère de kill sur cinq ne pouvait pas se déclencher.", "red"),
        Spacer(1, 6 * mm),
        p("Décision opérationnelle", "h2"),
        p("Ne pas relancer un cron qui collecterait des mesures invalides sur un objet déjà réfuté. Le harnais a été corrigé pour ne pas laisser de code trompeur, mais l'observation a été archivée et aucune micro-mise en production n'a été autorisée."),
        Rule(),
        p("Ce qui a été corrigé", "h2"),
        bullet("Pagination complète du funding et statut explicite no_data au-delà de la fraîcheur autorisée."),
        bullet("Gates de puissance, direction, placebo, p-value et BH-FDR dans le pipeline dérivés."),
        bullet("Sorties exit-only autorisées par le risk manager sous les plafonds et stops."),
        bullet("Replay standalone réel, persistance de sa courbe d'equity et critères d'arrêt évaluables."),
        bullet("CI réparée ; suite de 1 058 tests et lint exécutables de bout en bout."),
        Spacer(1, 5 * mm),
        p("Ces corrections améliorent la qualité du logiciel. Elles ne transforment pas un résultat négatif en signal tradable."),
        PageBreak(),
    ])

    story.extend(section("06 · Recommandation", "Plan d'action livré au décideur"))
    actions = [
        ["Priorité", "Action", "Décision / critère de sortie"],
        ["P0", "Clôturer le track BTC/ETH/SOL OHLC + funding/basis/OI", "Pas de phase 32 sur le même univers"],
        ["P0", "Ne pas engager de capital sur l'overlay", "0/4 bundle supporté ; aucune observation forward"],
        ["P1", "Conserver le dépôt comme preuve méthodologique", "Publier le verdict négatif et la provenance"],
        ["P1", "Séparer chiffres historiques caducs et preuves encore valides", "Ne pas réutiliser les métriques par run phases 14-30"],
        ["P2", "Ne reprendre qu'avec une nouvelle source d'information", "Nouvelle classe d'actifs, donnée ou mécanisme économique pré-enregistré"],
    ]
    story.extend([
        styled_table(actions, [22 * mm, 75 * mm, 73 * mm]),
        Spacer(1, 7 * mm),
        p("Valeur économique du verdict", "h2"),
        p("Le rapport ne promet pas qu'une stratégie robuste gagnera. Il réduit le risque de financer une illusion : temps d'équipe, infrastructure, frais de marché, capital immobilisé et risque réputationnel."),
        KeepTogether([
            Spacer(1, 3 * mm),
            card("Décision finale", "RESEARCH_CLOSED. Le résultat solide du projet est l'absence d'edge démontrée de façon convergente, pas la découverte d'un signal exploitable.", "green"),
        ]),
        Spacer(1, 7 * mm),
        p("Limites", "h2"),
        bullet("Ce rapport exemple synthétise un cas public ; il ne remplace pas les artefacts techniques complets."),
        bullet("Le verdict porte sur l'univers, les données et les implémentations audités, pas sur tous les marchés possibles."),
        bullet("Une absence de preuve n'est pas une preuve universelle d'absence ; elle suffit ici pour refuser la mise en risque."),
        PageBreak(),
    ])

    story.extend(section("07 · Méthode", "Ce qu'un audit Alpha Reality Check vérifie"))
    checks = [
        ["Bloc", "Contrôles représentatifs", "Sortie"],
        ["Reproductibilité", "Environnement, seeds, versions, provenance, empreintes", "Backtest rejouable"],
        ["Données", "Couverture, trous, timezone, pagination, ajustements, fraîcheur", "Carte de qualité"],
        ["Code", "Look-ahead, leakage, états, exécution, sorties, sizing", "Constats reproductibles"],
        ["Économie", "Frais, spread, slippage, turnover, capacité", "Seuil de viabilité"],
        ["Statistique", "Puissance, placebos, multi-tests, stabilité, OOS", "Niveau de preuve"],
        ["Décision", "Go, retravailler ou arrêter avec conditions", "Verdict actionnable"],
    ]
    story.extend([
        styled_table(checks, [35 * mm, 92 * mm, 43 * mm]),
        Spacer(1, 7 * mm),
        p("Sources publiques de ce rapport exemple", "h2"),
        p("1. <b>reports/PHASE31_FINAL_VERDICT.md</b> - décision finale, constats, métriques et limites.<br/>2. <b>reports/phase31_rerun/README.md</b> - protocole du rejeu et comparaison publiée/réelle.<br/>3. <b>reports/phase31_rerun/derivatives_event_study_summary.json</b> - résultats structurés des quatre bundles.<br/>4. <b>reports/phase31_rerun/cache_manifest.json</b> - volumes et empreintes des caches reconstruits."),
        Rule(),
        p("À propos", "h2"),
        p("Alpha Reality Check est un service d'audit technique et méthodologique de stratégies quantitatives. Le livrable cherche activement les raisons pour lesquelles une performance pourrait ne pas exister et documente les conditions nécessaires à une décision de mise en risque."),
        p("Avertissement", "h2"),
        p("Ce document est fourni à titre d'information et de démonstration. Il ne constitue ni un conseil en investissement, ni une recommandation d'achat ou de vente, ni une garantie de performance. Toute décision financière reste sous la responsabilité du lecteur."),
        Spacer(1, 8 * mm),
        Paragraph("Continuer · corriger · arrêter", ParagraphStyle("closing", parent=S["h1"], alignment=TA_CENTER, textColor=EMERALD_DARK, fontSize=18)),
        Paragraph("Une décision documentée vaut mieux qu'une courbe séduisante.", ParagraphStyle("closing2", parent=S["small"], alignment=TA_CENTER)),
    ])

    doc.build(story)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("output/pdf/alpha-reality-check-sample-report.pdf"))
    args = parser.parse_args()
    build_report(args.output)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
