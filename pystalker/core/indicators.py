"""
PyStalker - Technical Indicators using TA-Lib
"""
import numpy as np
import pandas as pd
import warnings
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

try:
    import talib
    TALIB_AVAILABLE = True
except ImportError:
    TALIB_AVAILABLE = False

@dataclass
class PlotLine:
    name: str
    data: np.ndarray
    color: str = 'white'
    line_type: str = 'line'
    width: int = 1

class Indicator:
    OVERLAY = 'overlay'
    INDICATOR = 'indicator'
    
    def __init__(self, name: str, indicator_type: str = OVERLAY):
        self.name = name
        self.indicator_type = indicator_type
        self.lines: List[PlotLine] = []
        self.enabled = True
        self.parameters: Dict = {}
        self.hlines: List[Dict] = []
    
    def add_line(self, line: PlotLine):
        self.lines.append(line)
    
    def clear_lines(self):
        self.lines.clear()
    
    def calculate(self, data: pd.DataFrame) -> List[PlotLine]:
        raise NotImplementedError

class IndicatorManager:
    OVERLAY_INDICATORS = {
        'SMA': {'func': 'SMA', 'params': {'period': 20}, 'type': Indicator.OVERLAY},
        'EMA': {'func': 'EMA', 'params': {'period': 20}, 'type': Indicator.OVERLAY},
        'BBANDS': {'func': 'BBANDS', 'params': {'period': 20, 'nbdevup': 2, 'nbdevdn': 2}, 'type': Indicator.OVERLAY},
        'SAR': {'func': 'SAR', 'params': {'acceleration': 0.02, 'maximum': 0.2}, 'type': Indicator.OVERLAY},
        'SuperTrend': {'func': 'SUPERTREND', 'params': {'period': 10, 'multiplier': 3.0}, 'type': Indicator.OVERLAY},
        'Donchian': {'func': 'DONCHIAN', 'params': {'period': 20}, 'type': Indicator.OVERLAY},
        'ML Predict (Random Forest)': {'func': 'ML_PREDICT_RF', 'params': {'lookback': 200, 'horizon': 5}, 'type': Indicator.OVERLAY},
        'ML Predict (XGBoost)': {'func': 'ML_PREDICT_XGB', 'params': {'lookback': 200, 'horizon': 5}, 'type': Indicator.OVERLAY},
    }
    
    SEPARATE_INDICATORS = {
        'MACD': {'func': 'MACD', 'params': {'fastperiod': 12, 'slowperiod': 26, 'signalperiod': 9}, 'type': Indicator.INDICATOR},
        'RSI': {'func': 'RSI', 'params': {'period': 14}, 'type': Indicator.INDICATOR},
        'CCI': {'func': 'CCI', 'params': {'period': 20}, 'type': Indicator.INDICATOR},
        'ADX': {'func': 'ADX', 'params': {'period': 14}, 'type': Indicator.INDICATOR},
        'ATR': {'func': 'ATR', 'params': {'period': 14}, 'type': Indicator.INDICATOR},
        'MOM': {'func': 'MOM', 'params': {'period': 10}, 'type': Indicator.INDICATOR},
        'ROC': {'func': 'ROC', 'params': {'period': 10}, 'type': Indicator.INDICATOR},
        'STOCH': {'func': 'STOCH', 'params': {'fastk_period': 5, 'slowk_period': 3, 'slowd_period': 3}, 'type': Indicator.INDICATOR},
        'STOCHRSI': {'func': 'STOCHRSI', 'params': {'period': 14, 'fastk_period': 5, 'fastd_period': 3}, 'type': Indicator.INDICATOR},
        'WILLR': {'func': 'WILLR', 'params': {'period': 14}, 'type': Indicator.INDICATOR},
        'OBV': {'func': 'OBV', 'params': {}, 'type': Indicator.INDICATOR},
        'MFI': {'func': 'MFI', 'params': {'period': 14}, 'type': Indicator.INDICATOR},
    }
    
    ALL_INDICATORS = {**OVERLAY_INDICATORS, **SEPARATE_INDICATORS}
    
    LINE_DEFAULTS = {
        'SMA': [{'name': 'SMA', 'color': '#00BFFF'}],
        'EMA': [{'name': 'EMA', 'color': '#FFD700'}],
        'ML Predict (Random Forest)': [{'name': 'Predicted', 'color': '#E040FB'}, {'name': 'Future', 'color': '#FF6EC7'}],
        'ML Predict (XGBoost)': [{'name': 'Predicted', 'color': '#00E676'}, {'name': 'Future', 'color': '#76FF03'}],
        'BBANDS': [
            {'name': 'Upper', 'color': '#FF6B6B'},
            {'name': 'Middle', 'color': '#4ECDC4'},
            {'name': 'Lower', 'color': '#95E1D3'},
        ],
        'SAR': [{'name': 'SAR', 'color': '#00CED1'}],
        'SuperTrend': [
            {'name': 'Up', 'color': '#00FF7F'},
            {'name': 'Down', 'color': '#FF6B6B'},
            {'name': 'Upper', 'color': '#FF6B6B'},
            {'name': 'Lower', 'color': '#4ECDC4'},
        ],
        'Donchian': [
            {'name': 'Upper', 'color': '#FF6B6B'},
            {'name': 'Middle', 'color': '#4ECDC4'},
            {'name': 'Lower', 'color': '#95E1D3'},
        ],
        'MACD': [
            {'name': 'MACD', 'color': '#4169E1'},
            {'name': 'Signal', 'color': '#FF8C00'},
            {'name': 'Histogram', 'color': '#32CD32'},
        ],
        'RSI': [{'name': 'RSI', 'color': '#9370DB'}],
        'CCI': [{'name': 'CCI', 'color': '#FFD700'}],
        'ADX': [{'name': 'ADX', 'color': '#DA70D6'}],
        'ATR': [{'name': 'ATR', 'color': '#00CED1'}],
        'MOM': [{'name': 'MOM', 'color': '#FF8C00'}],
        'ROC': [{'name': 'ROC', 'color': '#FFD700'}],
        'STOCH': [
            {'name': '%K', 'color': '#4169E1'},
            {'name': '%D', 'color': '#FF6347'},
        ],
        'STOCHRSI': [
            {'name': 'FastK', 'color': '#4169E1'},
            {'name': 'FastD', 'color': '#FF6347'},
        ],
        'WILLR': [{'name': 'WILLR', 'color': '#FFD700'}],
        'OBV': [{'name': 'OBV', 'color': '#00CED1'}],
        'MFI': [{'name': 'MFI', 'color': '#9370DB'}],
    }
    
    HLINE_DEFAULTS = {
        'RSI': [{'level': 70, 'color': '#FF6B6B'}, {'level': 30, 'color': '#4ECDC4'}],
        'CCI': [{'level': 100, 'color': '#FF6B6B'}, {'level': -100, 'color': '#4ECDC4'}],
        'STOCH': [{'level': 80, 'color': '#FF6B6B'}, {'level': 20, 'color': '#4ECDC4'}],
        'STOCHRSI': [{'level': 80, 'color': '#FF6B6B'}, {'level': 20, 'color': '#4ECDC4'}],
        'WILLR': [{'level': -20, 'color': '#FF6B6B'}, {'level': -80, 'color': '#4ECDC4'}],
        'MFI': [{'level': 80, 'color': '#FF6B6B'}, {'level': 20, 'color': '#4ECDC4'}],
    }
    
    @staticmethod
    def get_available_indicators() -> Dict[str, dict]:
        return IndicatorManager.ALL_INDICATORS
    
    @staticmethod
    def get_overlay_indicators() -> Dict[str, dict]:
        return IndicatorManager.OVERLAY_INDICATORS
    
    @staticmethod
    def get_separate_indicators() -> Dict[str, dict]:
        return IndicatorManager.SEPARATE_INDICATORS
    
    @staticmethod
    def calculate_indicator(name: str, data: pd.DataFrame, params: Dict = None, colors: Dict = None) -> Optional[Indicator]:
        if name not in IndicatorManager.ALL_INDICATORS:
            return None
        
        if name == 'ML Predict (Random Forest)':
            default_params = IndicatorManager.ALL_INDICATORS[name]['params'].copy()
            if params:
                default_params.update(params)
            result = _calculate_ml_predict(data, default_params, colors or {}, model_type='rf')
            return result
        
        if name == 'ML Predict (XGBoost)':
            default_params = IndicatorManager.ALL_INDICATORS[name]['params'].copy()
            if params:
                default_params.update(params)
            result = _calculate_ml_predict(data, default_params, colors or {}, model_type='xgb')
            return result
        
        if name == 'SuperTrend':
            default_params = IndicatorManager.ALL_INDICATORS[name]['params'].copy()
            if params:
                default_params.update(params)
            result = _calculate_supertrend(data, default_params, colors or {})
            return result
        
        if name == 'Donchian':
            default_params = IndicatorManager.ALL_INDICATORS[name]['params'].copy()
            if params:
                default_params.update(params)
            result = _calculate_donchian(data, default_params, colors or {})
            return result
        
        if not TALIB_AVAILABLE:
            raise ImportError("TA-Lib is not installed. Install with: pip install TA-Lib")
        
        indicator_info = IndicatorManager.ALL_INDICATORS[name]
        func_name = indicator_info['func']
        default_params = indicator_info['params'].copy()
        
        if params:
            default_params.update(params)
        
        indicator = Indicator(name, indicator_info['type'])
        indicator.parameters = default_params
        
        close = data['Close'].values
        high = data['High'].values if 'High' in data.columns else close
        low = data['Low'].values if 'Low' in data.columns else close
        open_price = data['Open'].values if 'Open' in data.columns else close
        volume = data['Volume'].values if 'Volume' in data.columns else np.ones(len(close))
        
        func = getattr(talib, func_name, None)
        if func is None:
            return None
        
        try:
            line_colors = colors or {}
            if name == 'SMA':
                result = func(close, timeperiod=default_params['period'])
                line = PlotLine(f'SMA({default_params["period"]})', result, line_colors.get('SMA', '#00BFFF'))
                indicator.add_line(line)
            elif name == 'EMA':
                result = func(close, timeperiod=default_params['period'])
                line = PlotLine(f'EMA({default_params["period"]})', result, line_colors.get('EMA', '#FFD700'))
                indicator.add_line(line)
            elif name == 'BBANDS':
                upper, middle, lower = func(close, timeperiod=default_params['period'],
                                            nbdevup=default_params['nbdevup'], nbdevdn=default_params['nbdevdn'])
                indicator.add_line(PlotLine('Upper', upper, line_colors.get('Upper', '#FF6B6B')))
                indicator.add_line(PlotLine('Middle', middle, line_colors.get('Middle', '#4ECDC4')))
                indicator.add_line(PlotLine('Lower', lower, line_colors.get('Lower', '#95E1D3')))
            elif name == 'SAR':
                result = func(high, low, acceleration=default_params['acceleration'], maximum=default_params['maximum'])
                indicator.add_line(PlotLine('SAR', result, line_colors.get('SAR', '#00CED1')))
            elif name == 'MACD':
                macd, signal, hist = func(close, fastperiod=default_params['fastperiod'],
                                         slowperiod=default_params['slowperiod'],
                                         signalperiod=default_params['signalperiod'])
                indicator.add_line(PlotLine('MACD', macd, line_colors.get('MACD', '#4169E1')))
                indicator.add_line(PlotLine('Signal', signal, line_colors.get('Signal', '#FF8C00')))
                indicator.add_line(PlotLine('Histogram', hist, line_colors.get('Histogram', '#32CD32')))
            elif name == 'RSI':
                result = func(close, timeperiod=default_params['period'])
                indicator.add_line(PlotLine(f'RSI({default_params["period"]})', result, line_colors.get('RSI', '#9370DB')))
                hlines = params.pop('hlines', None) if params else None
                if hlines is None:
                    hlines = IndicatorManager.HLINE_DEFAULTS.get('RSI', [])
                indicator.hlines = hlines
            elif name == 'CCI':
                result = func(high, low, close, timeperiod=default_params['period'])
                indicator.add_line(PlotLine(f'CCI({default_params["period"]})', result, line_colors.get('CCI', '#FFD700')))
                hlines = params.pop('hlines', None) if params else None
                if hlines is None:
                    hlines = IndicatorManager.HLINE_DEFAULTS.get('CCI', [])
                indicator.hlines = hlines
            elif name == 'ADX':
                result = func(high, low, close, timeperiod=default_params['period'])
                indicator.add_line(PlotLine(f'ADX({default_params["period"]})', result, line_colors.get('ADX', '#DA70D6')))
            elif name == 'ATR':
                result = func(high, low, close, timeperiod=default_params['period'])
                indicator.add_line(PlotLine(f'ATR({default_params["period"]})', result, line_colors.get('ATR', '#00CED1')))
            elif name == 'MOM':
                result = func(close, timeperiod=default_params['period'])
                indicator.add_line(PlotLine(f'MOM({default_params["period"]})', result, line_colors.get('MOM', '#FF8C00')))
            elif name == 'ROC':
                result = func(close, timeperiod=default_params['period'])
                indicator.add_line(PlotLine(f'ROC({default_params["period"]})', result, line_colors.get('ROC', '#FFD700')))
            elif name == 'STOCH':
                slowk, slowd = func(high, low, close,
                                   fastk_period=default_params['fastk_period'],
                                   slowk_period=default_params['slowk_period'],
                                   slowd_period=default_params['slowd_period'])
                indicator.add_line(PlotLine('%K', slowk, line_colors.get('%K', '#4169E1')))
                indicator.add_line(PlotLine('%D', slowd, line_colors.get('%D', '#FF6347')))
                hlines = params.pop('hlines', None) if params else None
                if hlines is None:
                    hlines = IndicatorManager.HLINE_DEFAULTS.get('STOCH', [])
                indicator.hlines = hlines
            elif name == 'STOCHRSI':
                fastk, fastd = func(close, timeperiod=default_params['period'],
                                   fastk_period=default_params['fastk_period'],
                                   fastd_period=default_params['fastd_period'])
                indicator.add_line(PlotLine('FastK', fastk, line_colors.get('FastK', '#4169E1')))
                indicator.add_line(PlotLine('FastD', fastd, line_colors.get('FastD', '#FF6347')))
                hlines = params.pop('hlines', None) if params else None
                if hlines is None:
                    hlines = IndicatorManager.HLINE_DEFAULTS.get('STOCHRSI', [])
                indicator.hlines = hlines
            elif name == 'WILLR':
                result = func(high, low, close, timeperiod=default_params['period'])
                indicator.add_line(PlotLine(f'WILLR({default_params["period"]})', result, line_colors.get('WILLR', '#FFD700')))
                hlines = params.pop('hlines', None) if params else None
                if hlines is None:
                    hlines = IndicatorManager.HLINE_DEFAULTS.get('WILLR', [])
                indicator.hlines = hlines
            elif name == 'OBV':
                result = func(close, volume)
                indicator.add_line(PlotLine('OBV', result, line_colors.get('OBV', '#00CED1')))
            elif name == 'MFI':
                result = func(high, low, close, volume, timeperiod=default_params['period'])
                indicator.add_line(PlotLine(f'MFI({default_params["period"]})', result, line_colors.get('MFI', '#9370DB')))
                hlines = params.pop('hlines', None) if params else None
                if hlines is None:
                    hlines = IndicatorManager.HLINE_DEFAULTS.get('MFI', [])
                indicator.hlines = hlines
            
            return indicator
        except Exception:
            return None


def _calculate_supertrend(data: pd.DataFrame, params: dict, line_colors: dict) -> Indicator:
    period = int(params.get('period', 10))
    multiplier = float(params.get('multiplier', 3.0))
    
    high = data['High'].values.astype(float)
    low = data['Low'].values.astype(float)
    close = data['Close'].values.astype(float)
    n = len(data)
    
    if n < period + 1:
        return None
    
    hl2 = (high + low) / 2.0
    
    atr = np.full(n, np.nan)
    if TALIB_AVAILABLE:
        try:
            atr_raw = talib.ATR(high, low, close, timeperiod=period)
            if atr_raw is not None:
                atr = atr_raw
        except Exception:
            pass
    
    if np.all(np.isnan(atr)):
        tr = np.maximum(high - low, np.maximum(np.abs(high - np.roll(close, 1)), np.abs(low - np.roll(close, 1))))
        tr[0] = high[0] - low[0]
        atr[period - 1] = np.mean(tr[1:period])
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr
    
    supertrend = np.full(n, np.nan)
    direction = np.ones(n, dtype=int)
    
    for i in range(1, n):
        if np.isnan(atr[i]):
            upper_band[i] = np.nan
            lower_band[i] = np.nan
            continue
        
        if not np.isnan(supertrend[i - 1]):
            if direction[i - 1] == 1:
                lower_band[i] = max(lower_band[i], lower_band[i - 1])
                upper_band[i] = hl2[i] + multiplier * atr[i]
            else:
                upper_band[i] = min(upper_band[i], upper_band[i - 1])
                lower_band[i] = hl2[i] - multiplier * atr[i]
        
        if np.isnan(supertrend[i - 1]):
            if close[i] > lower_band[i]:
                direction[i] = 1
            elif close[i] < upper_band[i]:
                direction[i] = -1
            else:
                direction[i] = 1
        elif direction[i - 1] == 1:
            if close[i] < lower_band[i]:
                direction[i] = -1
            else:
                direction[i] = 1
        else:
            if close[i] > upper_band[i]:
                direction[i] = 1
            else:
                direction[i] = -1
        
        if direction[i] == 1:
            supertrend[i] = lower_band[i]
        else:
            supertrend[i] = upper_band[i]
    
    supertrend_up = np.full(n, np.nan)
    supertrend_down = np.full(n, np.nan)
    for i in range(n):
        if direction[i] == 1:
            supertrend_up[i] = supertrend[i]
        else:
            supertrend_down[i] = supertrend[i]
    
    indicator = Indicator('SuperTrend', Indicator.OVERLAY)
    indicator.parameters = params
    indicator.add_line(PlotLine(
        f'Up({period},{multiplier})', supertrend_up,
        line_colors.get('Up', '#00FF7F')
    ))
    indicator.add_line(PlotLine(
        f'Down({period},{multiplier})', supertrend_down,
        line_colors.get('Down', '#FF6B6B')
    ))
    indicator.add_line(PlotLine(
        'Upper', upper_band,
        line_colors.get('Upper', '#FF6B6B')
    ))
    indicator.add_line(PlotLine(
        'Lower', lower_band,
        line_colors.get('Lower', '#4ECDC4')
    ))
    
    return indicator


def _calculate_donchian(data: pd.DataFrame, params: dict, line_colors: dict) -> Indicator:
    period = int(params.get('period', 20))
    
    high = data['High'].values.astype(float)
    low = data['Low'].values.astype(float)
    close = data['Close'].values.astype(float)
    n = len(data)
    
    if n < period:
        return None
    
    upper_band = np.full(n, np.nan)
    lower_band = np.full(n, np.nan)
    middle_band = np.full(n, np.nan)
    
    for i in range(period - 1, n):
        upper_band[i] = np.max(high[i - period + 1:i + 1])
        lower_band[i] = np.min(low[i - period + 1:i + 1])
        middle_band[i] = (upper_band[i] + lower_band[i]) / 2.0
    
    indicator = Indicator('Donchian', Indicator.OVERLAY)
    indicator.parameters = params
    indicator.add_line(PlotLine(
        f'Upper({period})', upper_band,
        line_colors.get('Upper', '#FF6B6B')
    ))
    indicator.add_line(PlotLine(
        f'Middle({period})', middle_band,
        line_colors.get('Middle', '#4ECDC4')
    ))
    indicator.add_line(PlotLine(
        f'Lower({period})', lower_band,
        line_colors.get('Lower', '#95E1D3')
    ))
    
    return indicator


def _build_ml_features(data: pd.DataFrame):
    n = len(data)
    close = data['Close'].values.astype(float)
    high = data['High'].values.astype(float)
    low = data['Low'].values.astype(float)
    open_price = data['Open'].values.astype(float)
    volume = data['Volume'].values.astype(float) if 'Volume' in data.columns else np.ones(n)
    
    returns = np.full(n, np.nan)
    returns[1:] = (close[1:] - close[:-1]) / close[:-1]
    
    sma5 = np.full(n, np.nan)
    sma10 = np.full(n, np.nan)
    sma20 = np.full(n, np.nan)
    for i in range(4, n):
        sma5[i] = np.mean(close[i-4:i+1])
    for i in range(9, n):
        sma10[i] = np.mean(close[i-9:i+1])
    for i in range(19, n):
        sma20[i] = np.mean(close[i-19:i+1])
    
    volatility = np.full(n, np.nan)
    for i in range(19, n):
        volatility[i] = np.std(returns[i-19:i+1])
    
    rsi = np.full(n, np.nan)
    if TALIB_AVAILABLE:
        try:
            rsi_raw = talib.RSI(close, timeperiod=14)
            if rsi_raw is not None:
                rsi = rsi_raw
        except Exception:
            pass
    
    vol_change = np.zeros(n)
    vol_change[0] = np.nan
    np.divide(volume[1:] - volume[:-1], volume[:-1], out=vol_change[1:], where=volume[:-1] > 0)
    
    high_low_range = np.zeros(n)
    np.divide(high - low, close, out=high_low_range, where=(close > 0) & ((high - low) > 0))
    
    sma5_ratio = np.full(n, np.nan)
    np.divide(close, sma5, out=sma5_ratio, where=sma5 > 0)
    sma10_ratio = np.full(n, np.nan)
    np.divide(close, sma10, out=sma10_ratio, where=sma10 > 0)
    sma20_ratio = np.full(n, np.nan)
    np.divide(close, sma20, out=sma20_ratio, where=sma20 > 0)
    rsi_norm = rsi / 100.0
    
    feature_matrix = np.column_stack([
        returns, sma5_ratio, sma10_ratio, sma20_ratio,
        volatility, rsi_norm, vol_change, high_low_range
    ])
    
    return {
        'close': close, 'high': high, 'low': low, 'open': open_price, 'volume': volume,
        'returns': returns, 'volatility': volatility, 'rsi': rsi,
        'high_low_range': high_low_range, 'features': feature_matrix, 'n': n,
    }


def _calculate_ml_predict(data: pd.DataFrame, params: dict, line_colors: dict, model_type: str = 'rf') -> Indicator:
    lookback = int(params.get('lookback', 200))
    horizon = int(params.get('horizon', 5))
    
    if model_type == 'xgb':
        try:
            from xgboost import XGBRegressor
        except ImportError:
            warnings.warn("xgboost is required for ML Predict (XGBoost) indicator")
            return None
        indicator_name = 'ML Predict (XGBoost)'
    else:
        try:
            from sklearn.ensemble import RandomForestRegressor
            from sklearn.preprocessing import StandardScaler
        except ImportError:
            warnings.warn("scikit-learn is required for ML Predict (Random Forest) indicator")
            return None
        indicator_name = 'ML Predict (Random Forest)'
    
    feat = _build_ml_features(data)
    n = feat['n']
    close = feat['close']
    feature_matrix = feat['features']
    volatility = feat['volatility']
    rsi = feat['rsi']
    high_low_range = feat['high_low_range']
    returns = feat['returns']
    
    if n < lookback + 50:
        return None
    
    target = np.full(n, np.nan)
    target[:-1] = close[1:]
    
    predicted = np.full(n, np.nan)
    
    train_start = max(50, n - lookback)
    
    valid_train = np.arange(train_start, n - 1)
    valid_mask = ~np.any(np.isnan(feature_matrix[valid_train]), axis=1) & ~np.isnan(target[valid_train])
    train_idx = valid_train[valid_mask]
    
    if len(train_idx) < 30:
        return None
    
    X_train = feature_matrix[train_idx]
    y_train = target[train_idx]
    
    if model_type == 'xgb':
        from sklearn.preprocessing import StandardScaler
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        model = XGBRegressor(
            n_estimators=100,
            max_depth=6,
            learning_rate=0.1,
            min_child_weight=5,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbosity=0,
            n_jobs=-1
        )
        model.fit(X_train_scaled, y_train)
    else:
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        model = RandomForestRegressor(
            n_estimators=100,
            max_depth=10,
            min_samples_leaf=5,
            random_state=42,
            n_jobs=-1
        )
        model.fit(X_train_scaled, y_train)
    
    predict_from = train_start
    predict_to = n - 1
    predict_indices = np.arange(predict_from, predict_to)
    
    valid_pred_mask = ~np.any(np.isnan(feature_matrix[predict_indices]), axis=1)
    predict_indices = predict_indices[valid_pred_mask]
    
    if len(predict_indices) > 0:
        X_pred = feature_matrix[predict_indices]
        X_pred_scaled = scaler.transform(X_pred)
        preds = model.predict(X_pred_scaled)
        predicted[predict_indices] = preds
    
    future_predicted = np.full(n + horizon, np.nan)
    future_predicted[:n] = predicted
    
    last_features = feature_matrix[n - 1].reshape(1, -1)
    if not np.any(np.isnan(last_features)):
        last_scaled = scaler.transform(last_features)
        next_pred = model.predict(last_scaled)[0]
        
        future_close = close.copy()
        for h in range(horizon):
            future_close = np.append(future_close, next_pred)
            
            f_ret = (next_pred - future_close[-2]) / future_close[-2] if future_close[-2] != 0 else 0
            f_sma5 = np.mean(future_close[-5:])
            f_sma10 = np.mean(future_close[-10:]) if len(future_close) >= 10 else np.mean(future_close)
            f_sma20 = np.mean(future_close[-20:]) if len(future_close) >= 20 else np.mean(future_close)
            f_sma5_r = next_pred / f_sma5 if f_sma5 > 0 else 1.0
            f_sma10_r = next_pred / f_sma10 if f_sma10 > 0 else 1.0
            f_sma20_r = next_pred / f_sma20 if f_sma20 > 0 else 1.0
            f_vol = volatility[n - 1] if not np.isnan(volatility[n - 1]) else 0
            f_rsi = rsi[n - 1] / 100.0 if not np.isnan(rsi[n - 1]) else 0.5
            f_vchange = 0
            f_hl = high_low_range[n - 1]
            
            f_features = np.array([[f_ret, f_sma5_r, f_sma10_r, f_sma20_r, f_vol, f_rsi, f_vchange, f_hl]])
            f_scaled = scaler.transform(f_features)
            next_pred = model.predict(f_scaled)[0]
            future_predicted[n + h] = next_pred
    
    predicted_line = future_predicted[:n]
    future_line = future_predicted[n - 1:]
    
    predicted_clean = np.where(np.isnan(predicted_line), np.nan, predicted_line)
    future_clean = np.where(np.isnan(future_line), np.nan, future_line)
    
    indicator = Indicator(indicator_name, Indicator.OVERLAY)
    indicator.parameters = params
    indicator.add_line(PlotLine(
        'Predicted',
        predicted_clean,
        line_colors.get('Predicted', '#E040FB' if model_type == 'rf' else '#00E676')
    ))
    indicator.add_line(PlotLine(
        'Future',
        future_clean,
        line_colors.get('Future', '#FF6EC7' if model_type == 'rf' else '#76FF03')
    ))
    
    return indicator