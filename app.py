from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from benchmark_engine import compute_metrics, evaluate_single, load_dataset
from report_generator import generate_pdf
from target_bot import BlockedByDefenseError, OutputLeakError, chat

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="LLM Prompt Injection – Attack & Defense Lab",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.block-container { padding-top: 2.8rem; padding-bottom: 1rem; }

.panel-title {
    font-size: 1.05rem; font-weight: 700; letter-spacing: .03em;
    padding: 6px 12px; border-radius: 6px; margin-bottom: 10px;
}
.panel-attack  { background:#3d1515; color:#ff6b6b; }
.panel-control { background:#1a2a1a; color:#6bcb77; }
.panel-result  { background:#151f3d; color:#6bb8ff; }
.panel-bench   { background:#1f1a3d; color:#ce93d8; }

.response-box {
    background:#0e1117; border:1px solid #2a2a2a;
    border-left:4px solid #4caf50; border-radius:8px;
    padding:16px 18px; font-size:.88rem; line-height:1.65;
    color:#dcdcdc; white-space:pre-wrap; word-break:break-word;
    max-height:400px; overflow-y:auto;
}
.blocked-box {
    background:#1a0000; border:1px solid #5a1a1a;
    border-left:4px solid #e53935; border-radius:8px;
    padding:14px 16px; font-size:.88rem; color:#ff8a80;
}
.layer-badge {
    display:inline-block; padding:2px 8px; border-radius:12px;
    font-size:.72rem; font-weight:600; margin-right:4px;
}
.badge-ok  { background:#1b3d1b; color:#81c784; }
.badge-err { background:#3d1b1b; color:#ef9a9a; }
.badge-inf { background:#1b2a3d; color:#90caf9; }
.badge-warn{ background:#2b1e00; color:#ffcc80; }

div[data-testid="metric-container"] {
    border:1px solid #2a2a2a; border-radius:8px; padding:10px 14px;
}
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
st.session_state.setdefault("defense_on",    True)
st.session_state.setdefault("last_result",   None)
st.session_state.setdefault("prompt_input",  "")
st.session_state.setdefault("bench_results", None)
st.session_state.setdefault("bench_metrics", None)


# ── Cached loaders ────────────────────────────────────────────────────────────
@st.cache_data
def _load_attacks() -> dict:
    p = Path(__file__).parent / "attack_library.json"
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)

@st.cache_data
def _load_dataset() -> list[dict]:
    return load_dataset()

attacks = _load_attacks()
dataset = _load_dataset()

# ── Turkish outcome labels ────────────────────────────────────────────────────
_OUTCOME_TR = {
    "TP":    "✅ Başarılı Engelleme",   # attack correctly blocked
    "TN":    "✅ Başarılı Geçiş",       # benign correctly passed
    "FP":    "⚠️ Hatalı Engelleme",     # benign wrongly blocked
    "FN":    "❌ Kaçan Saldırı",        # attack bypassed defense
    "ERROR": "💥 Hata",
}
_PIE_LABELS = [
    "Başarılı Engelleme ✓",
    "Başarılı Geçiş ✓",
    "Hatalı Engelleme ✗",
    "Kaçan Saldırı ✗",
]

# ── Title ─────────────────────────────────────────────────────────────────────
st.markdown(
    "<h2 style='margin-bottom:.1rem'>🛡️ LLM Prompt Injection – Attack & Defense Lab</h2>"
    "<p style='color:#888;margin-top:0'>Llama 3 (Ollama) · Eğitim Amaçlı</p>",
    unsafe_allow_html=True,
)
st.divider()

tab_chat, tab_bench = st.tabs(["💬 Saldırı & Savunma", "📊 Otomatik Benchmark"])


# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — Chat
# ════════════════════════════════════════════════════════════════════════════
with tab_chat:
    col_left, col_mid, col_right = st.columns([1.35, 1.65, 2.0], gap="large")

    # ── Sol: Saldırı Kütüphanesi ──────────────────────────────────────────
    with col_left:
        st.markdown('<div class="panel-title panel-attack">🗡️ Attack Library</div>',
                    unsafe_allow_html=True)
        st.caption("Butona tıkla → prompt alanına yüklenir.")
        for category, items in attacks.items():
            with st.expander(f"**{category}**", expanded=True):
                for attack in items:
                    b_col, d_col = st.columns([5, 7], gap="small")
                    with b_col:
                        if st.button(attack["name"], key=f"atk_{attack['id']}",
                                     use_container_width=True):
                            st.session_state["prompt_input"] = attack["prompt"]
                            st.session_state["last_result"]  = None
                            st.rerun()
                    with d_col:
                        st.caption(attack["description"])

    # ── Orta: Kontrol + Girdi ─────────────────────────────────────────────
    with col_mid:
        st.markdown('<div class="panel-title panel-control">⚙️ Kontrol Paneli</div>',
                    unsafe_allow_html=True)

        def _toggle():
            st.session_state.defense_on = not st.session_state.defense_on

        tc, sc = st.columns([3, 2], gap="small")
        with tc:
            lbl   = "🛡️ Savunma AÇIK" if st.session_state.defense_on else "⚠️ Savunma KAPALI"
            btype = "primary"          if st.session_state.defense_on else "secondary"
            st.button(lbl, on_click=_toggle, use_container_width=True, type=btype)
        with sc:
            if st.session_state.defense_on:
                st.success("Aktif ✅")
            else:
                st.error("Pasif 🚨")

        if st.session_state.defense_on:
            st.caption("Unicode Normalize → Regex Filtre → Sınır Etiketleme → Semantik Kontrol → Çıktı Filtresi")
        else:
            st.caption("Ham girdi doğrudan modele iletilir — savunma devre dışı.")

        st.divider()

        user_input: str = st.text_area(
            "Girdi", height=200, key="prompt_input",
            placeholder="Bir mesaj yazın veya soldaki kütüphaneden bir saldırı seçin…",
            label_visibility="collapsed",
        )
        snd_c, clr_c = st.columns([5, 1], gap="small")
        with snd_c:
            send_clicked = st.button("➤ Gönder", type="primary", use_container_width=True)
        with clr_c:
            if st.button("🗑", use_container_width=True, help="Temizle"):
                st.session_state["prompt_input"] = ""
                st.session_state["last_result"]  = None
                st.rerun()

    # ── İstek gönder ─────────────────────────────────────────────────────
    if send_clicked and user_input.strip():
        with col_mid:
            with st.spinner("Model yanıtlıyor…"):
                try:
                    reply, report = chat(user_input,
                                         use_defense=st.session_state.defense_on)
                    st.session_state["last_result"] = {
                        "blocked": False, "reply": reply,
                        "report": report, "query": user_input,
                    }
                except BlockedByDefenseError as exc:
                    st.session_state["last_result"] = {
                        "blocked": True, "blocked_at": "input",
                        "error": str(exc), "report": exc.report, "query": user_input,
                    }
                except OutputLeakError as exc:
                    st.session_state["last_result"] = {
                        "blocked": True, "blocked_at": "output",
                        "error": str(exc), "report": exc.report, "query": user_input,
                    }
                except Exception as exc:
                    st.session_state["last_result"] = {
                        "blocked": False, "reply": None,
                        "error": str(exc), "report": {}, "query": user_input,
                    }

    # ── Sağ: Sonuçlar ────────────────────────────────────────────────────
    with col_right:
        st.markdown('<div class="panel-title panel-result">📊 Sonuçlar</div>',
                    unsafe_allow_html=True)
        result = st.session_state.get("last_result")

        if result is None:
            st.info("Henüz bir sorgu gönderilmedi.\n\n"
                    "Soldaki kütüphaneden bir saldırı seçin veya mesaj yazın.", icon="💡")
        else:
            if st.session_state.defense_on:
                st.markdown("**🔍 Savunma Katmanları**")
                rpt = result.get("report", {})

                # L0 – Unicode normalize
                hg = rpt.get("layer0_homoglyphs_found", 0)
                if hg:
                    st.markdown(
                        f'<span class="layer-badge badge-warn">L0 Unicode</span>'
                        f"{hg} homoglyph tespit edildi ve normalleştirildi.",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<span class="layer-badge badge-ok">L0 Unicode</span>'
                        "Homoglyph bulunamadı.",
                        unsafe_allow_html=True,
                    )

                # L1 – Regex
                kw = rpt.get("layer1_flagged_keywords", [])
                if kw:
                    st.markdown(
                        f'<span class="layer-badge badge-err">L1 Regex Filtresi</span>'
                        f"Tehlikeli kelime: {', '.join(f'`{k}`' for k in kw)}",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<span class="layer-badge badge-ok">L1 Regex Filtresi</span>'
                        "Tehlikeli kelime bulunamadı.",
                        unsafe_allow_html=True,
                    )

                # L2 – Sınır etiketleme
                if rpt.get("layer2_delimited"):
                    st.markdown(
                        '<span class="layer-badge badge-inf">L2 Sınır Etiketleme</span>'
                        "`[USER_INPUT]` etiketleri eklendi.",
                        unsafe_allow_html=True,
                    )

                # L3 – Semantik kontrol
                verdict = rpt.get("layer3_verdict")
                if verdict:
                    is_atk = rpt.get("layer3_is_attack", False)
                    badge  = "badge-err" if is_atk else "badge-ok"
                    lbl    = "SALDIRI TESPİT EDİLDİ" if is_atk else "GÜVENLİ"
                    st.markdown(
                        f'<span class="layer-badge {badge}">L3 Semantik Kontrol</span>'
                        f"Karar: **{verdict}** → {lbl}",
                        unsafe_allow_html=True,
                    )

                # L4 – Çıktı filtresi
                if "output_leaked" in rpt:
                    leaked   = rpt.get("output_leaked", False)
                    patterns = rpt.get("output_leaked_patterns", [])
                    if leaked:
                        st.markdown(
                            f'<span class="layer-badge badge-err">L4 Çıktı Filtresi</span>'
                            f"Sızıntı tespit edildi: {', '.join(f'`{p}`' for p in patterns)}",
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            '<span class="layer-badge badge-ok">L4 Çıktı Filtresi</span>'
                            "Yanıtta gizli değer bulunamadı.",
                            unsafe_allow_html=True,
                        )

                # Nihai karar
                blocked_by = rpt.get("blocked_by")
                if blocked_by:
                    st.error("⛔ GİRDİ ENGELLENDİ — model bu promptu hiç görmedi.")
                elif rpt.get("output_leaked"):
                    st.error("⛔ ÇIKTI ENGELLENDİ — model yanıtladı ama yanıt sızıntı içerdiği için gösterilmedi.")
                elif rpt:
                    st.success("✅ Tüm katmanlar geçildi — model güvenle yanıtladı.")

                st.divider()
            else:
                st.warning("⚠️ Savunma kapalı — yanıt filtresiz.", icon="🚨")
                st.divider()

            st.markdown("**🤖 Model Yanıtı**")
            if result.get("blocked"):
                at = result.get("blocked_at", "input")
                if at == "output":
                    st.markdown(
                        '<div class="blocked-box">🔴 <strong>ÇIKTI ENGELLENDİ</strong><br><br>'
                        "Model bir yanıt üretti, ancak yanıt gizli değer içerdiği için "
                        "kullanıcıya gösterilmedi."
                        "</div>", unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<div class="blocked-box">⛔ <strong>GİRDİ ENGELLENDİ</strong><br><br>'
                        "Bu prompt savunma katmanı tarafından durduruldu. "
                        "Model bu girdiyi hiç görmedi."
                        "</div>", unsafe_allow_html=True,
                    )
            elif result.get("error") and not result.get("reply"):
                st.error(f"Hata: {result['error']}", icon="💥")
            else:
                safe_txt = (
                    (result.get("reply") or "")
                    .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                )
                st.markdown(f'<div class="response-box">{safe_txt}</div>',
                            unsafe_allow_html=True)

            with st.expander("Gönderilen sorgu", expanded=False):
                st.code(result.get("query", ""), language=None)


# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — Benchmark
# ════════════════════════════════════════════════════════════════════════════
with tab_bench:
    st.markdown('<div class="panel-title panel-bench">📊 Otomatik Benchmark Suite</div>',
                unsafe_allow_html=True)

    n_attack = sum(1 for d in dataset if d["expected_result"] == "UNSAFE")
    n_benign = sum(1 for d in dataset if d["expected_result"] == "SAFE")
    total_n  = len(dataset)

    di1, di2, di3 = st.columns(3)
    di1.metric("Toplam Prompt", total_n)
    di2.metric("Saldırı Promptu", n_attack)
    di3.metric("Masum Soru",    n_benign)
    st.caption("Her prompt savunma katmanları AÇIK halde çalıştırılır; "
               "sonuç beklenen değerle karşılaştırılır.")
    st.divider()

    run_col, reset_col = st.columns([4, 1], gap="small")
    with run_col:
        run_clicked = st.button("▶ Otomatik Test Başlat", type="primary",
                                use_container_width=True)
    with reset_col:
        if st.button("🗑 Sıfırla", use_container_width=True):
            st.session_state["bench_results"] = None
            st.session_state["bench_metrics"] = None
            st.rerun()

    # ── Test çalıştır ─────────────────────────────────────────────────────
    if run_clicked:
        st.session_state["bench_results"] = None
        st.session_state["bench_metrics"] = None
        progress_bar = st.progress(0.0, text="Başlatılıyor…")
        status_area  = st.empty()
        live_rows: list[dict] = []

        for idx, item in enumerate(dataset):
            icon = "🔴" if item["expected_result"] == "UNSAFE" else "🟢"
            progress_bar.progress(
                idx / total_n,
                text=f"[{idx+1}/{total_n}] {icon} {item['prompt'][:60]}…",
            )
            r = evaluate_single(item)
            live_rows.append(r)
            status_area.dataframe(
                pd.DataFrame(live_rows[-5:])
                  [["id", "category", "expected", "outcome", "correct"]]
                  .rename(columns={
                      "id": "#", "category": "Kategori", "expected": "Beklenen",
                      "outcome": "Ham Sonuç", "correct": "Doğru?",
                  })
                  .set_index("#"),
                use_container_width=True,
            )

        progress_bar.progress(1.0, text=f"✅ {total_n}/{total_n} tamamlandı.")
        st.session_state["bench_results"] = live_rows
        st.session_state["bench_metrics"] = compute_metrics(live_rows)
        status_area.empty()
        st.rerun()

    # ── Sonuçları göster ──────────────────────────────────────────────────
    bench_results = st.session_state.get("bench_results")
    bench_metrics = st.session_state.get("bench_metrics")

    if bench_results and bench_metrics:
        m = bench_metrics

        # Metrik kartları
        st.markdown("### 📈 Metrikler")
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("Genel Başarı",
                   f"{m['accuracy']:.1%}",
                   f"{m['correct']}/{m['total']} doğru karar")
        mc2.metric("Saldırı Engelleme Oranı",
                   f"{m['detection_rate']:.1%}",
                   f"{m['tp']}/{m['attack_count']} saldırı engellendi")
        mc3.metric("Hatalı Engelleme Oranı",
                   f"{m['false_positive_rate']:.1%}",
                   f"{m['fp']}/{m['benign_count']} masum yanlış engellendi",
                   delta_color="inverse")
        mc4.metric("Kaçan Saldırı Oranı",
                   f"{m['bypass_rate']:.1%}",
                   f"{m['fn']}/{m['attack_count']} saldırı savunmayı aştı",
                   delta_color="inverse")

        st.divider()

        ch_col, tbl_col = st.columns([1, 2], gap="large")

        with ch_col:
            st.markdown("### 🥧 Sonuç Dağılımı")
            values = [m["tp"], m["tn"], m["fp"], m["fn"]]
            fig = go.Figure(go.Pie(
                labels=_PIE_LABELS,
                values=values,
                hole=0.38,
                marker=dict(
                    colors=["#4caf50", "#2196f3", "#ff9800", "#f44336"],
                    line=dict(color="#0e1117", width=2),
                ),
                textinfo="label+percent",
                textfont_size=11,
                pull=[0.04 if v > 0 else 0 for v in values],
            ))
            fig.update_layout(
                paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
                font_color="#dcdcdc",
                margin=dict(t=10, b=10, l=10, r=10),
                legend=dict(orientation="v", bgcolor="#0e1117", font_size=10),
                height=330,
            )
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("**Kategori Özeti**")
            cats: dict = {}
            for r in bench_results:
                c = r["category"]
                cats.setdefault(c, {"total": 0, "correct": 0})
                cats[c]["total"]   += 1
                cats[c]["correct"] += int(r["correct"] or 0)
            cat_df = pd.DataFrame([
                {"Kategori": k, "Toplam": v["total"],
                 "Doğru": v["correct"],
                 "Başarı": f"{v['correct']/v['total']:.0%}"}
                for k, v in cats.items()
            ]).set_index("Kategori")
            st.dataframe(cat_df, use_container_width=True)

        with tbl_col:
            st.markdown("### 📋 Detaylı Sonuçlar")
            st.caption(
                "✅ Başarılı Engelleme: saldırı doğru engellendi &nbsp;|&nbsp; "
                "✅ Başarılı Geçiş: masum soru doğru geçti &nbsp;|&nbsp; "
                "⚠️ Hatalı Engelleme: masum soru yanlışlıkla engellendi &nbsp;|&nbsp; "
                "❌ Kaçan Saldırı: saldırı savunmayı aştı"
            )

            rows = []
            for r in bench_results:
                rows.append({
                    "#":          r["id"],
                    "Kategori":   r["category"],
                    "Beklenen":   "Saldırı" if r["expected"] == "UNSAFE" else "Masum",
                    "Sistem Kararı": "Engellendi" if r["system_decision"] == "BLOCKED" else "Geçti",
                    "Sonuç":      _OUTCOME_TR.get(r["outcome"], r["outcome"]),
                    "Süre (s)":   r["elapsed_s"],
                    "Prompt":     r["prompt"][:70] + ("…" if len(r["prompt"]) > 70 else ""),
                })

            df = pd.DataFrame(rows).set_index("#")

            def _row_color(row: pd.Series) -> list[str]:
                outcome = bench_results[int(row.name) - 1]["outcome"]
                bg = {
                    "TP": "background-color:#0d2b0d; color:#c8e6c9",
                    "TN": "background-color:#0d1e2b; color:#bbdefb",
                    "FP": "background-color:#2b1f00; color:#ffe082",
                    "FN": "background-color:#2b0000; color:#ffcdd2",
                }.get(outcome, "")
                return [bg] * len(row)

            st.dataframe(df.style.apply(_row_color, axis=1),
                         use_container_width=True, height=520)

        st.divider()
        st.caption(f"⏱ Toplam test süresi: {m['total_elapsed_s']} saniye")

        # ── PDF İndir ─────────────────────────────────────────────────────
        st.markdown("### 📄 Rapor")
        st.caption("Benchmark sonuçlarını tek sayfalık PDF olarak indir.")

        with st.spinner("PDF oluşturuluyor…"):
            try:
                pdf_bytes = generate_pdf(bench_results, bench_metrics)
                fname = f"benchmark_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
                st.download_button(
                    label="📥 PDF Raporu İndir",
                    data=pdf_bytes,
                    file_name=fname,
                    mime="application/pdf",
                    type="primary",
                    use_container_width=False,
                )
            except Exception as e:
                st.error(f"PDF oluşturulamadı: {e}", icon="💥")
