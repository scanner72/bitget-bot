"""
Модель для хранения данных уровня расхождения
"""

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class DivergenceLevel:
    """
    Класс для представления одного уровня расхождения
    Эквивалент type divLevel из Pine Script
    
    Attributes:
        bar_index_start: Индекс бара начала линии
        bar_index_end: Индекс бара конца линии
        level_price: Цена уровня (Y координата)
        is_bullish: True если бычье расхождение, False если медвежье
        is_active: Активна ли линия в данный момент
        creation_bar: На каком баре была создана линия
    """
    bar_index_start: int
    bar_index_end: int
    level_price: float
    is_bullish: bool
    is_active: bool = True
    creation_bar: Optional[int] = None

    def __post_init__(self):
        """Валидация данных после инициализации"""
        if self.bar_index_start > self.bar_index_end:
            raise ValueError("bar_index_start не может быть больше bar_index_end")
        if self.level_price < 0:
            raise ValueError("level_price не может быть отрицательной")

    def get_coordinates(self) -> Tuple[int, int, float, float]:
        """
        Возвращает координаты линии: (x1, x2, y1, y2)
        
        Returns:
            Кортеж (bar_start, bar_end, price, price)
        """
        return (self.bar_index_start, self.bar_index_end, self.level_price, self.level_price)

    def update_end(self, new_bar_index: int, new_price: Optional[float] = None):
        """
        Обновить конечную точку линии
        
        Args:
            new_bar_index: Новый индекс бара конца
            new_price: Новая цена уровня (если нужно изменить)
        """
        self.bar_index_end = new_bar_index
        if new_price is not None:
            self.level_price = new_price

    def to_dict(self) -> dict:
        """Преобразование в словарь для экспорта"""
        return {
            'bar_start': self.bar_index_start,
            'bar_end': self.bar_index_end,
            'price': self.level_price,
            'type': 'bullish' if self.is_bullish else 'bearish',
            'is_active': self.is_active,
            'created_at': self.creation_bar
        }


@dataclass
class DivergenceLineState:
    """
    Состояние динамической линии расхождения с отслеживанием пробоев
    Эквивалент логики из Pine Script функции plotDivergenceLevels()
    
    На каждом баре проверяется пробой, и линия может:
    - Оставаться сплошной и продолжаться вперед (если нет пробоя)
    - Стать пунктирной и остановиться (если произошел пробой)
    """
    bar_index_start: int       # Бар создания линии (bar_index - 5 в Pine Script)
    bar_index_created: int     # Бар обнаружения расхождения
    level_price: float         # Ценовой уровень линии (high для медвежьего, low для бычьего)
    is_bullish: bool           # True = бычье (проверяем high > level), False = медвежье (low < level)
    is_broken: bool = False    # Пробита ли линия?
    break_bar_index: Optional[int] = None  # На каком баре произошел пробой?
    line_extension: int = 15   # Баров продления активной линии вперёд (Pine: +15)
    
    def check_break(self, current_bar_index: int, current_high: float, current_low: float) -> bool:
        """
        Проверить наличие пробоя на текущем баре.
        
        Соответствует Pine Script логике:
        - Bullish: high > level_price (цена выше)
        - Bearish: low < level_price (цена ниже)
        
        Args:
            current_bar_index: Текущий индекс бара
            current_high: High текущего бара
            current_low: Low текущего бара
        
        Returns:
            True если произошел пробой на этом баре
        """
        if self.is_broken:
            return False  # Уже пробита ранее
        
        # Защита: линия должна содержаться минимум 10 баров перед проверкой пробоя
        if current_bar_index < self.bar_index_created + 10:
            return False
        
        # 0.1% от уровня — относительный порог, корректный для любой цены
        penetration = self.level_price * 0.001

        if self.is_bullish:
            if current_high > self.level_price + penetration:
                self.is_broken = True
                self.break_bar_index = current_bar_index
                return True
        else:
            if current_low < self.level_price - penetration:
                self.is_broken = True
                self.break_bar_index = current_bar_index
                return True
        
        return False
    
    def get_end_bar_for_drawing(self, current_bar_index: int) -> int:
        """
        Получить индекс конца линии для отрисовки.
        
        Логика из Pine Script:
        - Если НЕ пробита: продолжить до current_bar_index + 15
        - Если пробита: остановить на bar_index пробоя
        
        Args:
            current_bar_index: Текущий индекс бара
        
        Returns:
            Индекс бара, где заканчивается линия
        """
        if self.is_broken:
            # Пробита: линия заканчивается на баре пробоя
            return self.break_bar_index
        else:
            return current_bar_index + self.line_extension
    
    def get_line_style(self) -> str:
        """
        Получить стиль линии.
        
        Returns:
            'solid' если не пробита, 'dashed' если пробита
        """
        return 'dashed' if self.is_broken else 'solid'
    
    def should_show_background(self) -> bool:
        """
        Показывать ли фоновую линию (толстая, полупрозрачная).
        
        В Pine Script фоновая линия удаляется при пробое:
        expired.bgLine.delete()
        
        Returns:
            False если линия пробита, иначе True
        """
        return not self.is_broken
