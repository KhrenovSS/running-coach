# Фиксированные константы проекта (Fixed project constants — not env-configurable)
import random
from typing import Final

# Пороги темпа и сегментации (Pace and segmentation thresholds)
MAX_CREDIBLE_PACE: Final[float] = 3.0
MIN_SEGMENT_DISTANCE_KM: Final[float] = 0.2
VARIABILITY_THRESHOLD: Final[float] = 1.0
PACE_SMOOTHING_WINDOW_SEC: Final[int] = 10
MIN_SMOOTHING_DISTANCE_M: Final[int] = 15
BIN_SIZE_M: Final[int] = 200

# Настройки очистки GPS (GPS cleaning settings)
MAX_GPS_JUMP_M: Final[float] = 100.0
MIN_DISTANCE_FOR_VALID_SEGMENT_M: Final[float] = 50.0

# Период синхронизации метрик здоровья (Health sync days)
HEALTH_SYNC_DAYS: Final[int] = 180

# Пороги пульсовых зон в процентах от max_hr (HR zone thresholds as % of max_hr)
HR_ZONE_1_MAX_PCT: Final[float] = 0.70
HR_ZONE_2_MAX_PCT: Final[float] = 0.80
HR_ZONE_3_MAX_PCT: Final[float] = 0.87
HR_ZONE_4_MAX_PCT: Final[float] = 0.93

# Настройки погоды Open-Meteo (Open-Meteo weather settings)
WEATHER_API_URL: Final[str] = "https://archive-api.open-meteo.com/v1/archive"
WEATHER_CACHE_TTL_SECONDS: Final[int] = 3600

# Настройки отображения (Display settings)
DISTANCE_DECIMALS: Final[int] = 1
PACE_DECIMALS: Final[int] = 2
HR_DISPLAY_UNIT: Final[str] = "уд/мин"
CADENCE_DISPLAY_UNIT: Final[str] = "spm"

# Тайминги (Timing)
CACHE_TTL_SECONDS: Final[int] = 300
SYNC_HEALTH_INTERVAL: Final[int] = 21600
SYNC_ACTIVITY_INTERVAL: Final[int] = 3600
JITTER_FACTOR: Final[float] = 0.2


def with_jitter(interval_seconds: int, factor: float = JITTER_FACTOR) -> int:
    """Применить jitter к интервалу: interval ± factor*interval.
    Apply jitter to an interval: interval ± factor*interval.
    """
    return int(interval_seconds * random.uniform(1 - factor, 1 + factor))


# Настройки детекции интервалов (Interval detection settings)
DEFAULT_PACE_THRESHOLD: Final[float] = 1.0          # мин/км — разница между базовым темпом и work-фазой
DEFAULT_MIN_PHASE_DURATION_SEC: Final[int] = 60     # сек — мин. длительность фазы
DEFAULT_MIN_PHASE_DISTANCE_M: Final[int] = 200      # м — мин. дистанция фазы
DEFAULT_HR_LAG_SEC: Final[int] = 5                  # сек — лаг пульса
DEFAULT_MIN_OSCILLATIONS: Final[int] = 3            # мин. число осцилляций для interval

# Пороги классификации тренировок (Training classification thresholds)
MIN_EFFECTIVE_PACE_GAP: Final[float] = 0.5        # мин/км — мин. adaptive gap для детекции осцилляций
RECOVERY_MAX_HR_PCT: Final[float] = 0.70          # max % от max_hr для recovery
EASY_MAX_HR_PCT: Final[float] = 0.75              # max % от max_hr для easy
EASY_MIN_Z2_PCT: Final[float] = 60.0              # мин. % времени в Z2 для easy
RECOVERY_MAX_Z4_PCT: Final[float] = 5.0           # макс. % времени в Z4+ для recovery
LONG_MAX_Z4_PCT: Final[float] = 15.0              # макс. % времени в Z4+ для long
EASY_MAX_Z4_SEGMENT_MIN: Final[float] = 3.0       # макс. длительность Z4+ сегмента для easy (мин)

# Диапазон достоверного темпа для графика HR/pace (Plausible pace range for HR/pace chart, мин/км)
CHART_MIN_PACE_MIN_PER_KM: Final[float] = 3.0     # быстрее — считаем GPS-шумом (faster → GPS noise)
CHART_MAX_PACE_MIN_PER_KM: Final[float] = 10.0    # медленнее — ходьба/остановка (slower → walking/stop)

# Интервалы синхронизации per-user (Per-user sync interval settings)
MIN_ACTIVITY_SYNC_INTERVAL_MIN: Final[int] = 15
MIN_HEALTH_SYNC_INTERVAL_MIN: Final[int] = 30
MAX_SYNC_INTERVAL_MIN: Final[int] = 1440
DEFAULT_ACTIVITY_SYNC_INTERVAL_MIN: Final[int] = 60
DEFAULT_HEALTH_SYNC_INTERVAL_MIN: Final[int] = 480

# Дедупликация тренировок (Training dedup — BACKLOG #228)
DEDUP_TIME_WINDOW_SEC: Final[int] = 120  # окно матчинга по времени для legacy-строк без внешнего ID

# Адаптивный максимальный пульс (Adaptive max HR — auto-raise / suggest lowering)
HR_SMOOTH_MEDIAN_WINDOW: Final[int] = 5      # окно скользящей медианы пика — фильтр одиночных выбросов (rolling-median window, spike filter)
MAX_HR_CAP: Final[int] = 220                 # выше — артефакт датчика; диапазон согласован с src/exceptions.py (above → sensor artifact)
MAX_HR_CONFIRM_COUNT: Final[int] = 3         # превышений за окно для принудительного обновления (exceedances to force-update)
MAX_HR_CONFIRM_WINDOW_DAYS: Final[int] = 30  # окно подтверждения превышений (confirmation window)
MAX_HR_LOWER_WINDOW_DAYS: Final[int] = 90    # окно наблюдения для предложения снизить (lowering observation window)
MAX_HR_LOWER_MIN_INTENSE: Final[int] = 5     # минимум интервальных/темповых в окне (min intense workouts in window)
MAX_HR_LOWER_MARGIN_BPM: Final[int] = 5      # пик ≤ max_hr − margin → кандидат на снижение (peak below profile by margin → suggest)
MAX_HR_SUGGEST_COOLDOWN_DAYS: Final[int] = 30  # не повторять предложение чаще (suggestion cooldown)

# Надёжность синхронизации (Sync reliability — BACKLOG #227)
SYNC_FAILURE_NOTIFY_THRESHOLD: Final[int] = 3    # подряд сбоев до Telegram-уведомления (consecutive failures before notify)
SYNC_BACKOFF_MAX_EXP: Final[int] = 5             # cap экспоненты backoff: 2^5 = 32× интервала (backoff exponent cap)
WATCH_API_PAGE_THROTTLE_SEC: Final[float] = 0.5  # пауза между страницами list_activities (page throttle, unofficial API)
WATCH_TOKEN_TTL_HOURS: Final[int] = 24           # консервативный TTL кэша токена (conservative token cache TTL)

# --- Физиологические метрики тренировки (Workout physio metrics — DEV_PLAN §9 D2) ---
# Потребитель — коуч (workout_insights.computed_json); интерпретация — за LLM.

# Кардиодрейф / decoupling Pa:HR (cardiac drift)
DRIFT_WARMUP_MIN: Final[int] = 5             # отброс разогрева перед расчётом (warmup discard)
DRIFT_MIN_STEADY_MIN: Final[int] = 25        # минимум steady-времени для применимости (min steady window)
DRIFT_MAX_SAMPLE_GAP_SEC: Final[int] = 10    # разрыв больше → автопауза, интервал выброшен (auto-pause gap)
DRIFT_MIN_MOVING_SPEED_MS: Final[float] = 0.5  # медленнее → стоим (standing threshold)
DRIFT_MIN_HR_COVERAGE: Final[float] = 0.8    # доля moving-сэмплов с HR (min HR coverage)
DRIFT_MAX_PACE_CV: Final[float] = 0.10       # CV по-км GAP-темпов выше → variable_pace (steady-pace gate)
DRIFT_MODERATE_PCT: Final[float] = 3.0       # drift выше → flag=moderate
DRIFT_HIGH_PCT: Final[float] = 5.0           # drift выше → flag=high (маркер детренированности/жары)

# Высота и grade-adjusted pace (elevation smoothing + GAP, Minetti 2002)
ALT_SMOOTH_MEDIAN_WINDOW: Final[int] = 5     # скользящая медиана — выбросы барометра/GPS (median window)
ALT_SMOOTH_MEAN_WINDOW: Final[int] = 5       # скользящее среднее — ступеньки квантования (mean window)
ELEV_MIN_DELTA_M: Final[float] = 1.0         # гистерезис набора/спуска (gain/loss hysteresis)
GAP_MAX_GRADE: Final[float] = 0.30           # клип уклона — граница валидности полинома Minetti (grade clip)
GAP_GRADE_WINDOW_M: Final[float] = 60.0      # окно локального уклона для посэмплового фактора (local grade window)
GAP_MIN_ALT_COVERAGE: Final[float] = 0.8     # доля точек с высотой, ниже → GAP недоступен (min alt coverage)
HILLY_GAIN_M_PER_KM: Final[float] = 10.0     # набор на км выше → «холмистая» (hilly threshold)

# Персональная базовая линия HR↔GAP-темп (personal HR↔pace baseline, OLS)
BASELINE_WINDOW_DAYS: Final[int] = 120       # окно истории (history window)
BASELINE_MIN_POINTS: Final[int] = 30         # минимум км-точек для регрессии (min km-points)
BASELINE_MIN_SESSIONS: Final[int] = 5        # минимум сессий (min sessions)
BASELINE_SKIP_FIRST_KM: Final[int] = 1       # первый км исключён: разогрев + колено (skip warmup km)
BASELINE_Z_FLAG: Final[float] = 1.5          # |z| выше → флаг hr_above/below_baseline (z-flag threshold)
BASELINE_TYPES: Final[tuple] = ("easy", "long", "recovery")  # steady-типы для регрессии (steady types)
BASELINE_PACE_PREDICT_MIN: Final[float] = 3.5   # прогноз темпа быстрее → None (prediction sanity floor, min/km)
BASELINE_PACE_PREDICT_MAX: Final[float] = 12.0  # прогноз темпа медленнее → None (prediction sanity ceiling)
BASELINE_PACE_HR_BAND_BPM: Final[int] = 10      # полоса пульса под потолком для медианы темпа (HR band below ceiling)
BASELINE_PACE_BAND_MIN_POINTS: Final[int] = 5   # минимум км-точек в полосе (min km-points in band)
BASELINE_HR_AT_PACE_BAND_MIN_KM: Final[float] = 0.25  # полоса темпа ±15 с/км для медианы HR (pace band for HR median)
BASELINE_HR_PREDICT_MIN: Final[int] = 90        # прогноз пульса ниже → None (HR prediction sanity floor, bpm)
BASELINE_HR_PREDICT_MAX: Final[int] = 200       # прогноз пульса выше → None (HR prediction sanity ceiling, bpm)

# Жара (heat)
HEAT_TEMP_THRESHOLD_C: Final[int] = 20       # температура старта выше → heat_flag (heat threshold)

# Отложенный разбор тренировки (Deferred workout review — DEV_PLAN §9 D5)
REVIEW_JOB_INTERVAL_MIN: Final[int] = 10     # период джобы pending-разборов (job interval)
REVIEW_WAIT_MAX_MIN: Final[int] = 30         # таймаут ожидания тапа RPE/боли (tap-wait timeout)
REVIEW_AFTER_RPE_DELAY_SEC: Final[int] = 120  # грейс после RPE-тапа на тап боли (post-RPE grace)
REVIEW_PENDING_TTL_H: Final[int] = 24        # старше → expired молча (pending TTL)
REVIEW_STALE_RUNNING_MIN: Final[int] = 15    # зависший running → re-claim (stale running)
