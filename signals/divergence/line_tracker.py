"""
Отслеживание динамического состояния линий расхождений
Реализует логику из Pine Script функции plotDivergenceLevels()
"""

from typing import List, Dict, Tuple
from signals.models import DivergenceLineState


class DivergenceLineTracker:
    """
    Отслеживает динамическое состояние всех линий расхождений через все бары.
    
    На каждом баре проверяются существующие линии на пробой:
    - Бычьи: если high > level_price → пробой
    - Медвежьи: если low < level_price → пробой
    
    При пробое линия становится пунктирной и удаляется фоновая зона.
    """
    
    def __init__(self, max_lines: int = 10, line_extension: int = 15):
        self.max_lines = max_lines
        self.line_extension = line_extension
        self.bullish_lines: List[DivergenceLineState] = []
        self.bearish_lines: List[DivergenceLineState] = []
    
    def add_bullish_line(self, bar_index_created: int, level_price: float) -> None:
        """
        Добавить новую бычью линию расхождения
        
        Args:
            bar_index_created: Индекс бара обнаружения
            level_price: Ценовой уровень (low расхождения)
        """
        # Линия начинается за 5 баров до обнаружения (как в Pine Script)
        line = DivergenceLineState(
            bar_index_start=bar_index_created - 5,
            bar_index_created=bar_index_created,
            level_price=level_price,
            is_bullish=True,
            line_extension=self.line_extension,
        )
        self.bullish_lines.append(line)
        
        # Если превышено максимум, удалить самую старую
        if len(self.bullish_lines) > self.max_lines:
            self.bullish_lines.pop(0)
    
    def add_bearish_line(self, bar_index_created: int, level_price: float) -> None:
        """
        Добавить новую медвежью линию расхождения
        
        Args:
            bar_index_created: Индекс бара обнаружения
            level_price: Ценовой уровень (high расхождения)
        """
        # Линия начинается за 5 баров до обнаружения
        line = DivergenceLineState(
            bar_index_start=bar_index_created - 5,
            bar_index_created=bar_index_created,
            level_price=level_price,
            is_bullish=False,
            line_extension=self.line_extension,
        )
        self.bearish_lines.append(line)
        
        # Если превышено максимум, удалить самую старую
        if len(self.bearish_lines) > self.max_lines:
            self.bearish_lines.pop(0)
    
    def update_all_lines(self, current_bar_index: int, high: float, low: float) -> Tuple[List[DivergenceLineState], List[DivergenceLineState]]:
        """
        Обновить все линии по состоянию текущего бара.
        Проверить пробои и вернуть списки активных линий.
        
        Args:
            current_bar_index: Текущий индекс бара
            high: High текущего бара
            low: Low текущего бара
        
        Returns:
            Кортеж (bullish_lines, bearish_lines) - все активные линии с обновленным состоянием
        """
        # Проверить пробои для бычьих линий
        for bull_line in self.bullish_lines:
            bull_line.check_break(current_bar_index, high, low)
        
        # Проверить пробои для медвежьих линий
        for bear_line in self.bearish_lines:
            bear_line.check_break(current_bar_index, high, low)
        
        return self.bullish_lines, self.bearish_lines
    
    def get_active_bullish_lines(self) -> List[DivergenceLineState]:
        """Получить список активных бычьих линий"""
        return [line for line in self.bullish_lines]
    
    def get_active_bearish_lines(self) -> List[DivergenceLineState]:
        """Получить список активных медвежьих линий"""
        return [line for line in self.bearish_lines]
    
    def get_all_lines(self) -> List[DivergenceLineState]:
        """Получить все линии (и живые, и пробитые)"""
        return self.bullish_lines + self.bearish_lines
    
    def clear(self) -> None:
        """Очистить все линии"""
        self.bullish_lines.clear()
        self.bearish_lines.clear()
    
    def get_lines_for_bar_range(self, start_bar: int, end_bar: int) -> Dict[str, List[DivergenceLineState]]:
        """
        Получить все линии, которые активны в диапазоне баров
        
        Args:
            start_bar: Начальный индекс бара
            end_bar: Конечный индекс бара
        
        Returns:
            Словарь с ключами 'bullish' и 'bearish'
        """
        bullish = [
            line for line in self.bullish_lines 
            if line.bar_index_start <= end_bar and 
               (line.break_bar_index is None or line.break_bar_index >= start_bar)
        ]
        bearish = [
            line for line in self.bearish_lines 
            if line.bar_index_start <= end_bar and 
               (line.break_bar_index is None or line.break_bar_index >= start_bar)
        ]
        
        return {
            'bullish': bullish,
            'bearish': bearish
        }
