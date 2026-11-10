from fastapi import APIRouter
from app.api.routes import health, gee_test, farm, farms

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(gee_test.router)
api_router.include_router(farm.router)
api_router.include_router(farms.router)