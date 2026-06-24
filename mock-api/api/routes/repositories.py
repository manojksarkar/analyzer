"""
Repository routes — /api/v1/repositories/*

Backs the new-project wizard's repository step:
  * POST /repositories/test-connection  — validate a repo URL, list branches
  * GET  /repositories/browse           — browse the source tree (folders+files)
  * POST /repositories/uploads          — upload a build-config file (defs / data dict)

Branch lists and the source tree are produced by api.services.repo_git, which
shells out to real git (`git ls-remote` for the connection test, a cached
depth-1 clone + `git ls-tree` for browsing) via backend/git_service.py.
Uploaded files are kept in a process-local store (resets on restart).
"""
from __future__ import annotations
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel

from ..middleware.auth import get_current_user
from ..models.domain import User
from ..services import repo_git
from ..services.errors import bad_request
from ..schemas import TestConnectionResponse, BrowseResponse, UploadResponse

router = APIRouter(prefix="/repositories", tags=["repositories"])

# Process-local upload store: upload_id -> metadata (+ bytes). Resets on restart.
_UPLOADS: dict[str, dict[str, Any]] = {}

# Upload guard rails.
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024   # 5 MB — defs / data-dictionary files are small
_ALLOWED_KINDS = {"preprocessor_definitions", "data_dictionary"}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TestConnectionRequest(BaseModel):
    repo_url: str
    repo_provider: str = "github"
    access_token: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/test-connection", responses={200: {"model": TestConnectionResponse}})
def test_connection(
    body: TestConnectionRequest,
    current_user: User = Depends(get_current_user),
):
    """Real connection test: `git ls-remote` against the URL, returning its branches."""
    return repo_git.test_connection(body.repo_url, body.access_token)


@router.get("/browse", responses={200: {"model": BrowseResponse}})
def browse(
    repo_url: str = Query(..., description="Repository URL connected in step 1"),
    ref: Optional[str] = Query(None, description="Branch / ref to browse"),
    path: str = Query("", description="Repo-root-relative folder path"),
    access_token: Optional[str] = Query(None, description="Token for private repos"),
    current_user: User = Depends(get_current_user),
):
    """Browse the repository source tree rooted at ``path`` (real depth-1 clone)."""
    if not (repo_url or "").strip():
        raise bad_request("A repository URL is required to browse.")
    try:
        return repo_git.browse(repo_url, ref, path, access_token)
    except repo_git.git_cli.GitError as exc:
        raise bad_request(repo_git._friendly(str(exc)))


@router.post("/uploads", status_code=201, responses={201: {"model": UploadResponse}})
async def upload_file(
    file: UploadFile = File(...),
    kind: str = Form(...),
    current_user: User = Depends(get_current_user),
):
    """
    Upload a build-configuration file (preprocessor defs or data dictionary).

    Returns a reference (``id`` + ``file_name``) that the wizard stores in the
    project's ``build_config`` and that the pipeline can later resolve.
    """
    if kind not in _ALLOWED_KINDS:
        raise bad_request(f"Unknown upload kind '{kind}'.")
    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise bad_request("File exceeds the 5 MB upload limit.")

    upload_id = f"up_{uuid.uuid4().hex[:12]}"
    _UPLOADS[upload_id] = {
        "id": upload_id,
        "file_name": file.filename or "upload",
        "content_type": file.content_type,
        "size": len(data),
        "kind": kind,
        "uploaded_by": current_user.id,
        "data": data,
    }
    return {
        "id": upload_id,
        "file_name": file.filename or "upload",
        "size": len(data),
        "content_type": file.content_type,
        "kind": kind,
    }
