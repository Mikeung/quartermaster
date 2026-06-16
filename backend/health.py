import time

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

_start_time: float = time.time()


class HealthResponse(BaseModel):
    status: str
    uptime_seconds: float
    version: str
    environment: str


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health_check() -> HealthResponse:
    from backend.config import settings

    return HealthResponse(
        status="ok",
        uptime_seconds=round(time.time() - _start_time, 2),
        version=settings.app_version,
        environment=settings.app_env,
    )
