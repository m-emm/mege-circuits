import os
import subprocess
import sys
import textwrap
from pathlib import Path


def test_simple_logging_setup_uses_stdout_and_debug_level():
    result = _run_simple_logging_probe(
        {
            "MEGE_CIRCUITS_LOG_LEVEL": "DEBUG",
        }
    )

    assert "handlers=1" in result.stdout
    assert "root_level=10" in result.stdout
    assert "mege_level=10" in result.stdout
    assert "stdout=True" in result.stdout
    assert "debug-visible" in result.stdout


def test_simple_logging_setup_skips_under_pytest():
    result = _run_simple_logging_probe(
        {
            "MEGE_CIRCUITS_LOG_LEVEL": "DEBUG",
            "PYTEST_VERSION": "probe",
        }
    )

    assert "handlers=0" in result.stdout
    assert "debug-visible" not in result.stdout


def test_simple_logging_setup_can_be_disabled():
    result = _run_simple_logging_probe(
        {
            "MEGE_CIRCUITS_LOG_LEVEL": "DEBUG",
            "MEGE_CIRCUITS_NO_LOGGING_INIT": "1",
        }
    )

    assert "handlers=0" in result.stdout
    assert "debug-visible" not in result.stdout


def _run_simple_logging_probe(env_overrides):
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.pop("PYTEST_VERSION", None)
    env.pop("MEGE_CIRCUITS_NO_LOGGING_INIT", None)
    env.pop("MEGE_CIRCUITS_LOG_LEVEL", None)
    pythonpath = str(repo_root / "src")
    if env.get("PYTHONPATH"):
        pythonpath = f"{pythonpath}{os.pathsep}{env['PYTHONPATH']}"
    env["PYTHONPATH"] = pythonpath
    env.update(env_overrides)
    code = textwrap.dedent(
        """
        import logging
        import sys

        import mege_circuits.simple

        root = logging.getLogger()
        print(f"handlers={len(root.handlers)}")
        print(f"root_level={root.level}")
        print(f"mege_level={logging.getLogger('mege_circuits').level}")
        print(
            "stdout="
            f"{bool(root.handlers and root.handlers[0].stream is sys.stdout)}"
        )
        logging.getLogger("mege_circuits.logging_probe").debug("debug-visible")
        """
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
