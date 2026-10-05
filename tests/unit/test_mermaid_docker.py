"""Mermaid diagrams render in the minlag/mermaid-cli docker image when it draws on this machine.

On the offline Linux server local mmdc drew nothing, while `docker run ... minlag/mermaid-cli`
did: the image brings its own Chromium. So docker is used first when the image is loaded (never
pulled) AND a test drawing in it works, and local mmdc otherwise -- and `doctor` asks for one of
the two, not for mmdc.
"""
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "engine"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import doctor  # noqa: E402
import utils  # noqa: E402


def _machine(monkeypatch, *, docker, image, draws=True):
    """A machine with or without docker, the image loaded or not, and a docker that can draw
    in this folder or not. Returns every docker command it was asked to run."""
    import core.subprocess_util as su
    asked = []

    def which(name):
        return "/usr/bin/docker" if (name == "docker" and docker) else None

    def run(cmd, **kw):
        asked.append(cmd)
        return subprocess.CompletedProcess(cmd, 0 if image else 1, "", "")

    def test_drawing(cmd, *, timeout, shell=False):
        asked.append(cmd)
        if draws:
            out = cmd[cmd.index("-v") + 1].rsplit(":", 1)[0]
            open(os.path.join(out, "test.png"), "wb").close()
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 1, "", "EACCES: permission denied, open '/data/test.png'")
    monkeypatch.setattr("shutil.which", which)
    monkeypatch.setattr("subprocess.run", run)
    monkeypatch.setattr(su, "run_capture", test_drawing)
    monkeypatch.setattr(utils, "_mermaid_in_docker", None)
    doctor.mermaid_docker_image.cache_clear()
    return asked


def test_docker_with_the_image_draws_in_docker(monkeypatch, tmp_path):
    asked = _machine(monkeypatch, docker=True, image=True)
    cmd = utils.mmdc_command(str(tmp_path), str(tmp_path / "a.mmd"), str(tmp_path / "a.png"), scale=2)
    assert asked[0] == ["docker", "image", "inspect", "minlag/mermaid-cli"]   # loaded? never a pull
    assert asked[1][-4:] == ["-i", "/data/test.mmd", "-o", "/data/test.png"]  # then a test drawing
    assert len(asked) == 2
    assert not os.listdir(tmp_path / ".mmdc_cache")                           # which is cleaned up
    assert cmd[:3] == ["docker", "run", "--rm"]
    assert cmd[cmd.index("-v") + 1] == f"{tmp_path}:/data"
    i = cmd.index("minlag/mermaid-cli")
    assert cmd[i + 1:] == ["-i", "/data/a.mmd", "-o", "/data/a.png", "--scale", "2"]
    assert "-p" not in cmd                       # our puppeteer config names a host browser
    assert ("-u" in cmd) == hasattr(os, "getuid")


def test_asked_once_per_process(monkeypatch, tmp_path):
    asked = _machine(monkeypatch, docker=True, image=True)
    for _ in range(3):
        utils.mmdc_command(str(tmp_path), str(tmp_path / "a.mmd"), str(tmp_path / "a.png"))
    assert len(asked) == 2


def test_a_docker_that_cannot_draw_here_means_local_mmdc(monkeypatch, tmp_path):
    """SELinux, rootless docker, the analyzer itself in a container: the image is there, but
    a drawing in this folder fails -- so every diagram would have failed."""
    logged = []
    monkeypatch.setattr(utils, "log", lambda msg, *a, **k: logged.append(msg))
    _machine(monkeypatch, docker=True, image=True, draws=False)
    cmd = utils.mmdc_command(str(tmp_path), "a.mmd", "a.png")
    assert cmd[0] == utils.mmdc_path(str(tmp_path))
    assert any("permission denied" in m for m in logged)                 # says why
    assert logged[-1] == "mermaid diagrams: local mmdc"


@pytest.mark.parametrize("docker,image", [(False, False), (True, False)])
def test_otherwise_local_mmdc_as_before(monkeypatch, tmp_path, docker, image):
    asked = _machine(monkeypatch, docker=docker, image=image)
    cmd = utils.mmdc_command(ROOT, "a.mmd", "a.png", scale=2)
    assert not any(c[:2] == ["docker", "run"] for c in asked)          # no test drawing either
    assert cmd[0] == utils.mmdc_path(ROOT)
    assert cmd[1:5] == ["-i", "a.mmd", "-o", "a.png"]
    assert cmd[-2:] == ["--scale", "2"]
    pup = os.path.join(ROOT, "engine", "config", "puppeteer-config.json")
    assert ("-p" in cmd) == os.path.isfile(pup)


def test_the_behaviour_view_renders_through_the_same_command():
    src = open(os.path.join(ROOT, "engine", "views", "behaviour_diagram.py"), encoding="utf-8").read()
    assert "mmdc_command(project_root, mmd_path, png, scale=2)" in src
    assert "mmdc_path(" not in src


# --- doctor: one of the two is enough --------------------------------------------------------------

def test_doctor_is_satisfied_by_the_image_alone(monkeypatch):
    _machine(monkeypatch, docker=True, image=True)
    monkeypatch.setattr(doctor.os.path, "isfile", lambda p: False)       # no local mmdc anywhere
    c = doctor.check_mmdc()
    assert c.status == doctor.OK and "docker" in c.detail


def test_doctor_is_satisfied_by_local_mmdc_alone(monkeypatch):
    _machine(monkeypatch, docker=False, image=False)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/mmdc" if name == "mmdc" else None)
    assert doctor.check_mmdc().status == doctor.OK


def test_doctor_fails_with_neither(monkeypatch):
    _machine(monkeypatch, docker=True, image=False)
    monkeypatch.setattr(doctor.os.path, "isfile", lambda p: False)
    c = doctor.check_mmdc()
    assert c.status == doctor.FAIL and "minlag/mermaid-cli" in c.fix


def test_preflight_wants_no_local_browser_for_mermaid_drawn_in_docker(monkeypatch):
    monkeypatch.setattr(doctor, "mermaid_docker_image", lambda: True)
    browser_missing = doctor.Check("chromium", doctor.FAIL, category="render")
    monkeypatch.setattr(doctor, "collect_checks", lambda: [browser_missing])
    assert doctor.preflight(need_flowchart=False, need_mermaid=True) == []
    assert doctor.preflight(need_flowchart=True, need_mermaid=True) == [browser_missing]
