# Сборка роутов страниц в один APIRouter (Page routes bundled in one APIRouter)
from fastapi import APIRouter

from src.web.routes.pages.auth import router as auth_router
from src.web.routes.pages.index import router as index_router
from src.web.routes.pages.session import router as session_router
from src.web.routes.pages.settings import router as settings_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(index_router)
router.include_router(session_router)
router.include_router(settings_router)