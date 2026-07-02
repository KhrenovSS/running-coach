# Сборка веб-роутов в один APIRouter (Web routes bundled in one APIRouter)
from fastapi import APIRouter
from src.web.routes.pages import router as pages_router
from src.web.routes.uploads import router as uploads_router
from src.web.routes.sync import router as sync_router
from src.web.routes.logs import router as logs_router

web_router = APIRouter()
web_router.include_router(pages_router)
web_router.include_router(uploads_router)
web_router.include_router(sync_router)
web_router.include_router(logs_router)
