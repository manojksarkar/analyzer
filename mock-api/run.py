"""
Launcher for the mock API — works from ANY current directory.

    python run.py                      # http://127.0.0.1:8000, autoreload on

This is the cwd-independent equivalent of (run from this folder):

    uvicorn api.main:app --reload --app-dir . --port 8000

The `api` package lives next to this file (mock-api/api). We pass that directory
to uvicorn as `app_dir` so the import works in the reloader's child process too
(on Windows the spawned worker does not inherit the cwd on sys.path, which is the
usual cause of `ModuleNotFoundError: No module named 'api'` when using --reload).

Optional env overrides: HOST, PORT, RELOAD=0 to disable autoreload.
"""
import os
import pathlib
import uvicorn

HERE = str(pathlib.Path(__file__).resolve().parent)

if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        reload=os.environ.get("RELOAD", "1") != "0",
        reload_dirs=[HERE],   # watch only this mock, not the whole repo / cwd
        app_dir=HERE,
    )
