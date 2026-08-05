# Дедупликация активностей при синхронизации (Activity dedup for sync — BACKLOG #228)
#
# Primary-ключ дедупа — внешний ID активности (Coros labelId и т.п.).
# Fallback — окно ±DEDUP_TIME_WINDOW_SEC по begin_ts, ТОЛЬКО для legacy-строк
# без внешнего ID (импортированных до Этапа 3) и старых DeletedTraining.
# (Primary dedup key is the brand's activity id; the time-window fallback
#  exists only for legacy rows imported before external ids were stored.)

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.config.constants import DEDUP_TIME_WINDOW_SEC
from src.models import TrainingSession, DeletedTraining
from src.services.sync.utils import ensure_aware_utc


@dataclass
class DedupState:
    """Снимок существующих/удалённых тренировок пользователя для дедупа
    (Snapshot of a user's existing/deleted trainings for dedup)."""
    ext_ids: set = field(default_factory=set)          # внешние ID существующих сессий
    legacy_begins: list = field(default_factory=list)  # begin_ts сессий БЕЗ внешнего ID
    deleted_by_ext: dict = field(default_factory=dict)  # ext_id -> DeletedTraining
    deleted_legacy: list = field(default_factory=list)  # DeletedTraining без внешнего ID


def load_dedup_state(db, user_id: int, brand: str, db_since: Optional[datetime]) -> DedupState:
    """Собрать состояние дедупа: внешние ID — за всю историю (дёшево),
    legacy-строки по времени — только в окне db_since (как раньше).
    (Ext ids are loaded for all history — cheap; legacy time rows only within the window.)"""
    state = DedupState()

    state.ext_ids = {r[0] for r in db.query(TrainingSession.external_activity_id).filter(
        TrainingSession.user_id == user_id,
        TrainingSession.source_brand == brand,
        TrainingSession.external_activity_id.isnot(None),
    ).all()}

    legacy_q = db.query(TrainingSession.begin_ts).filter(
        TrainingSession.user_id == user_id,
        TrainingSession.external_activity_id.is_(None),
    )
    if db_since is not None:
        legacy_q = legacy_q.filter(TrainingSession.begin_ts >= db_since)
    state.legacy_begins = [ensure_aware_utc(r[0]) for r in legacy_q.all() if r[0]]

    deleted_q = db.query(DeletedTraining).filter(DeletedTraining.user_id == user_id)
    if db_since is not None:
        deleted_q = deleted_q.filter(DeletedTraining.begin_ts >= db_since)
    for d in deleted_q.all():
        if d.external_activity_id and d.source_brand == brand:
            state.deleted_by_ext[d.external_activity_id] = d
        elif d.begin_ts:
            state.deleted_legacy.append(d)
    return state


def near_any(begin_ts: Optional[datetime], timestamps: list,
             window_sec: int = DEDUP_TIME_WINDOW_SEC) -> bool:
    """Есть ли таймстемп в окне ±window_sec (Is any timestamp within ±window_sec)."""
    if begin_ts is None:
        return False
    bt = ensure_aware_utc(begin_ts)
    return any(abs((ensure_aware_utc(t) - bt).total_seconds()) < window_sec for t in timestamps)


def is_duplicate(state: DedupState, ext_id: Optional[str],
                 begin_ts: Optional[datetime]) -> bool:
    """Дубликат ли активность: сперва по внешнему ID, затем окно для legacy-строк.
    (Duplicate check: external id first, then the legacy time window.)"""
    if ext_id and ext_id in state.ext_ids:
        return True
    return near_any(begin_ts, state.legacy_begins)


def find_deleted_match(state: DedupState, ext_id: Optional[str],
                       begin_ts: Optional[datetime]) -> Optional[DeletedTraining]:
    """Найти ранее удалённую тренировку: по внешнему ID, затем окно по времени.
    (Find previously deleted training: by external id, then by time window.)"""
    if ext_id and ext_id in state.deleted_by_ext:
        return state.deleted_by_ext[ext_id]
    if begin_ts is None:
        return None
    bt = ensure_aware_utc(begin_ts)
    for d in state.deleted_legacy:
        if abs((ensure_aware_utc(d.begin_ts) - bt).total_seconds()) < DEDUP_TIME_WINDOW_SEC:
            return d
    return None
