"""
RSI и Momentum индикаторы
"""

import numpy as np
import pandas as pd
from typing import Union


def calculate_momentum(data: Union[pd.Series, np.ndarray], period: int = 10) -> Union[pd.Series, np.ndarray]:
    """
    Расчет momentum (изменение цены за период)
    Эквивалент ta.mom() из Pine Script
    
    Args:
        data: Массив или Series с ценами
        period: Период для расчета momentum
    
    Returns:
        Массив momentum значений
    """
    if isinstance(data, pd.Series):
        return data - data.shift(period)
    else:
        # Для numpy array
        result = np.empty_like(data, dtype=float)
        result[:period] = np.nan
        result[period:] = data[period:] - data[:-period]
        return result


def calculate_rsi(data: Union[pd.Series, np.ndarray], period: int = 14) -> Union[pd.Series, np.ndarray]:
    """
    Расчет RSI (Relative Strength Index)
    Эквивалент ta.rsi() из Pine Script
    
    Args:
        data: Массив или Series с ценами
        period: Период для расчета RSI (по умолчанию 14)
    
    Returns:
        Массив RSI значений (0-100)
    """
    if isinstance(data, pd.Series):
        # Для pandas
        delta = data.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    else:
        # Для numpy array
        delta = np.diff(data, prepend=np.nan)
        
        # Расчет средних выигрышей и потерь
        gains = np.where(delta > 0, delta, 0)
        losses = np.where(delta < 0, -delta, 0)
        
        gain_avg = np.full_like(data, np.nan, dtype=float)
        loss_avg = np.full_like(data, np.nan, dtype=float)
        
        # Простое скользящее среднее для первых period баров
        gain_avg[period] = np.mean(gains[1:period+1])
        loss_avg[period] = np.mean(losses[1:period+1])
        
        # Экспоненциальное сглаживание для остальных
        for i in range(period + 1, len(data)):
            gain_avg[i] = (gain_avg[i-1] * (period - 1) + gains[i]) / period
            loss_avg[i] = (loss_avg[i-1] * (period - 1) + losses[i]) / period
        
        # Расчет RS и RSI
        rs = np.divide(gain_avg, loss_avg, where=loss_avg != 0, out=np.full_like(gain_avg, np.nan))
        rsi = 100 - (100 / (1 + rs))
        
        return rsi


def calculate_rsi_with_momentum(close: Union[pd.Series, np.ndarray], 
                                 mom_period: int = 10, 
                                 rsi_period: int = 14) -> tuple:
    """
    Комбинированный расчет Momentum + RSI (как в Pine Script)
    rsiSrc = ta.mom(close, 10)
    rsiVal = ta.rsi(rsiSrc, rsiLength)
    
    Args:
        close: Массив/Series с ценами закрытия
        mom_period: Период для momentum
        rsi_period: Период для RSI
    
    Returns:
        Кортеж (momentum_values, rsi_values)
    """
    momentum = calculate_momentum(close, mom_period)
    rsi = calculate_rsi(momentum, rsi_period)
    return momentum, rsi
