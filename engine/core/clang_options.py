"""libclang parse options that every parse of a translation unit shares.

Phase 1 (`engine/parser.py`) and the flowchart engine (`engine/flowchart/`, a process of its own)
parse the same sources. The model's call edges and the flowcharts' control flow must come from
the same AST, so the option both add on top of their own lives here, once.
"""

# CXTranslationUnit_KeepGoing, from clang-c/Index.h. The Python bindings (18.1.1) have no
# constant for it, so the raw value gets a name here.
#
# Without it, the first FATAL error in a translation unit -- a missing `#include` -- makes clang
# stop instantiating templates for the rest of that file. A call on a class-template member
# (`g_ring.push(p)`) then comes back as a CALL_EXPR with an empty spelling and no referenced
# cursor: the call edge is lost, so is the global read through it, and an `auto` return type
# stays `auto`. With it, the missing include is an ordinary error (severity 3, not 4), clang
# carries on, and later missing includes are reported too. Plain functions, globals and calls
# come out the same either way, and headers after the missing one are entered either way.
#
# Always on, with no config switch. Phase 1 folds it into `parseFingerprint`, so a narrowed
# parse never merges onto a baseline that was parsed without it.
PARSE_KEEP_GOING = 0x200
