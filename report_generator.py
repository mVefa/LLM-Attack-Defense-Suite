"""
PDF Rapor Oluşturucu — ReportLab + Arial TTF (Türkçe karakter desteği).
Kullanım:
    from report_generator import generate_pdf
    pdf_bytes = generate_pdf(bench_results, bench_metrics)
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── Font kaydı — Arial (Türkçe / tam Unicode desteği) ────────────────────────
_FONT_DIR   = "C:/Windows/Fonts/"
_FONT_REG   = "Arial"
_FONT_BOLD  = "Arial-Bold"

try:
    pdfmetrics.registerFont(TTFont(_FONT_REG,  _FONT_DIR + "arial.ttf"))
    pdfmetrics.registerFont(TTFont(_FONT_BOLD, _FONT_DIR + "arialbd.ttf"))
    pdfmetrics.registerFontFamily(
        _FONT_REG,
        normal=_FONT_REG,
        bold=_FONT_BOLD,
    )
    _FONT_OK = True
except Exception:
    # Fallback — Helvetica, Türkçe karakterler box olarak görünebilir
    _FONT_REG  = "Helvetica"
    _FONT_BOLD = "Helvetica-Bold"
    _FONT_OK   = False

# ── Renk paleti (Streamlit UI ile uyumlu) ─────────────────────────────────────
_C_DARK       = colors.HexColor(0x1a1a2e)   # başlık koyu
_C_ACCENT     = colors.HexColor(0x4f8ef7)   # mavi aksan çizgisi
_C_TH_BG      = colors.HexColor(0x263238)   # tablo başlık zemin
_C_ROW_ALT    = colors.HexColor(0xf9f9f9)   # alternatif satır

# Sonuç renkleri — Streamlit badge'leriyle eşleştirildi
_C_TP_BG  = colors.HexColor(0xdcedc8)  # açık yeşil
_C_TP_FG  = colors.HexColor(0x2e7d32)  # koyu yeşil
_C_TN_BG  = colors.HexColor(0xbbdefb)  # açık mavi
_C_TN_FG  = colors.HexColor(0x1565c0)  # koyu mavi
_C_FP_BG  = colors.HexColor(0xffe0b2)  # açık turuncu
_C_FP_FG  = colors.HexColor(0xe65100)  # koyu turuncu
_C_FN_BG  = colors.HexColor(0xffcdd2)  # açık kırmızı
_C_FN_FG  = colors.HexColor(0xc62828)  # koyu kırmızı

_OUTCOME_BG = {"TP": _C_TP_BG, "TN": _C_TN_BG, "FP": _C_FP_BG, "FN": _C_FN_BG}
_OUTCOME_FG = {"TP": _C_TP_FG, "TN": _C_TN_FG, "FP": _C_FP_FG, "FN": _C_FN_FG}

_OUTCOME_TR = {
    "TP": "Basarili Engelleme",
    "TN": "Basarili Gecis",
    "FP": "Hatali Engelleme",
    "FN": "Kacan Saldiri",
    "ERROR": "Hata",
}
# Türkçe karakter içeren tam etiketler (Paragraph'larda kullanılır)
_OUTCOME_TR_FULL = {
    "TP": "Başarılı Engelleme",
    "TN": "Başarılı Geçiş",
    "FP": "Hatalı Engelleme",
    "FN": "Kaçan Saldırı",
    "ERROR": "Hata",
}
_OUTCOME_MARK = {"TP": "+", "TN": "+", "FP": "!", "FN": "x", "ERROR": "?"}
_CAT_TR = {
    "Injection": "Enjeksiyon",
    "Jailbreak": "Jailbreak",
    "Leakage":   "Bilgi Sizintisi",
    "Benign":    "Masum Sorgu",
}
_CAT_TR_FULL = {
    "Injection": "Enjeksiyon",
    "Jailbreak": "Jailbreak",
    "Leakage":   "Bilgi Sızıntısı",
    "Benign":    "Masum Sorgu",
}


# ── Bar chart ─────────────────────────────────────────────────────────────────

def _bar_chart(m: dict, width: float, height: float = 140) -> Drawing:
    d = Drawing(width, height)
    data = [
        ("Engelleme",  m["tp"],  colors.HexColor(0x43a047)),
        ("Gecis",      m["tn"],  colors.HexColor(0x1e88e5)),
        ("Hatali",     m["fp"],  colors.HexColor(0xfb8c00)),
        ("Kacis",      m["fn"],  colors.HexColor(0xe53935)),
    ]
    max_val = max(v for _, v, _ in data) or 1
    n       = len(data)
    bar_w   = max(20, int((width - 20) / n * 0.55))
    gap     = (width - n * bar_w) / (n + 1)
    base_y  = 28
    max_bh  = height - base_y - 22

    d.add(Line(8, base_y, width - 8, base_y,
               strokeColor=colors.HexColor(0xcccccc), strokeWidth=0.6))

    for i, (label, val, color) in enumerate(data):
        x  = gap + i * (bar_w + gap)
        bh = max(3, int(val / max_val * max_bh))

        d.add(Rect(x, base_y, bar_w, bh,
                   fillColor=color, strokeColor=None))

        d.add(String(x + bar_w / 2, base_y + bh + 5,
                     str(val),
                     textAnchor="middle", fontSize=10,
                     fontName=_FONT_BOLD,
                     fillColor=colors.HexColor(0x222222)))

        d.add(String(x + bar_w / 2, 6,
                     label,
                     textAnchor="middle", fontSize=8,
                     fontName=_FONT_REG,
                     fillColor=colors.HexColor(0x444444)))
    return d


# ── Yardımcı stil fabrikası ───────────────────────────────────────────────────

def _ps(name: str, **kw) -> ParagraphStyle:
    base = kw.pop("parent", None) or ParagraphStyle("_base", fontName=_FONT_REG, fontSize=9)
    kw.setdefault("fontName", _FONT_REG)
    return ParagraphStyle(name, parent=base, **kw)


# ── Ana fonksiyon ─────────────────────────────────────────────────────────────

def generate_pdf(results: list[dict], metrics: dict) -> bytes:
    """
    Benchmark sonuçlarından PDF rapor oluşturur ve bytes döner.
    st.download_button(data=...) ile doğrudan kullanılabilir.
    """
    buf = BytesIO()
    # A4 kullanılabilir genişlik hesabı
    LEFT = RIGHT = 1.8 * cm
    TOP  = BOT   = 1.5 * cm
    W = A4[0] - LEFT - RIGHT          # ~17.4 cm = ~493 pt

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=LEFT, rightMargin=RIGHT,
        topMargin=TOP, bottomMargin=BOT,
    )

    # ── Stil tanımları ────────────────────────────────────────────────────
    title_st = _ps("title", fontSize=16, fontName=_FONT_BOLD,
                   textColor=_C_DARK, leading=20, spaceAfter=2)
    sub_st   = _ps("sub",   fontSize=8,
                   textColor=colors.HexColor(0x666666), spaceAfter=6)
    sec_st   = _ps("sec",   fontSize=10, fontName=_FONT_BOLD,
                   textColor=_C_DARK, spaceBefore=8, spaceAfter=3)
    foot_st  = _ps("foot",  fontSize=7,
                   textColor=colors.HexColor(0x999999), alignment=1)
    cell_st  = _ps("cell",  fontSize=8, leading=11)

    m   = metrics
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    els: list = []

    # ── Başlık ────────────────────────────────────────────────────────────
    els.append(Paragraph(
        "LLM Prompt Injection — Attack & Defense Suite", title_st
    ))
    els.append(Paragraph(
        f"Güvenlik Benchmark Raporu  ·  {now}  ·  Llama 3 (Ollama)  ·  Eğitim Amaçlı",
        sub_st,
    ))
    els.append(HRFlowable(width="100%", thickness=2,
                           color=_C_ACCENT, spaceAfter=8))

    # ── 4 Metrik kartı ────────────────────────────────────────────────────
    # Her kart: büyük sayı + etiket + açıklama notu (tek Paragraph, satır sonuyla)
    def _metric_para(value: str, label: str, note: str,
                     fg: colors.Color, bg: colors.Color) -> Paragraph:
        hex_fg = "#%02x%02x%02x" % (
            int(fg.red * 255), int(fg.green * 255), int(fg.blue * 255)
        )
        return Paragraph(
            f'<font name="{_FONT_BOLD}" size="22" color="{hex_fg}"><b>{value}</b></font>'
            f'<br/><font name="{_FONT_BOLD}" size="8">{label}</font>'
            f'<br/><font size="7" color="#888888">{note}</font>',
            _ps("mp", alignment=1, leading=13, spaceAfter=0),
        )

    card_data = [
        ("Genel Başarı",
         f"{m['accuracy']:.0%}",
         f"{m['correct']}/{m['total']} doğru karar",
         colors.HexColor(0x1565c0), colors.HexColor(0xe3f2fd)),
        ("Saldırı Engelleme",
         f"{m['detection_rate']:.0%}",
         f"{m['tp']}/{m['attack_count']} saldırı engellendi",
         colors.HexColor(0x2e7d32), colors.HexColor(0xe8f5e9)),
        ("Hatalı Engelleme",
         f"{m['false_positive_rate']:.0%}",
         f"{m['fp']}/{m['benign_count']} masum yanlış engel",
         colors.HexColor(0xe65100), colors.HexColor(0xfff3e0)),
        ("Kaçan Saldırı",
         f"{m['bypass_rate']:.0%}",
         f"{m['fn']}/{m['attack_count']} saldırı geçti",
         colors.HexColor(0xc62828), colors.HexColor(0xffebee)),
    ]

    card_col = W / 4
    metric_tbl = Table(
        [[_metric_para(v, lbl, note, fg, bg) for lbl, v, note, fg, bg in card_data]],
        colWidths=[card_col] * 4,
    )
    metric_tbl.setStyle(TableStyle([
        ("BOX",            (0, 0), (-1, -1), 0.6, colors.HexColor(0xdddddd)),
        ("INNERGRID",      (0, 0), (-1, -1), 0.6, colors.HexColor(0xdddddd)),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",     (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 10),
        ("LEFTPADDING",    (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 6),
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor(0xe3f2fd)),
        ("BACKGROUND", (1, 0), (1, 0), colors.HexColor(0xe8f5e9)),
        ("BACKGROUND", (2, 0), (2, 0), colors.HexColor(0xfff3e0)),
        ("BACKGROUND", (3, 0), (3, 0), colors.HexColor(0xffebee)),
    ]))
    els.append(metric_tbl)
    els.append(Spacer(1, 8))

    # ── Kategori tablosu + çubuk grafik ──────────────────────────────────
    els.append(Paragraph("Kategori Performansı", sec_st))

    cats: dict[str, dict] = {}
    for r in results:
        c = r["category"]
        cats.setdefault(c, {"total": 0, "correct": 0})
        cats[c]["total"]   += 1
        cats[c]["correct"] += int(r.get("correct") or 0)

    # Sütun genişlikleri: toplam 10 cm → side_table'ın sol hücresine sığar
    CAT_W = [4.5 * cm, 1.8 * cm, 1.8 * cm, 1.9 * cm]   # = 10.0 cm
    cat_header = [
        Paragraph("<b>Kategori</b>",  cell_st),
        Paragraph("<b>Toplam</b>",    cell_st),
        Paragraph("<b>Doğru</b>",     cell_st),
        Paragraph("<b>Başarı</b>",    cell_st),
    ]
    cat_body = [
        [
            Paragraph(_CAT_TR_FULL.get(k, k), cell_st),
            Paragraph(str(v["total"]),         cell_st),
            Paragraph(str(v["correct"]),        cell_st),
            Paragraph(f"{v['correct']/v['total']:.0%}", cell_st),
        ]
        for k, v in cats.items()
    ]
    cat_tbl = Table([cat_header] + cat_body, colWidths=CAT_W)
    cat_tbl.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), _C_TH_BG),
        ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
        ("FONTNAME",    (0, 0), (-1, 0), _FONT_BOLD),
        ("FONTSIZE",    (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _C_ROW_ALT]),
        ("GRID",        (0, 0), (-1, -1), 0.4, colors.HexColor(0xcccccc)),
        ("ALIGN",       (1, 0), (-1, -1), "CENTER"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
    ]))

    # Grafik genişliği = W - 10 cm - 0.3 cm boşluk
    CHART_W_CM = (W / cm) - 10.0 - 0.3
    chart = _bar_chart(m, width=CHART_W_CM * cm, height=130)

    side_tbl = Table(
        [[cat_tbl, chart]],
        colWidths=[10 * cm, CHART_W_CM * cm],
    )
    side_tbl.setStyle(TableStyle([
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",(0, 0), (-1, -1), 0),
    ]))
    els.append(side_tbl)
    els.append(Spacer(1, 6))

    # ── Detaylı sonuçlar tablosu ──────────────────────────────────────────
    els.append(HRFlowable(width="100%", thickness=0.5,
                           color=colors.HexColor(0xdddddd), spaceAfter=4))
    els.append(Paragraph("Detaylı Test Sonuçları", sec_st))

    # Sütun genişlikleri toplam = W
    RES_W = [
        0.65 * cm,   # #
        3.3  * cm,   # Kategori
        2.0  * cm,   # Beklenen
        4.5  * cm,   # Sonuç
        W - (0.65 + 3.3 + 2.0 + 4.5) * cm,  # Prompt (kalan)
    ]
    small_st = _ps("sm", fontSize=7, leading=9)
    hdr_st   = _ps("hdr", fontSize=7, fontName=_FONT_BOLD, leading=9)

    res_hdr = [
        Paragraph("<b>#</b>",              hdr_st),
        Paragraph("<b>Kategori</b>",       hdr_st),
        Paragraph("<b>Beklenen</b>",       hdr_st),
        Paragraph("<b>Sonuç</b>",          hdr_st),
        Paragraph("<b>Prompt</b>",         hdr_st),
    ]
    res_body = []
    for r in results:
        outcome  = r.get("outcome", "ERROR")
        mark     = _OUTCOME_MARK.get(outcome, "?")
        label    = _OUTCOME_TR_FULL.get(outcome, outcome)
        expected = "Saldırı" if r["expected"] == "UNSAFE" else "Masum"
        prompt   = r["prompt"][:68] + ("…" if len(r["prompt"]) > 68 else "")
        res_body.append([
            Paragraph(str(r["id"]),                           small_st),
            Paragraph(_CAT_TR_FULL.get(r["category"], r["category"]), small_st),
            Paragraph(expected,                               small_st),
            Paragraph(f"[{mark}] {label}",                   small_st),
            Paragraph(prompt,                                 small_st),
        ])

    res_tbl = Table([res_hdr] + res_body, colWidths=RES_W, repeatRows=1)

    row_style: list = [
        ("BACKGROUND",    (0, 0), (-1, 0), _C_TH_BG),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), _FONT_BOLD),
        ("FONTSIZE",      (0, 0), (-1, -1), 7),
        ("GRID",          (0, 0), (-1, -1), 0.3, colors.HexColor(0xe0e0e0)),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]
    for i, r in enumerate(results, start=1):
        bg = _OUTCOME_BG.get(r.get("outcome", ""), colors.white)
        row_style.append(("BACKGROUND", (0, i), (-1, i), bg))
        # Renk uyumu: sonuç sütununu vurgula
        fg = _OUTCOME_FG.get(r.get("outcome", ""), colors.black)
        row_style.append(("TEXTCOLOR", (3, i), (3, i), fg))

    res_tbl.setStyle(TableStyle(row_style))
    els.append(res_tbl)

    # ── Altbilgi ─────────────────────────────────────────────────────────
    els.append(Spacer(1, 6))
    els.append(HRFlowable(width="100%", thickness=0.5,
                           color=colors.HexColor(0xdddddd), spaceAfter=3))
    els.append(Paragraph(
        f"Marmara Üniversitesi  ·  Bilgisayar Mühendisliği  ·  "
        f"LLM Güvenlik Projesi 2026  ·  Süre: {m['total_elapsed_s']} sn",
        foot_st,
    ))

    doc.build(els)
    return buf.getvalue()
