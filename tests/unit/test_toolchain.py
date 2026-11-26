"""The compiler that builds the code (`core.toolchain`, armCompiler.path) and the layer target
args Phase 1 parses with (2026-11-25).

libclang reads the code; armclang builds it. What armclang brings by itself -- its header
folders and the macros it defines -- is asked of it once per set of target flags, and joins the
build's target flags (compile_commands.json, checked with libclang first) in every TU's args.

No Arm compiler is installed here, so the compiler is a stand-in: a canned answer for the
reading rules, and a Python script for the one test that starts a real process (through `ask`'s
`run` hook, so it runs the same on Windows and Linux). The parser tests need libclang and skip
without it.

Also here (2026-11-26): what a missing compiler header costs, on the sample's own fixture
(Layer1/Diag/ArmCompilerHeaders.cpp), parsed without the compiler's folder and with stand-ins.
"""
import copy
import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ENGINE = os.path.join(ROOT, "engine")
if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)

from core import toolchain as tc                      # noqa: E402
from core.compile_commands import target_args          # noqa: E402

# Shaped like armclang's -v output (not a copy of it): a version block, then the search lists.
ARMCLANG_STDERR = """\
Product: Arm Compiler for Embedded 6.16 Professional
Component: Arm Compiler for Embedded 6.16
Tool: armclang [5e000000]
Target: arm-arm-none-eabi
#include "..." search starts here:
#include <...> search starts here:
 {libcxx}
 {include}
End of search list.
"""
ARMCLANG_STDOUT = """\
#define __ARMCC_VERSION 6160001
#define __ARM_ARCH 7
#define __clang_major__ 13
#define __ARMCOMPILER_LIBCXX 1
#define __ARM_INTRIN(x) x
#define __EMPTY
"""


def _dirs(tmp_path):
    libcxx = tmp_path / "include" / "libcxx"
    libcxx.mkdir(parents=True)
    return str(libcxx), str(tmp_path / "include")


class _Done:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out.encode(), err.encode()


# ---------------------------------------------------------------------------
# Reading an answer
# ---------------------------------------------------------------------------

class TestReadingAnAnswer:
    def test_the_header_folders_come_from_the_angle_bracket_list_in_order(self, tmp_path):
        libcxx, include = _dirs(tmp_path)
        answer = tc.read_answer("", ARMCLANG_STDERR.format(libcxx=libcxx, include=include))
        assert answer.include_dirs == [libcxx, include]
        assert answer.version == "Component: Arm Compiler for Embedded 6.16"

    def test_linux_paths_and_a_framework_suffix_read_the_same(self):
        err = ("clang version 21.1.8\n#include <...> search starts here:\n"
               " /opt/arm/include\n /Library/Frameworks (framework directory)\nEnd of search list.\n")
        answer = tc.read_answer("", err)
        assert answer.include_dirs == ["/opt/arm/include", "/Library/Frameworks"]
        assert answer.version == "clang version 21.1.8"

    def test_object_like_macros_are_read_and_function_like_skipped(self):
        macros = tc.read_answer(ARMCLANG_STDOUT, "").macros
        assert macros == {"__ARMCC_VERSION": "6160001", "__ARM_ARCH": "7",
                          "__clang_major__": "13", "__ARMCOMPILER_LIBCXX": "1", "__EMPTY": ""}

    def test_only_macros_libclang_lacks_are_added_and_libclangs_value_stays(self):
        macros = tc.read_answer(ARMCLANG_STDOUT, "").macros
        added = tc.macros_to_add(macros, {"__ARM_ARCH", "__clang_major__"})
        assert added == {"__ARMCC_VERSION": "6160001", "__ARMCOMPILER_LIBCXX": "1", "__EMPTY": ""}

    def test_the_args_are_one_each_folders_on_this_machine_first(self, tmp_path):
        libcxx, include = _dirs(tmp_path)       # include/libcxx exists, so include does too
        answer = tc.read_answer(ARMCLANG_STDOUT, ARMCLANG_STDERR.format(
            libcxx=libcxx, include=include) + "")
        answer.include_dirs.append(str(tmp_path / "not-here"))
        args = tc.parse_args(answer, {"__ARM_ARCH", "__clang_major__", "__EMPTY"})
        assert args == [f"-isystem{libcxx}", f"-isystem{include}",
                        "-D__ARMCC_VERSION=6160001", "-D__ARMCOMPILER_LIBCXX=1"]

    def test_a_failed_answer_adds_nothing(self):
        assert tc.parse_args(tc.CompilerAnswer(error="exit 1: boom", macros={"A": "1"}), set()) == []


# ---------------------------------------------------------------------------
# Asking
# ---------------------------------------------------------------------------

class TestAsking:
    def test_the_query_preprocesses_empty_input_with_the_target_flags(self):
        assert tc.query_command("armclang", ["--target=arm-arm-none-eabi", "-mcpu=cortex-m7"]) == [
            "armclang", "--target=arm-arm-none-eabi", "-mcpu=cortex-m7",
            "-x", "c++", "-std=c++14", "-E", "-dM", "-v", "-"]

    def test_the_query_flags_are_target_flags_only_project_last(self):
        build = ["--target=arm-arm-none-eabi", "-mcpu=cortex-m7", "-include/x/pre.h"]
        project = ["-mcpu=cortex-m4", "-DPUBLIC=", "-I/x", "-isystem/y"]
        assert tc.query_flags(build, project, target_args) == [
            "--target=arm-arm-none-eabi", "-mcpu=cortex-m7", "-mcpu=cortex-m4"]

    def test_a_compiler_that_is_not_there_is_said_not_raised(self, tmp_path):
        answer = tc.ask(str(tmp_path / "armclang.exe"), [])
        assert answer.error.startswith("not found:")

    def test_a_failing_compiler_names_its_error(self, tmp_path):
        exe = tmp_path / "armclang"
        exe.write_text("")
        answer = tc.ask(str(exe), [], run=lambda *a, **k: _Done(
            1, err="armclang: error: Failed to check out a license.\n"))
        assert answer.error == "exit 1: armclang: error: Failed to check out a license."

    def test_a_compiler_with_no_search_list_is_not_used(self, tmp_path):
        exe = tmp_path / "armcc"
        exe.write_text("")
        answer = tc.ask(str(exe), [], run=lambda *a, **k: _Done(0, out="#define __CC_ARM 1\n"))
        assert "no header search list" in answer.error
        assert tc.parse_args(answer, set()) == []

    def test_a_compiler_that_does_not_finish_is_stopped(self, tmp_path):
        exe = tmp_path / "armclang"
        exe.write_text("")

        def hang(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        assert tc.ask(str(exe), [], run=hang, timeout=5).error == "no answer in 5 s"

    def test_a_real_process_answers_through_empty_input(self, tmp_path):
        """A stand-in compiler script, started as a real process: it gets the query's arguments
        and empty input, and prints what armclang would."""
        libcxx, include = _dirs(tmp_path)
        stub = tmp_path / "stand_in_armclang.py"
        stub.write_text(
            "import sys\n"
            "args = sys.argv[1:]\n"
            "assert args[-4:] == ['-E', '-dM', '-v', '-'], args\n"
            "assert sys.stdin.read() == ''\n"
            f"sys.stdout.write({ARMCLANG_STDOUT!r})\n"
            f"sys.stderr.write({ARMCLANG_STDERR.format(libcxx=libcxx, include=include)!r})\n",
            encoding="utf-8")

        def run(cmd, **kw):
            return subprocess.run([sys.executable, str(stub), *cmd[1:]], **kw)
        answer = tc.ask(str(stub), ["--target=arm-arm-none-eabi"], run=run)
        assert not answer.error
        assert answer.include_dirs == [libcxx, include]
        assert answer.macros["__ARMCC_VERSION"] == "6160001"

    def test_the_path_is_this_machines_config_local_setting(self):
        assert tc.configured_path({"armCompiler": {"path": " C:/Arm/bin/armclang.exe "}}) == \
            "C:/Arm/bin/armclang.exe"
        assert tc.configured_path({"armCompiler": {"path": None}}) == ""
        assert tc.configured_path({}) == ""


# ---------------------------------------------------------------------------
# Phase 1: the layer target args
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def parser_mod():
    """Import parser.py (reads argv at import; also configures libclang)."""
    old_argv = sys.argv
    sys.argv = ["parser.py", ROOT]
    try:
        import parser as P
    except Exception as e:  # libclang missing / load failure
        pytest.skip(f"parser/libclang unavailable: {e}")
    finally:
        sys.argv = old_argv
    yield P


@pytest.fixture
def layer_state(parser_mod, tmp_path, monkeypatch):
    """The parser's layer state, put back afterwards; its model dir in tmp_path."""
    P = parser_mod
    saved = (dict(P._BUILD_FLAG_ARGS_BY_LAYER), dict(P._TARGET_ARGS_BY_LAYER))
    monkeypatch.setattr(P, "MODEL_DIR", str(tmp_path))
    P._LAYER_ARGS_CACHE.clear()
    yield P
    P._BUILD_FLAG_ARGS_BY_LAYER.clear()
    P._BUILD_FLAG_ARGS_BY_LAYER.update(saved[0])
    P._TARGET_ARGS_BY_LAYER.clear()
    P._TARGET_ARGS_BY_LAYER.update(saved[1])
    P._LAYER_ARGS_CACHE.clear()


M7 = ["--target=arm-arm-none-eabi", "-mcpu=cortex-m7"]


class TestLibclangChecksTheBuildFlags:
    def test_flags_it_takes_are_kept_whole(self, parser_mod):
        assert parser_mod._flags_libclang_takes(M7 + ["-fshort-enums"]) == (M7 + ["-fshort-enums"], [])

    def test_an_unknown_cpu_is_left_out_and_the_rest_kept(self, parser_mod):
        """Measured: `-mcpu=` of a CPU libclang does not know makes every TU fail to load."""
        kept, left_out = parser_mod._flags_libclang_takes(
            ["--target=arm-arm-none-eabi", "-mcpu=not-a-cpu", "-fshort-enums"])
        assert kept == ["--target=arm-arm-none-eabi", "-fshort-enums"]
        assert left_out == ["-mcpu=not-a-cpu"]

    def test_a_flag_wrong_only_with_the_cpu_before_it_is_left_out(self, parser_mod):
        kept, left_out = parser_mod._flags_libclang_takes(M7 + ["-marm"])
        assert kept == M7 and left_out == ["-marm"]

    def test_an_include_file_is_kept_even_if_it_does_not_parse_alone(self, parser_mod, tmp_path):
        """The probe has no include dirs; a forced header that needs them is no wrong flag."""
        pre = tmp_path / "pre.h"
        pre.write_text("#include \"needs_an_include_dir.h\"\nproject_t g;\n", encoding="utf-8")
        flags = M7 + ["-include" + str(pre)]
        assert parser_mod._flags_libclang_takes(flags) == (flags, [])

    def test_libclangs_own_macros_follow_the_cpu(self, parser_mod):
        names = parser_mod._libclang_macro_names(M7)
        assert {"__ARM_ARCH", "__ARM_ARCH_7EM__", "__clang__"} <= names
        assert "__ARMCC_VERSION" not in names


class TestSettlingTheTargetArgs:
    def _answer(self, tmp_path):
        libcxx, include = _dirs(tmp_path)
        return tc.read_answer(ARMCLANG_STDOUT, ARMCLANG_STDERR.format(libcxx=libcxx, include=include))

    def test_build_flags_then_the_compilers_folders_and_missing_macros(self, layer_state, tmp_path,
                                                                       monkeypatch):
        P = layer_state
        P._BUILD_FLAG_ARGS_BY_LAYER.clear()
        P._BUILD_FLAG_ARGS_BY_LAYER.update({"Layer1": M7 + ["-mcpu=not-a-cpu"]})
        asked = []
        answer = self._answer(tmp_path)
        monkeypatch.setattr(tc, "ask", lambda path, flags, **k: asked.append(flags) or answer)
        monkeypatch.setattr(P, "_config", {**P._config, "armCompiler": {"path": "C:/Arm/armclang.exe"},
                                           "layers": {"Layer1": {}}})
        monkeypatch.setattr(P, "_selected_layers", [])
        P._settle_target_args()
        libcxx, include = answer.include_dirs
        assert P._TARGET_ARGS_BY_LAYER == {"Layer1": M7 + [
            f"-isystem{libcxx}", f"-isystem{include}",
            "-D__ARMCC_VERSION=6160001", "-D__ARMCOMPILER_LIBCXX=1", "-D__EMPTY="]}
        assert asked == [tc.query_flags(M7, P._CLANG_EXTRA, target_args)]     # once, checked flags
        stored = json.loads((tmp_path / "clang_target_args.json").read_text(encoding="utf-8"))
        assert stored == P._TARGET_ARGS_BY_LAYER

    def test_no_compiler_set_means_the_checked_build_flags_alone(self, layer_state, monkeypatch):
        P = layer_state
        P._BUILD_FLAG_ARGS_BY_LAYER.clear()
        P._BUILD_FLAG_ARGS_BY_LAYER.update({"Layer1": M7})
        monkeypatch.setattr(tc, "ask", lambda *a, **k: pytest.fail("asked with no armCompiler.path"))
        monkeypatch.setattr(P, "_config", {k: v for k, v in P._config.items() if k != "armCompiler"})
        P._settle_target_args()
        assert P._TARGET_ARGS_BY_LAYER == {"Layer1": M7}

    def test_a_layer_without_build_flags_gets_the_compilers_answer_as_star(self, layer_state, tmp_path,
                                                                          monkeypatch):
        P = layer_state
        P._BUILD_FLAG_ARGS_BY_LAYER.clear()
        answer = self._answer(tmp_path)
        monkeypatch.setattr(tc, "ask", lambda path, flags, **k: answer)
        monkeypatch.setattr(P, "_config", {**P._config, "armCompiler": {"path": "C:/Arm/armclang.exe"}})
        P._settle_target_args()
        assert list(P._TARGET_ARGS_BY_LAYER) == ["*"]
        assert P.target_args_for_layer("Layer9") == P._TARGET_ARGS_BY_LAYER["*"]

    def test_a_failed_answer_leaves_the_build_flags_as_they_are(self, layer_state, monkeypatch):
        P = layer_state
        P._BUILD_FLAG_ARGS_BY_LAYER.clear()
        P._BUILD_FLAG_ARGS_BY_LAYER.update({"Layer1": M7})
        monkeypatch.setattr(tc, "ask", lambda *a, **k: tc.CompilerAnswer(error="not found: x"))
        monkeypatch.setattr(P, "_config", {**P._config, "armCompiler": {"path": "x"},
                                           "layers": {"Layer1": {}}})
        monkeypatch.setattr(P, "_selected_layers", [])
        P._settle_target_args()
        assert P._TARGET_ARGS_BY_LAYER == {"Layer1": M7}


class TestTheArgsATranslationUnitGets:
    def test_target_args_sit_between_the_fixed_args_and_clang_args(self, layer_state):
        """clang honours the last --target / -mcpu / -D: the project's clangArgs still win."""
        P = layer_state
        P._TARGET_ARGS_BY_LAYER.clear()
        P._TARGET_ARGS_BY_LAYER.update({"Layer1": M7 + ["-D__ARMCC_VERSION=6160001"]})
        args = P.clang_args_for(os.path.join(ROOT, "not_in_any_component.cpp"))   # no layer
        n = len(P._CLANG_BASE)
        assert args[:n] == P._CLANG_BASE
        assert args[n:n + 3] == M7 + ["-D__ARMCC_VERSION=6160001"]
        assert args[n + 3:n + 3 + len(P._CLANG_EXTRA)] == P._CLANG_EXTRA

    def test_without_target_args_a_tu_gets_what_it_got_before(self, layer_state):
        P = layer_state
        P._TARGET_ARGS_BY_LAYER.clear()
        args = P.clang_args_for(os.path.join(ROOT, "not_in_any_component.cpp"))
        assert args[:len(P.CLANG_ARGS)] == P.CLANG_ARGS

    def test_the_fingerprint_moves_with_them_and_not_without(self, layer_state):
        P = layer_state
        P._TARGET_ARGS_BY_LAYER.clear()
        before = P._fingerprint_args()
        assert not any(a.startswith("--layer-target=") for a in before)
        P._TARGET_ARGS_BY_LAYER.update({"Layer1": M7})
        after = P._fingerprint_args()
        assert "--layer-target=Layer1" in after and after != before


# ---------------------------------------------------------------------------
# Phase 1: headers that only the compiler has (SampleCppProject/Layer1/Diag/ArmCompilerHeaders.cpp)
# ---------------------------------------------------------------------------

DIAG = os.path.join(ROOT, "SampleCppProject", "Layer1", "Diag")
COMPILER_HEADERS_UNITS = ("ArmLog.cpp", "ArmCompilerHeaders.cpp", "ArmCompilerHeadersUser.cpp")

# Stand-ins for two headers of Arm Compiler 6's include folder: what the fixture uses, no more.
STAND_IN_HEADERS = {
    "arm_compat.h": "static inline void __disable_irq(void) { __asm__ volatile(\"cpsid i\"); }\n"
                    "static inline void __enable_irq(void) { __asm__ volatile(\"cpsie i\"); }\n"
                    "static inline void __nop(void) { __asm__ volatile(\"nop\"); }\n",
    "string.h": "extern \"C\" unsigned int strlen(const char *s);\n",
}


def _parse_diag(P, extra_args):
    """Phase 1's two passes over the fixture's three units, with `extra_args` after the parser's
    own args; what they recorded, by plain name. The parser's module state is put back after."""
    saved = {n: (v, copy.copy(v)) for n, v in vars(P).items()
             if isinstance(v, (dict, set, list)) and not n.startswith("__")}
    real = (P.is_project_file, P.index)

    class _WithArgs:
        def parse(self, path, args=None, options=0, **kw):
            return real[1].parse(path, args=list(args or []) + extra_args, options=options, **kw)

    try:
        for name in ("functions", "call_graph", "reverse_call_graph", "_visited_function_keys",
                     "_visited_call_keys", "_visited_global_access_keys", "_visited_usage_keys",
                     "_diag_unresolved_calls", "_diag_missing_headers"):
            getattr(P, name).clear()
        diag = os.path.normcase(DIAG)
        P.is_project_file = lambda p: os.path.normcase(os.path.abspath(p)).startswith(diag)
        P.index = _WithArgs()
        paths = [os.path.join(DIAG, f) for f in COMPILER_HEADERS_UNITS]
        for path in paths:
            P.parse_file(path)
        for path in paths:
            P.parse_calls_and_globals(path)
        name = {k: f["functionName"] for k, f in P.functions.items()}
        return {
            "functions": set(name.values()),
            "calls": {name[k]: [name.get(c, c) for c in cs] for k, cs in P.call_graph.items()},
            "unresolved": [(os.path.basename(f), line, text, why)
                           for f, line, text, why in P._diag_unresolved_calls],
            "missing": set(P._diag_missing_headers),
        }
    finally:
        P.is_project_file, P.index = real
        for _n, (obj, before) in saved.items():
            obj.clear()
            obj.extend(before) if isinstance(obj, list) else obj.update(before)


def _line_of(code, file="ArmCompilerHeaders.cpp"):
    """The line a statement starts on -- not the comment that quotes it."""
    with open(os.path.join(DIAG, file), encoding="utf-8") as fh:
        return next(i for i, line in enumerate(fh, 1) if line.strip().startswith(code))


@pytest.fixture(scope="module")
def compiler_folder(tmp_path_factory):
    d = tmp_path_factory.mktemp("armclang_include")
    for name, text in STAND_IN_HEADERS.items():
        (d / name).write_text(text, encoding="utf-8")
    return str(d)


class TestAHeaderOnlyTheCompilerHas:
    """Measured 2026-11-26: without the compiler's folder, a call loses its callee when it, or
    one of its arguments, names something from the missing header -- a project call included."""

    @pytest.fixture(scope="class")
    def without(self, parser_mod):
        return _parse_diag(parser_mod, [])

    @pytest.fixture(scope="class")
    def with_folder(self, parser_mod, compiler_folder):
        return _parse_diag(parser_mod, ["-isystem" + compiler_folder])

    def test_without_it_the_header_is_missing_and_the_functions_are_still_there(self, without):
        assert "arm_compat.h" in without["missing"]
        assert {"ArmCriticalReport", "ArmAsmBarrier", "ArmFastAdd", "ArmResetEntry",
                "DiagLogText", "DiagLogLength", "ArmStartup"} <= without["functions"]

    def test_without_it_a_project_call_with_strlen_in_its_argument_is_lost(self, without):
        assert without["calls"]["ArmCriticalReport"] == ["DiagLogText"]
        assert ("ArmCompilerHeaders.cpp", _line_of("DiagLogLength(strlen"), "DiagLogLength",
                "a callee the parse cannot see") in without["unresolved"]

    def test_with_it_every_project_call_is_linked(self, with_folder):
        assert not with_folder["missing"]
        assert with_folder["calls"]["ArmCriticalReport"] == ["DiagLogText", "DiagLogLength"]
        assert not [u for u in with_folder["unresolved"] if u[0] == "ArmCompilerHeaders.cpp"]

    def test_the_compilers_own_functions_are_not_the_projects(self, with_folder):
        assert not {"__disable_irq", "__enable_irq", "__nop", "strlen"} & with_folder["functions"]

    def test_calls_that_name_nothing_from_it_are_linked_either_way(self, without, with_folder):
        for parsed in (without, with_folder):
            assert parsed["calls"]["ArmStartup"] == ["ArmCriticalReport", "ArmAsmBarrier"]


# ---------------------------------------------------------------------------
# analyzer.py doctor
# ---------------------------------------------------------------------------

class TestDoctorSaysWhatIsSet:
    """Optional: never a run-blocking check, whatever it finds."""

    @pytest.fixture
    def doctor(self, monkeypatch):
        tools = os.path.join(ROOT, "tools")
        if tools not in sys.path:
            sys.path.insert(0, tools)
        import doctor as D
        return D

    def _check(self, D, monkeypatch, block):
        monkeypatch.setattr(D, "_server_settings", lambda: {"armCompiler": block} if block else {})
        return D.check_arm_compiler()

    def test_not_set_is_fine(self, doctor, monkeypatch):
        c = self._check(doctor, monkeypatch, None)
        assert (c.status, c.required) == (doctor.OK, False) and "not set" in c.detail

    def test_a_path_that_is_not_there_is_a_warning(self, doctor, monkeypatch, tmp_path):
        c = self._check(doctor, monkeypatch, {"path": str(tmp_path / "armclang.exe")})
        assert (c.status, c.required) == (doctor.WARN, False) and "not found" in c.detail

    def test_a_compiler_that_answers_shows_its_version(self, doctor, monkeypatch):
        c = self._check(doctor, monkeypatch, {"path": sys.executable})   # `python --version`
        assert c.status == doctor.OK and "Python" in c.detail
