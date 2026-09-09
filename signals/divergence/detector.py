"""
Детектор RSI расхождений - основной алгоритм
"""

from collections import deque
from typing import Tuple, List, Optional
import numpy as np
import pandas as pd

from signals.config import (
    RSI_LENGTH, RSI_MOM_PERIOD,
    DIV_LOOKBACK_LEFT, DIV_LOOKBACK_RIGHT,
    MIN_BARS_IN_RANGE, MAX_BARS_IN_RANGE
)
from signals.indicators import calculate_rsi_with_momentum, find_pivot_low, find_pivot_high
from signals.models import DivergenceLevel


class RSIDivergenceDetector:
    """
    Основной детектор RSI расхождений
    Преобразание логики из Pine Script в Python OOP
    """
    
    def __init__(self, df: pd.DataFrame, config: dict = None):
        """
        Инициализация детектора
        
        Args:
            df: DataFrame с OHLC данными
                Обязательные колонки: 'open', 'high', 'low', 'close'
            config: Словарь с параметрами (опционально)
        """
        self.df = df.copy()
        self.config = config or {}
        
        # Параметры из конфига или по умолчанию
        self.rsi_length = self.config.get('rsi_length', RSI_LENGTH)
        self.rsi_mom_period = self.config.get('rsi_mom_period', RSI_MOM_PERIOD)
        self.lookback_left = self.config.get('lookback_left', DIV_LOOKBACK_LEFT)
        self.lookback_right = self.config.get('lookback_right', DIV_LOOKBACK_RIGHT)
        self.min_bars = self.config.get('min_bars_in_range', MIN_BARS_IN_RANGE)
        self.max_bars = self.config.get('max_bars_in_range', MAX_BARS_IN_RANGE)
        
        # Хранилище результатов
        self.momentum = None
        self.rsi_values = None
        self.bull_divergences = deque(maxlen=self.config.get('max_divergences', 10))
        self.bear_divergences = deque(maxlen=self.config.get('max_divergences', 10))
        
        # Результаты последнего анализа бара
        self.last_analysis = {
            'found_pivot_low': False,
            'found_pivot_high': False,
            'is_bullish_div': False,
            'is_bearish_div': False,
            'rsi_value': None,
            'price_high': None,
            'price_low': None,
            'bar_index': -1
        }
    
    def calculate_indicators(self) -> bool:
        """
        Расчет индикаторов (Momentum и RSI)
        
        Returns:
            True если расчет успешен, False иначе
        """
        # Валидация входных данных
        min_required = self.rsi_length + self.rsi_mom_period + 5
        if len(self.df) < min_required:
            # Недостаточно данных — это не ошибка, а нормальное состояние для новой пары
            return False

        try:
            self.momentum, self.rsi_values = calculate_rsi_with_momentum(
                self.df['close'].values,
                mom_period=self.rsi_mom_period,
                rsi_period=self.rsi_length
            )
            
            # Добавить в DataFrame для удобства
            self.df['momentum'] = self.momentum
            self.df['rsi'] = self.rsi_values
            
            return True
        except Exception as e:
            # Тут логируем только реальные неожиданные ошибки
            import logging
            logging.getLogger(__name__).error(f"Unexpected error calculating indicators: {e}")
            return False
    
    def _in_range(self, pivot_bar_index: int, current_bar_index: int) -> bool:
        """
        Проверить, находится ли расстояние между pivot'ами в допустимом диапазоне
        Эквивалент _inRange() из Pine Script
        
        Args:
            pivot_bar_index: Индекс бара где был detection
            current_bar_index: Текущий индекс бара
        
        Returns:
            True если расстояние в диапазоне [min_bars, max_bars]
        """
        bar_count = current_bar_index - pivot_bar_index
        return self.min_bars <= bar_count <= self.max_bars
    
    def _detect_bullish_divergence(self, pivot_low_idx: Optional[int], 
                                   prior_pivot_low_idx: Optional[int],
                                   current_idx: int) -> Tuple[bool, str]:
        """
        Обнаружить бычье расхождение (Price LL, RSI HL)
        
        Returns:
            Кортеж (found, reason)
        """
        if pivot_low_idx is None or prior_pivot_low_idx is None:
            return False, "No pivot lows found"
        
        # RSI Higher Low (текущий RSI выше чем был на предыдущем pivot low)
        if pd.isna(self.rsi_values[pivot_low_idx]) or pd.isna(self.rsi_values[prior_pivot_low_idx]):
            return False, "RSI values are NaN"
        
        rsi_hl = self.rsi_values[pivot_low_idx] > self.rsi_values[prior_pivot_low_idx]
        
        # Price Lower Low (текущая цена ниже чем была на предыдущем pivot low)
        price_ll = self.df['low'].iloc[pivot_low_idx] < self.df['low'].iloc[prior_pivot_low_idx]
        
        # Проверить расстояние между pivot'ами
        bars_ok = self._in_range(prior_pivot_low_idx, current_idx)
        
        if rsi_hl and price_ll and bars_ok:
            return True, "Bullish divergence confirmed"
        
        reason = f"RSI HL: {rsi_hl}, Price LL: {price_ll}, Bars OK: {bars_ok}"
        return False, reason
    
    def _detect_bearish_divergence(self, pivot_high_idx: Optional[int], 
                                   prior_pivot_high_idx: Optional[int],
                                   current_idx: int) -> Tuple[bool, str]:
        """
        Обнаружить медвежье расхождение (Price HH, RSI LH)
        
        Returns:
            Кортеж (found, reason)
        """
        if pivot_high_idx is None or prior_pivot_high_idx is None:
            return False, "No pivot highs found"
        
        # RSI Lower High (текущий RSI ниже чем был на предыдущем pivot high)
        if pd.isna(self.rsi_values[pivot_high_idx]) or pd.isna(self.rsi_values[prior_pivot_high_idx]):
            return False, "RSI values are NaN"
        
        rsi_lh = self.rsi_values[pivot_high_idx] < self.rsi_values[prior_pivot_high_idx]
        
        # Price Higher High (текущая цена выше чем была на предыдущем pivot high)
        price_hh = self.df['high'].iloc[pivot_high_idx] > self.df['high'].iloc[prior_pivot_high_idx]
        
        # Проверить расстояние между pivot'ами
        bars_ok = self._in_range(prior_pivot_high_idx, current_idx)
        
        if rsi_lh and price_hh and bars_ok:
            return True, "Bearish divergence confirmed"
        
        reason = f"RSI LH: {rsi_lh}, Price HH: {price_hh}, Bars OK: {bars_ok}"
        return False, reason
    
    def detect_divergences(self) -> pd.DataFrame:
        """
        Основной метод обнаружения расхождений для всех баров
        
        Returns:
            DataFrame с результатами обнаружения расхождений
        """
        if self.momentum is None or self.rsi_values is None:
            self.calculate_indicators()
        
        results = []
        
        # Заполняем пустыми значениями начальные бары для сохранения длины
        for idx in range(self.lookback_right):
            current_bar = self.df.iloc[idx]
            results.append({
                'bar_index': idx,
                'timestamp': current_bar.name if isinstance(current_bar.name, pd.Timestamp) else None,
                'close': current_bar['close'],
                'high': current_bar['high'],
                'low': current_bar['low'],
                'rsi': self.rsi_values[idx] if self.rsi_values is not None else None,
                'momentum': self.momentum[idx] if self.momentum is not None else None,
                'found_pivot_low': False,
                'found_pivot_high': False,
                'bullish_divergence': False,
                'bearish_divergence': False,
                'bull_prior_idx': None,
                'bear_prior_idx': None
            })
        
        # Нужна история pivot'ов для сравнения
        for idx in range(self.lookback_right, len(self.df)):
            current_bar = self.df.iloc[idx]
            
            # Найти pivot low и high в текущей позиции
            pivot_low_idx = None
            pivot_high_idx = None
            
            # Поиск pivot в окне [-lookback_left : +lookback_right]
            window_start = max(0, idx - self.lookback_left)
            window_end = min(len(self.df), idx + self.lookback_right + 1)
            
            rsi_window = self.rsi_values[window_start:window_end]
            
            # Ищем локальные экстремумы
            if window_end - window_start > self.lookback_left + self.lookback_right:
                local_pivots_low = find_pivot_low(rsi_window, self.lookback_left, self.lookback_right)
                local_pivots_high = find_pivot_high(rsi_window, self.lookback_left, self.lookback_right)
                
                if local_pivots_low and local_pivots_low[-1][0] + window_start == idx:
                    pivot_low_idx = idx
                if local_pivots_high and local_pivots_high[-1][0] + window_start == idx:
                    pivot_high_idx = idx
            
            # Булевы значения для расхождений
            is_bullish_div = False
            is_bearish_div = False
            
            # Поиск предыдущих pivot'ов для сравнения (если нужны)
            bull_prior_idx = None
            bear_prior_idx = None

            if pivot_low_idx is not None and idx > self.max_bars:
                # Найти предыдущий pivot low
                for prev_idx in range(idx - 1, max(0, idx - self.max_bars), -1):
                    prev_window_start = max(0, prev_idx - self.lookback_left)
                    prev_window_end = min(len(self.df), prev_idx + self.lookback_right + 1)
                    
                    if prev_window_end - prev_window_start > self.lookback_left + self.lookback_right:
                        prev_rsi_window = self.rsi_values[prev_window_start:prev_window_end]
                        prev_pivots = find_pivot_low(prev_rsi_window, self.lookback_left, self.lookback_right)
                        
                        if prev_pivots and prev_pivots[-1][0] + prev_window_start == prev_idx:
                            found_bull, _ = self._detect_bullish_divergence(
                                pivot_low_idx, prev_idx, idx
                            )
                            if found_bull:
                                is_bullish_div = True
                                bull_prior_idx = prev_idx
                            break
            
            # Аналогично для медвежьего расхождения
            if pivot_high_idx is not None and idx > self.max_bars:
                for prev_idx in range(idx - 1, max(0, idx - self.max_bars), -1):
                    prev_window_start = max(0, prev_idx - self.lookback_left)
                    prev_window_end = min(len(self.df), prev_idx + self.lookback_right + 1)
                    
                    if prev_window_end - prev_window_start > self.lookback_left + self.lookback_right:
                        prev_rsi_window = self.rsi_values[prev_window_start:prev_window_end]
                        prev_pivots = find_pivot_high(prev_rsi_window, self.lookback_left, self.lookback_right)
                        
                        if prev_pivots and prev_pivots[-1][0] + prev_window_start == prev_idx:
                            found_bear, _ = self._detect_bearish_divergence(
                                pivot_high_idx, prev_idx, idx
                            )
                            if found_bear:
                                is_bearish_div = True
                                bear_prior_idx = prev_idx
                            break
            
            # Добавить результат
            result = {
                'bar_index': idx,
                'timestamp': current_bar.name if isinstance(current_bar.name, pd.Timestamp) else None,
                'close': current_bar['close'],
                'high': current_bar['high'],
                'low': current_bar['low'],
                'rsi': self.rsi_values[idx],
                'momentum': self.momentum[idx],
                'found_pivot_low': pivot_low_idx is not None,
                'found_pivot_high': pivot_high_idx is not None,
                'bullish_divergence': is_bullish_div,
                'bearish_divergence': is_bearish_div,
                'bull_prior_idx': bull_prior_idx,
                'bear_prior_idx': bear_prior_idx
            }
            results.append(result)
            
            # Обновить последний анализ
            if idx == len(self.df) - 1:  # Последний полностью сформированный бар
                self.last_analysis.update({
                    'found_pivot_low': pivot_low_idx is not None,
                    'found_pivot_high': pivot_high_idx is not None,
                    'is_bullish_div': is_bullish_div,
                    'is_bearish_div': is_bearish_div,
                    'rsi_value': self.rsi_values[idx],
                    'price_high': current_bar['high'],
                    'price_low': current_bar['low'],
                    'bar_index': idx
                })
        
        return pd.DataFrame(results)
    
    def detect_crossings(self, results_df: pd.DataFrame) -> List[dict]:
        """
        Обнаружить пересечения уровней дивергенции на последнем баре.
        Проходит по истории, создает зоны и проверяет их статус.
        """
        if results_df.empty:
            return []

        active_bull_zones = [] # [(price, bar_idx)]
        active_bear_zones = []
        
        crossings = []
        n = len(self.df)
        if n < 5: return []

        # Кэшируем результаты по bar_index
        results_by_idx = {int(row['bar_index']): row for _, row in results_df.iterrows()}

        # Кэшируем цены для скорости
        highs = self.df['high'].values
        lows = self.df['low'].values
        closes = self.df['close'].values

        for i in range(1, n):
            # 1. Проверяем пробои существующих зон
            # Bullish zones (support)
            for zone in active_bull_zones[:]:
                price, start_idx = zone
                # Пересечение вниз (пробой поддержки)
                if closes[i-1] >= price and closes[i] < price:
                    if i == n - 1: # Оповещаем только если пробой на последнем баре
                        crossings.append({
                            'type': 'LEVEL_CROSS_DOWN',
                            'level_price': price,
                            'zone_type': 'BULLISH',
                            'bar_index': i
                        })
                    active_bull_zones.remove(zone)
                # Или пересечение вверх (возврат над поддержку?) - по желанию
                
            # Bearish zones (resistance)
            for zone in active_bear_zones[:]:
                price, start_idx = zone
                # Пересечение вверх (пробой сопротивления)
                if closes[i-1] <= price and closes[i] > price:
                    if i == n - 1:
                        crossings.append({
                            'type': 'LEVEL_CROSS_UP',
                            'level_price': price,
                            'zone_type': 'BEARISH',
                            'bar_index': i
                        })
                    active_bear_zones.remove(zone)

            # 2. Добавляем новые зоны из результатов детектора
            row = results_by_idx.get(i)
            if row is not None:
                if row['bullish_divergence']:
                    active_bull_zones.append((row['low'], i))
                    # Ограничиваем количество
                    if len(active_bull_zones) > 10: active_bull_zones.pop(0)
                if row['bearish_divergence']:
                    active_bear_zones.append((row['high'], i))
                    if len(active_bear_zones) > 10: active_bear_zones.pop(0)
                    
        return crossings

    def add_divergence_level(self, bar_index: int, level_price: float, is_bullish: bool):
        """
        Добавить уровень расхождения в очередь
        
        Args:
            bar_index: Индекс бара
            level_price: Цена уровня
            is_bullish: Бычий ли уровень
        """
        div_level = DivergenceLevel(
            bar_index_start=max(0, bar_index - 5),
            bar_index_end=bar_index,
            level_price=level_price,
            is_bullish=is_bullish,
            creation_bar=bar_index
        )
        
        if is_bullish:
            self.bull_divergences.append(div_level)
        else:
            self.bear_divergences.append(div_level)
    
    def get_summary(self) -> dict:
        """
        Получить краткую сводку последнего анализа
        """
        return self.last_analysis