# Тонкие роуты синхронизации — делегируют в sync_service.run_sync_for_user (Thin sync routes — delegate to sync_service)

import threading
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.models import get_db, User, WatchCredential
from src.api.deps import get_current_user
from src.services.sync_service import run_sync_for_user
from src.web.state import _pending, _sync_tasks, _sync_tasks_lock

from src.utils.logger import get_logger

logger = get_logger("app")
router = APIRouter()


def _start_sync_thread(user_id: int, brand: str, sync_type: str) -> str:
    """Создать task_id, запустить синхронизацию в отдельном треде (Create task_id, start sync in a thread)."""
    task_id = str(uuid.uuid4())
    progress = {
        'task_id': task_id, 'step': 'queued', 'message': 'В очереди...',
        'total': 0, 'current': 0, 'synced': 0, 'errors': [], 'total_found': 0, 'done': False,
    }
    with _sync_tasks_lock:
        _sync_tasks[task_id] = progress

    def _run():
        pending = _pending if sync_type == 'activity' else None
        run_sync_for_user(user_id, brand, sync_type, progress=progress, pending=pending)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return task_id


@router.post('/sync/{brand}/run')
async def sync_run(brand: str, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    brand = brand.lower()
    cred = db.query(WatchCredential).filter(
        WatchCredential.user_id == current_user.id,
        WatchCredential.brand == brand,
        WatchCredential.is_active == True,
    ).first()
    if not cred or not cred.encrypted_password:
        return JSONResponse({'status': 'error', 'message': f'{brand.capitalize()} credentials not configured.'})
    task_id = _start_sync_thread(current_user.id, brand, 'activity')
    return JSONResponse({'task_id': task_id, 'status': 'started'})


@router.get('/sync/status/{task_id}')
async def sync_status(task_id: str):
    with _sync_tasks_lock:
        p = _sync_tasks.get(task_id)
    if not p:
        return JSONResponse({'status': 'error', 'message': 'Task not found'})
    return JSONResponse(p)


@router.post('/sync/{brand}/health')
async def sync_health(brand: str, db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    brand = brand.lower()
    cred = db.query(WatchCredential).filter(
        WatchCredential.user_id == current_user.id,
        WatchCredential.brand == brand,
        WatchCredential.is_active == True,
    ).first()
    if not cred or not cred.encrypted_password:
        return JSONResponse({'status': 'error', 'message': f'{brand.capitalize()} credentials not configured.'})
    task_id = _start_sync_thread(current_user.id, brand, 'health')
    return JSONResponse({'task_id': task_id, 'status': 'started'})


# Обратная совместимость: старые /coros/sync роуты (Backward compat: old /coros/sync routes)
@router.post('/coros/sync')
async def coros_sync_redirect(db: Session = Depends(get_db),
                              current_user: User = Depends(get_current_user)):
    return await sync_run('coros', db=db, current_user=current_user)


@router.post('/coros/sync/health')
async def coros_sync_health_redirect(db: Session = Depends(get_db),
                                     current_user: User = Depends(get_current_user)):
    return await sync_health('coros', db=db, current_user=current_user)


@router.get('/coros/sync/status/{task_id}')
async def coros_sync_status_redirect(task_id: str):
    return await sync_status(task_id)