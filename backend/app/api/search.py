"""Vorschläge für das Suchfeld."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..search import suggest as suggestions
from .deps import require_user

router = APIRouter(
    prefix="/api/search", tags=["search"], dependencies=[Depends(require_user)]
)


@router.get("/suggest")
def suggest(q: str = Query("", alias="q"), limit: int = 14) -> dict:
    """Tags, Ordner, Looks, Sammlungen und Dateinamen zum angefangenen Wort."""
    return {"query": q, "items": suggestions.suggest(q, limit)}
