"""
Configuration for RSI Momentum Divergence Zones Indicator
Переводит параметры из Pine Script в Python
"""

# ===== RSI Settings =====
RSI_LENGTH = 14  # Длина периода для расчета RSI
RSI_MOM_PERIOD = 10  # Период для momentum (ta.mom)

# ===== Divergence Detection Settings =====
ENABLE_DIVERGENCE_DETECTION = True  # Включить обнаружение расхождений
SHOW_DIVERGENCE_ZONES = True  # Показывать зоны расхождений
QTY_DIVERGENCE_ZONES = 10  # Количество отрисовываемых зон

# ===== Pivot Detection Settings =====
DIV_LOOKBACK_RIGHT = 5  # Количество баров справа для поиска pivot
DIV_LOOKBACK_LEFT = 5  # Количество баров слева для поиска pivot
MIN_BARS_IN_RANGE = 5  # Минимальное расстояние между pivot'ами
MAX_BARS_IN_RANGE = 50  # Максимальное расстояние между pivot'ами

# ===== Colors =====
COLOR_BEARISH = '#ae4ce6'  # Медвежий цвет (фиолетовый)
COLOR_BULLISH = '#33c570'  # Бычий цвет (зеленый)
COLOR_TEXT = '#ffffff'  # Белый текст
COLOR_NEUTRAL = '#808080'  # Серый нейтральный

# ===== Plot Settings =====
PLOT_WIDTH_MAIN = 2  # Толщина основной линии
PLOT_WIDTH_BG = 6  # Толщина фоновой линии
COLOR_TRANSPARENCY = 70  # Прозрачность фоновых линий (0-100)

# ===== Line Extension =====
LINE_EXTENSION_BARS = 15  # На сколько баров расширять активные линии

# ===== Output Settings =====
EXPORT_FORMAT = 'csv'  # Формат экспорта: 'csv', 'json'
SAVE_CHARTS = True  # Сохранять ли графики в файл
CHART_DPI = 300  # Качество сохраняемых графиков

# ===== Agent decide RSI extremes (SKIP when long overbought / short oversold) =====
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30