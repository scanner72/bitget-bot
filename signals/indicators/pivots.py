"""
Поиск pivot high и pivot low
"""

import numpy as np
import pandas as pd
from typing import Union, List, Tuple


def find_pivot_low(data: Union[pd.Series, np.ndarray], 
                   left_bars: int = 5, 
                   right_bars: int = 5) -> List[Tuple[int, float]]:
    """
    Поиск локальных минимумов (pivot low)
    Эквивалент ta.pivotlow() из Pine Script
    
    Args:
        data: Массив или Series с ценами
        left_bars: Количество баров слева для сравнения
        right_bars: Количество баров справа для сравнения
    
    Returns:
        Список кортежей (индекс, значение) найденных pivot low
    """
    if isinstance(data, pd.Series):
        data_arr = data.values
    else:
        data_arr = np.asarray(data)
    
    pivots = []
    window_size = left_bars + right_bars + 1
    
    if len(data_arr) < window_size:
        return pivots
    
    for i in range(left_bars, len(data_arr) - right_bars):
        # Проверяем, что значение в позиции i меньше всех соседних баров
        is_pivot = True
        window_start = i - left_bars
        window_end = i + right_bars + 1
        
        left_part = data_arr[window_start:i]
        right_part = data_arr[i+1:window_end]
        
        if np.any(left_part <= data_arr[i]) or np.any(right_part <= data_arr[i]):
            is_pivot = False
        
        if is_pivot:
            pivots.append((i, float(data_arr[i])))
    
    return pivots


def find_pivot_high(data: Union[pd.Series, np.ndarray], 
                    left_bars: int = 5, 
                    right_bars: int = 5) -> List[Tuple[int, float]]:
    """
    Поиск локальных максимумов (pivot high)
    Эквивалент ta.pivothigh() из Pine Script
    
    Args:
        data: Массив или Series с ценами
        left_bars: Количество баров слева для сравнения
        right_bars: Количество баров справа для сравнения
    
    Returns:
        Список кортежей (индекс, значение) найденных pivot high
    """
    if isinstance(data, pd.Series):
        data_arr = data.values
    else:
        data_arr = np.asarray(data)
    
    pivots = []
    window_size = left_bars + right_bars + 1
    
    if len(data_arr) < window_size:
        return pivots
    
    for i in range(left_bars, len(data_arr) - right_bars):
        # Проверяем, что значение в позиции i больше всех соседних баров
        is_pivot = True
        window_start = i - left_bars
        window_end = i + right_bars + 1
        
        left_part = data_arr[window_start:i]
        right_part = data_arr[i+1:window_end]
        
        if np.any(left_part >= data_arr[i]) or np.any(right_part >= data_arr[i]):
            is_pivot = False
        
        if is_pivot:
            pivots.append((i, float(data_arr[i])))
    
    return pivots


def get_last_pivot_low(data: Union[pd.Series, np.ndarray], 
                       lookback_left: int = 5, 
                       lookback_right: int = 5) -> Tuple[bool, float, int]:
    """
    Найти последний pivot low (если существует на текущей позиции)
    
    Args:
        data: Массив/Series данных
        lookback_left: Смотреть окна влево
        lookback_right: Смотреть окна вправо
    
    Returns:
        Кортеж (найден ли pivot, его значение, его индекс)
    """
    pivots = find_pivot_low(data, lookback_left, lookback_right)
    if pivots:
        idx, val = pivots[-1]
        return True, val, idx
    return False, np.nan, -1


def get_last_pivot_high(data: Union[pd.Series, np.ndarray], 
                        lookback_left: int = 5, 
                        lookback_right: int = 5) -> Tuple[bool, float, int]:
    """
    Найти последний pivot high (если существует на текущей позиции)
    
    Args:
        data: Массив/Series данных
        lookback_left: Смотреть окна влево
        lookback_right: Смотреть окна вправо
    
    Returns:
        Кортеж (найден ли pivot, его значение, его индекс)
    """
    pivots = find_pivot_high(data, lookback_left, lookback_right)
    if pivots:
        idx, val = pivots[-1]
        return True, val, idx
    return False, np.nan, -1


def bars_since(condition: List[bool]) -> int:
    """
    Найти количество баров с момента последнего True в списке
    Эквивалент ta.barssince() из Pine Script
    
    Args:
        condition: Список булевых значений
    
    Returns:
        Количество баров с последнего True (или -1 если нет True)
    """
    for i in range(len(condition) - 1, -1, -1):
        if condition[i]:
            return len(condition) - 1 - i
    return -1
