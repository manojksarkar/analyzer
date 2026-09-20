"""The V-model pairing: a SWE.3 document against its SWE.4 document.

This is a different question from comparing two versions of the same document.
Here the two documents are *different documents about the same code*, and both
wikis state how they must line up:

- `SWE4_WIKI.md`, 'Who gets a spec' -- every function in the SWE.3 detailed design
  gets a spec, **except** inline public functions, which are covered through their
  own unit's callers.
- `SWE4_WIKI.md`, 'Dynamic Behaviour test specs' -- a dynamic-behaviour spec exists
  **exactly** where SWE.3 draws a behaviour diagram. The two pair one-to-one.
- `SWE4_WIKI.md`, 'Table B' -- a Test Case ID is `TC_<interfaceId>`, so the SWE.4
  id and the SWE.3 id are the same string with four characters in front.

None of that needs the source code, a model file or a pipeline run: it is all
printed in the two documents. Which makes it checkable at a client's desk, on a
pair of documents that came back from review.

The interaction check is the valuable one. The two sides pick their interactions
through the same selector but SWE.3 then applies two further filters, so the
counts can silently drift apart -- the reason `tools/swe4_dynamic_diff.py` exists.
This catches that from the delivered documents rather than from a model dump.
"""
from __future__ import annotations

from .compare import Finding
from .model import HIGH, INFO, LOW, MEDIUM, normalise_key

WIKI3 = "docs/spec/SWE3_WIKI.md"
WIKI4 = "docs/spec/SWE4_WIKI.md"


def _design_functions(design):
    """{(component, unit, function): [interface rows]} for every public function.

    A list, not a single entry: two entries under one key is a name collision, and
    a dict that overwrote the first would hide exactly the defect worth reporting.
    """
    out = {}
    for component in design.of_kind("component"):
        for unit in component.of_kind("unit"):
            for iface in unit.of_kind("interface"):
                if (iface.fields.get("interfaceType") or "").casefold().startswith("func"):
                    key = (normalise_key(component.name), normalise_key(unit.name),
                           normalise_key(iface.name))
                    out.setdefault(key, []).append((component, unit, iface))
    return out


def _spec_functions(spec):
    """{(component, unit, function): [test cases]} for every function spec."""
    out = {}
    for component in spec.of_kind("component"):
        for unit in component.of_kind("unit"):
            for case in unit.of_kind("testcase"):
                key = (normalise_key(component.name), normalise_key(unit.name),
                       normalise_key(case.name))
                out.setdefault(key, []).append((component, unit, case))
    return out


def _interaction_key(entity):
    """The four names a behaviour heading carries, as a comparable key."""
    f = entity.fields
    return (normalise_key(f.get("unit", "")), normalise_key(f.get("function", "")),
            normalise_key(f.get("callerUnit", "")), normalise_key(f.get("callerFunction", "")))


def _design_interactions(design):
    out = {}
    for component in design.of_kind("component"):
        for ia in component.of_kind("interaction"):
            out[_interaction_key(ia)] = (component, ia)
    return out


def _spec_interactions(spec):
    out = {}
    for component in spec.of_kind("component"):
        for ia in component.of_kind("interaction"):
            out[_interaction_key(ia)] = (component, ia)
    return out


def _bare(name):
    """`SignalProcessor::normalize` -> `normalize`."""
    return normalise_key(str(name).split("::")[-1])


def _same_function_two_names(functions, specs):
    """Pair the leftovers that differ only by the class qualifier.

    SWE.3 prints a method with its class in front, because that is what tells two
    same-named methods apart. When SWE.4 prints the bare name, the same function
    appears once as a design entry with no spec and once as a spec with no design
    entry. Reporting that as two findings hides what it is -- one function, two
    names -- so the pair is found here and reported once.
    """
    left = {k: v for k, v in functions.items() if k not in specs}
    right = {k: v for k, v in specs.items() if k not in functions}
    by_bare = {}
    for key in right:
        by_bare.setdefault((key[0], key[1], _bare(key[2])), []).append(key)

    # A bare name claimed by more than one design entry is the collision the
    # qualifier exists to prevent -- `AddOperation::apply` and
    # `MultiplyOperation::apply` both go to `apply`. Guessing which spec belongs
    # to which method would invent an answer, so neither is paired and the
    # ambiguity is reported instead.
    claims = {}
    for key in left:
        claims.setdefault((key[0], key[1], _bare(key[2])), []).append(key)

    pairs, ambiguous = {}, []
    for bare_key, design_keys in claims.items():
        bucket = by_bare.get(bare_key) or []
        if len(design_keys) > 1 or len(bucket) > 1:
            ambiguous.append((bare_key, sorted(design_keys), list(bucket)))
            continue
        if bucket:
            pairs[design_keys[0]] = bucket[0]
    return pairs, ambiguous


def check(design, spec):
    """Findings from holding a SWE.3 document against its SWE.4 document."""
    out = []
    functions, specs = _design_functions(design), _spec_functions(spec)

    # One heading, two specs -- a defect in its own right, and the reason an
    # ambiguous pairing below cannot be resolved.
    for key, entries in sorted(specs.items()):
        if len(entries) < 2:
            continue
        component, unit, case = entries[0]
        out.append(Finding(
            level="L2", kind="integrity", field="duplicateName",
            path="%s / %s / %s" % (component.name, unit.name, case.name),
            severity=HIGH,
            summary="%d specifications share the heading %r"
                    % (len(entries), case.fields.get("qualifiedName") or case.name),
            rule=("two methods of different classes take the same heading once the class is "
                  "dropped; the design keeps it precisely so they stay apart (%s, 'Names')"
                  % WIKI3),
        ))

    renamed, ambiguous = _same_function_two_names(functions, specs)
    renamed_specs = set(renamed.values())

    for bare_key, design_keys, spec_keys in sorted(ambiguous):
        component, unit, iface = functions[design_keys[0]][0]
        names = sorted(functions[k][0][2].name for k in design_keys)
        out.append(Finding(
            level="L2", kind="integrity", field="ambiguousPairing",
            path="%s / %s / %s" % (component.name, unit.name, bare_key[2]),
            severity=HIGH, left=names,
            summary="%s cannot be paired with a specification: %s all reduce to the same "
                    "bare name" % (bare_key[2], ", ".join(names)),
            rule=("the design distinguishes them by the class in front; a specification that "
                  "prints the bare name leaves no way to tell which spec is which (%s, 'Names')"
                  % WIKI3),
        ))

    for design_key, spec_key in sorted(renamed.items()):
        component, unit, iface = functions[design_key][0]
        _c, _u, case = specs[spec_key][0]
        out.append(Finding(
            level="L2", kind="renamed",
            path="%s / %s / %s" % (component.name, unit.name, iface.name),
            field="functionName", severity=MEDIUM,
            left=iface.name, right=case.name,
            summary="the design calls this function %r and the specification calls it %r"
                    % (iface.name, case.name),
            rule=("the design keeps the class in front of a method because that is what tells "
                  "two same-named methods apart (%s, 'Names'); a specification that drops it "
                  "cannot tell them apart, and two methods of different classes in one unit "
                  "would take the same heading" % WIKI3),
        ))

    ambiguous_design = {k for _b, keys, _s in ambiguous for k in keys}
    for key, entries in sorted(functions.items()):
        component, unit, iface = entries[0]
        where = "%s / %s / %s" % (component.name, unit.name, iface.name)
        if key in specs or key in renamed or key in ambiguous_design:
            continue
        # An inline public function is defined in a header and is covered through
        # its own unit's callers, so it is *expected* to have no spec. Neither
        # document says which functions are inline, so this is named as the likely
        # reason rather than asserted.
        out.append(Finding(
            level="L2", kind="missing", path=where, field="spec",
            severity=MEDIUM,
            summary="the design publishes this function but the test specification has no spec for it",
            rule=("an inline public function -- one defined in a header -- gets no spec of its "
                  "own and is covered through its own unit's callers (%s, 'Who gets a spec'). "
                  "Neither document states which functions are inline, so this needs a look at "
                  "the code to settle." % WIKI4),
        ))

    ambiguous_spec = {k for _b, _d, keys in ambiguous for k in keys}
    for key, entries in sorted(specs.items()):
        component, unit, case = entries[0]
        if key in functions or key in renamed_specs or key in ambiguous_spec:
            continue
        out.append(Finding(
            level="L2", kind="extra", path="%s / %s / %s" % (component.name, unit.name, case.name),
            field="spec", severity=HIGH,
            summary="the test specification specifies a function the design does not publish",
            rule=("every function with a spec should appear in the detailed design (%s, "
                  "'Who gets a spec'); a spec for something the design does not publish is a "
                  "test for an interface nobody is told about" % WIKI4),
        ))

    # The Test Case ID is the Interface ID with TC_ in front, so the two documents
    # can be checked against each other without agreeing on anything else.
    for key, entries in sorted(functions.items()):
        component, unit, iface = entries[0]
        spec_key = key if key in specs else renamed.get(key)
        # An ambiguous or duplicated name has no single spec to check against.
        if spec_key is None or len(entries) > 1 or len(specs.get(spec_key, [])) > 1:
            continue
        _c, _u, case = specs[spec_key][0]
        design_id = (iface.fields.get("interfaceId") or "").strip().strip("`")
        spec_id = (case.fields.get("testCaseId") or "").strip().strip("`")
        if not design_id or not spec_id:
            continue
        if spec_id != "TC_" + design_id:
            out.append(Finding(
                level="L2", kind="differs",
                path="%s / %s / %s" % (component.name, unit.name, iface.name),
                field="testCaseId", severity=MEDIUM,
                left=design_id, right=spec_id,
                summary="Test Case ID %r is not TC_ plus the design's Interface ID %r"
                        % (spec_id, design_id),
                rule="a Test Case ID is derived as `TC_<interfaceId>` (%s, 'Table B')" % WIKI4,
            ))

    # One to one, with no exception written anywhere -- so a difference here is a
    # difference, not a judgement call.
    design_ia, spec_ia = _design_interactions(design), _spec_interactions(spec)
    for key, (component, ia) in sorted(design_ia.items()):
        if key in spec_ia:
            continue
        out.append(Finding(
            level="L4", kind="missing", path="%s / %s" % (component.name, ia.name),
            field="interaction", severity=HIGH,
            summary="the design draws this behaviour diagram but the test specification "
                    "has no interaction spec for it",
            rule=("a dynamic-behaviour spec exists exactly where SWE.3 draws a behaviour "
                  "diagram; the two pair one to one (%s, 'Dynamic Behaviour test specs')" % WIKI4),
        ))
    for key, (component, ia) in sorted(spec_ia.items()):
        if key in design_ia:
            continue
        out.append(Finding(
            level="L4", kind="extra", path="%s / %s" % (component.name, ia.name),
            field="interaction", severity=HIGH,
            summary="the test specification specifies an interaction the design draws no "
                    "diagram for",
            rule=("the same pairing rule, the other way round: SWE.3 applies two filters after "
                  "the shared selector, so the two sides can drift apart (%s, 'Dynamic "
                  "Behaviour test specs'; see tools/swe4_dynamic_diff.py)" % WIKI4),
        ))

    out.sort(key=lambda f: f.sort_key())
    return out


def summary(design, spec, findings):
    """A line saying how far the two documents agree."""
    functions = sum(len(v) for v in _design_functions(design).values())
    specs = sum(len(v) for v in _spec_functions(spec).values())
    d_ia, s_ia = len(_design_interactions(design)), len(_spec_interactions(spec))
    return ("design publishes %d function(s), the specification specifies %d; "
            "behaviour diagrams %d, interaction specs %d; %d finding(s)"
            % (functions, specs, d_ia, s_ia, len(findings)))
