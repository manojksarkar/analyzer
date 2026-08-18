"""
flowchart_engine.py — Main entry point.

Usage:
    python flowchart_engine.py \\
        --interface-json functions.json \\
        --metaData-json  metadata.json  \\
        --std            c++14          \\
        --clang-arg="-I/path/to/includes" \\
        --out-dir        output         \\
        --llm-url        http://localhost:11434/api/generate \\
        --llm-model      qwen2.5-coder:14b \\
        [--function-key  "src|file|qualified|params"]

The engine:
  1. Builds the Project Knowledge Base (PKB) from the model
  2. Groups functions by source file
  3. For each source file, for each function:
       a. Extracts source text (by line range)
       b. Parses a libclang TranslationUnit (full, with bodies)
       c. Resolves the function cursor
       d. Builds the Control Flow Graph (CFG) via AST traversal
       e. Enriches CFG nodes with PKB context
       f. Calls LLM (one call per function) to generate labels
       g. Builds and validates the Mermaid script
  4. Writes one JSON file per source file to --out-dir
  5. Writes a _summary.json
"""

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

# When launched as a script, sys.path[0] is this file's directory (src/flowchart).
# Add the analyzer's src/ directory too so we can import the shared llm_core
# package (the single LlmClient used by the whole project).
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.insert(1, _SRC_DIR)

from ast_engine.cfg_builder import CFGBuilder
from ast_engine.parser import SourceExtractor, TranslationUnitParser
from ast_engine.resolver import find_function_cursor, get_function_body
from config import EngineConfig
from enrichment.enricher import NodeEnricher
from llm_core.client import LlmClient
from llm.generator import LabelGenerator
from dot_builder import build_dot
from mermaid.validator import validate_cfg
from models import FileResult, FlowchartResult, FunctionEntry, NodeType, ProjectMeta
from output.writer import OutputWriter
from pkb.builder import ProjectKnowledgeBase
from pkb.knowledge import ProjectKnowledge, load_knowledge

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

# Logging is configured once via core.logging_setup.configure_logging() in
# _parse_args (stderr→INFO, file→DEBUG). Do NOT call logging.basicConfig here:
# it would install a second, level-less root handler that both duplicates every
# line and leaks DEBUG to the console once configure_logging lowers the root
# level to DEBUG. get_logger()/configure_logging is the single config point.
logger = logging.getLogger("flowchart_engine")


# ---------------------------------------------------------------------------
# Header-file detection
# ---------------------------------------------------------------------------
# Headers are NOT excluded from flowchart generation (a public inline function
# defined in a header is a real definition and needs its own flowchart). This is
# only used to pick which path represents a merged .h + .cpp unit in the summary.

# All recognised C/C++ header extensions (both cases for case-sensitive FSes).
_HEADER_SUFFIXES = frozenset({
    '.h', '.hpp', '.hxx', '.hh',
    '.H', '.HPP', '.HXX', '.HH',
})


def _is_header_file(path: str) -> bool:
    """Return True if path is a C/C++ header file based on its extension."""
    return Path(path).suffix in _HEADER_SUFFIXES




# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> EngineConfig:
    p = argparse.ArgumentParser(
        description="C++ → Mermaid flowchart generator powered by libclang + LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        fromfile_prefix_chars='@',
    )

    p.add_argument("--version-id", default=None,
                   help="doc 10 step 7: read the model, project metadata, knowledge base and "
                        "header->TU map from the DATABASE for this version, instead of the "
                        "four --*-json paths. Requires a configured database.")
    p.add_argument("--component", default=None,
                   help="with --version-id: narrow the model to one component, using the "
                        "(version_id, component) index instead of a pre-filtered file.")
    p.add_argument("--restrict-from-plan", action="store_true",
                   help="with --version-id: regenerate only the functions named by this "
                        "version's incremental plan (flowchartFids). The list is too long for "
                        "a command line, so it is read from the database.")
    p.add_argument("--interface-json", default=None,
                   help="Path to functions.json (generated by analyzer)")
    p.add_argument("--metaData-json", default=None,
                   help="Path to metadata.json (basePath, projectName)")
    p.add_argument("--std", default="c++14",
                   help="C++ standard for libclang (default: c++14)")
    p.add_argument("--clang-arg", dest="clang_args", action="append",
                   default=[], metavar="ARG",
                   help="Extra clang argument (repeatable, e.g. -I/path)")
    p.add_argument("--out-dir", required=True,
                   help="Output directory for JSON files")
    p.add_argument("--llm-url", default="http://localhost:11434/api/generate",
                   help="Local LLM endpoint URL")
    p.add_argument("--llm-model", default="qwen2.5-coder:14b",
                   help="LLM model name (default: qwen2.5-coder:14b)")
    p.add_argument("--function-key", default=None,
                   help="Process only this function key (optional filter)")
    p.add_argument("--knowledge-json", default=None,
                   dest="knowledge_json",
                   help="Path to project_knowledge.json built by project_scanner.py")
    p.add_argument("--tu-includes", default=None,
                   dest="tu_includes",
                   help="Path to model/tu_includes.json. Lets a function defined in a "
                        "header that does not parse standalone be resolved inside a "
                        "translation unit that includes that header.")
    # --no-cache / --cache-dir governed the PKB disk cache, deleted with it: the knowledge base
    # is rebuilt from the model every run, so there is nothing left to opt out of.
    p.add_argument("--llm-cache-version", type=int, default=1,
                   help="llm.cacheVersion — part of the node-label cache key, so bumping it in "
                        "config invalidates cached labels too.")
    p.add_argument("--llm-timeout", type=int, default=120,
                   help="LLM request timeout in seconds (default: 120)")
    p.add_argument("--llm-retries", type=int, default=2,
                   help="LLM retry attempts on validation failure (default: 2)")
    p.add_argument("--llm-batch-size", type=int, default=4,
                   help="Nodes per LLM call (default: 4). Generator auto-halves on no-response.")
    p.add_argument("--llm-num-ctx", type=int, default=8192,
                   help="Ollama num_ctx (context window tokens, default: 8192). "
                        "Ollama defaults to 2048 which causes empty responses for "
                        "prompts >2048 tokens. Set higher for large functions.")
    p.add_argument("--max-stmts", type=int, default=3,
                   help="Max statements per ACTION node segment (default: 3)")
    p.add_argument("--max-lines", type=int, default=10,
                   help="Max source lines per ACTION node segment (default: 10)")
    p.add_argument("--no-llm", action="store_true",
                   help="Skip the LLM entirely; emit fallback (non-LLM) node labels. "
                        "For deterministic, LLM-free runs (timing tests).")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Enable debug logging")
    p.add_argument("--quiet", "-q", action="store_true",
                   help="Suppress info logging (warnings/errors only)")

    args = p.parse_args()

    # Configure unified logging (stderr + daily file). Idempotent.
    try:
        from core.logging_setup import configure_logging
        configure_logging(quiet=args.quiet, verbose=args.verbose)
    except Exception:
        # Last-resort fallback when core.logging_setup is unavailable: install a
        # single basic handler so logs still appear (no duplicate-handler risk
        # here — configure_logging never ran).
        logging.basicConfig(
            level=logging.DEBUG if args.verbose else logging.INFO,
            format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

    return EngineConfig(
        functions_json_path=args.interface_json,
        metadata_json_path=args.metaData_json,
        out_dir=args.out_dir,
        std=args.std,
        clang_args=args.clang_args,
        llm_cache_version=args.llm_cache_version,
        llm_url=args.llm_url,
        llm_model=args.llm_model,
        function_key=args.function_key,
        knowledge_json_path=args.knowledge_json,
        tu_includes_json_path=args.tu_includes,
        llm_timeout=args.llm_timeout,
        llm_max_retries=args.llm_retries,
        max_stmts_per_segment=args.max_stmts,
        max_lines_per_segment=args.max_lines,
        llm_batch_size=args.llm_batch_size,
        llm_num_ctx=args.llm_num_ctx,
        no_llm=args.no_llm,
        version_id=args.version_id,
        component=args.component,
        restrict_from_plan=args.restrict_from_plan,
    )


# ---------------------------------------------------------------------------
# I/O loaders
# ---------------------------------------------------------------------------

def _parse_error_hint(tu, limit: int = 2) -> str:
    """First few libclang errors for a TU, appended to a resolution failure.

    A header that cannot be resolved almost always failed to PARSE first; showing
    the actual diagnostic turns "could not resolve cursor" into an actionable
    message (missing include, unknown macro, …)."""
    try:
        import clang.cindex as _ci
        errs = [d for d in tu.diagnostics if d.severity >= _ci.Diagnostic.Error]
    except Exception:
        return ""
    if not errs:
        return ""
    shown = "; ".join(f"{d.spelling} ({d.location.file}:{d.location.line})"
                      for d in errs[:limit])
    more = f" (+{len(errs) - limit} more)" if len(errs) > limit else ""
    return f" — parse errors: {shown}{more}"


def _build_including_tus(tu_includes: Dict) -> Dict[str, List[str]]:
    """Reverse model/tu_includes.json into {header: [TUs that include it]}.

    Same-stem TUs come first (Foo.h → Foo.cpp is the most likely place a header's
    inline definitions actually compile), then the rest in sorted order so the
    choice is deterministic.
    """
    reverse: Dict[str, List[str]] = defaultdict(list)
    for tu_path, headers in (tu_includes or {}).items():
        if _is_header_file(tu_path):
            continue                      # only real TUs (.cpp) are useful here
        for header in headers or []:
            reverse[header].append(tu_path)

    for header, tus in reverse.items():
        stem = Path(header).stem
        reverse[header] = sorted(set(tus),
                                 key=lambda p: (Path(p).stem != stem, p))
    return dict(reverse)


def _load_json(path: str, label: str) -> Dict:
    p = Path(path)
    if not p.exists():
        logger.error("%s not found: %s", label, path)
        sys.exit(1)
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Database-native inputs (doc 10, step 7)
# ---------------------------------------------------------------------------
# The engine is a separate program with a file CLI, which is why its inputs were paths. Once the
# model lives in Postgres the caller cannot always produce a path — so the engine reads the
# database itself. Its four inputs load in ONE place, which is what kept this small.

def _db_conn():
    """A connection to the configured database. Raises if none is configured — a run asked to
    read a version from the database must not silently produce an empty model."""
    import sys as _sys
    _root = str(Path(__file__).resolve().parents[2])
    for _p in (_root, str(Path(_root) / "engine")):
        if _p not in _sys.path:
            _sys.path.insert(0, _p)
    from core.db import get_engine, is_database_configured
    if not is_database_configured():
        raise RuntimeError("--version-id needs a configured database (db.url in "
                           "engine/config/config.local.json)")
    return get_engine()


# --- LLM label cache (content-addressed, shared with the description cache) ------------
_LABEL_CACHE = None
_LABEL_NS = "flowchart_labels"


def _label_cache(config: EngineConfig):
    """Lazy `EntityCache` for node labels, or None when unavailable.

    Shares `llm_description_cache` under its own namespace, so labels get the same
    project-scoped, cross-node behaviour descriptions already have.
    """
    global _LABEL_CACHE
    if _LABEL_CACHE is None:
        try:
            from llm_core.cache import EntityCache
            pid = _project_id_for(config.version_id)
            ver = int(getattr(config, "llm_cache_version", 1) or 1)
            _LABEL_CACHE = EntityCache(pid, _LABEL_NS, cache_version=ver)
        except Exception as exc:
            logger.warning("label cache unavailable (%s); labels will not be cached", exc)
            _LABEL_CACHE = False
    return _LABEL_CACHE or None


def _project_id_for(version_id: str) -> str:
    if not version_id:
        return ""
    try:
        from sqlalchemy import select
        from api.db.postgres import schema as _s
        with _db_conn().connect() as cx:
            row = cx.execute(select(_s.versions.c.project_id)
                             .where(_s.versions.c.id == version_id)).first()
        return (row.project_id if row else "") or ""
    except Exception:
        return ""


def _label_cache_key(source_code: str, config: EngineConfig) -> str:
    """Content hash over the function source AND the model that would label it.

    The model is in the key because a different model produces different prose; the source is
    the whole of the rest, since the CFG is derived from it deterministically.
    """
    try:
        from llm_core.cache import EntityCache
        return EntityCache.compute_hash(f"{source_code}|model={config.llm_model}")
    except Exception:
        return ""


def _apply_cached_labels(cfg, key: str, config: EngineConfig) -> bool:
    """Fill `cfg` from the cache. True only if EVERY labelable node was covered.

    The node-id set is stored with the labels and must match exactly. CFG construction is
    deterministic for a given source, but a change to the BUILDER would shift ids while the
    source hash stayed the same — that would silently attach the wrong label to the wrong node,
    which is worse than paying for the call.
    """
    cache = _label_cache(config)
    if not (cache and key):
        return False
    try:
        import json as _json
        raw = cache.get(key, key)
        if not raw:
            return False
        stored = _json.loads(raw)
        want = {str(n.node_id) for n in cfg.nodes.values()
                if n.node_type not in (NodeType.START, NodeType.END)}
        if set(stored) != want:
            return False
        for node in cfg.nodes.values():
            nid = str(node.node_id)
            if nid in stored:
                node.label = stored[nid]
        return True
    except Exception:
        return False


def _store_labels(cfg, key: str, config: EngineConfig) -> None:
    cache = _label_cache(config)
    if not (cache and key):
        return
    try:
        import json as _json
        labels = {str(n.node_id): n.label for n in cfg.nodes.values()
                  if n.node_type not in (NodeType.START, NodeType.END)}
        if labels:
            cache.put(key, key, _json.dumps(labels, ensure_ascii=False))
    except Exception:
        pass



def _load_inputs_from_db(config: EngineConfig):
    """(ProjectMeta, functions) for `config.version_id`, optionally one component only.

    The component filter is an indexed query — `ix_ev_version_component` — rather than loading
    the whole model and filtering in Python, which is what the pre-filtered
    functions_<group>.json forced. So this is cheaper than the file path it replaces.
    """
    from core import model_store
    from sqlalchemy import select
    from api.db.postgres import schema as _s
    eng = _db_conn()
    with eng.connect() as cx:
        functions = model_store.load_functions(cx, config.version_id)
        row = cx.execute(select(_s.versions.c.base_path, _s.versions.c.project_name)
                         .where(_s.versions.c.id == config.version_id)).first()
        if config.restrict_from_plan:
            plan = model_store.load_incremental_plan(cx, config.version_id) or {}
            fids = plan.get("flowchartFids")
            if fids is not None:
                keep = set(fids)
                before = len(functions)
                functions = {k: v for k, v in functions.items() if k in keep}
                logger.info("incremental: restricted to %d of %d function(s) from the stored "
                            "plan", len(functions), before)
    if config.component:
        functions = {k: v for k, v in functions.items()
                     if k.split("|", 1)[0] == config.component}
    meta = ProjectMeta(base_path=(row.base_path if row else "") or "",
                       project_name=(row.project_name if row else "") or "")
    logger.debug("loaded %d function(s) from the database for %s%s",
                 len(functions), config.version_id,
                 f" (component {config.component})" if config.component else "")
    return meta, functions


def _db_knowledge_base(version_id: str) -> Optional[dict]:
    from core import model_store
    with _db_conn().connect() as cx:
        return model_store.load_knowledge_base(cx, version_id) or None


def _db_tu_includes(version_id: str) -> Dict:
    from core import model_store
    with _db_conn().connect() as cx:
        return model_store.load_tu_includes(cx, version_id) or {}


def _load_project_meta(metadata_path: str) -> ProjectMeta:
    data = _load_json(metadata_path, "metadata.json")
    return ProjectMeta(
        base_path=data.get("basePath", "."),
        project_name=data.get("projectName", "unknown"),
    )


def _load_functions(functions_path: str) -> Dict:
    return _load_json(functions_path, "functions.json")


# ---------------------------------------------------------------------------
# PKB construction (with optional disk cache)
# ---------------------------------------------------------------------------

def _build_pkb(functions_data: Dict) -> ProjectKnowledgeBase:
    """Build the knowledge base from the model. Always built, never cached.

    `PkbCache` used to persist this to `.flowchart_cache/pkb_<hash>.json`, keyed on the
    functions payload. It cached nothing the model does not already hold — `pkb.build()`
    reconstructs it in full — so the file was a derived copy that could only go stale
    (doc 04 §13.2: "derived; holds nothing unique — drop"). Now that the model is read from
    the database, keeping a JSON mirror of it on local disk is exactly backwards.
    """
    pkb = ProjectKnowledgeBase()
    pkb.build(functions_data)
    return pkb


# ---------------------------------------------------------------------------
# Core per-function processing
# ---------------------------------------------------------------------------

def _process_function(
    func_entry: FunctionEntry,
    pkb: ProjectKnowledgeBase,
    source_extractor: SourceExtractor,
    tu_parser: TranslationUnitParser,
    label_generator: LabelGenerator,
    config: EngineConfig,
    base_path: str,
    project_knowledge: Optional[ProjectKnowledge] = None,
    including_tus: Optional[Dict[str, List[str]]] = None,
) -> FlowchartResult:
    """
    Process a single function end-to-end.
    Returns a FlowchartResult (with error field set on failure).
    """
    key = func_entry.key
    qn = func_entry.qualified_name

    try:
        # 1. Extract source text by line range
        source_code = source_extractor.extract_by_lines(
            func_entry.file, func_entry.line, func_entry.end_line
        )
        source_lines = source_extractor.get_lines(func_entry.file)

        # 2. Parse full TU (with function bodies)
        abs_path = source_extractor.abs_path(func_entry.file)
        tu = tu_parser.get_tu_full(abs_path)

        # 3. Resolve function cursor
        # Pass abs_path so the resolver can use Strategy 1 (direct position
        # lookup) and can match loc.file.name against the exact parsed path.
        func_cursor = find_function_cursor(tu, func_entry, abs_path)

        # Fallback for functions DEFINED in a header that does not parse
        # standalone — its macros/types come from an include the .cpp pulls in
        # first (e.g. "#include cfg.h" then "#include foo.h", where foo.h uses a
        # macro from cfg.h). Parsed alone the definition is a syntax error and
        # yields no cursor. Phase 1 never hits this because it captures the
        # function from the .cpp TU. So retry inside each TU that INCLUDES this
        # header, keeping abs_path (the header) as the resolution target: the
        # cursor still reports the header as its location.
        if func_cursor is None:
            for including_tu in (including_tus or {}).get(func_entry.file, []):
                try:
                    alt_tu = tu_parser.get_tu_full(
                        source_extractor.abs_path(including_tu)
                    )
                except Exception as exc:          # unreadable/missing TU — try next
                    logger.debug("including TU %s unusable: %s", including_tu, exc)
                    continue
                func_cursor = find_function_cursor(alt_tu, func_entry, abs_path)
                if func_cursor is not None:
                    logger.info("Resolved '%s' via including TU %s "
                                "(header does not parse standalone)",
                                qn, including_tu)
                    break

        if func_cursor is None:
            raise RuntimeError(
                f"Could not resolve cursor for '{qn}' in {func_entry.file}:{func_entry.line}"
                + _parse_error_hint(tu)
            )

        # 4. Build CFG
        builder = CFGBuilder(
            source_lines,
            max_stmts=config.max_stmts_per_segment,
            max_lines=config.max_lines_per_segment,
        )
        cfg = builder.build(func_cursor, func_entry)
        logger.debug("CFG built: %d nodes, %d edges for '%s'",
                     len(cfg.nodes), len(cfg.edges), qn)

        # 5. Enrich CFG nodes with PKB context + project knowledge
        enricher = NodeEnricher(
            pkb,
            source_lines_by_file={func_entry.file: source_lines},
            knowledge=project_knowledge,
        )
        enricher.enrich(cfg, func_entry)

        # 6. Generate LLM labels (one call per function) — cached by CONTENT.
        #
        # This was the pipeline's largest unbounded cost. Nothing cached these: every run
        # re-labelled every function, and at the gateway's one-call-per-three-seconds a
        # 14-flowchart component took 225 seconds of pure LLM wait, repeated in full on the
        # next run even when not a line had changed.
        _lbl_key = _label_cache_key(source_code, config)
        if not _apply_cached_labels(cfg, _lbl_key, config):
            label_generator.label_cfg(cfg, func_entry, source_code, base_path)
            _store_labels(cfg, _lbl_key, config)

        # 7. Validate CFG
        cfg_validation = validate_cfg(cfg)
        if not cfg_validation.is_valid:
            logger.warning("CFG validation errors for '%s':\n%s", qn, cfg_validation)
        elif cfg_validation.warnings:
            logger.debug("CFG validation warnings for '%s':\n%s", qn, cfg_validation)

        # 8. Build the flowchart script.  The pipeline renders flowcharts with
        # Graphviz (loop-aware layout: Return/End at the bottom, no crossing
        # back-edges).  The FlowchartResult field is still named mermaid_script
        # for compatibility with the writer/schema, but now carries a DOT script.
        flowchart_script = build_dot(cfg)

        return FlowchartResult(
            function_key=key,
            qualified_name=qn,
            mermaid_script=flowchart_script,
        )

    except Exception as exc:
        logger.error("Failed to process '%s': %s", qn, exc, exc_info=True)
        return FlowchartResult(
            function_key=key,
            qualified_name=qn,
            mermaid_script="",
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# LLM client construction
# ---------------------------------------------------------------------------

def _load_analyzer_llm_config() -> Optional[Dict]:
    """Return the resolved llm config block, walking up from cwd.

    flowchart_engine is launched with cwd=project_root by views/flowcharts.py,
    so the first hit is the analyzer config. Returns None if no config.defaults.json
    is reachable (e.g. standalone CLI invocation from another directory).

    Raises LlmConfigError (from core.config) if the config.defaults.json IS reachable
    but has missing/invalid required fields — that is a user-facing error,
    not a silent fallback.
    """
    from utils import load_config, load_llm_config  # noqa: WPS433
    cwd = os.path.abspath(os.getcwd())
    for candidate in (cwd, os.path.dirname(cwd)):
        cfg_path = os.path.join(candidate, "engine", "config", "config.defaults.json")
        if os.path.isfile(cfg_path):
            cfg = load_config(os.path.join(candidate, "engine"))
            return load_llm_config(cfg)
    return None


class _NullLlmClient:
    """No-op LLM client for --no-llm runs: every generate() returns "" so the label
    generator treats each node as 'no LLM response' and falls back to non-LLM labels.
    Lets the engine produce flowcharts (CFG + fallback labels) with zero LLM calls."""

    model = "no-llm"

    def generate(self, system: str = "", user: str = "", *args, **kwargs) -> str:
        return ""


def _build_llm_client(config: EngineConfig, llm_cfg: Optional[Dict]):
    """Build an LlmClient from the resolved llm config, or legacy CLI args.

    When *llm_cfg* is provided (analyzer config was reachable), we use the
    unified from_config path so provider/custom headers/retries/api_key all
    flow through. Otherwise fall back to the legacy CLI-arg constructor
    (Ollama only, backwards compatible with standalone subprocess usage).
    """
    if llm_cfg is not None:
        from llm_core.client import from_config  # noqa: WPS433
        # CLI args still win for num_ctx if explicitly larger — lets a
        # standalone caller bump the window without editing config.defaults.json.
        if config.llm_num_ctx and config.llm_num_ctx > llm_cfg["numCtx"]:
            llm_cfg["numCtx"] = config.llm_num_ctx
        return from_config(llm_cfg)

    # Legacy fallback — works for standalone Ollama-only invocations.
    return LlmClient(
        url=config.llm_url,
        model=config.llm_model,
        timeout=config.llm_timeout,
        temperature=config.llm_temperature,
        num_ctx=config.llm_num_ctx,
    )


# ---------------------------------------------------------------------------
# libclang bootstrap
# ---------------------------------------------------------------------------

def _configure_libclang() -> None:
    """Point libclang at the configured DLL before any Index.create().

    The flowchart engine runs as its own subprocess and (unlike Phase 1's
    src/parser.py) does not otherwise configure libclang, so clang.cindex falls
    back to OS default discovery and fails with LibclangError when libclang.dll
    is not on the loader path. Resolve the library from LIBCLANG_PATH (set by the
    API) or the analyzer config's clang.llvmLibPath, mirroring src/parser.py.
    """
    lib = os.environ.get("LIBCLANG_PATH") or ""
    if not lib:
        try:
            from utils import load_config  # noqa: WPS433
            cwd = os.path.abspath(os.getcwd())
            for candidate in (cwd, os.path.dirname(cwd)):
                if os.path.isfile(os.path.join(candidate, "engine", "config", "config.defaults.json")):
                    cfg = load_config(os.path.join(candidate, "engine")) or {}
                    clang_cfg = cfg.get("clang") or {}
                    lib = clang_cfg.get("llvmLibPath") or cfg.get("llvmLibPath") or ""
                    break
        except Exception:
            lib = ""
    if not (lib and os.path.isfile(lib)):
        logger.warning(
            "libclang not configured (LIBCLANG_PATH / clang.llvmLibPath unset or "
            "missing); relying on default discovery - flowchart parsing may fail.")
        return
    lib_dir = os.path.dirname(lib)
    if lib_dir and os.path.isdir(lib_dir):
        try:
            os.add_dll_directory(lib_dir)  # type: ignore[attr-defined]
        except Exception:
            os.environ["PATH"] = lib_dir + os.pathsep + os.environ.get("PATH", "")
    import clang.cindex as ci  # noqa: WPS433
    ci.Config.set_library_file(lib)
    logger.info("libclang configured: %s", lib)


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run(config: EngineConfig) -> None:
    _configure_libclang()
    logger.debug("=" * 60)
    logger.debug("flowchart_engine starting")
    logger.debug("  functions.json : %s", config.functions_json_path)
    logger.debug("  metadata.json  : %s", config.metadata_json_path)
    logger.debug("  out-dir        : %s", config.out_dir)
    if config.knowledge_json_path:
        logger.debug("  knowledge-json : %s", config.knowledge_json_path)
    if config.function_key:
        logger.debug("  filter key     : %s", config.function_key)
    logger.debug("=" * 60)

    # Resolve and display the LLM config the subprocess is actually going to
    # use. Any missing/invalid required field surfaces here as LlmConfigError,
    # so the user sees the exact failing field instead of a silent fallback.
    from utils import format_llm_config_banner, LlmConfigError  # noqa: WPS433
    try:
        llm_cfg_resolved = _load_analyzer_llm_config()
    except LlmConfigError as exc:
        logger.error("Invalid LLM config: %s", exc)
        sys.exit(2)
    if llm_cfg_resolved is not None:
        for _line in format_llm_config_banner(llm_cfg_resolved).splitlines():
            logger.debug(_line)
    else:
        logger.debug("LLM (legacy standalone): %s  model=%s",
                     config.llm_url, config.llm_model)

    # Load inputs — from the DATABASE when a version id is given (doc 10, step 7), else the
    # four JSON paths. One block, because that is what made this tractable.
    if config.version_id:
        meta, functions_data = _load_inputs_from_db(config)
    else:
        meta = _load_project_meta(config.metadata_json_path)
        functions_data = _load_functions(config.functions_json_path)
    base_path = meta.base_path

    logger.debug("Project: %s  |  base_path: %s", meta.project_name, base_path)
    logger.debug("Loaded %d functions from functions.json", len(functions_data))

    # Load project knowledge (optional — built by project_scanner.py)
    project_knowledge: Optional[ProjectKnowledge] = None
    if config.version_id:
        from pkb.knowledge import load_knowledge_data
        project_knowledge = load_knowledge_data(_db_knowledge_base(config.version_id))
        if project_knowledge is None:
            logger.debug("no knowledge base stored for %s; continuing without it",
                         config.version_id)
    elif config.knowledge_json_path:
        project_knowledge = load_knowledge(config.knowledge_json_path)
        if project_knowledge is None:
            logger.warning("--knowledge-json file not loaded; continuing without it")
    else:
        logger.debug("No --knowledge-json provided; running without project knowledge")

    # Reverse include map (optional — written by Phase 1 as model/tu_includes.json).
    # Lets a header-defined function be resolved inside a TU that includes the
    # header when the header does not parse standalone.
    including_tus: Dict[str, List[str]] = {}
    if config.version_id:
        including_tus = _build_including_tus(_db_tu_includes(config.version_id))
        logger.debug("Include map (database): %d header(s) reachable from a .cpp TU",
                     len(including_tus))
    elif config.tu_includes_json_path and Path(config.tu_includes_json_path).is_file():
        try:
            with open(config.tu_includes_json_path, "r", encoding="utf-8") as f:
                including_tus = _build_including_tus(json.load(f))
            logger.debug("Include map: %d header(s) reachable from a .cpp TU",
                         len(including_tus))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("--tu-includes not loaded (%s); header-defined functions "
                           "that need an including TU may fail to resolve", exc)

    # Build PKB
    pkb = _build_pkb(functions_data)

    # Attach project knowledge to PKB for richer context packets
    if project_knowledge:
        pkb.load_project_knowledge(project_knowledge)

    # Apply function-key filter
    if config.function_key:
        if config.function_key not in functions_data:
            logger.error("function-key not found in functions.json: %s",
                         config.function_key)
            sys.exit(1)
        target_keys = [config.function_key]
        logger.debug("Filtered to 1 function: %s", config.function_key)
    else:
        target_keys = list(functions_data.keys())

    # Build FunctionEntry objects for targets
    target_entries: List[FunctionEntry] = []
    for key in target_keys:
        entry = pkb.get(key)
        if entry:
            target_entries.append(entry)
        else:
            logger.warning("Key not in PKB (skipping): %s", key)

    # Drop synthetic pseudo-functions (var-decls recorded as functions — e.g. a
    # macro-obscured "UNIT _f(arg);" parsed as a VAR_DECL). They have no body, so
    # there is no CFG to build. Every other functions.json entry is a real
    # definition — INCLUDING public inline functions defined in headers, which
    # libclang parses fine as their own TUs (-x c++) and which the document needs
    # a flowchart for.
    processable = [e for e in target_entries if not e.synthetic_from_var_decl]
    skipped = len(target_entries) - len(processable)
    if skipped:
        logger.info("Skipping %d synthetic (no-body) function(s) (no output generated)",
                    skipped)

    # Group by OUTPUT STEM, not by path: OutputWriter names each file
    # "<stem>.json" with the extension stripped, so Foo.h and Foo.cpp share one
    # output file. Grouping by path would emit two FileResults for that stem and
    # the second write would silently overwrite the first (losing every .cpp
    # flowchart in the unit). Merging here also matches the rest of the pipeline,
    # which collapses Foo.h + Foo.cpp into a single unit (utils
    # _path_to_component_unit) and looks flowcharts up per unit.
    by_stem: Dict[str, List[FunctionEntry]] = defaultdict(list)
    for entry in processable:
        by_stem[Path(entry.file).stem].append(entry)

    # One group -> one FileResult. Prefer a non-header path as the reported
    # source_file (_summary.json) so a merged unit still names its .cpp.
    by_file: Dict[str, List[FunctionEntry]] = {}
    for _stem, group in by_stem.items():
        paths = sorted({e.file for e in group})
        representative = next((p for p in paths if not _is_header_file(p)), paths[0])
        by_file[representative] = sorted(group, key=lambda e: (e.file, e.line))

    logger.info("Processing %d function(s) across %d source file(s)",
                len(processable), len(by_file))

    # Initialise shared infrastructure
    source_extractor = SourceExtractor(base_path)
    tu_parser = TranslationUnitParser(config.std, config.clang_args)
    if config.no_llm:
        logger.debug("--no-llm: skipping the LLM; emitting fallback node labels")
        llm_client = _NullLlmClient()
    else:
        llm_client = _build_llm_client(config, llm_cfg_resolved)

    # Derive enrichment flags + authoritative max_context_tokens from the
    # resolved llm config (displayed above). When standalone without a
    # reachable config, both stay None and every enrichment feature is off.
    enrichment_cfg: Dict = {}
    max_context_tokens: Optional[int] = None
    if llm_cfg_resolved is not None:
        from llm_core.budget import resolve_max_tokens  # noqa: WPS433
        enrichment_cfg = llm_cfg_resolved.get("enrichment") or {}
        max_context_tokens = resolve_max_tokens(llm_cfg_resolved)
        logger.debug("Coherence/simplify budget = %d tokens (provider=%s)",
                     max_context_tokens, llm_cfg_resolved.get("provider"))

    label_generator = LabelGenerator(
        client=llm_client,
        pkb=pkb,
        max_retries=config.llm_max_retries,
        batch_size=config.llm_batch_size,
        enrichment_config=enrichment_cfg,
        max_context_tokens=max_context_tokens,
    )
    writer = OutputWriter(config.out_dir)

    # Process each source file
    file_results: List[FileResult] = []
    total_ok = 0
    total_err = 0
    total_funcs = len(processable)  # global denominator (functions actually processed)
    processed = 0                   # global running counter across all files

    for source_file, entries in sorted(by_file.items()):
        logger.debug("── File: %s  (%d function(s))", source_file, len(entries))
        fr = FileResult(source_file=source_file)

        for entry in entries:
            processed += 1
            logger.info("[%d/%d] Processing: %s",
                        processed, total_funcs, entry.qualified_name)
            result = _process_function(
                func_entry=entry,
                pkb=pkb,
                source_extractor=source_extractor,
                tu_parser=tu_parser,
                label_generator=label_generator,
                config=config,
                base_path=base_path,
                project_knowledge=project_knowledge,
                including_tus=including_tus,
            )
            fr.flowcharts.append(result)
            if result.error:
                total_err += 1
                logger.warning("   ✗ Error: %s", result.error)
            else:
                total_ok += 1
                logger.debug("   ✓ OK: %d chars of Mermaid",
                             len(result.mermaid_script))

        file_results.append(fr)

    # Write output
    written = writer.write_all(file_results)
    writer.write_summary(file_results, total_ok + total_err, total_err)

    logger.debug("=" * 60)
    logger.info("Done.  ✓ %d  ✗ %d  |  %d file(s) written",
                total_ok, total_err, len(written))
    logger.info("Output: %s", config.out_dir)
    logger.debug("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    config = _parse_args()
    run(config)
