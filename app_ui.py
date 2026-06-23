#!/usr/bin/env python3
"""Streamlit UI — batch timing accuracy tool.

Compares each tested item against the Reference. Steps in order:
    1. Reference  — folder with Reference files
    2. Tested     — add one tested folder at a time
    3. Results    — per-tested stats, plotly graphs, overlay, export
    4. Strength overlay — butterfly view

Run:
    streamlit run app_ui.py
"""
import glob
import os
import sys

import streamlit as st
import streamlit.components.v1 as _components

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

DEFAULT_CHIRP = os.path.join(HERE, "marker.mp3")
TMP = os.path.join(HERE, "._ui_tmp")
os.makedirs(TMP, exist_ok=True)

import session
import viz
import report

st.set_page_config(page_title="test", layout="wide")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _show_svg(svg_str, height=480):
    """Render an SVG string inline, with fallback for Streamlit versions
    that cannot handle raw SVG bytes in st.image."""
    try:
        st.image(svg_str.encode(), use_container_width=True)
    except Exception:
        _components.html(svg_str, height=height)


# --------------------------------------------------------------------------
# Step 1 · Reference
# --------------------------------------------------------------------------


def view_reference():
    st.header("Step 1 · Reference")
    st.markdown("Point at the folder that holds the Reference files. Nothing else to set.")
    d = st.text_input(
        "📁 Reference folder path",
        placeholder=r"C:\path\to\reference\folder",
    ).strip().strip('"')
    if not d:
        st.info("Enter the Reference folder path.")
        return
    if not os.path.isdir(d):
        st.error(f"not a folder: {d}")
        return
    try:
        ref = session.run_reference(d, DEFAULT_CHIRP)
    except Exception as e:
        st.error(f"Reference failed: {e}")
        return
    st.session_state["ref"] = ref
    m1, m2, m3 = st.columns(3)
    m1.metric("files", len(ref["files"]))
    m2.metric("Reference lines", len(ref["rows"]))
    worst = max((f["pps_rmse_ms"] for f in ref["files"]), default=0.0)
    m3.metric("clock fit (max)", f"{worst:.2f} ms")
    st.success(f"Step 1 done — {len(ref['rows'])} Reference lines. Open Step 2.")


# --------------------------------------------------------------------------
# Step 2 · Tested
# --------------------------------------------------------------------------


def view_tested():
    st.header("Step 2 · Tested")
    st.markdown("Add each tested folder. Format is detected automatically.")
    if "tested" not in st.session_state:
        st.session_state["tested"] = {}
    d = st.text_input("📁 tested folder path", key="tested_path").strip().strip('"')
    if st.button("Add this tested folder") and d:
        if not os.path.isdir(d):
            st.error(f"not a folder: {d}")
        else:
            try:
                t = session.run_tested(d, DEFAULT_CHIRP)
                st.session_state["tested"][t["name"]] = t
                st.success(
                    f"added {t['name']} — {len(t['rows'])} lines ({t['fmt']} format)"
                )
            except Exception as e:
                st.error(f"{os.path.basename(d)}: {e}")
    items = st.session_state["tested"]
    if items:
        st.write("Added so far:")
        for name, t in list(items.items()):
            c1, c2 = st.columns([4, 1])
            c1.write(
                f"• **{name}** — {len(t['rows'])} lines, {t['fmt']}"
                + (" low-confidence" if t["low_confidence"] else "")
            )
            if c2.button("remove", key=f"rm_{name}"):
                del items[name]
                st.rerun()
        st.success(f"{len(items)} tested item(s) ready. Open Step 3.")


# --------------------------------------------------------------------------
# Step 3 · Results
# --------------------------------------------------------------------------


def view_results():
    st.header("Step 3 · Results")
    ref = st.session_state.get("ref")
    items = st.session_state.get("tested", {})
    if not ref or not items:
        st.warning("Finish Step 1 (Reference) and Step 2 (Tested) first.")
        return
    target = st.number_input("Accuracy target (ms)", value=10.0, step=1.0)
    results = []
    for name, t in items.items():
        c = session.compare_tested(t["rows"], ref["rows"], target_ms=target)
        if not c["pairs"]:
            st.error(f"{name}: no matching lines — not the same session?")
            continue
        results.append({"name": name, "compare": c, "rows": t["rows"]})
        m = c["metrics"]
        v = c["verdict"]
        tag = "PASS" if v["pass"] else "FAIL"
        st.subheader(f"{name} — {tag}")
        a, b, cc, dd = st.columns(4)
        a.metric("offset (bias)", f"{m['bias']:+.2f} ms", v["direction"])
        b.metric("1σ", f"± {m['one_sigma']:.2f} ms")
        cc.metric("2σ", f"± {m['two_sigma']:.2f} ms")
        dd.metric("drift", f"{m['drift_slope_ms_per_min']:+.2f} ms/min")
        st.plotly_chart(
            viz.error_timeline_plotly(c["pairs"], m, target),
            use_container_width=True,
        )
        st.plotly_chart(
            viz.hist_plotly(c["dt_ms"], m),
            use_container_width=True,
        )
    if len(results) > 1:
        st.subheader("All tested — overlay")
        svg, _ = viz.multi_overlay_mpl(
            [{"name": r["name"], "pairs": r["compare"]["pairs"]} for r in results]
        )
        _show_svg(svg, height=480)
    if results and st.button("Export report"):
        out = report.build_html(
            {"target_ms": target, "tested": results},
            os.path.join(HERE, "_report_out"),
        )
        st.success(f"Wrote {out['html_path']} and {out['csv_path']}")
        st.session_state["last_report"] = out


# --------------------------------------------------------------------------
# Step 4 · Strength overlay
# --------------------------------------------------------------------------


def view_overlay():
    st.header("Step 4 · Strength overlay")
    ref = st.session_state.get("ref")
    items = st.session_state.get("tested", {})
    if not ref or not items:
        st.warning("Finish Steps 1 and 2 first.")
        return
    name = st.selectbox("tested item", list(items.keys()))
    t = items[name]
    st.plotly_chart(
        viz.butterfly_plotly(
            ref["bin_paths"],
            ref["t0_iso"],
            ref["fs"],
            t["media_path"],
            t["fmt"],
            t["fs"],
            t["t0_iso"],
            [r["start_utc"] for r in ref["rows"]],
            [r["start_utc"] for r in t["rows"]],
            window=None,
            max_cols=3500,
            ref_bin_t0s=ref["bin_t0s"],
        ),
        use_container_width=True,
    )
    st.caption("Drag to box-zoom. For a crisp slice, pick a window and render sharp:")
    c1, c2 = st.columns(2)
    w0 = c1.text_input("window start (UTC ISO)", ref["t0_iso"])
    w1 = c2.text_input("window end (UTC ISO)", "")
    if st.button("Render sharp window") and w1:
        svg, png = viz.butterfly_image(
            ref["bin_paths"],
            ref["t0_iso"],
            ref["fs"],
            t["media_path"],
            t["fmt"],
            t["fs"],
            t["t0_iso"],
            [r["start_utc"] for r in ref["rows"]],
            [r["start_utc"] for r in t["rows"]],
            window=(w0, w1),
            ref_bin_t0s=ref["bin_t0s"],
        )
        st.download_button(
            "Download SVG", svg.encode(), "strength_overlay.svg", "image/svg+xml"
        )
        st.download_button(
            "Download PNG", png, "strength_overlay.png", "image/png"
        )


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

st.title("test")
st.caption("Compare each tested item against the Reference. Do the steps in order.")

tabs = st.sidebar.radio(
    "Steps",
    ["1 · Reference", "2 · Tested", "3 · Results", "4 · Strength overlay"],
)
if tabs.startswith("1"):
    view_reference()
elif tabs.startswith("2"):
    view_tested()
elif tabs.startswith("3"):
    view_results()
else:
    view_overlay()
