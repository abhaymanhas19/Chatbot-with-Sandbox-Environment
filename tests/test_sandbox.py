import pytest
import subprocess

from executor import sandbox


def test_rejects_empty_and_oversized_code():
    with pytest.raises(ValueError):
        sandbox.run_code("  ")
    with pytest.raises(ValueError):
        sandbox.run_code("x" * (sandbox.MAX_CODE_BYTES + 1))


def test_run_code_uses_restricted_docker_command(monkeypatch):
    seen = {}

    # Test command construction separately from OS pipe behavior.
    def fake_popen(command, **kwargs):
        seen["command"] = command
        raise OSError("test stop")

    monkeypatch.setattr(sandbox.subprocess, "Popen", fake_popen)
    with pytest.raises(RuntimeError):
        sandbox.run_code("print(3)")
    command = seen["command"]
    for flag in ("--network=none", "--read-only", "--cap-drop=ALL",
                 "--pids-limit=32", "--memory=128m", "--cpus=0.5",
                 "--security-opt=seccomp=builtin"):
        assert flag in command
    assert "--privileged" not in command


def test_sandbox_streams_input_and_captures_output(monkeypatch):
    original_popen = subprocess.Popen
    monkeypatch.setattr(sandbox.subprocess, "Popen",
                        lambda command, **kwargs: original_popen(["cat"], **kwargs))
    result = sandbox.run_code("print(3)")
    assert result == {"stdout": "print(3)", "stderr": "", "exit_code": 0,
                      "timed_out": False, "output_truncated": False}
