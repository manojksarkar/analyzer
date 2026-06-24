"""Standardised HTTP errors used by all service and route layers."""
from fastapi import HTTPException, status


def not_found(resource: str, id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "NOT_FOUND",
                "message": f"{resource} {id} does not exist.",
                "status": 404},
    )


def forbidden(msg: str = "You do not have permission to perform this action.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "FORBIDDEN", "message": msg, "status": 403},
    )


def conflict(code: str, msg: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": msg, "status": 409},
    )


def bad_request(msg: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "VALIDATION_ERROR", "message": msg, "status": 400},
    )
