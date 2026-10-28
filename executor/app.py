import os
import secrets
import subprocess
import threading

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from executor.sandbox import run_code

app = FastAPI(title="Isolated Python Executor")
SLOTS = threading.BoundedSemaphore(2)


class ExecuteRequest(BaseModel):
    code: str = Field(min_length=1, max_length=8192)


def authorize(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("EXECUTOR_TOKEN", "")
    if not expected or not authorization or not secrets.compare_digest(
        authorization, f"Bearer {expected}"
    ):
        raise HTTPException(status_code=401, detail="unauthorized")


@app.post("/execute", dependencies=[Depends(authorize)])
def execute(request: ExecuteRequest):
    if not SLOTS.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="executor is busy")
    try:
        return run_code(request.code)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        SLOTS.release()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    image = os.getenv("RUNNER_IMAGE", "python-chatbot-runner:local")
    try:
        result = subprocess.run(["docker", "image", "inspect", image],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=503, detail="Docker is unavailable") from exc
    if result.returncode != 0:
        raise HTTPException(status_code=503, detail="runner image is unavailable")
    return {"status": "ready", "image": image}
