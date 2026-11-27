"""What the compiler that builds the code knows and libclang does not (2026-11-25).

libclang reads the code; the firmware is built by another compiler (armclang, Arm Compiler 6).
That compiler brings two things the build never writes down, because it finds them itself:

* its own header folders -- the C and C++ library: `stdio.h`, `string.h`, `<cstring>`. LLVM's
  folder (`llvm.includePath`) has only the few every compiler brings (`stddef.h`, `stdint.h`),
  so without these the parse says `'stdio.h' file not found`, and an `#if` on a macro of such
  a header takes the wrong branch;
* the macros it defines by itself -- `__ARMCC_VERSION` for armclang -- which code tests.

`armCompiler.path` in config.local.json names that compiler on THIS machine (a server setting:
the build machine's path is not this one's). The parser asks it once per set of target flags
(`query_command`: preprocess nothing, print the macros and the header search list) and passes
the folders as `-isystem` and only the macros libclang does not define with the same flags as
`-D` -- one it defines too keeps libclang's value. Any clang- or gcc-style compiler answers the
same way (armclang, clang, arm-none-eabi-gcc); one that does not (armcc, Arm Compiler 5) gives
no search list, and the run says so and parses as before.

The compiler is started with its arguments as a list and empty input -- no shell, so the same
code runs on Windows and Linux.
"""
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

#: The query's language and standard: the parser reads every file as C++14.
_LANGUAGE = ["-x", "c++", "-std=c++14"]
_SEARCH_START = "#include <...> search starts here:"
_SEARCH_END = "End of search list."
_DEFINE_RE = re.compile(r"^#define\s+([A-Za-z_]\w*)(\(?)(?:\s+(.*))?$")
_TIMEOUT_SECONDS = 60


@dataclass
class CompilerAnswer:
    """What one query gave: the header folders in search order, the macros, a version line, or
    why there is nothing."""
    include_dirs: List[str] = field(default_factory=list)
    macros: Dict[str, str] = field(default_factory=dict)
    version: str = ""
    error: str = ""
    #: Why the compiler itself did not answer, when the answer was read from its install instead.
    not_run: str = ""


def configured_path(config: Dict[str, Any]) -> str:
    """`armCompiler.path` of this machine's config.local.json, "" when it is not set."""
    block = config.get("armCompiler") if isinstance(config, dict) else None
    return str((block or {}).get("path") or "").strip() if isinstance(block, dict) else ""


def configured_defines(config: Dict[str, Any]) -> Dict[str, str]:
    """`armCompiler.defines` of this machine's config.local.json: the compiler's own macros given
    by hand, for a copy that cannot run here -- `{"__ARMCC_VERSION": "6160001"}`, or a list of
    `"NAME=VALUE"` (`"NAME"` alone is 1). {} when not set."""
    block = config.get("armCompiler") if isinstance(config, dict) else None
    raw = block.get("defines") if isinstance(block, dict) else None
    if isinstance(raw, dict):
        items = [(str(k), "" if v is None else str(v)) for k, v in raw.items()]
    elif isinstance(raw, list):
        items = [(n, v if sep else "1") for n, sep, v in (str(i).partition("=") for i in raw)]
    else:
        return {}
    return {name.strip(): value.strip() for name, value in items if name.strip()}


def _existing(path: str) -> str:
    """`path` as it is on this machine: `armclang` names `armclang.exe` on Windows. "" when
    neither is there."""
    if os.path.exists(path):
        return path
    return path + ".exe" if os.path.isfile(path + ".exe") else ""


def install_include_dirs(path: str) -> List[str]:
    """The header folders of the Arm Compiler 6 install that `path` is in -- the compiler
    (`<install>/bin/armclang.exe`), its `bin` or the install folder: `<install>/include/libcxx`
    (C++) before `<install>/include` (C), those that exist. Read when the compiler cannot answer
    (a copy without its license); the layout is an install's, not an answer's."""
    found = _existing(path)
    if not found:
        return []
    found = os.path.abspath(found)
    base = found if os.path.isdir(found) else os.path.dirname(found)
    for root in (base, os.path.dirname(base)):
        include = os.path.join(root, "include")
        if os.path.isdir(include):
            return [d for d in (os.path.join(include, "libcxx"), include) if os.path.isdir(d)]
    return []


def arg_folders(args: Sequence[str]) -> List[str]:
    """The include folders `args` name: `-isystem<dir>`, `-isystem <dir>`, `-idirafter`, `-I`."""
    folders, it = [], iter([str(a) for a in (args or [])])
    for arg in it:
        for flag in ("-isystem", "-idirafter", "-I"):
            if arg == flag:
                folders.append(next(it, "").strip())
                break
            if arg.startswith(flag):
                folders.append(arg[len(flag):].strip())
                break
    return [f for f in folders if f]


def query_command(path: str, flags: Sequence[str]) -> List[str]:
    """The compiler asked to preprocess empty input (`-`) with the build's target flags: `-dM`
    prints every macro it defines, `-v` its header search list (on stderr)."""
    return [path, *flags, *_LANGUAGE, "-E", "-dM", "-v", "-"]


def read_answer(stdout: str, stderr: str) -> CompilerAnswer:
    """The header folders between `#include <...> search starts here:` and `End of search
    list.`, the object-like `#define`s, and the version line (`Component: ...` for armclang,
    else the first line of the -v output)."""
    answer = CompilerAnswer()
    lines = (stderr or "").splitlines()
    inside = False
    for line in lines:
        text = line.strip()
        if text == _SEARCH_START:
            inside = True
        elif text == _SEARCH_END:
            inside = False
        elif inside and text:
            if text.endswith(" (framework directory)"):
                text = text[: -len(" (framework directory)")]
            answer.include_dirs.append(text)
    versions = [l.strip() for l in lines if l.strip()]
    component = [l for l in versions if l.startswith("Component:")]
    answer.version = (component or versions or [""])[0]
    for line in (stdout or "").splitlines():
        m = _DEFINE_RE.match(line.strip())
        if m and not m.group(2):                       # function-like: fragile as a -D
            answer.macros[m.group(1)] = (m.group(3) or "").strip()
    return answer


def _first_error(stderr: str) -> str:
    for line in (stderr or "").splitlines():
        if "error" in line.lower():
            return line.strip()
    lines = [l.strip() for l in (stderr or "").splitlines() if l.strip()]
    return lines[-1] if lines else ""


def ask(path: str, flags: Sequence[str], *,
        run: Callable[..., Any] = subprocess.run,
        timeout: int = _TIMEOUT_SECONDS) -> CompilerAnswer:
    """Ask the compiler at `path` (`query_command`). Never raises: a compiler that is not there,
    does not finish, fails, or prints no search list gives an answer with `error` set."""
    path = _existing(path) or path
    if not os.path.isfile(path):
        return CompilerAnswer(error=f"not found: {path}")
    try:
        done = run(query_command(path, flags), stdin=subprocess.DEVNULL, capture_output=True,
                   timeout=timeout)
    except subprocess.TimeoutExpired:
        return CompilerAnswer(error=f"no answer in {timeout} s")
    except OSError as exc:
        return CompilerAnswer(error=f"could not start it ({exc})")
    stdout = _text(done.stdout)
    stderr = _text(done.stderr)
    answer = read_answer(stdout, stderr)
    if done.returncode != 0:
        answer.error = f"exit {done.returncode}: {_first_error(stderr) or 'no message'}"
    elif not answer.include_dirs:
        answer.error = "it printed no header search list (not a clang- or gcc-style compiler?)"
    return answer


def ask_or_read_install(path: str, flags: Sequence[str], defines: Optional[Dict[str, str]] = None,
                        **kw: Any) -> CompilerAnswer:
    """`ask`, and when the compiler cannot answer, what its install still gives: its header
    folders (`install_include_dirs`). `defines` (armCompiler.defines) join either answer; a
    macro the compiler itself prints keeps its value. So a copied armclang that has no license
    here works as it is, with its `__ARMCC_VERSION` set by hand."""
    answer = ask(path, flags, **kw)
    if answer.error and _existing(path):                # a wrong path stays "not found"
        folders = install_include_dirs(path)
        if not folders and not defines:
            return answer
        answer = CompilerAnswer(include_dirs=folders, not_run=answer.error)
    answer.macros = {**(defines or {}), **answer.macros}
    return answer


def _text(data: Any) -> str:
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return str(data or "")


def macros_to_add(compiler_macros: Dict[str, str], libclang_names: Iterable[str]) -> Dict[str, str]:
    """The compiler's macros libclang does not define with the same flags, by name. A macro both
    define keeps libclang's value: its own builtins (`__clang_major__`, `__cplusplus`) describe
    the parse, and the CPU's ones come from the same flags."""
    known = set(libclang_names)
    return {name: compiler_macros[name] for name in sorted(compiler_macros) if name not in known}


def parse_args(answer: CompilerAnswer, libclang_names: Iterable[str]) -> List[str]:
    """The arguments the parse takes from an answer: each header folder that is on this machine
    as `-isystem<dir>` (search order kept), then `-D<name>=<value>` for `macros_to_add`. One
    argument each, so no reader that dedupes arguments can split a pair."""
    if answer.error:
        return []
    args = [f"-isystem{d}" for d in answer.include_dirs if os.path.isdir(d)]
    args += [f"-D{name}={value}" for name, value in macros_to_add(answer.macros, libclang_names).items()]
    return args


def summary(path: str, answer: CompilerAnswer, args: Sequence[str]) -> str:
    """One log line for a query."""
    if answer.error:
        return f"{path}: {answer.error} -- its header folders and macros are not used"
    dirs = sum(1 for a in args if a.startswith("-isystem"))
    defines = [a[2:] for a in args if a.startswith("-D")]
    shown = ", ".join(defines[:5]) + (" ..." if len(defines) > 5 else "")
    head = (f"{path}: could not run ({answer.not_run}), so its install's header folders and "
            f"armCompiler.defines" if answer.not_run
            else f"{path} ({answer.version or 'version not printed'})")
    return (f"{head}: {dirs} header folder(s), "
            f"{len(defines)} macro(s) libclang does not define" + (f": {shown}" if shown else ""))


def query_flags(build_flags: Optional[Sequence[str]], clang_args: Sequence[str],
                target_filter: Callable[[Sequence[str]], List[str]]) -> List[str]:
    """The target flags a query is made with: the layer's from the build, then the project's
    `clang.clangArgs` (last wins, as in the parse), both through `target_filter` -- so a
    `-include`, a `-D` or an include dir never reaches the compiler's answer."""
    return target_filter(list(build_flags or []) + list(clang_args or []))
