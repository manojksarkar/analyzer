"""Pydantic models for the analyzer backend HTTP API.

Mirrors the contract agreed with the UI side (Vite dev server on
http://localhost:5173). Each section is grouped by purpose so the file stays
navigable as the API grows.
"""

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Core data models
# ---------------------------------------------------------------------------


class Repository(BaseModel):
    """One entry in backend/repository_config.json.

    Simplified to just (name, path) — the multi-repository API replaces the
    earlier single-repo placeholder shape. The UI distinguishes repos by
    name; the path drives the analyzer pipeline.
    """
    name: str
    path: str


class TreeNode(BaseModel):
    id: str
    type: Literal["module", "submodule", "fn"]
    name: str
    meta: Optional[str] = None
    children: Optional[List["TreeNode"]] = None


class Module(BaseModel):
    id: str
    name: str
    path: str
    files: int
    tree: TreeNode
    loc: str = "0"  # shape-parity placeholder; see Repository.loc note


class Component(BaseModel):
    id: str
    code: str
    name: str
    desc: str
    modules: List[Module]


class ComponentSummary(BaseModel):
    id: str
    code: str
    name: str
    desc: str
    moduleCount: int


class ModuleSummary(BaseModel):
    id: str
    name: str
    path: str
    files: int
    loc: str = "0"  # shape-parity placeholder; see Repository.loc note


class FunctionCaller(BaseModel):
    id: str
    name: str
    loc: str = "0"  # shape-parity placeholder; see Repository.loc note


class Flowchart(BaseModel):
    id: str
    name: str
    code: str


class FunctionDetail(BaseModel):
    id: str
    name: str
    file: str
    line: str
    ret: str
    description: str
    callers: List[FunctionCaller]
    callees: List[FunctionCaller]
    flowchart: str


class FunctionDetailWithHidden(FunctionDetail):
    hidden: bool


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class PatchFunctionBody(BaseModel):
    description: Optional[str] = None
    hidden: Optional[bool] = None


class PatchFunctionResult(BaseModel):
    fnId: str
    savedAt: str


class PrepareJobRequest(BaseModel):
    # componentId / moduleId are accepted for shape parity with the UI's
    # existing payload but the backend doesn't forward them to run.py —
    # `path` (or `?name=` query) alone drives the pipeline per the team
    # decision. Optional with default None so direct callers (Postman,
    # Swagger, scripts) can post just `{"path": "..."}` without a 422.
    #
    # `path` is now optional too: when `?name=` query is provided the
    # backend looks up the path from repository_config.json and uses
    # that. Validation: exactly one of {?name=, body.path} must resolve
    # to an existing directory, else 400.
    componentId: Optional[str] = None
    moduleId: Optional[str] = None
    path: Optional[str] = None


class ExportJobRequest(BaseModel):
    componentId: Optional[str] = None
    moduleId: Optional[str] = None
    path: Optional[str] = None
    # hiddenFns is accepted but currently ignored (see API 12 — "ignore
    # hiddenFns" decision). Optional[Dict]=None (rather than = {}) so the
    # field validates clean even on strict-mode Pydantic instances and on
    # older/forked models.py copies where the literal mutable default
    # might not be honored.
    hiddenFns: Optional[Dict[str, bool]] = None


class PrepLog(BaseModel):
    id: str
    t: str
    level: str
    msg: str


class ExportProgress(BaseModel):
    pct: int
    stage: str


class JobStartResult(BaseModel):
    jobId: str


class JobCompleteResult(BaseModel):
    jobId: str


class ExportCompleteResult(BaseModel):
    jobId: str
    filename: str
    hiddenCount: int


class UpdateConfigRequest(BaseModel):
    """Body shape for POST /api/v1/config — surgical update of just the
    `layers` key (main schema). Each layer maps to an object with a `path`
    and a `groups` map (group -> {component: path | [paths]}); the whole
    `layers` object is replaced verbatim, preserving every other config key
    and all comments.
    """
    layers: Dict[str, object]


# ---------------------------------------------------------------------------
# Error response
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    status: int
    message: str


# Resolve forward references for TreeNode.children
TreeNode.model_rebuild()
