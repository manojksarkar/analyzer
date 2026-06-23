"""Notifications routes — /api/v1/notifications/*"""
from fastapi import APIRouter, Depends

from ..db.session import get_db
from ..db.in_memory import InMemoryDatabase
from ..middleware.auth import get_current_user
from ..models.domain import User
from ..services.errors import not_found

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _notif_dict(n) -> dict:
    return {
        "id": n.id,
        "project_id": n.project_id,
        "type": n.type,
        "message": n.message,
        "read_at": n.read_at.isoformat() if n.read_at else None,
        "created_at": n.created_at.isoformat(),
    }


@router.get("")
def list_notifications(
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    notifs = db.notifications.list_unread(current_user.id)
    return {"notifications": [_notif_dict(n) for n in notifs]}


@router.patch("/{notification_id}/read")
def mark_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    try:
        n = db.notifications.mark_read(notification_id)
    except KeyError:
        raise not_found("Notification", notification_id)
    return {"notification": _notif_dict(n)}


@router.post("/read-all")
def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: InMemoryDatabase = Depends(get_db),
):
    db.notifications.mark_all_read(current_user.id)
    return {"message": "All notifications marked as read."}
