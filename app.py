# UK ECONOMIC CRISIS SIMULATOR — Normalise removed (always OFF)
# Run: python app.py  → open http://127.0.0.1:8050

import os, re
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd
from pandas.api.types import is_period_dtype, is_datetime64_any_dtype

import plotly.graph_objs as go
from plotly.subplots import make_subplots

from dash import Dash, dcc, html, Input, Output, State, callback_context
import dash
try:
    import dash_bootstrap_components as dbc
    USE_DBC = True
except Exception:
    USE_DBC = False

try:
    from dash import dash_table
except Exception:
    import dash_table

# =========================
# ====== CONFIG ===========
# =========================

HERE = Path.cwd()
CANDIDATES = [
    HERE / "Scenario_Forecasts_NEW.xlsx",
    HERE / "data" / "Scenario_Forecasts_NEW.xlsx",
    Path("C:/Users/user/Yashashree_PC/STFECP/Scenario_Forecasts_NEW.xlsx"),
    Path(os.environ.get("SCENARIO_XLSX", "")),
]
FILE_PATH = next((p for p in CANDIDATES if p and p.is_file()), None)

SHEET_TO_NAME = {
    "Credit_Card_Growth": "Credit Card Growth",
    "Unemployment_rate_aged_16_and_o": "Unemployment",
    "CPIH_ANNUAL_RATE_00_ALL_ITEMS_2": "CPIH",
    "Gross_Domestic_Product_Quarter_": "GDP",
    "10Y_2Y_Spread": "Yield Spread",
    "RSI_Predominantly_food_stores": "RSI: Predominantly food stores",
    "RSI_clothing_footwear": "RSI: Clothing & Footwear",
    "RSI_Household_goods_stores": "RSI: Household goods",
    "Non_store_Retailing": "Non-store Retailing",
    "RSI_electrical_household_applia": "RSI: Electrical household appliances",
    "RSI_watches_and_jewellery_": "RSI: Watches & Jewellery",
}

MACROS = ["Credit Card Growth", "CPIH", "Unemployment", "GDP", "Yield Spread"]
MICROS = [
    "RSI: Predominantly food stores", "RSI: Clothing & Footwear",
    "RSI: Household goods", "Non-store Retailing",
    "RSI: Electrical household appliances", "RSI: Watches & Jewellery",
]

MODEL_META: Dict[str, List[Dict]] = {
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
    "CPIH": [{"driver": "Credit Card Growth", "coef": 0.067, "p": 0.006, "sig": True}],
    "RSI: Predominantly food stores": [{"driver": "Credit Card Growth", "coef": -0.170, "p": 0.000, "sig": True}],
    "RSI: Clothing & Footwear": [
        {"driver": "GDP", "coef": 1.282, "p": 0.000, "sig": True},
        {"driver": "Credit Card Growth", "coef": 1.168, "p": 0.000, "sig": True},
    ],
    "RSI: Household goods": [{"driver": "GDP", "coef": 1.162, "p": 0.000, "sig": True}],
    "Non-store Retailing": [
        {"driver": "Credit Card Growth", "coef": -0.859, "p": 0.000, "sig": True},
        {"driver": "GDP", "coef": -0.241, "p": 0.000, "sig": True},
    ],
    "RSI: Electrical household appliances": [{"driver": "GDP", "coef": 0.585, "p": 0.000, "sig": True}],
    "RSI: Watches & Jewellery": [
        {"driver": "GDP", "coef": 1.474, "p": 0.000, "sig": True},
        {"driver": "Credit Card Growth", "coef": 1.046, "p": 0.000, "sig": True},
    ],
}

# =========================
# ====== HELPERS ==========
# =========================

def detect_time_col(df: pd.DataFrame) -> str:
    for c in df.columns:
        if str(c).strip().lower() in ("date", "quarter", "unnamed: 0", "time", "period"):
            return c
    for c in df.columns:
        try:
            pd.to_datetime(df[c], errors="raise"); return c
        except Exception:
            continue
    return df.columns[0]

def _qindex(dates) -> pd.PeriodIndex:
    if isinstance(dates, pd.PeriodIndex):
        try: return dates.asfreq("Q")
        except Exception: return dates
    if isinstance(dates, pd.DatetimeIndex):
        return dates.to_period("Q")
    if isinstance(dates, pd.Series):
        if is_period_dtype(dates.dtype): return pd.PeriodIndex(dates.astype("period[Q]"))
        if is_datetime64_any_dtype(dates.dtype): return pd.DatetimeIndex(dates).to_period("Q")
        dt = pd.to_datetime(dates, errors="coerce"); return pd.DatetimeIndex(dt).to_period("Q")
    try: return pd.PeriodIndex(dates, freq="Q")
    except Exception:
        dt = pd.to_datetime(dates, errors="coerce"); return pd.DatetimeIndex(dt).to_period("Q")

def read_all_sheets(file_path: str) -> Dict[str, pd.DataFrame]:
    xls = pd.ExcelFile(file_path)
    out = {}
    CANON_SCN = {"baseline":"Baseline","recession":"Recession","recovery":"Recovery","crisis":"Crisis"}

    def find_forecast_scenarios(df):
        pairs=[]
        for col in df.columns:
            m=re.match(r'(?i)^forecast[_\s]*(.+)$', str(col).strip())
            if m: pairs.append((m.group(1).strip(), col))
        return pairs

    def find_ci_cols(df, scenario):
        lower, upper=None, None
        sl=scenario.lower()
        toks={sl, sl.replace(" ","_"), sl.replace("_"," "), sl.title(), sl.capitalize()}
        for col in df.columns:
            cl=str(col).lower()
            if "lower" in cl and any(t in cl for t in toks): lower=col
            if "upper" in cl and any(t in cl for t in toks): upper=col
        return lower, upper

    for sheet in xls.sheet_names:
        if sheet not in SHEET_TO_NAME: continue
        nice = SHEET_TO_NAME[sheet]
        df = pd.read_excel(file_path, sheet_name=sheet)
        df.columns = df.columns.astype(str).str.strip()
        tcol = detect_time_col(df)
        df = df.rename(columns={tcol:"Quarter"})
        df["Quarter"] = pd.to_datetime(df["Quarter"], errors="coerce")

        scn_pairs = find_forecast_scenarios(df)
        crisis_cols = [c for c in df.columns if str(c).startswith("Crisis_")]
        actual_exists = "Actual" in df.columns
        frames=[]
        if scn_pairs:
            for scn_raw, fcol in scn_pairs:
                key=scn_raw.lower().replace(" ","").replace("_","")
                scn_name = CANON_SCN.get(key, scn_raw.replace("_"," ").title())
                keep = ["Quarter", fcol] + (["Actual"] if actual_exists else []) + crisis_cols
                tmp = df[keep].copy().rename(columns={fcol:"Forecast"}); tmp["Scenario"] = scn_name
                lcol, ucol = find_ci_cols(df, scn_raw)
                if lcol and ucol and lcol in df.columns and ucol in df.columns:
                    tmp["Lower CI"]=df[lcol].values; tmp["Upper CI"]=df[ucol].values
                frames.append(tmp)
        else:
            if "Forecast" not in df.columns: continue
            tmp = df[["Quarter","Forecast"] + (["Actual"] if actual_exists else []) + crisis_cols].copy()
            tmp["Scenario"]="Baseline"; frames.append(tmp)

        long = pd.concat(frames, ignore_index=True)
        cols=["Quarter","Scenario"] + (["Actual"] if actual_exists else []) + ["Forecast"]
        if "Lower CI" in long.columns and "Upper CI" in long.columns: cols+=["Lower CI","Upper CI"]
        cols += crisis_cols
        out[nice] = long[cols].sort_values(["Scenario","Quarter"]).reset_index(drop=True)
    return out

def to_index_100_safe(y: pd.Series) -> pd.Series:
    y=pd.Series(y).dropna().astype(float)
    if y.empty: return y
    base=y.iloc[0]
    return (y/base*100) if pd.notna(base) and base!=0 else y

def to_index_100_relative(y: pd.Series, base_value: float) -> pd.Series:
    y=pd.Series(y).astype(float)
    if pd.isna(base_value) or base_value==0: return y
    return (y/base_value)*100.0

def add_hist_forecast_divider(fig: go.Figure, df: pd.DataFrame, row=None, col=None):
    if "Actual" in df.columns and df["Actual"].notna().any() and df["Forecast"].notna().any():
        idx=df["Forecast"].first_valid_index()
        if idx is not None:
            x0=df.loc[idx,"Quarter"]
            if row and col: fig.add_vline(x=x0, line_dash="dot", line_width=1, row=row, col=col)
            else: fig.add_vline(x=x0, line_dash="dot", line_width=1)

def add_ci_band(fig: go.Figure, df: pd.DataFrame, norm_on: bool, row=None, col=None):
    if {"Upper CI", "Lower CI"}.issubset(df.columns):
        up = pd.to_numeric(df["Upper CI"], errors="coerce")
        lo = pd.to_numeric(df["Lower CI"], errors="coerce")
        if up.notna().any() and lo.notna().any():
            if norm_on:
                f = pd.to_numeric(df["Forecast"], errors="coerce").dropna()
                base0 = f.iloc[0] if len(f) else np.nan
                if pd.notna(base0) and base0 != 0:
                    up = to_index_100_relative(up, base0)
                    lo = to_index_100_relative(lo, base0)
            t_up = go.Scatter(x=df["Quarter"], y=up, mode="lines", line=dict(width=0),
                              showlegend=False, hoverinfo="skip")
            t_lo = go.Scatter(x=df["Quarter"], y=lo, mode="lines", line=dict(width=0),
                              fill="tonexty", fillcolor="rgba(0,0,0,0.12)",
                              showlegend=False, hoverinfo="skip")
            if row and col:
                fig.add_trace(t_up, row=row, col=1); fig.add_trace(t_lo, row=row, col=1)
            else:
                fig.add_trace(t_up); fig.add_trace(t_lo)

# ======= Crisis shading & legend — exact color match =======
def hex_to_rgba(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip('#'); r = int(hex_color[0:2],16); g = int(hex_color[2:4],16); b=int(hex_color[4:6],16)
    return f"rgba({r},{g},{b},{alpha})"

CRISIS_PERIODS = [
    {"x0":"2008-01-01","x1":"2009-12-31","hex":"#ff0000", "name":"2008–09 crisis"},
    {"x0":"2020-03-01","x1":"2021-03-31","hex":"#800080", "name":"2020–21 COVID-19"},
    {"x0":"2022-01-01","x1":"2023-12-31","hex":"#ff8c00", "name":"2022–23 recession"},
]

def add_global_crisis_bands(fig: go.Figure, row=None, col=None, alpha=0.35):
    for p in CRISIS_PERIODS:
        fill = hex_to_rgba(p["hex"], alpha)
        if row and col:
            fig.add_vrect(x0=p["x0"], x1=p["x1"], fillcolor=fill, opacity=1.0, line_width=0, row=row, col=col)
        else:
            fig.add_vrect(x0=p["x0"], x1=p["x1"], fillcolor=fill, opacity=1.0, line_width=0)

def add_crisis_legend(fig: go.Figure):
    for p in CRISIS_PERIODS:
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines",
                                 line=dict(color=p["hex"], width=8),
                                 name=p["name"], hoverinfo="skip", showlegend=True, legendgroup="crisis"))

# ======= Consistent bordered-plot styling =======
def apply_bordered_style(fig: go.Figure):
    fig.update_layout(paper_bgcolor="#ffffff", plot_bgcolor="#ffffff")
    fig.update_xaxes(showline=True, linewidth=1, linecolor="#bdbdbd", mirror=True, zeroline=False)
    fig.update_yaxes(showline=True, linewidth=1, linecolor="#bdbdbd", mirror=True, zeroline=False)
    return fig

# ---------- Thresholds / classification ----------
def _baseline_df(data: Dict[str,pd.DataFrame], var: str, scn="Baseline") -> pd.DataFrame:
    if var not in data: return pd.DataFrame()
    df=data[var]
    if scn not in df["Scenario"].unique(): scn="Baseline"
    return df[df["Scenario"]==scn].copy().sort_values("Quarter")

def _hist_series_for_bands(df: pd.DataFrame) -> pd.Series:
    if "Actual" in df.columns and df["Actual"].notna().any():
        s=pd.to_numeric(df["Actual"], errors="coerce")
    else:
        s=pd.to_numeric(df["Forecast"], errors="coerce")
    s.index=_qindex(df["Quarter"])
    return s.dropna()

def calibrate_bands_simple(data: Dict[str,pd.DataFrame], var: str, mode="Balanced") -> Dict[str,float]:
    q_map={"Early":0.80, "Balanced":0.85, "Conservative":0.95}
    q=q_map.get(mode,0.85); q_amb=max(0.55, q-0.05)
    df=_baseline_df(data,var,"Baseline")
    if df.empty: return {}
    s=_hist_series_for_bands(df)
    if s.empty: return {}
    if var=="GDP":
        red=float(np.nanpercentile(s,(1-q)*100))
        amber=float(np.nanpercentile(s,(1-q_amb)*100))
        return {"direction":"lower","red":red,"amber":amber}
    else:
        red=float(np.nanpercentile(s,q*100))
        amber=float(np.nanpercentile(s,q_amb*100))
        return {"direction":"upper","red":red,"amber":amber}

def classify_point(value: float, bands: Dict[str,float]) -> str:
    if not bands or value is None or np.isnan(value): return "Unknown"
    if bands.get("direction")=="lower":
        if value<=bands["red"]: return "Red"
        if value<=bands["amber"]: return "Amber"
        return "Green"
    else:
        if value>=bands["red"]: return "Red"
        if value>=bands["amber"]: return "Amber"
        return "Green"

def color_for_state_bg(state: str) -> str:
    return {"Green":"#e6f4ea","Amber":"#fff59d","Red":"#ffcccc","Unknown":"#f0f0f0"}.get(state, "#f0f0f0")

def latest_value(df: pd.DataFrame, prefer_actual=True) -> Optional[float]:
    if prefer_actual and "Actual" in df.columns and df["Actual"].notna().any():
        return float(pd.to_numeric(df["Actual"], errors="coerce").dropna().iloc[-1])
    if df["Forecast"].notna().any():
        return float(pd.to_numeric(df["Forecast"], errors="coerce").dropna().iloc[-1])
    return None

# ---------- People impact helpers ----------
def yield_spread_logistic_prob(DATA: Dict[str,pd.DataFrame]) -> Optional[float]:
    try:
        from sklearn.linear_model import LogisticRegression
    except Exception:
        return None
    if "Yield Spread" not in DATA: return None
    df=DATA["Yield Spread"].copy().sort_values("Quarter")
    crisis_cols=[c for c in df.columns if str(c).startswith("Crisis_")]
    if not crisis_cols: return None
    y = (df[crisis_cols].apply(pd.to_numeric, errors="coerce").sum(axis=1) > 0).astype(int)
    x = df["Actual"] if "Actual" in df and df["Actual"].notna().any() else df["Forecast"]
    x = pd.to_numeric(x, errors="coerce")
    X = pd.DataFrame({"x":x}).shift(4).dropna()
    Y = y.loc[X.index]
    if Y.nunique()<2 or len(X)<20: return None
    try:
        lr=LogisticRegression(); lr.fit(X, Y)
        p=float(lr.predict_proba([[X.iloc[-1,0]]])[0,1])
        return p
    except Exception:
        return None

def people_impact_panel(DATA: Dict[str,pd.DataFrame], mode: str) -> Dict[str, str]:
    cpi_df=_baseline_df(DATA,"CPIH"); cpi = latest_value(cpi_df)
    basket_month = 2200
    monthly_cost = None if cpi is None else basket_month * (cpi/100.0)

    un_df=_baseline_df(DATA,"Unemployment"); un = latest_value(un_df)
    gdp_df=_baseline_df(DATA,"GDP")
    gvals = pd.to_numeric(gdp_df["Actual"] if "Actual" in gdp_df and gdp_df["Actual"].notna().any() else gdp_df["Forecast"], errors="coerce").dropna()
    g_mom = None if len(gvals)<3 else float(gvals.iloc[-1]-gvals.iloc[-3])

    cc_df=_baseline_df(DATA,"Credit Card Growth"); cc=latest_value(cc_df, prefer_actual=False)
    ys_df=_baseline_df(DATA,"Yield Spread"); ys=latest_value(ys_df)
    credit_stress="Normal"
    if cc is not None and ys is not None:
        if cc>=20 or ys<0: credit_stress="Elevated"
        if cc>=30 and ys< -0.2: credit_stress="High"

    p = yield_spread_logistic_prob(DATA)
    p_txt = "—" if p is None else f"{p*100:.0f}%"

    job_heat = "Moderate"
    if (un is not None and un >= 7) or (g_mom is not None and g_mom < -1):
        job_heat = "Hot (Tight market risk)"
    elif (un is not None and un <= 4) and (g_mom is not None and g_mom > 0.5):
        job_heat = "Cool (Improving)"

    para=[]
    if cpi is not None: para.append(f"Prices rising ~{cpi:.1f}%, ~£{monthly_cost:,.0f}/mo extra.")
    if un is not None: para.append(f"Unemployment ~{un:.1f}%.")
    if g_mom is not None: para.append("Growth " + ("weaker" if g_mom<0 else "firmer") + " lately.")
    if credit_stress!="Normal": para.append(f"Borrowing {credit_stress.lower()}.")
    if p is not None: para.append(f"Curve signal puts downturn odds ~{p_txt}.")
    story=" ".join(para) if para else "We’ll summarise conditions here as data loads."

    return {
        "cpi": "—" if cpi is None else f"{cpi:.1f}%",
        "un": "—" if un is None else f"{un:.1f}%",
        "gdp_mom": "—" if g_mom is None else f"{g_mom:+.2f} pts",
        "prob": p_txt,
        "monthly_cost": "—" if monthly_cost is None else f"£{monthly_cost:,.0f}/mo",
        "job_heat": job_heat,
        "credit": credit_stress,
        "story": story
    }

def _parse_driver(name: str) -> Tuple[str, int]:
    if "_lag" in name:
        base, lag = name.split("_lag")
        try: return base, int(lag)
        except: return base, 0
    return name, 0

def align_by_quarter(s: pd.Series, target_dates, lag: int = 0) -> pd.Series:
    if isinstance(s.index, pd.PeriodIndex):
        s_q=s.copy()
        try: s_q.index=s_q.index.asfreq("Q")
        except Exception: pass
    elif isinstance(s.index, pd.DatetimeIndex):
        s_q=s.copy(); s_q.index=s_q.index.to_period("Q")
    else:
        s_q=pd.Series(s.values, index=_qindex(s.index))
    s_q=s_q.sort_index()
    if lag>0: s_q=s_q.shift(lag)
    tgt_q=target_dates if isinstance(target_dates,pd.PeriodIndex) else _qindex(target_dates)
    try: tgt_q=tgt_q.asfreq("Q")
    except Exception: pass
    out=s_q.reindex(tgt_q)
    return out.ffill().bfill()

def macro_adjusted_series(DATA: Dict[str, pd.DataFrame], scn: str, pct_map: Dict[str, float]) -> Dict[str, pd.DataFrame]:
    present_macros=[m for m in MACROS if m in DATA]
    base={}
    for var in present_macros:
        dfb=DATA[var][DATA[var]["Scenario"]==scn].copy().sort_values("Quarter")
        s=pd.Series(dfb["Forecast"].values, index=_qindex(dfb["Quarter"]))
        base[var]=(dfb,s)
    forced={}
    for var in present_macros:
        _,s_base=base[var]; pct=(pct_map.get(var,0.0) or 0.0)/100.0
        forced[var]=s_base*(1.0+pct)
    adj={var:forced[var].copy() for var in present_macros}
    MAX_ITERS,TOL=12,1e-6
    for _ in range(MAX_ITERS):
        maxdiff=0.0; new_adj={}
        for var in present_macros:
            s_target=forced[var].copy(); tgt_q=s_target.index
            for d in MODEL_META.get(var,[]):
                drv_name, lag = _parse_driver(d["driver"])
                if drv_name not in base or drv_name not in adj: continue
                _, s_bdrv = base[drv_name]; s_adrv = adj[drv_name]
                s_b = align_by_quarter(s_bdrv, tgt_q, lag); s_a = align_by_quarter(s_adrv, tgt_q, lag)
                delta=(s_a-s_b).fillna(0.0)
                s_target=s_target.add(float(d["coef"])*delta, fill_value=0.0)
            new_adj[var]=s_target
            prev=adj[var].reindex(s_target.index)
            diff=(s_target-prev).abs().max(skipna=True)
            if pd.notna(diff) and float(diff)>maxdiff: maxdiff=float(diff)
        adj=new_adj
        if not np.isfinite(maxdiff) or maxdiff<TOL: break
    out={}
    for var in present_macros:
        dfb,_=base[var]; tgt_q=_qindex(dfb["Quarter"]); s_adj=adj[var].reindex(tgt_q).astype(float)
        df_out=dfb.copy(); df_out["Adj Forecast"]=s_adj.values; out[var]=df_out
    return out

def micro_adjusted_series(DATA: Dict[str,pd.DataFrame], scn: str, adj_macros: Dict[str,pd.DataFrame]) -> Dict[str,pd.DataFrame]:
    out={}
    for var in [m for m in MICROS if m in DATA]:
        df_micro = DATA[var][DATA[var]["Scenario"]==scn].copy().sort_values("Quarter")
        if df_micro.empty: continue
        tgt_q = _qindex(df_micro["Quarter"])

        baseF = pd.to_numeric(df_micro["Forecast"], errors="coerce")
        adjF = baseF.copy()

        for d in MODEL_META.get(var, []):
            drv_name, lag = _parse_driver(d["driver"])
            if drv_name not in DATA or drv_name not in adj_macros:
                continue

            df_bdrv = DATA[drv_name][DATA[drv_name]["Scenario"]==scn].copy().sort_values("Quarter")
            s_b = pd.to_numeric(df_bdrv["Forecast"], errors="coerce"); s_b.index = _qindex(df_bdrv["Quarter"])
            df_adrv = adj_macros[drv_name].copy().sort_values("Quarter")
            s_a = pd.to_numeric(df_adrv.get("Adj Forecast", df_adrv["Forecast"]), errors="coerce"); s_a.index = _qindex(df_adrv["Quarter"])

            delta = align_by_quarter(s_a, tgt_q, lag) - align_by_quarter(s_b, tgt_q, lag)
            adjF = adjF.add(float(d["coef"]) * delta.values, fill_value=0.0)

        df_out = df_micro.copy()
        df_out["Adj Forecast"] = adjF.values
        out[var] = df_out
    return out

def tidy_var_scenarios(data: Dict[str,pd.DataFrame])->Dict[str,List[str]]:
    return {var:sorted([s for s in df["Scenario"].dropna().unique().tolist()]) for var,df in data.items()}

def scenario_exists_for_var(var: str, scn: str, var_scenarios: Dict[str,List[str]])->bool:
    return scn in (var_scenarios.get(var) or [])

# ======= Overall crisis prob (from adjusted macros) & contributions =======
def _ecdf_prob(s: pd.Series, v: float) -> Optional[float]:
    arr = np.sort(pd.to_numeric(s, errors="coerce").dropna().values)
    if len(arr)==0 or v is None or not np.isfinite(v): return None
    F = np.searchsorted(arr, v, side="right") / len(arr)
    return float(F)

def overall_crisis_prob_from_adj(DATA: Dict[str,pd.DataFrame], adj_macros: Dict[str,pd.DataFrame], mode: str) -> Optional[float]:
    if not adj_macros: return None
    w_base = {"GDP":0.28, "Unemployment":0.28, "CPIH":0.20, "Yield Spread":0.18, "Credit Card Growth":0.06}
    gamma_map = {"Early":0.85, "Balanced":1.0, "Conservative":1.25}
    gamma = gamma_map.get(mode, 1.0)

    ps, ws = [], []
    for var in MACROS:
        if var not in DATA: continue
        df_hist = _baseline_df(DATA, var, "Baseline")
        if df_hist.empty: continue
        s_hist = _hist_series_for_bands(df_hist)
        v = None
        if var in adj_macros and "Adj Forecast" in adj_macros[var]:
            v = pd.to_numeric(adj_macros[var]["Adj Forecast"], errors="coerce").dropna()
            v = float(v.iloc[-1]) if len(v) else None
        if v is None:
            dfb = DATA[var][DATA[var]["Scenario"]=="Baseline"].copy().sort_values("Quarter")
            v = latest_value(dfb, prefer_actual=False)
        F = _ecdf_prob(s_hist, v)
        if F is None: continue
        direction = calibrate_bands_simple(DATA, var, mode).get("direction","upper")
        p_i = F if direction=="upper" else (1.0 - F)
        p_i = min(max(p_i, 0.0), 1.0) ** gamma
        ws.append(w_base.get(var, 0.1)); ps.append(p_i)

    if not ps: return None
    ws = np.array(ws, dtype=float); ws = ws / ws.sum()
    ps = np.array(ps, dtype=float)
    prod = np.prod(1.0 - ws * ps)
    P = 1.0 - prod
    return float(min(max(P, 0.0), 1.0))

def contribution_shares(DATA: Dict[str,pd.DataFrame], adj_macros: Dict[str,pd.DataFrame], mode: str) -> Dict[str,float]:
    """Return % contribution shares by macro using base weights × current risk intensity."""
    w_base = {"GDP":0.28, "Unemployment":0.28, "CPIH":0.20, "Yield Spread":0.18, "Credit Card Growth":0.06}
    gamma_map = {"Early":0.85, "Balanced":1.0, "Conservative":1.25}
    gamma = gamma_map.get(mode, 1.0)

    scores = {}
    for var in MACROS:
        if var not in DATA: continue
        df_hist = _baseline_df(DATA, var, "Baseline")
        if df_hist.empty: continue
        s_hist = _hist_series_for_bands(df_hist)

        # current adjusted value
        v = None
        if var in adj_macros and "Adj Forecast" in adj_macros[var]:
            vser = pd.to_numeric(adj_macros[var]["Adj Forecast"], errors="coerce").dropna()
            v = float(vser.iloc[-1]) if len(vser) else None
        if v is None:
            dfb = DATA[var][DATA[var]["Scenario"]=="Baseline"].copy().sort_values("Quarter")
            v = latest_value(dfb, prefer_actual=False)

        F = _ecdf_prob(s_hist, v)
        if F is None: 
            continue
        direction = calibrate_bands_simple(DATA, var, mode).get("direction","upper")
        intensity = F if direction == "upper" else (1.0 - F)         # 0..1 badness percentile
        intensity = min(max(intensity,0.0),1.0) ** gamma

        scores[var] = w_base.get(var, 0.1) * float(intensity)

    if not scores:
        return {}
    total = sum(scores.values())
    if total <= 0:
        return {k: 0.0 for k in scores}
    return {k: 100.0 * v / total for k, v in scores.items()}

# =========================
# ====== LOAD DATA ========
# =========================

if FILE_PATH is None:
    DATA={}
    LOAD_ERROR="Dataset not found. Place 'Scenario_Forecasts_NEW.xlsx' in the working folder, a 'data/' folder, or set SCENARIO_XLSX."
else:
    DATA=read_all_sheets(str(FILE_PATH))
    LOAD_ERROR=""

VAR_SCENARIOS=tidy_var_scenarios(DATA)
macro_opts=[{"label":m,"value":m} for m in MACROS if m in DATA]
micro_opts=[{"label":m,"value":m} for m in MICROS if m in DATA]
avail_scn_all=sorted(set(sum([DATA[k]["Scenario"].dropna().unique().tolist() for k in DATA], []))) if DATA else []
scenario_opts_global=[{"label":s,"value":s} for s in (avail_scn_all or ["Baseline"])]

# =========================
# ====== UI / LAYOUT ======
# =========================

external_stylesheets = [dbc.themes.LUX] if USE_DBC else []
app = Dash(__name__, external_stylesheets=external_stylesheets)
app.title = "UK Economic Crisis Simulator"

# --- green sliders CSS scoped to #sim-sliders ---
app.index_string = """
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            /* Scope to the simulation slider container */
            #sim-sliders .rc-slider-track { background-color: #2e7d32 !important; }
            #sim-sliders .rc-slider-handle { border-color: #2e7d32 !important; }
            #sim-sliders .rc-slider-dot-active { border-color: #2e7d32 !important; }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
"""

# ---- small wrappers so we never pass width= to html.Div ----
def Row(children=None, **kwargs):
    return dbc.Row(children, **kwargs) if USE_DBC else html.Div(children, **kwargs)

def Col(children=None, width=None, **kwargs):
    if USE_DBC:
        return dbc.Col(children, width=width, **kwargs)
    # approximate column width with style when not using dbc
    style = kwargs.pop("style", {})
    if width:
        pct = int(round(width/12*100))
        style = {**style, "flex": f"0 0 {pct}%", "maxWidth": f"{pct}%"}
    return html.Div(children, style=style, **kwargs)

def Card(children=None, **kwargs):
    return dbc.Card(dbc.CardBody(children), **kwargs) if USE_DBC else html.Div(children, style={"padding":"10px","background":"#fff","border":"1px solid #eee","borderRadius":"10px","boxShadow":"0 1px 5px rgba(0,0,0,0.05)"})

def kpi_card(title, value, sub=None, color="primary"):
    if USE_DBC:
        return dbc.Card(
            dbc.CardBody([
                html.Div(title, className="text-muted"),
                html.H3(value, className=f"text-{color}"),
                html.Div(sub or "", style={"fontSize":"12px","opacity":0.8})
            ]), className="shadow-sm"
        )
    return html.Div([
        html.Div(title, style={"color":"#6c757d"}), html.H3(value, style={"color":"#0d6efd"}),
        html.Div(sub or "", style={"fontSize":"12px","opacity":0.8})
    ], style={"border":"1px solid #eee","padding":"12px","borderRadius":"10px","boxShadow":"0 1px 5px rgba(0,0,0,0.05)","background":"#fff"})

def info_badge(text, bgcolor):
    style={"display":"inline-block","padding":"4px 10px","borderRadius":"999px","background":bgcolor,"border":"1px solid #ddd","fontSize":"12px","marginRight":"6px","marginBottom":"6px"}
    return html.Span(text, style=style)

def scenario_preset_buttons():
    if not USE_DBC:
        return html.Div([
            html.Button("Recession", id="preset-recession"),
            html.Button("Recovery", id="preset-recovery", style={"marginLeft": "8px"}),
            html.Button("Persistent inflation", id="preset-infl", style={"marginLeft": "8px"}),
        ], style={"marginBottom": "8px"})
    return html.Div([
        dbc.Button("Recession", id="preset-recession", color="danger", outline=True, className="me-2"),
        dbc.Button("Recovery", id="preset-recovery", color="success", outline=True, className="me-2"),
        dbc.Button("Persistent inflation", id="preset-infl", color="warning", outline=True),
    ])

top_banner = (dbc.Alert(LOAD_ERROR, color="danger", className="mb-2") if USE_DBC else
              html.Div(LOAD_ERROR, style={"background":"#ffecec","border":"1px solid #ffb3b3","padding":"8px 12px","borderRadius":"8px","color":"#b30000","marginBottom":"10px"})) if LOAD_ERROR else None

# ---- Controls (ONLY risk sensitivity now) ----
controls_block = Card([
    html.Div([
        html.Label("Risk sensitivity"),
        dcc.RadioItems(
            id="risk-mode",
            options=[
                {"label":" Early (more alerts)  q≈0.80","value":"Early"},
                {"label":" Balanced  q≈0.85","value":"Balanced"},
                {"label":" Conservative (fewer alerts)  q≈0.95","value":"Conservative"},
            ],
            value="Balanced", inline=False
        )
    ]),
], className="shadow-sm")

# --- Tabs layout ---
TABS = dcc.Tabs(
    id="tabs", value="tab-people",
    children=[
        dcc.Tab(label="People Impact", value="tab-people", children=[
            Row([
                Col(id="kpi-prob", width=3),
                Col(id="kpi-cpi",  width=3),
                Col(id="kpi-un",   width=3),
                Col(id="kpi-gdp",  width=3),
            ], className="g-3 my-1"),
            html.Div([dcc.Graph(id="people-donut")], style={"maxWidth":"720px","margin":"0 auto"}),
            Row([
                Col([html.H5("Current Situation"), html.Div(id="people-cards")], width=6),
                Col([
                    html.H5("overview"),
                    Card([html.Div(id="people-story", style={"fontSize": "14px"})], className="shadow-sm"),
                ], width=6),
            ], className="g-3 my-1"),
        ]),

        dcc.Tab(label="Indicators", value="tab-ind", children=[
            html.H5("Macroeconomic"),
            Row([
                Col([
                    html.Label("Variable"),
                    dcc.Dropdown(id="macro-var", options=macro_opts, value=macro_opts[0]["value"] if macro_opts else None)
                ], width=4),
                Col([
                    html.Label("Scenario"),
                    dcc.Dropdown(id="macro-scn", options=scenario_opts_global, value=scenario_opts_global[0]["value"])
                ], width=3),
            ], className="g-2"),
            dcc.Graph(id="macro-graph"),
            html.Div(id="macro-risk-chip"),
            html.Hr(),
            html.H5("Microeconomic (RSI)"),
            Row([
                Col([
                    html.Label("Variable"),
                    dcc.Dropdown(id="micro-var", options=micro_opts, value=micro_opts[0]["value"] if micro_opts else None)
                ], width=6),
                Col([
                    html.Label("Scenario"),
                    dcc.Dropdown(id="micro-scn", options=scenario_opts_global, value=scenario_opts_global[0]["value"])
                ], width=3),
            ], className="g-2"),
            dcc.Graph(id="micro-graph"),
        ]),

        dcc.Tab(label="Simulation", value="tab-sim", children=[
            scenario_preset_buttons(),
            html.Div(id="sim-overall-prob", className="my-2"),
            # Donut FIRST, centered & large
            html.Div(
                dcc.Graph(id="sim-donut"),
                style={"maxWidth":"740px","margin":"0 auto"}
            ),
            html.Div(id="sim-analyst-line", className="my-2", style={"fontWeight":"500"}),

            Row([
                Col([
                    html.Label("View Micro (RSI)"),
                    dcc.Dropdown(id="sim-micro-var", options=micro_opts, value=micro_opts[0]["value"] if micro_opts else None)
                ], width=6),
                Col([
                    html.Label("Scenario"),
                    dcc.Dropdown(id="sim-scn", options=scenario_opts_global, value=scenario_opts_global[0]["value"])
                ], width=3),
            ], className="g-2"),

            html.Div(id="sim-sliders", children=[
                Row([
                    Col([html.Label("Δ Credit Card Growth (%)"),
                        dcc.Slider(id="pct-ccg", min=-50, max=50, step=1, value=0,
                                   marks={-50:"-50", -25:"-25", 0:"0", 25:"25", 50:"+50"})], width=6),
                    Col([html.Label("Δ CPIH (%)"),
                        dcc.Slider(id="pct-cpih", min=-50, max=50, step=1, value=0,
                                   marks={-50:"-50", -25:"-25", 0:"0", 25:"25", 50:"+50"})], width=6),
                ], className="g-2"),
                Row([
                    Col([html.Label("Δ Unemployment (%)"),
                        dcc.Slider(id="pct-unemp", min=-50, max=50, step=1, value=0,
                                   marks={-50:"-50", -25:"-25", 0:"0", 25:"25", 50:"+50"})], width=6),
                    Col([html.Label("Δ GDP (%)"),
                        dcc.Slider(id="pct-gdp", min=-50, max=50, step=1, value=0,
                                   marks={-50:"-50", -25:"-25", 0:"0", 25:"25", 50:"+50"})], width=6),
                ], className="g-2"),
                Row([
                    Col([html.Label("Δ Yield Spread (%)"),
                        dcc.Slider(id="pct-yield", min=-50, max=50, step=1, value=0,
                                   marks={-50:"-50", -25:"-25", 0:"0", 25:"25", 50:"+50"})], width=6),
                ], className="g-2"),
            ]),

            html.Div(id="sim-pct-readout", className="mt-1 text-muted"),
            dcc.Graph(id="sim-macro-graph"),
            dcc.Graph(id="sim-micro-graph"),
            html.Div(id="sim-risk-chips", className="mt-2"),
            html.Hr(),
            html.H5("Simulation Summary"),
            html.H6("Current values"),
            dash_table.DataTable(
                id="sim-table",
                columns=[], data=[],
                style_table={"overflowX": "auto"},
                style_cell={"padding":"8px","border":"1px solid #eee"},
                style_header={"backgroundColor":"#f3f4f6","fontWeight":"bold"}
            ),
        ]),

        dcc.Tab(label="Risk Overview", value="tab-risk", children=[
            dcc.Graph(id="risk-counts"),
            dcc.Graph(id="risk-table-simple"),
        ]),
    ],
)

# ===== Layout: Store set to False so normalisation is OFF forever =====
app.layout = (dbc.Container if USE_DBC else html.Div)([
    html.Div([ html.H2("UK Economic Crisis Simulator", className="mb-0") ], className="my-3"),
    *( [top_banner] if top_banner else [] ),
    dcc.Store(id="normalize-flag", storage_type="memory", data=False),  # <- always False
    controls_block,
    TABS
], fluid=True)

# =========================
# ====== CALLBACKS ========
# =========================

# People Impact
@app.callback(
    Output("kpi-prob","children"),
    Output("kpi-cpi","children"),
    Output("kpi-un","children"),
    Output("kpi-gdp","children"),
    Output("people-cards","children"),
    Output("people-story","children"),
    Output("people-donut","figure"),
    Input("risk-mode","value"),
)
def cb_people(mode):
    if not DATA:
        blank = (kpi_card("Crisis probability","—"),
                 kpi_card("Inflation (CPIH)","—"),
                 kpi_card("Unemployment","—"),
                 kpi_card("GDP momentum","—"))
        empty = go.Figure(); apply_bordered_style(empty)
        return *blank, html.Div(), "Load data to view summary.", empty

    info = people_impact_panel(DATA, mode)
    k1 = kpi_card("Crisis probability (12m)", info["prob"], "Yield spread signal", color="danger")
    k2 = kpi_card("Inflation (CPIH, y/y)", info["cpi"], f"~ {info['monthly_cost']} extra", color="warning")
    k3 = kpi_card("Unemployment", info["un"], info["job_heat"], color="primary")
    k4 = kpi_card("GDP momentum", info["gdp_mom"], "last few quarters", color="success")

    # tile text: "Cost of living: £…/mo extra"
    tiles = [
        info_badge(f"Cost of living: {info['monthly_cost']} extra", "#fff59d"),
        info_badge(f"Job market: {info['job_heat']}", color_for_state_bg("Green") if "Cool" in info["job_heat"]
                   else color_for_state_bg("Amber") if "Moderate" in info["job_heat"]
                   else color_for_state_bg("Red")),
        info_badge(f"Borrowing: {info['credit']}", color_for_state_bg({"Normal":"Green","Elevated":"Amber","High":"Red"}.get(info["credit"],"Unknown"))),
    ]

    def state_and_val(var):
        dfv = _baseline_df(DATA, var, "Baseline")
        bands = calibrate_bands_simple(DATA, var, mode)
        val = latest_value(dfv, prefer_actual=True) if not dfv.empty else None
        return classify_point(val, bands), val

    col_state, col_val = state_and_val("CPIH") if "CPIH" in DATA else ("Unknown", None)
    jobs_state, jobs_val = state_and_val("Unemployment") if "Unemployment" in DATA else ("Unknown", None)
    credit_state = {"Normal":"Green","Elevated":"Amber","High":"Red"}.get(info["credit"], "Unknown")

    labels = ["Cost of living (CPIH)", "Unemployment", "Credit Stress"]
    states = [col_state, jobs_state, credit_state]
    sev_weight = {"Green":1.0, "Amber":2.0, "Red":3.0, "Unknown":1.5}
    values = [sev_weight.get(s,1.5) for s in states]
    colors = [ {"Green":"#2e7d32","Amber":"#FFD700","Red":"#FF0000","Unknown":"#9e9e9e"}[s] for s in states ]

    col_txt   = "—" if col_val is None else f"{col_val:.1f}%"
    jobs_txt  = "—" if jobs_val is None else f"{jobs_val:.1f}%"
    credit_txt = info["credit"]

    customdata = [col_txt, jobs_txt, credit_txt]
    hover = [
        f"Cost of living (CPIH) — {col_state}<br>CPIH: {col_txt}<br>~{info['monthly_cost']} extra",
        f"Unemployment — {jobs_state}<br>Unemployment: {jobs_txt}<br>{info['job_heat']}",
        f"Credit Stress — {credit_state}<br>Status: {credit_txt}",
    ]

    donut = go.Figure(data=[
        go.Pie(labels=labels, values=values, hole=0.55,
               marker=dict(colors=colors, line=dict(color="white", width=1)),
               customdata=customdata, texttemplate="%{label}<br><b>%{customdata}</b>",
               textposition="inside", insidetextorientation="radial", textfont=dict(size=14),
               hovertext=hover, hoverinfo="text", showlegend=True)
    ])
    donut.update_layout(title="Current impact", paper_bgcolor="#ffffff", plot_bgcolor="#ffffff", height=380)
    apply_bordered_style(donut)
    return k1, k2, k3, k4, tiles, info["story"], donut

# Indicators: dropdown sync
@app.callback(Output("macro-scn","options"), Output("macro-scn","value"), Input("macro-var","value"))
def sync_macro_scn(var):
    scns=(VAR_SCENARIOS.get(var,[]) if var else []) or avail_scn_all or ["Baseline"]
    return [{"label":s,"value":s} for s in scns], scns[0]

@app.callback(Output("micro-scn","options"), Output("micro-scn","value"), Input("micro-var","value"))
def sync_micro_scn(var):
    scns=(VAR_SCENARIOS.get(var,[]) if var else []) or avail_scn_all or ["Baseline"]
    return [{"label":s,"value":s} for s in scns], scns[0]

def _add_threshold_lines(fig: go.Figure, df: pd.DataFrame, bands: Dict[str,float], norm_on: bool, row=None):
    if not bands: return
    base0 = None
    if norm_on and "Forecast" in df.columns:
        f = pd.to_numeric(df["Forecast"], errors="coerce").dropna()
        base0 = f.iloc[0] if len(f) else None
    def maybe_norm(val):
        if val is None: return None
        if norm_on and base0 is not None and base0 != 0:
            return float(val) / float(base0) * 100.0
        return float(val)
    amber = maybe_norm(bands.get("amber")); red = maybe_norm(bands.get("red"))
    x0 = df["Quarter"].min(); x1 = df["Quarter"].max()
    if amber is not None:
        if row:
            fig.add_shape(type="line", x0=x0, x1=x1, y0=amber, y1=amber, line=dict(dash="dot", width=1, color="#FFD700"), row=row, col=1)
            fig.add_annotation(x=x1, y=amber, text="Amber", showarrow=False, yshift=6, xanchor="right",
                               font=dict(size=10, color="#FFD700"), row=row, col=1)
        else:
            fig.add_shape(type="line", x0=x0, x1=x1, y0=amber, y1=amber, line=dict(dash="dot", width=1, color="#FFD700"))
            fig.add_annotation(x=x1, y=amber, text="Amber", showarrow=False, yshift=6, xanchor="right",
                               font=dict(size=10, color="#FFD700"))
    if red is not None:
        if row:
            fig.add_shape(type="line", x0=x0, x1=x1, y0=red, y1=red, line=dict(dash="dash", width=1, color="#FF0000"), row=row, col=1)
            fig.add_annotation(x=x1, y=red, text="Red", showarrow=False, yshift=-10, xanchor="right",
                               font=dict(size=10, color="#FF0000"), row=row, col=1)
        else:
            fig.add_shape(type="line", x0=x0, x1=x1, y0=red, y1=red, line=dict(dash="dash", width=1, color="#FF0000"))
            fig.add_annotation(x=x1, y=red, text="Red", showarrow=False, yshift=-10, xanchor="right",
                               font=dict(size=10, color="#FF0000"))

# Indicators: macro chart
@app.callback(
    Output("macro-graph","figure"),
    Output("macro-risk-chip","children"),
    Input("macro-var","value"),
    Input("macro-scn","value"),
    Input("normalize-flag","data"),  # always False
    Input("risk-mode","value"),
)
def cb_macro(var, scn, norm_on, mode):
    fig=go.Figure()
    if not var or var not in DATA:
        apply_bordered_style(fig); return fig, ""
    df_all=DATA[var]
    use_scn=scn if scenario_exists_for_var(var, scn, VAR_SCENARIOS) else (VAR_SCENARIOS.get(var,["Baseline"])[0])
    df=df_all[df_all["Scenario"]==use_scn].copy().sort_values("Quarter")
    bands=calibrate_bands_simple(DATA, var, mode)

    if "Actual" in df.columns and df["Actual"].notna().any():
        yA=to_index_100_safe(df["Actual"]) if norm_on else df["Actual"]
        fig.add_trace(go.Scatter(x=df["Quarter"], y=yA, mode="lines", name="Actual"))
    if df["Forecast"].notna().any():
        yF=to_index_100_safe(df["Forecast"]) if norm_on else df["Forecast"]
        fig.add_trace(go.Scatter(x=df["Quarter"], y=yF, mode="lines", line=dict(dash="dash"), name=f"Forecast · {use_scn}"))
        add_ci_band(fig, df, norm_on)

    _add_threshold_lines(fig, df, bands, norm_on)
    add_hist_forecast_divider(fig, df); add_global_crisis_bands(fig); add_crisis_legend(fig)
    fig.update_layout(title=f"{var} · {use_scn}", hovermode="x unified", xaxis_title="Quarter")
    apply_bordered_style(fig)

    latest = latest_value(df, prefer_actual=False)
    state = classify_point(latest, bands)
    chip = info_badge(f"{var}: {state}", color_for_state_bg(state))
    return fig, chip

# Indicators: micro chart
@app.callback(
    Output("micro-graph","figure"),
    Input("micro-var","value"),
    Input("micro-scn","value"),
    Input("normalize-flag","data"),  # always False
    Input("risk-mode","value"),
)
def cb_micro(var, scn, norm_on, mode):
    fig=go.Figure()
    if not var or var not in DATA:
        apply_bordered_style(fig); return fig
    df_all=DATA[var]; use_scn=scn if scenario_exists_for_var(var, scn, VAR_SCENARIOS) else (VAR_SCENARIOS.get(var,["Baseline"])[0])
    df=df_all[df_all["Scenario"]==use_scn].copy().sort_values("Quarter")
    bands=calibrate_bands_simple(DATA, var, mode)

    if "Actual" in df.columns and df["Actual"].notna().any():
        yA=to_index_100_safe(df["Actual"]) if norm_on else df["Actual"]
        fig.add_trace(go.Scatter(x=df["Quarter"], y=yA, mode="lines", name="Actual"))
    if df["Forecast"].notna().any():
        yF=to_index_100_safe(df["Forecast"]) if norm_on else df["Forecast"]
        fig.add_trace(go.Scatter(x=df["Quarter"], y=yF, mode="lines", line=dict(dash="dash"), name=f"Forecast · {use_scn}"))
        add_ci_band(fig, df, norm_on)

    _add_threshold_lines(fig, df, bands, norm_on)
    add_hist_forecast_divider(fig, df); add_global_crisis_bands(fig); add_crisis_legend(fig)
    fig.update_layout(title=f"{var} · {use_scn}", hovermode="x unified", xaxis_title="Quarter")
    apply_bordered_style(fig)
    return fig

# Simulation: scenario sync
@app.callback(Output("sim-scn","options"), Output("sim-scn","value"), Input("sim-micro-var","value"))
def sync_sim_scn(micro_var):
    macro_sets=[set(VAR_SCENARIOS.get(m,[])) for m in MACROS if m in VAR_SCENARIOS]
    sets=macro_sets+([set(VAR_SCENARIOS.get(micro_var,[]))] if micro_var in VAR_SCENARIOS else [])
    inter=set.intersection(*sets) if sets else set()
    scns=sorted(inter) or (VAR_SCENARIOS.get(micro_var,[]) if micro_var in VAR_SCENARIOS else avail_scn_all) or ["Baseline"]
    return [{"label":s,"value":s} for s in scns], scns[0]

# ------- helper: build analyst one-liner -------
def build_analyst_line(micro_var: str, mode: str, df_micro_base: pd.DataFrame, df_micro_adj: pd.DataFrame, overall_p: Optional[float]) -> str:
    p_str = "—" if overall_p is None else f"{overall_p*100:.0f}%"
    # choose series for value / trend
    series_for_trend = None
    if isinstance(df_micro_adj, pd.DataFrame) and "Adj Forecast" in df_micro_adj:
        series_for_trend = pd.to_numeric(df_micro_adj["Adj Forecast"], errors="coerce")
    if (series_for_trend is None or series_for_trend.notna().sum() < 2) and isinstance(df_micro_base, pd.DataFrame):
        series_for_trend = pd.to_numeric(df_micro_base.get("Forecast", pd.Series(dtype=float)), errors="coerce")
        if series_for_trend.notna().sum() < 2 and "Actual" in df_micro_base:
            series_for_trend = pd.to_numeric(df_micro_base["Actual"], errors="coerce")

    trend = "—"
    if series_for_trend is not None and series_for_trend.notna().sum() >= 2:
        s = series_for_trend.dropna()
        d = s.iloc[-1] - s.iloc[-2]
        trend = "rising" if d > 0 else ("falling" if d < 0 else "flat")

    # current value for state/distance
    if isinstance(df_micro_adj, pd.DataFrame) and "Adj Forecast" in df_micro_adj:
        v = pd.to_numeric(df_micro_adj["Adj Forecast"], errors="coerce").dropna()
        v = float(v.iloc[-1]) if len(v) else None
    else:
        v = None
    if v is None and isinstance(df_micro_base, pd.DataFrame):
        if "Forecast" in df_micro_base:
            vv = pd.to_numeric(df_micro_base["Forecast"], errors="coerce").dropna()
            v = float(vv.iloc[-1]) if len(vv) else None
        if v is None and "Actual" in df_micro_base:
            vv = pd.to_numeric(df_micro_base["Actual"], errors="coerce").dropna()
            v = float(vv.iloc[-1]) if len(vv) else None

    bands = calibrate_bands_simple(DATA, micro_var, mode)
    state = classify_point(v, bands) if v is not None else "Unknown"

    next_thr = None
    dist = None
    if bands and v is not None and state in ("Green","Amber"):
        direction = bands.get("direction","upper")
        if state == "Green":
            next_thr = "Amber"
            thr_val = bands.get("amber")
            dist = (v - thr_val) if direction=="lower" else (thr_val - v)
        elif state == "Amber":
            next_thr = "Red"
            thr_val = bands.get("red")
            dist = (v - thr_val) if direction=="lower" else (thr_val - v)
        if dist is not None:
            dist = max(float(dist), 0.0)
    elif state == "Red":
        next_thr = "Red"
        dist = 0.0

    if next_thr and dist is not None:
        dist_txt = f"{dist:.2f} pts"
        return f"At {p_str} 12-m crisis odds, {micro_var} is {trend} and {dist_txt} from {next_thr} (status: {state})."
    else:
        return f"At {p_str} 12-m crisis odds, {micro_var} is {trend} (status: {state})."

# Simulation main
@app.callback(
    Output("sim-overall-prob","children"),
    Output("sim-donut","figure"),
    Output("sim-analyst-line","children"),
    Output("sim-pct-readout","children"),
    Output("sim-macro-graph","figure"),
    Output("sim-micro-graph","figure"),
    Output("sim-risk-chips","children"),
    Output("sim-table","data"),
    Output("sim-table","columns"),
    Input("sim-micro-var","value"),
    Input("sim-scn","value"),
    Input("normalize-flag","data"),   # always False
    Input("risk-mode","value"),
    Input("preset-recession","n_clicks"),
    Input("preset-recovery","n_clicks"),
    Input("preset-infl","n_clicks"),
    Input("pct-ccg","value"), Input("pct-cpih","value"),
    Input("pct-unemp","value"), Input("pct-gdp","value"), Input("pct-yield","value"),
)
def cb_sim(micro_var, scn, norm_on, mode, n1, n2, n3, s_ccg, s_cpih, s_un, s_gdp, s_yield):
    try: trig_id = dash.ctx.triggered_id
    except Exception:
        trig_id = callback_context.triggered[0]['prop_id'].split('.')[0] if callback_context.triggered else None

    if trig_id == "preset-recession":
        s_ccg, s_cpih, s_un, s_gdp, s_yield = -10, +10, +25, -15, -40
    elif trig_id == "preset-recovery":
        s_ccg, s_cpih, s_un, s_gdp, s_yield = +5, -10, -15, +12, +20
    elif trig_id == "preset-infl":
        s_ccg, s_cpih, s_un, s_gdp, s_yield = +12, +20, +5, -5, -10

    if not micro_var or not scn or not DATA:
        empty = kpi_card("Overall crisis probability (12m)", "—", "based on adjusted macros", color="danger")
        empty_donut = go.Figure(); apply_bordered_style(empty_donut)
        return empty, empty_donut, "", "", go.Figure(), go.Figure(), [], [], []

    present_macros=[m for m in MACROS if m in DATA]
    inter_sets=[set(VAR_SCENARIOS.get(m,[])) for m in present_macros]+[set(VAR_SCENARIOS.get(micro_var,[]))]
    inter=set.intersection(*inter_sets) if inter_sets else set()
    scn_use=scn if (not inter or scn in inter) else sorted(inter)[0]

    pct_map={"Credit Card Growth":s_ccg or 0,"CPIH":s_cpih or 0,"Unemployment":s_un or 0,"GDP":s_gdp or 0,"Yield Spread":s_yield or 0}

    base_macros={var: DATA[var][DATA[var]["Scenario"]==scn_use].copy().sort_values("Quarter") for var in present_macros}
    adj_macros=macro_adjusted_series(DATA, scn_use, pct_map)
    micro_adj = micro_adjusted_series(DATA, scn_use, adj_macros)

    overall_p = overall_crisis_prob_from_adj(DATA, adj_macros, mode)
    prob_card = kpi_card("Overall crisis probability (12m)", "—" if overall_p is None else f"{overall_p*100:.0f}%", "based on adjusted macros", color="danger")

    # ----- Donut (Approximate Risk Factor) -----
    shares = contribution_shares(DATA, adj_macros, mode)
    if shares:
        labels = list(shares.keys())
        vals   = list(shares.values())
    else:
        labels = present_macros
        vals   = [100/len(labels)]*len(labels) if labels else []

    macro_colors = {
        "GDP":"#1f77b4", "Unemployment":"#ff7f0e", "CPIH":"#2ca02c",
        "Yield Spread":"#9467bd", "Credit Card Growth":"#8c564b"
    }
    colors = [macro_colors.get(l, "#999999") for l in labels]

    sim_donut = go.Figure(data=[
        go.Pie(labels=labels, values=vals, hole=0.55,
               textinfo="label+percent", insidetextorientation="radial",
               marker=dict(colors=colors, line=dict(color="white", width=1)))
    ])
    sim_donut.update_layout(
        title="Approximate Risk Factor",
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        height=430, legend=dict(orientation="h", yanchor="bottom", y=-0.08, xanchor="center", x=0.5)
    )
    apply_bordered_style(sim_donut)

    # ----- Macro multi-plot -----
    rows_n=len(present_macros) if present_macros else 1
    macro_fig=make_subplots(rows=rows_n, cols=1, shared_xaxes=True, subplot_titles=present_macros, vertical_spacing=0.06)
    chips=[]

    for i,var in enumerate(present_macros, start=1):
        dfb=base_macros.get(var, pd.DataFrame()); dfa=adj_macros.get(var, pd.DataFrame())
        if dfb.empty: continue
        bands = calibrate_bands_simple(DATA, var, mode)

        if "Actual" in dfb.columns and dfb["Actual"].notna().any():
            yA=to_index_100_safe(dfb["Actual"]) if norm_on else dfb["Actual"]
            macro_fig.add_trace(go.Scatter(x=dfb["Quarter"], y=yA, mode="lines", name="Actual", showlegend=(i==1)), row=i, col=1)

        baseF=pd.to_numeric(dfb["Forecast"], errors="coerce")
        base0=baseF.dropna().iloc[0] if baseF.notna().any() else np.nan
        if baseF.notna().any():
            yF=to_index_100_relative(baseF, base0) if norm_on else baseF
            macro_fig.add_trace(go.Scatter(x=dfb["Quarter"], y=yF, mode="lines", line=dict(dash="dot"), name=f"Forecast · {scn_use}", showlegend=(i==1)), row=i, col=1)
            add_ci_band(macro_fig, dfb, norm_on, row=i, col=1)

        adjF=dfa.get("Adj Forecast", dfa.get("Forecast"))
        if adjF is not None and pd.Series(adjF).notna().any() and baseF.notna().any():
            fidx=baseF.first_valid_index()
            if fidx is not None:
                fdate=dfb.loc[fidx,"Quarter"]; mask=dfa["Quarter"]>=fdate
                yAdj_full=to_index_100_relative(adjF, base0) if norm_on else adjF
                yAdj_ser=pd.Series(yAdj_full, index=dfa.index)
                macro_fig.add_trace(go.Scatter(x=dfa.loc[mask,"Quarter"], y=yAdj_ser.loc[mask], mode="lines", name="Adjusted", showlegend=(i==1)), row=i,col=1)

        _add_threshold_lines(macro_fig, dfb, bands, norm_on, row=i)
        add_hist_forecast_divider(macro_fig, dfb, row=i, col=1); add_global_crisis_bands(macro_fig, row=i, col=1)

        tail = pd.to_numeric(pd.Series(adjF), errors="coerce").dropna().tail(2) if adjF is not None else pd.Series([], dtype=float)
        st="Unknown"
        if len(tail):
            b=calibrate_bands_simple(DATA, var, mode); sts=[classify_point(v, b) for v in tail]
            st="Red" if all(s=="Red" for s in sts) else ("Amber" if any(s in("Amber","Red") for s in sts) else "Green")
        chips.append(info_badge(f"{var}: {st}", color_for_state_bg(st)))

    add_crisis_legend(macro_fig)
    macro_fig.update_layout(title=f"Simulation — {scn_use}", hovermode="x unified", height=220*rows_n)
    apply_bordered_style(macro_fig)

    # Micro fig
    df_micro_base=DATA[micro_var][DATA[micro_var]["Scenario"]==scn_use].copy().sort_values("Quarter")
    df_micro_adj = micro_adj.get(micro_var, pd.DataFrame())
    micro_fig=go.Figure()
    if not df_micro_base.empty:
        mb = df_micro_base
        bands_m = calibrate_bands_simple(DATA, micro_var, mode)

        if "Actual" in mb.columns and mb["Actual"].notna().any():
            yA=to_index_100_safe(mb["Actual"]) if norm_on else mb["Actual"]
            micro_fig.add_trace(go.Scatter(x=mb["Quarter"], y=yA, mode="lines", name="Actual"))

        baseF=pd.to_numeric(mb["Forecast"], errors="coerce")
        base0=baseF.dropna().iloc[0] if baseF.notna().any() else np.nan
        if baseF.notna().any():
            yF=to_index_100_relative(baseF, base0) if norm_on else baseF
            micro_fig.add_trace(go.Scatter(x=mb["Quarter"], y=yF, mode="lines", line=dict(dash="dot"), name=f"Forecast · {scn_use}"))
            add_ci_band(micro_fig, mb, norm_on)

        if isinstance(df_micro_adj, pd.DataFrame) and not df_micro_adj.empty:
            adjF = pd.to_numeric(df_micro_adj["Adj Forecast"], errors="coerce")
            yAdj = to_index_100_relative(adjF, base0) if norm_on else adjF
            fidx = baseF.first_valid_index()
            if fidx is not None:
                fdate = mb.loc[fidx, "Quarter"]; mask = df_micro_adj["Quarter"] >= fdate
                micro_fig.add_trace(go.Scatter(x=df_micro_adj.loc[mask,"Quarter"], y=pd.Series(yAdj, index=df_micro_adj.index).loc[mask], mode="lines", name="Adjusted"))

        _add_threshold_lines(micro_fig, mb, bands_m, norm_on)
        add_hist_forecast_divider(micro_fig, mb); add_global_crisis_bands(micro_fig); add_crisis_legend(micro_fig)
        micro_fig.update_layout(title=f"{micro_var} — simulation view", xaxis_title="Quarter", hovermode="x unified")
        apply_bordered_style(micro_fig)

    # Analyst one-liner
    analyst_line = build_analyst_line(micro_var, mode, df_micro_base, df_micro_adj, overall_p)

    # Summary table
    headers = ["Indicator","Latest Actual","Latest Forecast","Latest Adjusted","Amber thr.","Red thr."]
    data_rows = []
    for var in present_macros:
        dfb = base_macros.get(var, pd.DataFrame()); dfa = adj_macros.get(var, pd.DataFrame())
        latest_act = f"{pd.to_numeric(dfb['Actual'], errors='coerce').dropna().iloc[-1]:.2f}" if (not dfb.empty and "Actual" in dfb and dfb['Actual'].notna().any()) else "—"
        latest_fc  = f"{pd.to_numeric(dfb['Forecast'], errors='coerce').dropna().iloc[-1]:.2f}" if (not dfb.empty and dfb['Forecast'].notna().any()) else "—"
        latest_adj = f"{pd.to_numeric(dfa['Adj Forecast'], errors='coerce').dropna().iloc[-1]:.2f}" if (isinstance(dfa, pd.DataFrame) and "Adj Forecast" in dfa and pd.to_numeric(dfa['Adj Forecast'], errors='coerce').notna().any()) else "—"
        bands = calibrate_bands_simple(DATA, var, mode)
        amber = f"{bands['amber']:.2f}" if bands and 'amber' in bands else "—"
        red   = f"{bands['red']:.2f}" if bands and 'red' in bands else "—"
        data_rows.append({"Indicator":var, "Latest Actual":latest_act, "Latest Forecast":latest_fc,
                          "Latest Adjusted":latest_adj, "Amber thr.":amber, "Red thr.":red})
    columns = [{"name":h, "id":h} for h in headers]

    rd=(f"Shocks → CardGrowth {pct_map['Credit Card Growth']}%, CPIH {pct_map['CPIH']}%, "
        f"Unemp {pct_map['Unemployment']}%, GDP {pct_map['GDP']}%, YieldSpread {pct_map['Yield Spread']}%.")

    return prob_card, sim_donut, analyst_line, rd, macro_fig, micro_fig, chips, data_rows, columns

# --------- Risk Overview (MACRO only; bordered) ----------
@app.callback(
    Output("risk-counts","figure"),
    Output("risk-table-simple","figure"),
    Input("risk-mode","value"),
)
def cb_risk_overview_simple(mode):
    vars_all=[v for v in MACROS if v in DATA]
    latest_vals={}; state_map={}
    for var in vars_all:
        df=_baseline_df(DATA, var, "Baseline")
        if df.empty:
            state_map[var] = "Unknown"; latest_vals[var] = np.nan; continue
        bands = calibrate_bands_simple(DATA, var, mode)
        s = (pd.to_numeric(df["Actual"], errors="coerce") if "Actual" in df and df["Actual"].notna().any()
             else pd.to_numeric(df["Forecast"], errors="coerce"))
        last = s.dropna().iloc[-1] if s.dropna().size else np.nan
        latest_vals[var]=last if pd.notna(last) else np.nan
        state_map[var]=classify_point(last, bands)

    cG = sum(1 for v in state_map.values() if v=="Green")
    cA = sum(1 for v in state_map.values() if v=="Amber")
    cR = sum(1 for v in state_map.values() if v=="Red")
    counts = go.Figure()
    counts.add_bar(x=["Now"], y=[cG], name="Green", marker_color="#2e7d32")
    counts.add_bar(x=["Now"], y=[cA], name="Amber", marker_color="#FFD700")
    counts.add_bar(x=["Now"], y=[cR], name="Red", marker_color="#FF0000")
    counts.update_layout(barmode="stack", title="number of crisis indicators", showlegend=True, yaxis_title="Count")
    apply_bordered_style(counts)

    order_key = {"Red":0, "Amber":1, "Green":2, "Unknown":3}
    rows = []
    for var in sorted(vars_all, key=lambda v: (order_key.get(state_map[v],3), v)):
        bands = calibrate_bands_simple(DATA, var, mode)
        amber = f"{bands['amber']:.2f}" if bands and 'amber' in bands else "—"
        red   = f"{bands['red']:.2f}" if bands and 'red' in bands else "—"
        latest = f"{latest_vals[var]:.2f}" if pd.notna(latest_vals[var]) else "—"
        rows.append([var, state_map[var], latest, amber, red])

    table = go.Figure(data=[go.Table(
        header=dict(values=["Indicator","State","Latest","Amber thr.","Red thr."], fill_color="#f3f4f6"),
        cells=dict(values=[list(col) for col in zip(*rows)])
    )])
    table.update_layout(title="current status (baseline)", paper_bgcolor="#ffffff", plot_bgcolor="#ffffff")
    return counts, table


# =========================
# ====== RUN SERVER =======
# =========================

if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 8052)))
