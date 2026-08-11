"""
Shared C++ token helpers for flowchart labelling.

One definition of "a function call", used by three places that must agree:

  * ``enrichment.enricher``  — declares every call on the node as ``call_names``
  * ``llm.prompts``          — tells the LLM which names its label must contain
  * ``llm.generator``        — deterministically verifies/repairs the label afterwards

The label rule those three implement: **a label is descriptive prose that names
every function the node calls**, each rendered as ``Name()`` — bare name plus
empty parens.  Argument lists are always stripped so the rendering is uniform
and the labels stay short against the DOT wrap width.

What counts as a call
---------------------
Named:      project functions and library/STL functions (``memcpy``, ``push_back``).
Not named:  macros (logging, assertions, ``MAX``-style), casts, and constructors.
Logging macros and assertions already have their own rules in the system prompt;
naming them as calls would contradict it.

Constructors cannot be told from functions textually — ``Point(1, 2)`` and
``process(1, 2)`` are the same shape — so that filter needs type knowledge.
Callers that have a PKB pass known type names via ``extract_call_names(exclude=…)``.
"""

import re
from typing import Iterable, List, Optional, Set

# ---------------------------------------------------------------------------
# C++ keywords — excluded from call detection and from data-flow identifiers
# ---------------------------------------------------------------------------

CPP_KEYWORDS: Set[str] = {
    "if", "else", "while", "for", "do", "switch", "case", "default",
    "return", "break", "continue", "goto", "throw", "try", "catch",
    "new", "delete", "nullptr", "true", "false", "this", "class", "struct",
    "public", "private", "protected", "virtual", "override", "const",
    "static", "auto", "int", "void", "bool", "char", "double", "float",
    "long", "short", "unsigned", "signed", "namespace", "using", "typedef",
    "template", "typename", "operator", "sizeof", "decltype", "explicit",
    "inline", "extern", "volatile", "enum", "union", "std", "nullptr",
    "and", "or", "not", "xor", "bitand", "bitor", "compl",
}

# Any identifier (optionally qualified / member-accessed) followed by '('.
# Mirrors enricher._CALL_PATTERN but keeps the receiver, so `doc.AddMember` and
# `obj->reset` survive as written — a label names them the way the code does.
_CALL_RE = re.compile(r'([A-Za-z_][\w:]*(?:\s*(?:\.|->)\s*[A-Za-z_]\w*)*)\s*\(')

# Type-level constructs that are syntactically calls but carry no behaviour
# worth naming in a flowchart box.
_CAST_NAMES: Set[str] = {
    "static_cast", "dynamic_cast", "const_cast", "reinterpret_cast",
    "sizeof", "alignof", "decltype", "typeid",
}

# Lowercase assertion forms. ALL-CAPS ones (ASSERT, SYS_ASSERT) fall under the
# macro rule below. The CFG builder already drops ASSERT statements so they
# never become nodes, but the text can still land inside a segment node's
# raw_code, where it must not turn into a named call.
_LOWER_ASSERTS: Set[str] = {"assert", "static_assert"}

_SPLIT_RE = re.compile(r'\.|->|::')


def short_name(name: str) -> str:
    """Leaf of a qualified/member call name (``Ops::Replicate`` → ``Replicate``)."""
    return _SPLIT_RE.split(name)[-1].strip()


def is_named_call(name: str, exclude: Optional[Set[str]] = None) -> bool:
    """True if *name* is a call worth naming in a flowchart label.

    ``exclude`` holds known type names (structs, typedefs, enums) so that
    constructor calls are filtered out; callers without a PKB omit it.
    """
    if not name:
        return False

    # The receiver is not part of the decision — `doc.AddMember` is judged on
    # `AddMember`, `Ns::fn` on `fn`.
    leaf = short_name(name)
    if not leaf:
        return False

    if leaf in CPP_KEYWORDS or name in CPP_KEYWORDS:
        return False
    if leaf in _CAST_NAMES or leaf in _LOWER_ASSERTS:
        return False

    # ALL-CAPS is the macro convention: logging (TRACE_DEBUG), assertions
    # (SYS_ASSERT), and value macros (MAX). None of them are functions.
    if leaf.isupper() and len(leaf) > 1:
        return False

    if exclude and (leaf in exclude or name in exclude):
        return False

    return True


def extract_call_names(
    raw_code: str,
    exclude: Optional[Iterable[str]] = None,
) -> List[str]:
    """Return every function called in *raw_code*, in source order, deduped.

    Names keep their receiver as written (``doc.AddMember``, ``obj->reset``,
    ``Ns::fn``) so a label can name the call the way the code does.

    ``exclude`` — known type names, to drop constructor calls.
    """
    if not raw_code:
        return []

    excluded = set(exclude) if exclude else None
    seen: Set[str] = set()
    names: List[str] = []
    for match in _CALL_RE.finditer(raw_code):
        name = re.sub(r'\s+', '', match.group(1))
        if name in seen or not is_named_call(name, excluded):
            continue
        seen.add(name)
        names.append(name)
    return names


def render_call(name: str) -> str:
    """Display form of a call name: ``Name()``.

    The single place that decides how a call appears inside a label. Arguments
    are never included — see the module docstring.
    """
    return f"{name.strip().rstrip('()')}()"
