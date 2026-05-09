"""
PyStalker - Spread calculation
"""
import pandas as pd


def calculate_spread(df1: pd.DataFrame, df2: pd.DataFrame, start_date: str):
    close1 = df1[['Close']].copy()
    close1.columns = ['Close1']
    close2 = df2[['Close']].copy()
    close2.columns = ['Close2']
    
    merged = close1.join(close2, how='inner')
    
    if start_date:
        merged = merged[merged.index >= start_date]
    
    if merged.empty:
        return None
    
    base1 = merged['Close1'].iloc[0]
    base2 = merged['Close2'].iloc[0]
    
    if base1 == 0 or base2 == 0:
        return None
    
    series1 = (merged['Close1'] / base1) * 100.0
    series2 = (merged['Close2'] / base2) * 100.0
    
    return merged.index, series1, series2