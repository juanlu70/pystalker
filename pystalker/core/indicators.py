"""
PyStalker - Technical Indicators using TA-Lib
"""
import numpy as np
import pandas as pd
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
        'BBANDS': [
            {'name': 'Upper', 'color': '#FF6B6B'},
            {'name': 'Middle', 'color': '#4ECDC4'},
            {'name': 'Lower', 'color': '#95E1D3'},
        ],
        'SAR': [{'name': 'SAR', 'color': '#00CED1'}],
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
            elif name == 'CCI':
                result = func(high, low, close, timeperiod=default_params['period'])
                indicator.add_line(PlotLine(f'CCI({default_params["period"]})', result, line_colors.get('CCI', '#FFD700')))
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
            elif name == 'STOCHRSI':
                fastk, fastd = func(close, timeperiod=default_params['period'],
                                   fastk_period=default_params['fastk_period'],
                                   fastd_period=default_params['fastd_period'])
                indicator.add_line(PlotLine('FastK', fastk, line_colors.get('FastK', '#4169E1')))
                indicator.add_line(PlotLine('FastD', fastd, line_colors.get('FastD', '#FF6347')))
            elif name == 'WILLR':
                result = func(high, low, close, timeperiod=default_params['period'])
                indicator.add_line(PlotLine(f'WILLR({default_params["period"]})', result, line_colors.get('WILLR', '#FFD700')))
            elif name == 'OBV':
                result = func(close, volume)
                indicator.add_line(PlotLine('OBV', result, line_colors.get('OBV', '#00CED1')))
            elif name == 'MFI':
                result = func(high, low, close, volume, timeperiod=default_params['period'])
                indicator.add_line(PlotLine(f'MFI({default_params["period"]})', result, line_colors.get('MFI', '#9370DB')))
            
            return indicator
        except Exception:
            return None