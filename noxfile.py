# Copyright (c) 2021 UAVCAN Consortium
# This software is distributed under the terms of the MIT License.
# Author: Pavel Kirienko <pavel@uavcan.org>
# type: ignore

import os
import shutil
from pathlib import Path
import nox


PYTHONS = ["3.6", "3.7", "3.8", "3.9"]
"""The newest supported Python shall be listed LAST."""

nox.options.error_on_external_run = True

ROOT_DIR = Path(__file__).resolve().parent
THIRD_PARTY_DIR = ROOT_DIR / "pydsdl" / "third_party"


@nox.session(python=False)
def clean(session):
    wildcards = [
        "dist",
        "build",
        "html*",
        ".coverage*",
        ".*cache",
        ".*compiled",
        ".*generated",
        "*.egg-info",
        "*.log",
        "*.tmp",
        ".nox",
        ".dsdl-test",
    ]
    for w in wildcards:
        for f in Path.cwd().glob(w):
            session.log(f"Removing: {f}")
            if f.is_dir():
                shutil.rmtree(f, ignore_errors=True)
            else:
                f.unlink(missing_ok=True)


@nox.session(python=PYTHONS)
def test(session):
    session.log("Using the newest supported Python: %s", is_latest_python(session))
    session.install("-e", ".")
    session.install(
        "pytest          ~= 6.2",
        "pytest-randomly ~= 3.5",
        "coverage        ~= 5.5",
    )
    session.run("coverage", "run", "-m", "pytest")
    session.run("coverage", "report", "--fail-under=95")
    if session.interactive:
        session.run("coverage", "html")
        report_file = Path.cwd().resolve() / "htmlcov" / "index.html"
        session.log(f"OPEN IN WEB BROWSER: file://{report_file}")


@nox.session(python=PYTHONS, reuse_venv=True)
def lint(session):
    session.log("Using the newest supported Python: %s", is_latest_python(session))
    session.install(
        "mypy   == 0.812",
        "pylint == 2.7.2",
    )
    session.run(
        "mypy",
        "--strict",
        f"--config-file={ROOT_DIR / 'setup.cfg'}",
        "pydsdl",
        env={
            "MYPYPATH": str(THIRD_PARTY_DIR),
        },
    )
    session.run(
        "pylint",
        str(ROOT_DIR / "pydsdl"),
        env={
            "PYTHONPATH": str(THIRD_PARTY_DIR),
        },
    )
    if is_latest_python(session):
        session.install("black == 20.8b1")
        session.run("black", "--check", ".")


@nox.session(reuse_venv=True)
def docs(session):
    session.install("-r", "docs/requirements.txt")
    out_dir = Path(session.create_tmp()).resolve()
    session.cd("docs")
    sphinx_args = ["-b", "html", "-W", "--keep-going", f"-j{os.cpu_count() or 1}", ".", str(out_dir)]
    session.run("sphinx-build", *sphinx_args)
    session.log(f"OPEN IN WEB BROWSER: file://{out_dir}/index.html")


def is_latest_python(session) -> bool:
    return PYTHONS[-1] in session.run("python", "-V", silent=True)
