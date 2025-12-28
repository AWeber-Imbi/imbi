import fastapi

from .status import status_router

routers: list[fastapi.APIRouter] = [status_router]

__all__ = ['routers']
