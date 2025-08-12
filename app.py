import pandas as pd
import numpy as np
import plotly.graph_objs as go
from dash import Dash, dcc, html, Input, Output

# -----------------------------
# CONFIG
# -----------------------------
FILE_PATH = "Database_final.xlsx"

MACRO = {
    "Credit Card Growth": {"sheet": "credit card growth", "threshold": 20},
    "CPIH": {"sheet": "CPIH", "threshold": 3},
    "Unemployment": {"sheet": "unemployment", "threshold": 6},
    "GDP": {"sheet": "GDP", "threshold": -2},
    "Yield Spread": {"sheet": "Yield Spread", "threshold": 0},
}

MICRO = {
    "RSI: Predominantly food stores": {"sheet": "RSI_Predominantly_food_stores"},
    "RSI: Clothing & Footwear": {"sheet": "RSI_clothing_footwear"},
    "RSI: Household goods": {"sheet": "RSI_Household_goods"},
    "RSI: Electrical household appliances": {"sheet": "RSI_electrical_household_applia"},
    "RSI: Watches & Jewellery": {"sheet": "RSI_watches_and_jewellery"},
}

COEF = {
    ("Credit Card Growth", "GDP"): 0.15,
    ("Credit Card Growth", "CPIH"): 1.20,
    ("Yield Spread", "CPIH"): 0.120,

    ("GDP_lag1", "Unemployment"): -0.0109,
    ("GDP_lag2", "Unemployment"): -0.0200,
    ("Credit Card Growth", "Unemployment"): -0.0268,

    ("Credit Card Growth", "RSI: Predominantly food stores"): -0.161,
    ("Credit Card Growth", "RSI: Clothing & Footwear"): 1.146,
    ("Credit Card Growth", "RSI: Electrical household appliances"): 0.493,
    ("Credit Card Growth", "RSI: Watches & Jewellery"): 0.880,

    ("GDP", "RSI: Clothing & Footwear"): 1.247,
    ("GDP", "RSI: Household goods"): 1.186,
    ("GDP", "RSI: Watches & Jewellery"): 1.553,

    ("GDP_lag1", "RSI: Electrical household appliances"): -0.338,
    ("GDP_lag2", "RSI: Electrical household appliances"): -0.469,
}

def load_all(file_path):
    data = {}
    for var, info in MACRO.items():
        df = pd.read_excel(file_path, sheet_name=info["sheet"])
        df["Quarter"] = pd.to_datetime(df["Quarter"])
        data[var] = df
    for var, info in MICRO.items():
        df = pd.read_excel(file_path, sheet_name=info["sheet"])
        df["Quarter"] = pd.to_datetime(df["Quarter"])
        data[var] = df
    return data

DATA = load_all(FILE_PATH)

def make_series_fig(df, variable, show_ci=True):
    fig = go.Figure()
    if "Actual" in df.columns and df["Actual"].notna().any():
        fig.add_trace(go.Scatter(x=df["Quarter"], y=df["Actual"], mode="lines", name="Actual"))
    if "Forecast" in df.columns:
        fig.add_trace(go.Scatter(x=df["Quarter"], y=df["Forecast"], mode="lines+markers", name="Forecast"))
    if show_ci and {"Upper CI", "Lower CI"}.issubset(df.columns):
        fig.add_trace(go.Scatter(x=df["Quarter"], y=df["Upper CI"], mode="lines", name="Upper CI", line=dict(dash="dot")))
        fig.add_trace(go.Scatter(x=df["Quarter"], y=df["Lower CI"], mode="lines", name="Lower CI", line=dict(dash="dot"), fill="tonexty", fillcolor="rgba(0,0,0,0.08)"))
    fig.update_layout(title=variable, xaxis_title="Quarter", hovermode="x unified")
    return fig

app = Dash(__name__)
app.title = "Economic Forecast Simulator"

macro_options = [{"label": k, "value": k} for k in MACRO.keys()]
micro_options = [{"label": k, "value": k} for k in MICRO.keys()]
scenario_options = [
    {"label": "Historical", "value": "Historical"},
    {"label": "Baseline", "value": "Baseline"},
    {"label": "Recession", "value": "Recession"},
    {"label": "Recovery", "value": "Recovery"},
]

app.layout = html.Div([
    html.H2("📊 Economic Dashboard (Macro, Micro & Combined Simulation)"),
    dcc.Tabs(id="tabs", value="tab-macro", children=[
        dcc.Tab(label="Macroeconomic", value="tab-macro", children=[
            html.Div([
                html.Div([
                    html.Label("Scenario"),
                    dcc.Dropdown(id="macro-scn", options=scenario_options, value="Baseline", style={"width": "260px"})
                ], style={"marginRight":"20px"}),
                html.Div([
                    html.Label("Variable"),
                    dcc.Dropdown(id="macro-var", options=macro_options, value="CPIH", style={"width": "320px"})
                ])
            ], style={"display":"flex", "gap":"8px", "marginBottom":"16px", "flexWrap":"wrap"}),
            dcc.Graph(id="macro-graph"),
            html.Div(id="macro-warning", style={"color":"red","fontWeight":"bold","fontSize":16, "marginTop":"8px"}),
        ]),
        dcc.Tab(label="Microeconomic (RSI)", value="tab-micro", children=[
            html.Div([
                html.Div([
                    html.Label("Scenario"),
                    dcc.Dropdown(id="micro-scn", options=scenario_options, value="Baseline", style={"width": "260px"})
                ], style={"marginRight":"20px"}),
                html.Div([
                    html.Label("Variable"),
                    dcc.Dropdown(id="micro-var", options=micro_options, value="RSI: Clothing & Footwear", style={"width": "360px"})
                ])
            ], style={"display":"flex", "gap":"8px", "marginBottom":"16px", "flexWrap":"wrap"}),
            dcc.Graph(id="micro-graph"),
        ]),
        dcc.Tab(label="Combined Simulation", value="tab-sim", children=[
            html.Div([
                html.Div([
                    html.Label("Scenario"),
                    dcc.Dropdown(id="sim-scn", options=scenario_options, value="Baseline", style={"width": "260px"}),
                ], style={"marginBottom":"12px"}),
                html.Div("Adjust macro variables (%). Example: +10 means increase macro forecast by 10%.", style={"marginBottom":"8px"}),
                html.Div([
                    html.Label("Credit Card Growth (%)"),
                    dcc.Slider(id="s-ccg", min=-20, max=20, step=1, value=0, marks=None, tooltip={"placement":"bottom", "always_visible":True}),
                    html.Label("CPIH (%)"),
                    dcc.Slider(id="s-cpih", min=-20, max=20, step=1, value=0, marks=None, tooltip={"placement":"bottom", "always_visible":True}),
                    html.Label("Unemployment (%)"),
                    dcc.Slider(id="s-unemp", min=-20, max=20, step=1, value=0, marks=None, tooltip={"placement":"bottom", "always_visible":True}),
                    html.Label("GDP (%)"),
                    dcc.Slider(id="s-gdp", min=-20, max=20, step=1, value=0, marks=None, tooltip={"placement":"bottom", "always_visible":True}),
                    html.Label("Yield Spread (%)"),
                    dcc.Slider(id="s-ys", min=-20, max=20, step=1, value=0, marks=None, tooltip={"placement":"bottom", "always_visible":True}),
                ], style={"display":"grid","gridTemplateColumns":"1fr","gap":"10px", "marginBottom":"16px"}),
                html.Div([
                    html.Div([html.H4("Adjusted Macro"), dcc.Graph(id="sim-macro-graph")], style={"flex":"1"}),
                    html.Div([html.H4("Impacted Micro"), dcc.Graph(id="sim-micro-graph")], style={"flex":"1"}),
                ], style={"display":"flex","gap":"16px","flexWrap":"wrap"}),
                html.Div(id="sim-warning", style={"color":"red","fontWeight":"bold","fontSize":16, "marginTop":"8px"}),
            ], style={"maxWidth":"1100px"})
        ]),
    ])
])

@app.callback(
    Output("macro-graph","figure"),
    Output("macro-warning","children"),
    Input("macro-var","value"),
    Input("macro-scn","value")
)
def update_macro(var, scn):
    df = DATA[var].copy()
    df = df[df["Scenario"] == scn]
    fig = make_series_fig(df, var)
    thr = MACRO[var]["threshold"]
    trig = False
    if thr >= 0:
        trig = df["Forecast"].dropna().gt(thr).any()
    else:
        trig = df["Forecast"].dropna().lt(thr).any()
    warn = f"⚠️ Crisis Warning: {var} crosses its threshold ({thr})." if trig else ""
    return fig, warn

@app.callback(
    Output("micro-graph","figure"),
    Input("micro-var","value"),
    Input("micro-scn","value")
)
def update_micro(var, scn):
    df = DATA[var].copy()
    df = df[df["Scenario"] == scn]
    fig = make_series_fig(df, var)
    return fig

@app.callback(
    Output("sim-macro-graph","figure"),
    Output("sim-micro-graph","figure"),
    Output("sim-warning","children"),
    Input("sim-scn","value"),
    Input("s-ccg","value"), Input("s-cpih","value"), Input("s-unemp","value"), Input("s-gdp","value"), Input("s-ys","value"),
)
def update_sim(scn, p_ccg, p_cpih, p_un, p_gdp, p_ys):
    mult = {
        "Credit Card Growth": 1 + (p_ccg or 0)/100.0,
        "CPIH": 1 + (p_cpih or 0)/100.0,
        "Unemployment": 1 + (p_un or 0)/100.0,
        "GDP": 1 + (p_gdp or 0)/100.0,
        "Yield Spread": 1 + (p_ys or 0)/100.0,
    }

    # Adjust macro forecasts
    adj_macro = {}
    for var in MACRO.keys():
        df = DATA[var]
        d = df[df["Scenario"] == scn].copy()
        if "Forecast" not in d.columns:
            continue
        d["Forecast_adj"] = d["Forecast"] * mult[var]
        adj_macro[var] = d[["Quarter","Forecast","Forecast_adj","Scenario"]].copy()

    # GDP lags
    if "GDP" in adj_macro:
        g = adj_macro["GDP"].sort_values("Quarter")
        g["GDP_lag1"] = g.groupby("Scenario")["Forecast_adj"].shift(1)
        g["GDP_lag2"] = g.groupby("Scenario")["Forecast_adj"].shift(2)
        adj_macro["GDP"] = g

    # Build adjusted micro via coefficients
    adj_micro_frames = []
    for mvar in MICRO.keys():
        dfm = DATA[mvar]
        d = dfm[dfm["Scenario"] == scn].copy().sort_values("Quarter")
        if "Forecast" not in d.columns:
            continue
        d["Forecast_adj"] = d["Forecast"].astype(float)
        total_pct_series = pd.Series(0.0, index=d.index)

        def pct_change_series(base, adj):
            return (adj - base) / (base.replace(0, 0.0).abs() + 1e-9)

        for driver in ["Credit Card Growth", "CPIH", "Unemployment", "GDP", "Yield Spread", "GDP_lag1", "GDP_lag2"]:
            key = (driver, mvar)
            if key not in COEF:
                continue
            coef = COEF[key]

            if driver in ["GDP_lag1","GDP_lag2"]:
                if "GDP" not in adj_macro:
                    continue
                g = adj_macro["GDP"].set_index("Quarter")
                base_series = g["Forecast"].reindex(d["Quarter"]).astype(float)
                adj_series = g["Forecast_adj"].reindex(d["Quarter"]).astype(float)
                if driver == "GDP_lag1":
                    base_series = base_series.shift(1)
                    adj_series = adj_series.shift(1)
                else:
                    base_series = base_series.shift(2)
                    adj_series = adj_series.shift(2)
            else:
                if driver not in adj_macro:
                    continue
                a = adj_macro[driver].set_index("Quarter")
                base_series = a["Forecast"].reindex(d["Quarter"]).astype(float)
                adj_series = a["Forecast_adj"].reindex(d["Quarter"]).astype(float)

            d_pct = pct_change_series(base_series, adj_series).fillna(0.0)
            total_pct_series = total_pct_series.add(coef * d_pct, fill_value=0.0)

        d["Forecast_adj"] = d["Forecast"] * (1.0 + total_pct_series.values)
        adj_micro_frames.append(d[["Quarter","Forecast","Forecast_adj","Scenario"]].assign(Variable=mvar))

    # Figures
    macro_fig = go.Figure()
    for var, d in adj_macro.items():
        macro_fig.add_trace(go.Scatter(x=d["Quarter"], y=d["Forecast_adj"], mode="lines", name=f"{var} (adj)"))
    macro_fig.update_layout(title="Adjusted Macro Forecasts", xaxis_title="Quarter", hovermode="x unified")

    micro_fig = go.Figure()
    if adj_micro_frames:
        all_micro = pd.concat(adj_micro_frames, ignore_index=True)
        for var, sub in all_micro.groupby("Variable"):
            micro_fig.add_trace(go.Scatter(x=sub["Quarter"], y=sub["Forecast_adj"], mode="lines", name=var))
    micro_fig.update_layout(title="Impacted Micro Forecasts", xaxis_title="Quarter", hovermode="x unified")

    # Crisis warnings on adjusted macro
    warnings = []
    for var, d in adj_macro.items():
        thr = MACRO[var]["threshold"]
        s = d["Forecast_adj"].dropna()
        if thr >= 0 and s.gt(thr).any():
            warnings.append(f"{var} > {thr}")
        if thr < 0 and s.lt(thr).any():
            warnings.append(f"{var} < {thr}")
    warn_txt = f"⚠️ Crisis Warning: " + ", ".join(warnings) if warnings else ""

    return macro_fig, micro_fig, warn_txt

if __name__ == "__main__":
    # Render expects host/port as below
    app.run(debug=False, host="0.0.0.0", port=8080)
