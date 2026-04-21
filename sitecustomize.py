"""Enable coverage measurement in subprocesses.

When COVERAGE_PROCESS_START is set (pytest-cov sets it automatically when
parallel=true is in .coveragerc), this file calls coverage.process_startup()
so that any python subprocess also records coverage data.
"""
try:
    import coverage
    coverage.process_startup()
except Exception:
    pass
