import pandas as pd
import plotly.graph_objs as go
!pip install dash
from dash import Dash, dcc, html, Input, Output

# === Load Forecast Data ===
# Use the actual sheets from your Excel file
file_path = "C:/Users/user/Yashashree_PC/STFECP/Database_final.xlsx"

# Define variables and thresholds
variables = {
    "Credit Card Growth": {"sheet": "credit card growth", "threshold": 20},
    "CPIH": {"sheet": "CPIH", "threshold": 3},
    "Unemployment": {"sheet": "unemployment", "threshold": 6},
    "GDP": {"sheet": "GDP", "threshold": -2},
    "Yield Spread": {"sheet": "Yield Spread", "threshold": 0}
}

# Read all data into memory
data = {var: pd.read_excel(file_path, sheet_name=info["sheet"]) for var, info in variables.items()}
for df in data.values():
    df['Quarter'] = pd.to_datetime(df['Quarter'])

# === Initialize Dash App ===
app = Dash(__name__)
app.title = "Economic Forecast Simulator"

# === Layout ===
app.layout = html.Div([
    html.H2("📊 Economic Forecast Dashboard with Crisis Simulation"),

    html.Div([
        html.Label("Select Economic Variable:"),
        dcc.Dropdown(
            id='variable-dropdown',
            options=[{'label': var, 'value': var} for var in variables],
            value='CPIH',
            style={'width': '300px'}
        ),
    ], style={'margin-bottom': '20px'}),

    html.Div([
        html.Label("Select Scenario:"),
        dcc.Dropdown(
            id='scenario-dropdown',
            options=[
                {'label': 'Historical', 'value': 'Historical'},
                {'label': 'Baseline', 'value': 'Baseline'},
                {'label': 'Recession', 'value': 'Recession'},
                {'label': 'Recovery', 'value': 'Recovery'},
            ],
            value='Baseline',
            style={'width': '300px'}
        )
    ], style={'margin-bottom': '20px'}),

    html.Div(id='sliders-container'),

    dcc.Graph(id='forecast-graph'),

    html.Div(id='crisis-warning', style={'color': 'red', 'fontWeight': 'bold', 'fontSize': 18})
])

# === Callback for dynamic graph and warning ===
@app.callback(
    Output('forecast-graph', 'figure'),
    Output('crisis-warning', 'children'),
    Input('variable-dropdown', 'value'),
    Input('scenario-dropdown', 'value')
)
def update_forecast(variable, scenario):
    df = data[variable].copy()
    df = df[df['Scenario'] == scenario]
    
    fig = go.Figure()

    # Plot Actual
    if 'Actual' in df.columns and df['Actual'].notna().any():
        fig.add_trace(go.Scatter(
            x=df['Quarter'], y=df['Actual'],
            mode='lines', name='Actual', line=dict(color='green')
        ))

    # Plot Forecast
    fig.add_trace(go.Scatter(
        x=df['Quarter'], y=df['Forecast'],
        mode='lines+markers', name='Forecast', line=dict(color='orange')
    ))

    # Plot Confidence Interval
    fig.add_trace(go.Scatter(
        x=df['Quarter'], y=df['Upper CI'],
        mode='lines', name='Upper CI', line=dict(dash='dot', color='lightblue'),
        showlegend=False
    ))
    fig.add_trace(go.Scatter(
        x=df['Quarter'], y=df['Lower CI'],
        mode='lines', fill='tonexty', name='Lower CI', line=dict(dash='dot', color='lightblue'),
        fillcolor='rgba(173,216,230,0.2)', showlegend=True
    ))

    fig.update_layout(
        title=f"{variable} Forecast – {scenario} Scenario",
        xaxis_title="Quarter",
        yaxis_title=variable,
        hovermode='x unified'
    )

    # Crisis Warning Logic
    threshold = variables[variable]['threshold']
    crisis_triggered = df['Forecast'].dropna().gt(threshold).any()
    crisis_msg = f"Crisis Warning: {variable} forecast exceeds threshold of {threshold}!" if crisis_triggered else ""

    return fig, crisis_msg

# === Run App ===
if __name__ == '__main__':
    app.run(debug=True)
