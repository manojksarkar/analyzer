"""`python analyzer.py ...`, stopped as Ctrl+C stops it (jst_core.CliRun.ctrl_c).

On Windows a process started in a group of its own -- which the test needs, to signal the run
alone -- cannot be sent Ctrl+C, only Ctrl+Break, and Ctrl+Break ends Python at once, its
`finally` blocks never run. Here Ctrl+Break raises the KeyboardInterrupt Ctrl+C raises, so the run
ends as a Ctrl+C in its window ends it: a command-line job cancelled (REQ-JS-29). Arguments are
analyzer.py's.
"""
import os
import runpy
import signal
import sys

ANALYZER = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "analyzer.py")

if hasattr(signal, "SIGBREAK"):
    signal.signal(signal.SIGBREAK, signal.default_int_handler)
sys.argv = [ANALYZER] + sys.argv[1:]
runpy.run_path(ANALYZER, run_name="__main__")
