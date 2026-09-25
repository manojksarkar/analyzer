"""UT export view (SWE.4): test_specs.json -> the unit-test automation JSON.

Two outputs from the same specs, per docs/spec/UT_EXPORT_SPEC.md:

  output/<group>/ut_export.json   OUR format -- kept as it always was, now with
                                  solved values filled in (REQ-UE-06).
  output/ut/                      the TARGET format (docs/spec/ut_templates/), one
                                  folder for the whole project: a `<environment>.json`
                                  test-case file per unit plus ONE `hierarchy.json`
                                  (REQ-UE-07..09).

Reads the specs the testSpecs view just wrote rather than re-deriving them, so the
document and the export can never disagree about what a unit's tests are -- the
same objects feed both. (Same arrangement as testSpecs reading the flowchart
engine's CFG.)

One case per PATH, not per function (REQ-UE-04). A spec covers every exit in one
row because that is what the document renders; `expected.returns[].step` names which
numbered step each return leaves by, so the paths are already distinguished and only
need splitting out.

Input VALUES come from `ut_paths` (REQ-UE-10): the conditions on each path, taken
from the flowchart CFG, solved where they are simple. What is not solved stays
null and says why in the case's `solve.notes` -- never a guess a generator would
trust.
"""
import glob
import json
import os

from .registry import register
from .ut_paths import Context, constants_from_macros, display, solve
from utils import get_range, log

FORMAT_VERSION = "1.0"
LEVEL_UT = "UT"
UT_DIR = "ut"                      # the project-level target-format folder
HIERARCHY_FILE = "hierarchy.json"
TESTCASE_SUFFIX = "_TS.json"       # every environment name ends in `_TS`

# Top-level keys in test_specs.json that are not unit entries.
_RESERVED = ("unitNames", "dynamicSpecs")


def _split_qualified(qualified_name):
    """`Class::method` -> ("Class", "method"); a free function -> ("", name).

    Most of the target firmware is C-style, so the empty ClassName is the common
    case, not the edge one.
    """
    qn = qualified_name or ""
    if "::" not in qn:
        return "", qn
    owner, _, method = qn.rpartition("::")
    return owner, method


def _inputs(spec, dd, values=None):
    """One entry per readable input, with its range and its solved value.

    The spec's Input already excludes what has no value to set -- out-parameters,
    write-only globals, void mocks. Ranges come from the data dictionary rather
    than from parsing them back out of the display text. `value` stays null when
    nothing was solved for it (no CFG, or a condition the solver cannot handle).
    """
    values = values or {}
    out = []
    for entry in (spec.get("input") or {}).get("entries") or ():
        rng = get_range(entry.get("type") or "", dd)
        v, shown = values.get(entry.get("name", ""), (None, None))
        item = {"name": entry.get("name", ""),
                "type": entry.get("type", ""),
                "kind": entry.get("kind", ""),
                "value": display(v, shown, entry.get("type", ""))}
        if rng and rng not in ("NA", "VOID"):
            item["range"] = rng
        out.append(item)
    return out


def _preconditions(spec, values=None):
    """Globals the case must set up, with the initial value the model recorded
    and, for a global the path reads, the value the case needs."""
    values = values or {}
    globals_ = []
    for g in (spec.get("precondition") or {}).get("globals") or ():
        entry = {"name": g.get("name", ""), "type": g.get("type", "")}
        if g.get("value") not in (None, ""):
            entry["initialValue"] = g["value"]
        if g.get("name", "") in values:
            v, shown = values[g["name"]]
            entry["value"] = display(v, shown, g.get("type", ""))
        globals_.append(entry)
    return {"globals": globals_}


def _stubs(spec):
    """Every stubbed callee, with what a generator needs to write it.

    Emitted per case rather than per function, even though the list is currently
    the function's whole set: narrowing it to the callees a given path actually
    reaches needs a mock-to-step mapping the transcription does not yet carry.

    Over-listing a stub is harmless -- an unused stub is registered and never
    called. Over-*asserting* one is not, which is why `expected` carries no
    called-mocks list; see `_cases_for`.
    """
    return [dict(m) for m in (spec.get("precondition") or {}).get("mocks") or ()]


def _case_name(func_name, ret, step):
    """A sentence a reviewer can check against the code."""
    if ret is None:
        return f"{func_name} completes"
    expr = ret.get("expression") or ret.get("source") or ""
    where = f" at step {step}" if step else ""
    return f"{func_name} returns {expr}{where}".replace("  ", " ")


def _solve_block(solution):
    """What the solver made of this case: `status` + the two verdicts + why."""
    if not solution:
        return {"status": "unsolved", "inputs": "partial", "expected": "open",
                "notes": ["not solved (no control-flow graph)"]}
    return {"status": solution["status"], "inputs": solution["inputs"],
            "expected": solution["expected"], "notes": list(solution["notes"])}


def _cases_for(spec, dd, review, solutions=None):
    """One case per return path; one case overall when the spec names no return.

    A void function, or one whose control flow was never transcribed, still needs
    a case -- it just has nothing to assert a return value against.

    `expected` names no called mocks. The spec's mock list is the union over every
    path, so on any one path most of it did not run: asserting it would fail three
    times out of four on a four-way branch. The solver does know which mocks a path
    calls; the target format carries that as `expected.stub_params`.

    `solutions` ({step: result} from `ut_paths.solve`) fills the values. Without
    it every value is null and there is no `solve` block -- the export as it was.
    """
    base_id = spec.get("testCaseId") or ""
    class_name, function_name = _split_qualified(spec.get("qualifiedName", ""))

    def shell(case_id, name, solution):
        values = (solution or {}).get("values") or {}
        case = {"id": case_id, "name": name,
                "level": LEVEL_UT,
                # No requirements source exists yet (Polarion / SWE.1); emitted empty
                # rather than omitted, so the field's absence is never mistaken for a
                # traced-but-unlinked case.
                "trace": "",
                "review": dict(review),
                "target": {"ClassName": class_name, "FunctionName": function_name},
                "preconditions": _preconditions(spec, values),
                "stubs": _stubs(spec),
                "inputs": _inputs(spec, dd, values)}
        if solutions is not None:
            case["solve"] = _solve_block(solution)
        return case

    returns = (spec.get("expected") or {}).get("returns") or []
    if not returns:
        # Suffixed like any other case. Interface ids already end in `_NN`, so a
        # bare id here would be indistinguishable from a path index -- and every
        # id then answers "which path?" the same way.
        solution = (solutions or {}).get("")
        case = shell(f"{base_id}_01", _case_name(spec.get("name", ""), None, ""), solution)
        case["expected"] = {"return": None}
        return [case]

    cases = []
    for index, ret in enumerate(returns, start=1):
        step = ret.get("step", "")
        solution = (solutions or {}).get(step)
        # The suffix scheme is provisional -- see UT_EXPORT_SPEC.md Open items.
        case = shell(f"{base_id}_{index:02d}", _case_name(spec.get("name", ""), ret, step),
                     solution)
        case["expected"] = {
            # `expression` is the source expression, so a return of `libAdd()` or
            # `sample` stays symbolic; `value` is what it evaluates to on this
            # path once the inputs are chosen (null when not computed).
            "return": ret.get("expression", ""),
            "atStep": step,
        }
        if solutions is not None:
            case["expected"]["value"] = (solution or {}).get("return")
        cases.append(case)
    return cases


def _environment(config):
    """Harness settings, carried from config verbatim (REQ-UE-05).

    These describe the test environment, not our source -- there is nothing here
    to derive, and synthesising a value would be inventing one.
    """
    cfg = ((config.get("views", {}) or {}).get("utExport", {}) or {})
    env = cfg.get("environment") or {}
    return {"flags": list(env.get("flags") or []),
            "probepoint": list(env.get("probepoint") or []),
            "usercode": list(env.get("usercode") or [])}


def _review(config):
    """DO-178C author/reviewer. Not derivable from code -- configuration only."""
    cfg = ((config.get("views", {}) or {}).get("utExport", {}) or {})
    review = cfg.get("review") or {}
    return {"author": review.get("author", ""), "reviewer": review.get("reviewer", "")}


def _iter_specs(test_specs):
    """Every spec that becomes cases, function specs then dynamic ones.

    Both kinds are unit-test specifications (REQ-UE-01) and share Table A's shape,
    so one loop covers them.
    """
    for key, unit in test_specs.items():
        if key in _RESERVED or not isinstance(unit, dict):
            continue
        for spec in unit.get("functions") or ():
            yield spec
    dynamic = test_specs.get("dynamicSpecs")
    if isinstance(dynamic, dict):
        for specs in dynamic.values():
            for spec in specs or ():
                yield spec
    elif isinstance(dynamic, list):
        for spec in dynamic:
            yield spec


def _ut_config(config):
    return ((config.get("views", {}) or {}).get("utExport", {}) or {})


def _read_json(path, default):
    """A model-side JSON file written by run.py / Phase 1, or `default` when absent."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _by_layer(data):
    """{layer: [...]} from a scope-keyed file; a flat list (the pre-scope shape)
    belongs to every layer, keyed ""."""
    if isinstance(data, dict):
        return {k: list(v) for k, v in data.items() if isinstance(v, list)}
    if isinstance(data, list):
        return {"": list(data)}
    return {}


def _base_path():
    """The project root the model was parsed from (metadata.basePath), or ""."""
    try:
        from core.model_io import METADATA, read_model_file
        meta = read_model_file(METADATA, required=False, default={}) or {}
        return (meta.get("basePath") or "").strip()
    except Exception:          # no repository / no metadata: paths stay as stored
        return ""


def infer_base_path(includes_by_layer, rel_files):
    """The project root, recovered from absolute include dirs that end in a unit's
    own (project-relative) folder -- `/abs/root` + `/Layer1/Sample/Core`. Used only
    when the model's metadata has no basePath. The most frequent answer wins; ties
    go to the shortest root, then alphabetical, so the result is deterministic."""
    dirs = {os.path.dirname(f).replace("\\", "/") for f in rel_files if f}
    votes = {}
    for paths in includes_by_layer.values():
        for p in paths:
            p = p.replace("\\", "/").rstrip("/")
            for d in dirs:
                if d and p.endswith("/" + d):
                    root = p[: -len(d) - 1]
                    votes[root] = votes.get(root, 0) + 1
    if not votes:
        return ""
    return sorted(votes.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))[0][0]


def solve_all(test_specs, cfgs, dd, macros_by_layer):
    """[(spec, ctx, {step: result})] for every spec, in `_iter_specs` order."""
    from .ut_paths import helpers_from_cfgs
    from .ut_target import split_unit_key
    # Every function with a CFG can be executed when it runs for real inside
    # another's path -- its result then becomes a known expected value.
    helpers = helpers_from_cfgs(cfgs)
    constants = {}
    out = []
    for spec in _iter_specs(test_specs):
        layer = split_unit_key(spec.get("unitKey", ""))[0]
        if layer not in constants:
            constants[layer] = constants_from_macros(
                (macros_by_layer.get("") or []) + (macros_by_layer.get(layer) or []))
        ctx = Context(spec, dd, constants[layer], layer=layer or None)
        ctx.helpers = helpers
        out.append((spec, ctx, solve(spec, cfgs.get(spec.get("functionId")), ctx)))
    return out


def _unit_files(test_specs):
    """{unitKey: project-relative file the unit is tested through}: the source file
    its functions are defined in, a header only when no function of the unit is
    defined anywhere else (a header-only unit)."""
    from .ut_target import is_header
    files = {}
    for spec in _iter_specs(test_specs):
        uk = spec.get("unitKey", "")
        f = ((spec.get("location") or {}).get("file") or "").replace("\\", "/")
        if uk and f and (uk not in files or (is_header(files[uk]) and not is_header(f))):
            files[uk] = f
    return files


def output_root(output_dir):
    """The folder the group folders sit in -- where the one `ut/` folder goes.

    A group, component or named run writes to `<root>/<name>`; a run with no
    layers writes to the root itself.
    """
    here = os.path.abspath(output_dir)
    try:
        from core.paths import paths
        root = paths().output_dir or ""
    except Exception:          # no path configuration: a group folder is the norm
        root = ""
    if root and os.path.normcase(here) == os.path.normcase(os.path.abspath(root)):
        return here
    return os.path.dirname(here)


def _configured_components(config):
    """Every component id the config names, spelled as unit keys spell them
    (spaces as `-`); None when it names none -- nothing can be judged stale then."""
    from core.config import get_flat_groups
    ids = set()
    for grp in (get_flat_groups(config) or {}).values():
        if isinstance(grp, dict):
            ids.update(str(k).replace(" ", "-") for k in grp)
    return ids or None


def project_units(root, config):
    """{unitKey: file} over every run under `root` -- the specs each group run
    left in its own folder -- keeping only units whose component the config still
    names. A removed or renamed component's folder may linger on disk; its units
    do not come back from it."""
    from .ut_target import is_header
    comps = _configured_components(config)
    sources = [os.path.join(root, "test_specs.json")] + sorted(
        glob.glob(os.path.join(root, "*", "test_specs.json")))
    units = {}
    for path in sources:
        specs = _read_json(path, None)
        if not isinstance(specs, dict):
            continue
        for uk, f in _unit_files(specs).items():
            if comps is not None and uk.partition("|")[0].replace(" ", "-") not in comps:
                continue
            if uk not in units or (is_header(units[uk]) and not is_header(f)):
                units[uk] = f
    return units


def write_hierarchy(ut_dir, root, model_dir, config):
    """Rebuild `hierarchy.json` whole from the current state -- never patched.

    Environments = the test-case files in `ut_dir` that a configured unit still
    owns. A test-case file no such unit owns (its component left the config, or
    the unit has no specs any more) is deleted first, so nothing stale is listed.
    Every group run calls this after writing its own files; the runs are
    sequential, so the last one leaves the whole project. Returns the unit count.
    """
    from core.config import get_layer_cores
    from .ut_target import build_hierarchy, environment_name, split_unit_key

    units = project_units(root, config)
    by_env = {environment_name(uk): uk for uk in units}
    for name in sorted(os.listdir(ut_dir)):
        if name.endswith(TESTCASE_SUFFIX) and name[:-len(".json")] not in by_env:
            os.remove(os.path.join(ut_dir, name))
    present = {n[:-len(".json")] for n in os.listdir(ut_dir) if n.endswith(TESTCASE_SUFFIX)}
    kept = {uk: units[uk] for env, uk in by_env.items() if env in present}

    ut_cfg = _ut_config(config)
    layers = {split_unit_key(uk)[0] for uk in kept}
    includes = _by_layer(_read_json(os.path.join(model_dir or "", "clang_include_paths.json"), {}))
    hierarchy = build_hierarchy(
        [{"unitKey": uk, "file": f} for uk, f in kept.items()],
        macros_by_layer=_by_layer(_read_json(os.path.join(model_dir or "", "clang_macros.json"), {})),
        includes_by_layer=includes,
        cores_by_layer={layer: get_layer_cores(config, layer) for layer in layers},
        library_dirs=ut_cfg.get("libraryDirectories") or {},
        env_overrides=ut_cfg.get("environments") or {},
        base_path=_base_path() or infer_base_path(includes, kept.values()))
    _dump(os.path.join(ut_dir, HIERARCHY_FILE), hierarchy)
    return len(kept)


def write_target_format(output_dir, model, model_dir, config, solved, review):
    """This group's test-case files into the project-level `ut/` folder, then the
    one hierarchy rebuilt. Returns (ut folder, test-case files written, cases,
    units in the hierarchy)."""
    from .test_specs import mock_writeback_sources
    from .ut_target import build_case, build_testcase_file, environment_name

    functions = model.get("functions", {}) or {}
    dd = model.get("dataDictionary", {}) or {}
    ut_cfg = _ut_config(config)
    environment = _environment(config)
    env_overrides = ut_cfg.get("environments") or {}

    per_unit = {}
    for spec, ctx, solutions in solved:
        uk = spec.get("unitKey", "")
        func = functions.get(spec.get("functionId", "")) or {}
        mocked = {m.get("functionId") for m in (spec.get("precondition") or {}).get("mocks") or []}
        writebacks = mock_writeback_sources(func, mocked, functions, dd) if func else []
        for case in _cases_for(spec, dd, review):
            step = (case.get("expected") or {}).get("atStep", "")
            per_unit.setdefault(uk, []).append(
                build_case(case["id"], case["name"], spec, solutions.get(step), ctx,
                           writebacks, review))

    root = output_root(output_dir)
    ut_dir = os.path.join(root, UT_DIR)
    os.makedirs(ut_dir, exist_ok=True)
    written = 0
    for uk in sorted(per_unit):
        env = environment_name(uk)
        env_block = dict(environment)
        # Per-environment overrides are split by file: the test-case file's
        # `usercode` is [{description, code}], the hierarchy's is [str].
        over = (env_overrides.get(env) or {}).get("testcase") or {}
        for k in ("flags", "probepoint", "usercode"):
            if k in over:
                env_block[k] = list(over[k])
        _dump(os.path.join(ut_dir, f"{env}.json"), build_testcase_file(env, per_unit[uk], env_block))
        written += 1

    n_units = write_hierarchy(ut_dir, root, model_dir, config)
    return ut_dir, written, sum(len(v) for v in per_unit.values()), n_units


def _dump(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


@register("utExport")
def run(model, output_dir, model_dir, config):
    specs_path = os.path.join(output_dir, "test_specs.json")
    if not os.path.isfile(specs_path):
        log("no test_specs.json under %s - nothing to export" % output_dir,
            component="utExport")
        return
    with open(specs_path, encoding="utf-8") as f:
        test_specs = json.load(f)

    from .test_steps import load_cfgs
    dd = model.get("dataDictionary", {}) or {}
    review = _review(config)
    macros_by_layer = _by_layer(_read_json(os.path.join(model_dir or "", "clang_macros.json"), {}))
    solved = solve_all(test_specs, load_cfgs(output_dir), dd, macros_by_layer)

    cases = []
    for spec, _ctx, solutions in solved:
        cases.extend(_cases_for(spec, dd, review, solutions))

    payload = {"format_version": FORMAT_VERSION,
               "environment": _environment(config),
               "cases": cases}

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "ut_export.json")
    _dump(out_path, payload)
    tally = {}
    for c in cases:
        s = (c.get("solve") or {}).get("status", "unsolved")
        tally[s] = tally.get(s, 0) + 1
    log("%s (%d case(s) from %d spec(s); values: %s)"
        % (out_path, len(cases), len(solved),
           ", ".join(f"{n} {k}" for k, n in sorted(tally.items())) or "none"),
        component="utExport")

    if _ut_config(config).get("targetFormat", True) is not False:
        ut_dir, n_files, n_cases, n_units = write_target_format(
            output_dir, model, model_dir, config, solved, review)
        log("%s (%d test-case file(s), %d case(s) in the target format; hierarchy: %d unit(s))"
            % (ut_dir, n_files, n_cases, n_units), component="utExport")
