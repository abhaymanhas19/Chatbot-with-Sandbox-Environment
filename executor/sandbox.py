"""Docker is invoked only by the executor service, never by the chatbot."""
import os
import selectors
import subprocess
import time
import uuid

IMAGE = os.getenv("RUNNER_IMAGE", "python-chatbot-runner:local")
MAX_CODE_BYTES = 8192
MAX_OUTPUT_BYTES = 16_384
WALL_SECONDS = 5


def _cleanup(name: str) -> None:
    # A killed Docker client can leave a container behind.
    try:
        subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass


def run_code(code: str) -> dict:
    if not code.strip():
        raise ValueError("code must not be empty")
    payload = code.encode("utf-8")
    if len(payload) > MAX_CODE_BYTES:
        raise ValueError(f"code exceeds {MAX_CODE_BYTES} bytes")
    name = f"chatbot-run-{uuid.uuid4().hex}"
    command = [
        "docker", "run", "--rm", "--name", name, "--pull=never", "--interactive",
        "--network=none", "--read-only", "--user=65534:65534", "--workdir=/tmp",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
        "--memory=128m", "--memory-swap=128m", "--cpus=0.5", "--pids-limit=32",
        "--ulimit=nofile=64:64", "--ulimit=core=0:0", "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true", "--security-opt=seccomp=builtin",
        "--env=HOME=/tmp", "--env=PYTHONDONTWRITEBYTECODE=1",
        IMAGE, "python", "-I", "-B", "-",
    ]
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   bufsize=0)
    except OSError as exc:
        raise RuntimeError("Docker CLI is unavailable") from exc

    output = {"stdout": bytearray(), "stderr": bytearray()}
    timed_out = False
    truncated = False
    selector = selectors.DefaultSelector()
    try:
        # Input is bounded to 8 KiB, below typical pipe capacity.
        try:
            process.stdin.write(payload)
        except BrokenPipeError:
            pass
        finally:
            process.stdin.close()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        deadline = time.monotonic() + WALL_SECONDS
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            for key, _ in selector.select(timeout=remaining):
                chunk = os.read(key.fileobj.fileno(), 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                room = MAX_OUTPUT_BYTES - sum(map(len, output.values()))
                output[key.data].extend(chunk[:room])
                if len(chunk) > room or room == 0:
                    truncated = True
                    break
            if truncated:
                break
        if timed_out or truncated:
            _cleanup(name)
            process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            timed_out = True
            _cleanup(name)
            process.kill()
            process.wait(timeout=5)
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
        if process.poll() is None:
            _cleanup(name)
            process.kill()
            process.wait()
    return {
        "stdout": output["stdout"].decode("utf-8", errors="replace"),
        "stderr": output["stderr"].decode("utf-8", errors="replace"),
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "output_truncated": truncated,
    }
