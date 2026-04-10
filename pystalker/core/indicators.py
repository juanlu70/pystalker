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
    
    def __init__(self):
        self.indicators: Dict[str, Indicator] = {}
    
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
    def calculate_indicator(name: str, data: pd.DataFrame, params: Dict = None) -> Optional[Indicator]:
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
            if name == 'SMA':
                result = func(close, timeperiod=default_params['period'])
                line = PlotLine(f'SMA({default_params["period"]})', result, '#00BFFF')
                indicator.add_line(line)
            elif name == 'EMA':
                result = func(close, timeperiod=default_params['period'])
                line = PlotLine(f'EMA({default_params["period"]})', result, '#FFD700')
                indicator.add_line(line)
            elif name == 'BBANDS':
                upper, middle, lower = func(close, timeperiod=default_params['period'],
                                            nbdevup=default_params['nbdevup'], nbdevdn=default_params['nbdevdn'])
                indicator.add_line(PlotLine('Upper', upper, '#FF6B6B'))
                indicator.add_line(PlotLine('Middle', middle, '#4ECDC4'))
                indicator.add_line(PlotLine('Lower', lower, '#95E1D3'))
            elif name == 'SAR':
                result = func(high, low, acceleration=default_params['acceleration'], maximum=default_params['maximum'])
                indicator.add_line(PlotLine('SAR', result, '#00CED1'))
            elif name == 'MACD':
                macd, signal, hist = func(close, fastperiod=default_params['fastperiod'],
                                         slowperiod=default_params['slowperiod'],
                                         signalperiod=default_params['signalperiod'])
                indicator.add_line(PlotLine('MACD', macd, '#4169E1'))
                indicator.add_line(PlotLine('Signal', signal, '#FF8C00'))
                indicator.add_line(PlotLine('Histogram', hist, '#32CD32'))
            elif name == 'RSI':
                result = func(close, timeperiod=default_params['period'])
                indicator.add_line(PlotLine(f'RSI({default_params["period"]})', result, '#9370DB'))
            elif name == 'CCI':
                result = func(high, low, close, timeperiod=default_params['period'])
                indicator.add_line(PlotLine(f'CCI({default_params["period"]})', result, '#FFD700'))
            elif name == 'ADX':
                result = func(high, low, close, timeperiod=default_params['period'])
                indicator.add_line(PlotLine(f'ADX({default_params["period"]})', result, '#DA70D6'))
            elif name == 'ATR':
                result = func(high, low, close, timeperiod=default_params['period'])
                indicator.add_line(PlotLine(f'ATR({default_params["period"]})', result, '#00CED1'))
            elif name == 'MOM':
                result = func(close, timeperiod=default_params['period'])
                indicator.add_line(PlotLine(f'MOM({default_params["period"]})', result, '#FF8C00'))
            elif name == 'ROC':
                result = func(close, timeperiod=default_params['period'])
                indicator.add_line(PlotLine(f'ROC({default_params["period"]})', result, '#FFD700'))
            elif name == 'STOCH':
                slowk, slowd = func(high, low, close,
                                   fastk_period=default_params['fastk_period'],
                                   slowk_period=default_params['slowk_period'],
                                   slowd_period=default_params['slowd_period'])
                indicator.add_line(PlotLine('%K', slowk, '#4169E1'))
                indicator.add_line(PlotLine('%D', slowd, '#FF6347'))
            elif name == 'STOCHRSI':
                fastk, fastd = func(close, timeperiod=default_params['period'],
                                   fastk_period=default_params['fastk_period'],
                                   fastd_period=default_params['fastd_period'])
                indicator.add_line(PlotLine('FastK', fastk, '#4169E1'))
                indicator.add_line(PlotLine('FastD', fastd, '#FF6347'))
            elif name == 'WILLR':
                result = func(high, low, close, timeperiod=default_params['period'])
                indicator.add_line(PlotLine(f'WILLR({default_params["period"]})', result, '#FFD700'))
            elif name == 'OBV':
                result = func(close, volume)
                indicator.add_line(PlotLine('OBV', result, '#00CED1'))
            elif name == 'MFI':
                result = func(high, low, close, volume, timeperiod=default_params['period'])
                indicator.add_line(PlotLine(f'MFI({default_params["period"]})', result, '#9370DB'))
            
            return indicator
        except Exception as e:
            print(f"Error calculating indicator {name}: {e}")
            return None
    
    def add_indicator(self, name: str, data: pd.DataFrame, params: Dict = None) -> bool:
        indicator = self.calculate_indicator(name, data, params)
        if indicator:
            self.indicators[name] = indicator
            return True
        return False
    
    def remove_indicator(self, name: str):
        if name in self.indicators:
            del self.indicators[name]
    
    def get_indicator(self, name: str) -> Optional[Indicator]:
        return self.indicators.get(name)
    
    def get_all_indicators(self) -> Dict[str, Indicator]:
        return self.indicators


Manager = IndicatorManager