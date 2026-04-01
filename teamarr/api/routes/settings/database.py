"""Database configuration settings routes."""

from sqlite3 import Connection

from fastapi import APIRouter, Depends

from teamarr.database.connection import get_connection
from teamarr.database.settings import get_database_settings, update_database_settings

from .models import DatabaseSettingsModel

router = APIRouter(prefix="/settings/database", tags=["settings"])


@router.get("", response_model=DatabaseSettingsModel)
def get_settings(conn: Connection = Depends(get_connection)) -> DatabaseSettingsModel:
    """Get stored database configuration."""
    settings = get_database_settings(conn)
    return DatabaseSettingsModel(
        backend=settings.backend,
        postgres_url=settings.postgres_url,
        postgres_database=settings.postgres_database,
        postgres_username=settings.postgres_username,
        postgres_password=settings.postgres_password,
    )


@router.put("", response_model=DatabaseSettingsModel)
def update_settings(
    payload: DatabaseSettingsModel,
    conn: Connection = Depends(get_connection),
) -> DatabaseSettingsModel:
    """Update stored database configuration."""
    update_database_settings(
        conn,
        backend=payload.backend,
        postgres_url=payload.postgres_url,
        postgres_database=payload.postgres_database,
        postgres_username=payload.postgres_username,
        postgres_password=payload.postgres_password,
    )
    settings = get_database_settings(conn)
    return DatabaseSettingsModel(
        backend=settings.backend,
        postgres_url=settings.postgres_url,
        postgres_database=settings.postgres_database,
        postgres_username=settings.postgres_username,
        postgres_password=settings.postgres_password,
    )
