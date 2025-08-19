# app.py — Macros, Micros, Simulation (all macros shown)
# Adjusted Forecast is ONLY drawn from the forecast start onward (not in history)
# Render-ready: uses Dash (Gunicorn will import `server`)

import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from pandas.api.types import is_period_dtype, is_datetime64_any_dtype
import plotly.graph_objs as go
from plotly.subplots import make_subplots
from dash import Dash, dcc, html, Input, Output

# =========================
# ====== CONFIG ===========
# =========================

# --- Portable path discovery for the Excel file (Render-safe) ---
HERE = Path(__file__).resolve().parent

CANDIDATES = [
    HERE / "Scenario_Forecasts_NEW.xlsx",
    HERE / "data" / "Scenario_Forecasts_NEW.xlsx",
    Path(os.environ.get("SCENARIO_XLSX", "")),  # allow override via env var
]
FILE_PATH = next((p for p in CANDIDATES if p and p.is_file()), None)

# Map workbook sheet names -> friendly names for UI
SHEET_TO_NAME = {
    # Macros
    "Credit_Card_Growth": "Credit Card Growth",
    "Unemployment_rate_aged_16_and_o": "Unemployment",
    "CPIH_ANNUAL_RATE_00_ALL_ITEMS_2": "CPIH",
    "Gross_Domestic_Product_Quarter_": "GDP",
    "10Y_2Y_Spread": "Yield Spread",
    # Micros (RSI)
    "RSI_Predominantly_food_stores": "RSI: Predominantly food stores",
    "RSI_clothing_footwear": "RSI: Clothing & Footwear",
    "RSI_Household_goods_stores": "RSI: Household goods",
    "Non_store_Retailing": "Non-store Retailing",
    "RSI_electrical_household_applia": "RSI: Electrical household appliances",
    "RSI_watches_and_jewellery_": "RSI: Watches & Jewellery",
}

MACROS = ["Credit Card Growth", "CPIH", "Unemployment", "GDP", "Yield Spread"]
MICROS = [
    "RSI: Predominantly food stores",
    "RSI: Clothing & Footwear",
    "RSI: Household goods",
    "Non-store Retailing",
    "RSI: Electrical household appliances",
    "RSI: Watches & Jewellery",
]

THRESHOLDS = {
    "Credit Card Growth": 20,
    "CPIH": 3,
    "Unemployment": 6,
    "GDP": -2,
    "Yield Spread": 0,
}

MODEL_META: Dict[str, List[Dict]] = {
    # Macros endogenously respond to others
    "Credit Card Growth": [
        {"driver": "GDP", "coef": 0.175, "p": 0.000, "sig": True},
        {"driver": "CPIH", "coef": 1.171, "p": 0.003, "sig": True},
    ],
    "Unemployment": [
        {"driver": "GDP_lag1", "coef": -0.018, "p": 0.000, "sig": True},
        {"driver": "GDP_lag2", "coef": -0.025, "p": 0.000, "sig": True},
        {"driver": "Credit Card Growth", "coef": -0.037, "p": 0.000, "sig": True},
        {"driver": "Yield Spread", "coef": 0.174, "p": 0.013, "sig": True},
    ],
    "CPIH": [
        {"driver": "Credit Card Growth", "coef": 0.067, "p": 0.006, "sig": True},
    ],

    # Micros respond to macros
    "RSI: Predominantly food stores": [
        {"driver": "Credit Card Growth", "coef": -0.170, "p": 0.000, "sig": True},
    ],
    "RSI: Clothing & Footwear": [
        {"driver": "GDP", "coef": 1.282, "p": 0.000, "sig": True},
        {"driver": "Credit Card Growth", "coef": 1.168, "p": 0.000, "sig": True},
    ],
    "RSI: Household goods": [
        {"driver": "GDP", "coef": 1.162, "p": 0.000, "sig": True},
    ],
    "Non-store Retailing": [
        {"driver": "Credit Card Growth", "coef": -0.859, "p": 0.000, "sig": True},
        {"driver": "GDP", "coef": -0.241, "p": 0.000, "sig": True},
    ],
    "RSI: Electrical household appliances": [
        {"driver": "GDP", "coef": 0.585, "p": 0.000, "sig": True},
    ],
    "RSI: Watches & Jewellery": [
        {"driver": "GDP", "coef": 1.474, "p": 0.000, "sig": True},
        {"driver": "Credit Card Growth", "coef": 1.046, "p": 0.000, "sig": True},
    ],
}

# =========================
# ====== HELPERS ==========
# =========================

def detect_time_col(df: pd.DataFrame) -> str:
    candidates = [c for c in df.columns if c.lower() in ("date", "quarter", "unnamed: 0")]
    if candidates:
        return candidates[0]
    first = df.columns[0]
    try:
        pd.to_datetime(df[first])
        return first
    except Exception:
        pass
    raise ValueError("No time column found (expect: Date/Quarter/Unnamed: 0).")

def find_forecast_scenarios(df: pd.DataFrame) -> List[Tuple[str, str]]:
    """Match Forecast_* columns → list of (scenario_token, column_name)."""
    pairs = []
    for col in df.columns:
        m = re.match(r'(?i)^forecast[_\s]*(.+)$', str(col).strip())
        if m:
            pairs.append((m.group(1).strip(), col))
    return pairs

def find_ci_cols(df: pd.DataFrame, scenario: str) -> Tuple[str, str]:
    """Find Lower/Upper CI columns for a given scenario (flexible matching)."""
    lower, upper = None, None
    sl = scenario.lower()
    scen_tokens = {sl, sl.replace(" ", "_"), sl.replace("_", " "), sl.title(), sl.capitalize()}
    for col in df.columns:
        cl = str(col).lower()
        if "lower" in cl and any(tok in cl for tok in scen_tokens):
            lower = col
        if "upper" in cl and any(tok in cl for tok in scen_tokens):
            upper = col
    return lower, upper

# ---------- PeriodIndex-safe quarter builder ----------
def _qindex(dates) -> pd.PeriodIndex:
    """Return a quarterly PeriodIndex from many input types without calling to_datetime on Periods."""
    if isinstance(dates, pd.PeriodIndex):
        try:
            return dates.asfreq("Q")
        except Exception:
            return dates
    if isinstance(dates, pd.DatetimeIndex):
        return dates.to_period("Q")
    if isinstance(dates, pd.Series):
        if is_period_dtype(dates.dtype):
            return pd.PeriodIndex(dates.astype("period[Q]"))
        if is_datetime64_any_dtype(dates.dtype):
            return pd.DatetimeIndex(dates).to_period("Q")
        dt = pd.to_datetime(dates, errors="coerce")
        return pd.DatetimeIndex(dt).to_period("Q")
    try:
        return pd.PeriodIndex(dates, freq="Q")
    except Exception:
        dt = pd.to_datetime(dates, errors="coerce")
        return pd.DatetimeIndex(dt).to_period("Q")

# ---------- PeriodIndex-safe alignment ----------
def align_by_quarter(s: pd.Series, target_dates, lag: int = 0) -> pd.Series:
    """Align series to target quarters using PeriodIndex; supports lags (in quarters)."""
    if isinstance(s.index, pd.PeriodIndex):
        s_q = s.copy()
        try:
            s_q.index = s_q.index.asfreq("Q")
        except Exception:
            pass
    elif isinstance(s.index, pd.DatetimeIndex):
        s_q = s.copy()
        s_q.index = s_q.index.to_period("Q")
    else:
        s_q = pd.Series(s.values, index=_qindex(s.index))
    s_q = s_q.sort_index()
    if lag > 0:
        s_q = s_q.shift(lag)

    tgt_q = target_dates if isinstance(target_dates, pd.PeriodIndex) else _qindex(target_dates)
    try:
        tgt_q = tgt_q.asfreq("Q")
    except Exception:
        pass

    out = s_q.reindex(tgt_q)
    return out.ffill().bfill()

def read_all_sheets(file_path: str) -> Dict[str, pd.DataFrame]:
    """Return dict[var_name] -> tidy df with:
       Quarter | Scenario | Actual | Forecast | (optional) Lower CI | Upper CI | Crisis_* flags
    """
    xls = pd.ExcelFile(file_path)
    out = {}

    CANON_SCN = {
        "baseline": "Baseline", "recession": "Recession",
        "recovery": "Recovery", "crisis": "Crisis"
    }

    for sheet in xls.sheet_names:
        if sheet not in SHEET_TO_NAME:
            continue
        nice = SHEET_TO_NAME[sheet]
        df = pd.read_excel(file_path, sheet_name=sheet)
        df.columns = df.columns.astype(str).str.strip()

        # time col
        tcol = detect_time_col(df)
        df = df.rename(columns={tcol: "Quarter"})
        df["Quarter"] = pd.to_datetime(df["Quarter"], errors="coerce")

        # scenarios
        scn_pairs = find_forecast_scenarios(df)  # [(ScenarioToken, Forecast_Column)]
        crisis_cols = [c for c in df.columns if str(c).startswith("Crisis_")]
        actual_exists = "Actual" in df.columns

        frames = []
        if scn_pairs:
            for scn_raw, fcol in scn_pairs:
                key = scn_raw.lower().replace(" ", "").replace("_", "")
                scn_name = CANON_SCN.get(key, scn_raw.replace("_", " ").title())
                keep = ["Quarter", fcol] + (["Actual"] if actual_exists else []) + crisis_cols
                tmp = df[keep].copy().rename(columns={fcol: "Forecast"})
                tmp["Scenario"] = scn_name

                lcol, ucol = find_ci_cols(df, scn_raw)
                if lcol and ucol and (lcol in df.columns) and (ucol in df.columns):
                    tmp["Lower CI"] = df[lcol].values
                    tmp["Upper CI"] = df[ucol].values

                frames.append(tmp)
        else:
            # fallback single Forecast
            if "Forecast" not in df.columns:
                continue
            tmp = df[["Quarter", "Forecast"] + (["Actual"] if actual_exists else []) + crisis_cols].copy()
            tmp["Scenario"] = "Baseline"
            frames.append(tmp)

        long = pd.concat(frames, ignore_index=True)
        cols = ["Quarter", "Scenario"]
        if actual_exists: cols.append("Actual")
        cols.append("Forecast")
        if "Lower CI" in long.columns and "Upper CI" in long.columns:
            cols += ["Lower CI", "Upper CI"]
        cols += crisis_cols
        long = long[cols].sort_values(["Scenario", "Quarter"]).reset_index(drop=True)
        out[nice] = long

    return out

def to_index_100_safe(y: pd.Series) -> pd.Series:
    y = pd.Series(y).dropna().astype(float)
    if y.empty: return y
    base = y.iloc[0]
    return (y / base * 100.0) if pd.notna(base) and base != 0 else y

def to_index_100_relative(y: pd.Series, base_value: float) -> pd.Series:
    y = pd.Series(y).astype(float)
    if pd.isna(base_value) or base_value == 0:
        return y
    return (y / base_value) * 100.0

def crisis_mask(series: pd.Series, threshold: float) -> pd.Series:
    return (series > threshold) if threshold >= 0 else (series < threshold)

def add_threshold_line(fig: go.Figure, y: float, x0, x1, row=None, col=None):
    if row is not None and col is not None:
        fig.add_hline(y=y, line_color="red", line_dash="dash", row=row, col=col)
    else:
        fig.add_hline(y=y, line_color="red", line_dash="dash")

def add_crisis_markers(fig: go.Figure, x, y, threshold: float, row=None, col=None):
    y = pd.Series(y, index=pd.Index(x))
    m = crisis_mask(y, threshold)
    cross = (~m.shift(1, fill_value=False)) & m
    if cross.any():
        tr = go.Scatter(x=y.index[cross], y=y[cross], mode="markers",
                        marker=dict(symbol="x", size=9, color="red"),
                        name="Threshold crossed", showlegend=False)
        if row is not None and col is not None:
            fig.add_trace(tr, row=row, col=col)
        else:
            fig.add_trace(tr)

def add_hist_forecast_divider(fig: go.Figure, df: pd.DataFrame, row=None, col=None):
    if "Actual" in df.columns and df["Actual"].notna().any() and df["Forecast"].notna().any():
        idx = df["Forecast"].first_valid_index()
        if idx is not None:
            x0 = df.loc[idx, "Quarter"]
            if row is not None and col is not None:
                fig.add_vline(x=x0, line_dash="dot", line_width=1, row=row, col=col)
            else:
                fig.add_vline(x=x0, line_dash="dot", line_width=1)

def add_crisis_bands(fig: go.Figure, df: pd.DataFrame, row=None, col=None):
    crisis_cols = [c for c in df.columns if str(c).startswith("Crisis_")]
    if not crisis_cols: return
    tmp = df[["Quarter"] + crisis_cols].copy()
    mask = tmp[crisis_cols].sum(axis=1) > 0
    if not mask.any(): return
    q = df["Quarter"].values
    on = False; start = None
    for i, flag in enumerate(mask):
        if flag and not on:
            on = True; start = q[i]
        if on and (i == len(mask) - 1 or not mask.iloc[i + 1]):
            end = q[i]
            if row is not None and col is not None:
                fig.add_vrect(x0=start, x1=end, fillcolor="lightgrey", opacity=0.2, line_width=0, row=row, col=col)
            else:
                fig.add_vrect(x0=start, x1=end, fillcolor="lightgrey", opacity=0.2, line_width=0)
            on = False

# --------- Global historical crisis shading (all graphs) ----------
CRISIS_PERIODS = [
    # 2008–09 Financial Crisis: red
    {"x0": "2008-01-01", "x1": "2009-12-31", "fillcolor": "rgba(255,0,0,0.18)"},
    # 2020 COVID: purple
    {"x0": "2020-03-01", "x1": "2021-03-31", "fillcolor": "rgba(128,0,128,0.18)"},
    # 2022–23 Recession: orange
    {"x0": "2022-01-01", "x1": "2023-12-31", "fillcolor": "rgba(255,165,0,0.18)"},
]

def add_global_crisis_bands(fig: go.Figure, row=None, col=None):
    """Add fixed historical shaded bands to any figure (or subplot via row/col)."""
    for p in CRISIS_PERIODS:
        if row is not None and col is not None:
            fig.add_vrect(x0=p["x0"], x1=p["x1"], fillcolor=p["fillcolor"], opacity=0.25, line_width=0, row=row, col=col)
        else:
            fig.add_vrect(x0=p["x0"], x1=p["x1"], fillcolor=p["fillcolor"], opacity=0.25, line_width=0)

def add_ci_band(fig: go.Figure, df: pd.DataFrame, norm_on: bool, row=None, col=None):
    if {"Upper CI", "Lower CI"}.issubset(df.columns):
        up, lo = df["Upper CI"], df["Lower CI"]
        if up.notna().any() and lo.notna().any():
            if norm_on:
                up = to_index_100_safe(up); lo = to_index_100_safe(lo)
            t_up = go.Scatter(x=df["Quarter"], y=up, mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip")
            t_lo = go.Scatter(x=df["Quarter"], y=lo, mode="lines", line=dict(width=0),
                              fill="tonexty", fillcolor="rgba(0,0,0,0.12)", showlegend=False, hoverinfo="skip")
            if row is not None and col is not None:
                fig.add_trace(t_up, row=row, col=col)
                fig.add_trace(t_lo, row=row, col=col)
            else:
                fig.add_trace(t_up); fig.add_trace(t_lo)

def relationship_table(target: str):
    rows = MODEL_META.get(target, [])
    if not rows:
        return html.Div("No model metadata.", style={"fontStyle":"italic"})
    rows = sorted(rows, key=lambda r: abs(r["coef"]), reverse=True)
    header = html.Tr([html.Th("Driver"), html.Th("Coef"), html.Th("Signif")])
    body = []
    for r in rows:
        sign = "✅" if r.get("sig") else "❌"
        body.append(html.Tr([html.Td(r["driver"]), html.Td(f'{r["coef"]:+.3f}'), html.Td(sign)]))
    return html.Div([
        html.Div("Exogenous drivers (ranked by |coef|)", style={"fontWeight":"600","marginBottom":"4px"}),
        html.Table([header] + body, style={"width":"100%","borderCollapse":"collapse","fontSize":"12px"})
    ], style={"marginTop":"6px"})

def model_badge_text(var: str) -> str:
    rows = MODEL_META.get(var, [])
    if any("lag" in r["driver"] for r in rows): model = "SARIMAX (lags)"
    elif rows: model = "ARIMAX"
    else: model = "—"
    sig = ", ".join([f'{r["driver"]} ({r["coef"]:+.3f})' for r in rows]) or "—"
    return f"Model: {model}. Drivers: {sig}"

def _parse_driver(name: str) -> Tuple[str, int]:
    if "_lag" in name:
        base, lag = name.split("_lag")
        try: return base, int(lag)
        except: return base, 0
    return name, 0

# ---------- Simulation helpers ----------

def macro_adjusted_series(DATA: Dict[str, pd.DataFrame], scn: str, pct_map: Dict[str, float]) -> Dict[str, pd.DataFrame]:
    """Endogenous macro propagation with QUARTER alignment; returns dict[var] with 'Adj Forecast'."""
    present_macros = [m for m in MACROS if m in DATA]

    # Base series per macro
    base: Dict[str, Tuple[pd.DataFrame, pd.Series]] = {}
    for var in present_macros:
        dfb = DATA[var][DATA[var]["Scenario"] == scn].copy().sort_values("Quarter")
        s = pd.Series(dfb["Forecast"].values, index=_qindex(dfb["Quarter"]))
        base[var] = (dfb, s)

    # Direct slider shocks (exogenous)
    forced: Dict[str, pd.Series] = {}
    for var in present_macros:
        _, s_base = base[var]
        pct = (pct_map.get(var, 0.0) or 0.0) / 100.0
        forced[var] = s_base * (1.0 + pct)

    # Iterate with model propagation
    adj = {var: forced[var].copy() for var in present_macros}
    MAX_ITERS, TOL = 12, 1e-6
    for _ in range(MAX_ITERS):
        maxdiff = 0.0
        new_adj: Dict[str, pd.Series] = {}
        for var in present_macros:
            s_target = forced[var].copy()
            tgt_q = s_target.index  # PeriodIndex
            for d in MODEL_META.get(var, []):
                drv_name, lag = _parse_driver(d["driver"])
                if drv_name not in base or drv_name not in adj:
                    continue
                _, s_bdrv = base[drv_name]
                s_adrv = adj[drv_name]

                s_b = align_by_quarter(s_bdrv, tgt_q, lag)
                s_a = align_by_quarter(s_adrv, tgt_q, lag)
                delta = (s_a - s_b).fillna(0.0)

                s_target = s_target.add(float(d["coef"]) * delta, fill_value=0.0)

            new_adj[var] = s_target
            prev = adj[var].reindex(s_target.index)
            diff = (s_target - prev).abs().max(skipna=True)
            if pd.notna(diff) and float(diff) > maxdiff:
                maxdiff = float(diff)

        adj = new_adj
        if not np.isfinite(maxdiff) or maxdiff < TOL:
            break

    # Build output frames
    out: Dict[str, pd.DataFrame] = {}
    for var in present_macros:
        dfb, _ = base[var]
        tgt_q = _qindex(dfb["Quarter"])
        s_adj = adj[var].reindex(tgt_q).astype(float)
        df_out = dfb.copy()
        df_out["Adj Forecast"] = s_adj.values
        out[var] = df_out

    return out

def micro_adjusted_series(DATA: Dict[str, pd.DataFrame],
                          scn: str,
                          micro_var: str,
                          base_macros: Dict[str, pd.DataFrame],
                          adj_macros: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Adjust micro forecast by quarter-aligned macro deltas with MODEL_META."""
    if micro_var not in DATA:
        return pd.DataFrame()

    df_micro = DATA[micro_var]
    df_micro = df_micro[df_micro["Scenario"] == scn].copy().sort_values("Quarter")

    if "Forecast" not in df_micro.columns:
        df_micro["Adj Forecast"] = np.nan
        return df_micro

    drivers = MODEL_META.get(micro_var, [])
    tgt_q = _qindex(df_micro["Quarter"])
    adj_series = pd.Series(df_micro["Forecast"].astype(float).values, index=tgt_q)

    for d in drivers:
        drv_name, lag = _parse_driver(d["driver"])
        base_df = base_macros.get(drv_name)
        adj_df = adj_macros.get(drv_name)
        if base_df is None or adj_df is None:
            continue

        s_base = pd.Series(base_df["Forecast"].values, index=_qindex(base_df["Quarter"]))
        s_adj  = pd.Series(adj_df.get("Adj Forecast", adj_df["Forecast"]).values, index=_qindex(adj_df["Quarter"]))

        s_b = align_by_quarter(s_base, df_micro["Quarter"], lag)
        s_a = align_by_quarter(s_adj,  df_micro["Quarter"], lag)
        delta = (s_a - s_b).reindex(tgt_q).fillna(0.0)

        adj_series = adj_series.add(float(d["coef"]) * delta, fill_value=0.0)

    df_micro["Adj Forecast"] = adj_series.reindex(tgt_q).values
    return df_micro

def tidy_var_scenarios(data: Dict[str, pd.DataFrame]) -> Dict[str, List[str]]:
    return {
        var: sorted([s for s in df["Scenario"].dropna().unique().tolist()])
        for var, df in data.items()
    }

def scenario_exists_for_var(var: str, scn: str, var_scenarios: Dict[str, List[str]]) -> bool:
    return scn in (var_scenarios.get(var) or [])

def scenario_identical_note(var: str, scn: str, data: Dict[str, pd.DataFrame]) -> str:
    if var not in data or scn == "Baseline":
        return ""
    df_all = data[var]
    have = set(df_all["Scenario"].unique().tolist())
    if not {"Baseline", scn}.issubset(have):
        return ""
    b = df_all[df_all["Scenario"] == "Baseline"].set_index("Quarter")["Forecast"]
    s = df_all[df_all["Scenario"] == scn].set_index("Quarter")["Forecast"]
    b, s = b.align(s, join="inner")
    if b.empty:
        return ""
    if np.allclose(b.values, s.values, equal_nan=True, rtol=1e-12, atol=1e-12):
        return f"(Note: For {var}, '{scn}' is identical to 'Baseline' in the source file.)"
    return ""

# =========================
# ====== LOAD DATA ========
# =========================

if FILE_PATH is None:
    DATA = {}
    LOAD_ERROR = "Dataset not found. Place 'Scenario_Forecasts_NEW.xlsx' in the project root, a 'data/' folder, or set SCENARIO_XLSX."
else:
    DATA = read_all_sheets(str(FILE_PATH))
    LOAD_ERROR = ""

VAR_SCENARIOS = tidy_var_scenarios(DATA)

macro_opts = [{"label": m, "value": m} for m in MACROS if m in DATA]
micro_opts = [{"label": m, "value": m} for m in MICROS if m in DATA]

avail_scn_all = sorted(set(sum([DATA[k]["Scenario"].dropna().unique().tolist() for k in DATA], []))) if DATA else []
scenario_opts_global = [{"label": s, "value": s} for s in (avail_scn_all or ["Baseline"])]

# =========================
# ====== DASH UI ==========
# =========================

app = Dash(__name__, suppress_callback_exceptions=True)
server = app.server  # <-- important for Gunicorn on Render

def pct_slider(id_, label):
    return html.Div([
        html.Label(f"{label} (%)"),
        dcc.Slider(id=id_, min=-50, max=50, step=1, value=0,
                   marks={-50: "-50", -25: "-25", 0: "0", 25: "25", 50: "+50"})
    ], style={"minWidth": "220px", "flex": "1 1 260px"})

top_banner = html.Div(
    LOAD_ERROR,
    style={"background":"#ffecec","border":"1px solid #ffb3b3","padding":"8px 12px","borderRadius":"8px","color":"#b30000","marginBottom":"10px"}
) if LOAD_ERROR else None

app.layout = html.Div([
    html.H2("📊 Economic Forecasts"),
    *( [top_banner] if top_banner else [] ),

    dcc.Checklist(id="normalize-toggle", options=[{"label":" Normalize to index = 100", "value":"norm"}],
                  value=["norm"], style={"marginBottom":"6px"}),
    dcc.Store(id="normalize-flag", storage_type="session"),

    dcc.Tabs(id="tabs", value="tab-macro", children=[
        # --- Macro tab
        dcc.Tab(label="Macroeconomic", value="tab-macro", children=[
            html.Div([
                html.Div([html.Label("Variable"),
                          dcc.Dropdown(id="macro-var", options=macro_opts,
                                       value=macro_opts[0]["value"] if macro_opts else None, style={"width":"300px"})],
                         style={"marginRight":"12px"}),
                html.Div([html.Label("Scenario"),
                          dcc.Dropdown(id="macro-scn", options=scenario_opts_global,
                                       value=scenario_opts_global[0]["value"], style={"width":"220px"})]),
            ], style={"display":"flex","flexWrap":"wrap","gap":"8px","marginBottom":"8px"}),

            dcc.Graph(id="macro-graph"),
            html.Div(id="macro-warning", style={"color":"red","fontWeight":"bold","marginTop":"4px"}),
            html.Div(id="macro-model-meta", style={"fontSize":"12px","opacity":0.85,"marginTop":"4px"}),
            html.Div(id="macro-rel-card", style={"maxWidth":"560px","marginTop":"6px"}),
        ]),

        # --- Micro tab
        dcc.Tab(label="Microeconomic (RSI)", value="tab-micro", children=[
            html.Div([
                html.Div([html.Label("Variable"),
                          dcc.Dropdown(id="micro-var", options=micro_opts,
                                       value=micro_opts[0]["value"] if micro_opts else None, style={"width":"360px"})],
                         style={"marginRight":"12px"}),
                html.Div([html.Label("Scenario"),
                          dcc.Dropdown(id="micro-scn", options=scenario_opts_global,
                                       value=scenario_opts_global[0]["value"], style={"width":"220px"})]),
            ], style={"display":"flex","flexWrap":"wrap","gap":"8px","marginBottom":"8px"}),

            dcc.Graph(id="micro-graph"),
            html.Div(id="micro-model-meta", style={"fontSize":"12px","opacity":0.85,"marginTop":"4px"}),
            html.Div(id="micro-rel-card", style={"maxWidth":"560px","marginTop":"6px"}),
        ]),

        # --- Simulation tab (ALL macros at once)
        dcc.Tab(label="Simulation", value="tab-sim", children=[
            html.Div([
                html.Div([html.Label("View Micro (RSI)"),
                          dcc.Dropdown(id="sim-micro-var", options=micro_opts,
                                       value=micro_opts[0]["value"] if micro_opts else None, style={"width":"360px"})],
                         style={"marginRight":"12px"}),
                html.Div([html.Label("Scenario (intersection)"),
                          dcc.Dropdown(id="sim-scn", options=scenario_opts_global,
                                       value=scenario_opts_global[0]["value"], style={"width":"240px"})]),
            ], style={"display":"flex","flexWrap":"wrap","gap":"8px","marginBottom":"6px"}),

            html.Div([
                pct_slider("pct-ccg", "Credit Card Growth"),
                pct_slider("pct-cpih", "CPIH"),
                pct_slider("pct-unemp", "Unemployment"),
                pct_slider("pct-gdp", "GDP"),
                pct_slider("pct-yield", "Yield Spread"),
            ], style={"display":"flex","flexWrap":"wrap","gap":"14px","margin":"8px 0 2px 0"}),

            html.Div(id="sim-pct-readout", style={"fontSize":"12px","opacity":0.8,"marginBottom":"4px"}),

            html.Div([
                html.Div([dcc.Graph(id="sim-macro-graph")], style={"flex":"1 1 800px","minWidth":"320px"}),
                html.Div([dcc.Graph(id="sim-micro-graph")], style={"flex":"1 1 520px","minWidth":"320px"}),
            ], style={"display":"flex","flexWrap":"wrap","gap":"12px","alignItems":"stretch"}),

            html.Div("Note: Sliders apply exogenous shocks; macros adjust endogenously via MODEL_META; micro reacts to macro deltas.",
                     style={"fontSize":"12px","opacity":0.7,"marginTop":"4px"}),
        ]),
    ])
])

# =========================
# ====== CALLBACKS ========
# =========================

@app.callback(Output("normalize-flag","data"), Input("normalize-toggle","value"))
def set_norm(value):
    return bool(value and "norm" in value)

@app.callback(Output("macro-scn","options"), Output("macro-scn","value"), Input("macro-var","value"))
def sync_macro_scn(var):
    scns = (VAR_SCENARIOS.get(var, []) if var else []) or avail_scn_all or ["Baseline"]
    return [{"label": s, "value": s} for s in scns], scns[0]

@app.callback(Output("micro-scn","options"), Output("micro-scn","value"), Input("micro-var","value"))
def sync_micro_scn(var):
    scns = (VAR_SCENARIOS.get(var, []) if var else []) or avail_scn_all or ["Baseline"]
    return [{"label": s, "value": s} for s in scns], scns[0]

@app.callback(Output("sim-scn","options"), Output("sim-scn","value"), Input("sim-micro-var","value"))
def sync_sim_scn(micro_var):
    macro_sets = [set(VAR_SCENARIOS.get(m, [])) for m in MACROS if m in VAR_SCENARIOS]
    sets = macro_sets + ([set(VAR_SCENARIOS.get(micro_var, []))] if micro_var in VAR_SCENARIOS else [])
    inter = set.intersection(*sets) if sets else set()
    scns = sorted(inter) or (VAR_SCENARIOS.get(micro_var, []) if micro_var in VAR_SCENARIOS else avail_scn_all) or ["Baseline"]
    return [{"label": s, "value": s} for s in scns], scns[0]

# Macro tab
@app.callback(
    Output("macro-graph","figure"),
    Output("macro-warning","children"),
    Output("macro-model-meta","children"),
    Output("macro-rel-card","children"),
    Input("macro-var","value"),
    Input("macro-scn","value"),
    Input("normalize-flag","data")
)
def cb_macro(var, scn, norm_on):
    if not var or var not in DATA: return go.Figure(), "", "", ""
    df_all = DATA[var]
    use_scn = scn if scenario_exists_for_var(var, scn, VAR_SCENARIOS) else (VAR_SCENARIOS.get(var, ["Baseline"])[0])
    fallback_note = "" if use_scn == scn else f"(Using {use_scn}; '{scn}' not available for {var}.) "
    df = df_all[df_all["Scenario"] == use_scn].copy().sort_values("Quarter")

    fig = go.Figure()
    if "Actual" in df.columns and df["Actual"].notna().any():
        yA = to_index_100_safe(df["Actual"]) if norm_on else df["Actual"]
        fig.add_trace(go.Scatter(x=df["Quarter"], y=yA, mode="lines", name="Actual"))

    if df["Forecast"].notna().any():
        yF = to_index_100_safe(df["Forecast"]) if norm_on else df["Forecast"]
        fig.add_trace(go.Scatter(x=df["Quarter"], y=yF, mode="lines",
                                 line=dict(dash="dash", width=2), name=f"Forecast · {use_scn}"))
        add_ci_band(fig, df, norm_on)

    add_hist_forecast_divider(fig, df)
    add_crisis_bands(fig, df)
    # Global historical crisis shading
    add_global_crisis_bands(fig)

    fig.update_xaxes(type="date"); fig.update_layout(title=f"{var} · {use_scn}", xaxis_title="Quarter", hovermode="x unified")

    warn = fallback_note
    thr = THRESHOLDS.get(var)
    if thr is not None and df["Forecast"].notna().any() and not norm_on:
        add_threshold_line(fig, thr, df["Quarter"].min(), df["Quarter"].max())
        add_crisis_markers(fig, df["Quarter"], df["Forecast"], thr)
        m = crisis_mask(df["Forecast"], thr)
        if m.any():
            direction = ">" if thr >= 0 else "<"
            warn += f"⚠️ {var} crosses threshold ({direction} {thr}) at {m.sum()} point(s)."

    note_ident = scenario_identical_note(var, use_scn, DATA)
    if note_ident:
        warn += " " + note_ident

    return fig, warn, model_badge_text(var), relationship_table(var)

# Micro tab
@app.callback(
    Output("micro-graph","figure"),
    Output("micro-model-meta","children"),
    Output("micro-rel-card","children"),
    Input("micro-var","value"),
    Input("micro-scn","value"),
    Input("normalize-flag","data")
)
def cb_micro(var, scn, norm_on):
    if not var or var not in DATA: return go.Figure(), "", ""
    df_all = DATA[var]
    use_scn = scn if scenario_exists_for_var(var, scn, VAR_SCENARIOS) else (VAR_SCENARIOS.get(var, ["Baseline"])[0])
    df = df_all[df_all["Scenario"] == use_scn].copy().sort_values("Quarter")

    fig = go.Figure()
    if "Actual" in df.columns and df["Actual"].notna().any():
        yA = to_index_100_safe(df["Actual"]) if norm_on else df["Actual"]
        fig.add_trace(go.Scatter(x=df["Quarter"], y=yA, mode="lines", name="Actual"))

    if df["Forecast"].notna().any():
        yF = to_index_100_safe(df["Forecast"]) if norm_on else df["Forecast"]
        fig.add_trace(go.Scatter(x=df["Quarter"], y=yF, mode="lines",
                                 line=dict(dash="dash", width=2), name=f"Forecast · {use_scn}"))
        add_ci_band(fig, df, norm_on)

    add_hist_forecast_divider(fig, df)
    add_crisis_bands(fig, df)
    # Global historical crisis shading
    add_global_crisis_bands(fig)

    fig.update_xaxes(type="date"); fig.update_layout(title=f"{var} · {use_scn}", xaxis_title="Quarter", hovermode="x unified")
    return fig, model_badge_text(var), relationship_table(var)

# Simulation
@app.callback(
    Output("sim-pct-readout","children"),
    Output("sim-macro-graph","figure"),
    Output("sim-micro-graph","figure"),
    Input("sim-micro-var","value"),
    Input("sim-scn","value"),
    Input("normalize-flag","data"),
    Input("pct-ccg","value"),
    Input("pct-cpih","value"),
    Input("pct-unemp","value"),
    Input("pct-gdp","value"),
    Input("pct-yield","value"),
)
def cb_sim(micro_var, scn, norm_on, p_ccg, p_cpih, p_unemp, p_gdp, p_yield):
    if not micro_var or not scn or not DATA:
        return "", go.Figure(), go.Figure()

    present_macros = [m for m in MACROS if m in DATA]
    inter_sets = [set(VAR_SCENARIOS.get(m, [])) for m in present_macros] + [set(VAR_SCENARIOS.get(micro_var, []))]
    inter = set.intersection(*inter_sets) if inter_sets else set()
    scn_use = scn if (not inter or scn in inter) else sorted(inter)[0]

    pct_map = {
        "Credit Card Growth": p_ccg or 0,
        "CPIH": p_cpih or 0,
        "Unemployment": p_unemp or 0,
        "GDP": p_gdp or 0,
        "Yield Spread": p_yield or 0,
    }

    base_macros = {var: DATA[var][DATA[var]["Scenario"] == scn_use].copy().sort_values("Quarter")
                   for var in present_macros}
    adj_macros = macro_adjusted_series(DATA, scn_use, pct_map)

    # --- Macro subplots (all macros) ---
    rows_n = len(present_macros) if present_macros else 1
    macro_fig = make_subplots(rows=rows_n, cols=1, shared_xaxes=True,
                              subplot_titles=present_macros, vertical_spacing=0.06)

    for i, var in enumerate(present_macros, start=1):
        dfm_base = base_macros.get(var, pd.DataFrame())
        dfm_adj = adj_macros.get(var, pd.DataFrame())
        if dfm_base.empty:
            continue

        # Actual
        if "Actual" in dfm_base.columns and dfm_base["Actual"].notna().any():
            yA = to_index_100_safe(dfm_base["Actual"]) if norm_on else dfm_base["Actual"]
            macro_fig.add_trace(go.Scatter(x=dfm_base["Quarter"], y=yA, mode="lines", name="Actual",
                                           showlegend=(i == 1)), row=i, col=1)

        # Base forecast
        baseF = dfm_base["Forecast"]
        common_base = baseF[baseF.notna()].iloc[0] if baseF.notna().any() else np.nan
        if baseF.notna().any():
            yF = to_index_100_relative(baseF, common_base) if norm_on else baseF
            macro_fig.add_trace(go.Scatter(x=dfm_base["Quarter"], y=yF, mode="lines",
                                           line=dict(dash="dot", width=2),
                                           name=f"Forecast · {scn_use} (Base)", showlegend=(i == 1)), row=i, col=1)
            add_ci_band(macro_fig, dfm_base, norm_on, row=i, col=1)

        # Adjusted forecast — show ONLY from forecast start onwards
        adjF = dfm_adj.get("Adj Forecast", dfm_adj.get("Forecast", pd.Series(index=dfm_base.index, dtype=float)))
        if adjF is not None and pd.Series(adjF).notna().any() and baseF.notna().any():
            fidx = baseF.first_valid_index()
            if fidx is not None:
                fdate = dfm_base.loc[fidx, "Quarter"]
                adj_mask = dfm_adj["Quarter"] >= fdate

                yAdj_full = to_index_100_relative(adjF, common_base) if norm_on else adjF
                yAdj_ser = pd.Series(yAdj_full, index=dfm_adj.index)
                x_adj = dfm_adj.loc[adj_mask, "Quarter"]
                y_adj = yAdj_ser.loc[adj_mask]

                macro_fig.add_trace(go.Scatter(x=x_adj, y=y_adj, mode="lines",
                                               line=dict(dash="solid", width=2),
                                               name="Adjusted Forecast", showlegend=(i == 1)), row=i, col=1)

                # Threshold markers only in forecast zone
                thr = THRESHOLDS.get(var)
                if thr is not None and not norm_on and ("Adj Forecast" in dfm_adj.columns):
                    add_threshold_line(macro_fig, thr, dfm_adj["Quarter"].min(), dfm_adj["Quarter"].max(), row=i, col=1)
                    add_crisis_markers(macro_fig, x_adj, y_adj, thr, row=i, col=1)

        add_hist_forecast_divider(macro_fig, dfm_base, row=i, col=1)
        add_crisis_bands(macro_fig, dfm_base, row=i, col=1)
        # Global historical crisis shading per subplot
        add_global_crisis_bands(macro_fig, row=i, col=1)

    macro_fig.update_xaxes(type="date")
    macro_fig.update_layout(title=f"All Macros · Simulation ({scn_use})", hovermode="x unified", height=220 * rows_n)

    # --- Micro reacts to macro deltas ---
    df_micro_base = DATA[micro_var][DATA[micro_var]["Scenario"] == scn_use].copy().sort_values("Quarter")
    df_micro_adj  = micro_adjusted_series(DATA, scn_use, micro_var, base_macros, adj_macros)
    micro_fig = go.Figure()

    if not df_micro_base.empty:
        # Actual
        if "Actual" in df_micro_base.columns and df_micro_base["Actual"].notna().any():
            yA = to_index_100_safe(df_micro_base["Actual"]) if norm_on else df_micro_base["Actual"]
            micro_fig.add_trace(go.Scatter(x=df_micro_base["Quarter"], y=yA, mode="lines", name="Actual"))

        # Base forecast
        baseF_mi = df_micro_base["Forecast"]
        common_base_mi = baseF_mi[baseF_mi.notna()].iloc[0] if baseF_mi.notna().any() else np.nan
        if baseF_mi.notna().any():
            yF = to_index_100_relative(baseF_mi, common_base_mi) if norm_on else baseF_mi
            micro_fig.add_trace(go.Scatter(x=df_micro_base["Quarter"], y=yF, mode="lines",
                                           line=dict(dash="dot", width=2), name=f"Forecast · {scn_use} (Base)"))
            add_ci_band(micro_fig, df_micro_base, norm_on)

        # Adjusted forecast — ONLY from forecast start onwards
        adjF_mi = df_micro_adj.get("Adj Forecast", df_micro_adj["Forecast"])
        if pd.Series(adjF_mi).notna().any() and baseF_mi.notna().any():
            fidx_mi = baseF_mi.first_valid_index()
            if fidx_mi is not None:
                fdate_mi = df_micro_base.loc[fidx_mi, "Quarter"]
                adj_mask_mi = df_micro_adj["Quarter"] >= fdate_mi

                yAdj_full_mi = to_index_100_relative(adjF_mi, common_base_mi) if norm_on else adjF_mi
                yAdj_ser_mi = pd.Series(yAdj_full_mi, index=df_micro_adj.index)
                x_adj_mi = df_micro_adj.loc[adj_mask_mi, "Quarter"]
                y_adj_mi = yAdj_ser_mi.loc[adj_mask_mi]

                micro_fig.add_trace(go.Scatter(x=x_adj_mi, y=y_adj_mi, mode="lines",
                                               line=dict(dash="solid", width=2), name="Adjusted Forecast"))

        add_hist_forecast_divider(micro_fig, df_micro_base)
        add_crisis_bands(micro_fig, df_micro_base)
        # Global historical crisis shading
        add_global_crisis_bands(micro_fig)

        micro_fig.update_xaxes(type="date")
        micro_fig.update_layout(title=f"{micro_var} · Simulation impact", xaxis_title="Quarter", hovermode="x unified")

    rd = (f"Applied % changes → "
          f"Credit Card Growth: {pct_map['Credit Card Growth']}%, "
          f"CPIH: {pct_map['CPIH']}%, "
          f"Unemployment: {pct_map['Unemployment']}%, "
          f"GDP: {pct_map['GDP']}%, "
          f"Yield Spread: {pct_map['Yield Spread']}%.")

    return rd, macro_fig, micro_fig

# =========================
# ====== MAIN (Render) ====
# =========================

if __name__ == "__main__":
    # Render provides $PORT; default to 8050 locally
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8050)), debug=False, use_reloader=False)
