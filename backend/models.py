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
    name: str
    branch: str
    path: str
    lastIndexed: str
    files: int
    # `loc` (lines of code) exists in the office models.py contract. We keep
    # the field for shape parity but never compute it — always "0". Stored
    # as a string for parity with the office shape; default lets call sites
    # omit it without breaking.
    loc: str = "0"


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
    # `path` alone drives the pipeline per the team decision. Optional with
    # default None so direct callers (Postman, Swagger, scripts) can post
    # just `{"path": "..."}` without a 422.
    componentId: Optional[str] = None
    moduleId: Optional[str] = None
    path: str


class ExportJobRequest(BaseModel):
    componentId: Optional[str] = None
    moduleId: Optional[str] = None
    path: str
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


# ---------------------------------------------------------------------------
# Error response
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    status: int
    message: str


# Resolve forward references for TreeNode.children
TreeNode.model_rebuild()
