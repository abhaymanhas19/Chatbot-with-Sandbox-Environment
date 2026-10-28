# Python chatbot with a separate execution service

The chatbot receives a question and asks the executor API to run Python. The executor starts a **new Docker container for each run** and returns only stdout, stderr, exit status, timeout, and truncation status. The chatbot process never calls `exec`, `eval`, `subprocess`, or Docker on user code.

Here `subprocess` starts the Docker CLI in the executor service. The Python interpreter **inside the container** reads code from standard input. Python's `exec()` in the chatbot would run code inside the chatbot process and has no isolation, so this project does not use it.

```text
client -> chatbot API (:8000) -> authenticated HTTP -> executor API (:8001)
                                                  -> Docker -> fresh Python container
```

## How this compares with ChatGPT and Pyodide

This example follows the **hosted sandbox** pattern: the browser or API client sends a request, and a separate server runs Python under limits. ChatGPT can run Python in a stateful notebook for some data-analysis tasks; this example deliberately starts a fresh, **stateless** container for every call. Variables and files from one call are not available in the next.

Pyodide is a different deployment choice: Python runs as WebAssembly **inside the user's browser**. A Web Worker keeps long computations off the page's main thread, but a worker alone is not a security boundary for your backend. Browser code can access browser capabilities permitted to its page, and its results are controlled by the client. Therefore a chatbot backend must not trust a Pyodide result for authorization, billing, or other server decisions. Pyodide is useful for local, interactive calculations; the Docker executor is useful when the chatbot needs an authoritative server-side tool result.

## Requirements and setup

Install Python 3.11+ and Docker Engine or Docker Desktop. Start Docker first. From this directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
docker build -t python-chatbot-runner:local runner
python scripts/init_env.py
```

The setup script creates `.env` with a random `EXECUTOR_TOKEN` and does not overwrite it later. For model mode, add your API key to `OPENAI_API_KEY` and choose an accessible `OPENAI_MODEL`. Demo mode needs no model key.

Open **two terminals** in this directory, activate the virtual environment, then load `.env` in both. Terminal 1:

```bash
source .venv/bin/activate
set -a; source .env; set +a
uvicorn executor.app:app --host 127.0.0.1 --port 8001
```

Terminal 2:

```bash
source .venv/bin/activate
set -a; source .env; set +a
uvicorn chatbot.app:app --host 127.0.0.1 --port 8000
```

The APIs have interactive docs at `http://127.0.0.1:8000/docs` and `http://127.0.0.1:8001/docs`. Keep the executor bound to loopback for this local example.

## Try it

Demo mode sends the explicit `code` field to the executor, making the flow testable without an API key:

```bash
curl -sS http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Calculate 2 + 2","mode":"demo","code":"print(2 + 2)"}'
```

Expected `answer`: `"4\n"`. Test an exception:

```bash
curl -sS http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Show an error","mode":"demo","code":"raise ValueError(\"example\")"}'
```

With `OPENAI_API_KEY` set, model mode lets the model choose the `run_python` tool. The chatbot sends the tool result back to the model to form the answer:

```bash
curl -sS http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Use Python to calculate the sum of squares from 1 through 10.","mode":"openai"}'
```

Run the local tests with `python -m pytest -q`. Once Docker and both APIs are running, check Docker readiness and run the live smoke test:

```bash
curl -fsS http://127.0.0.1:8001/ready
python scripts/smoke_test.py
```

The smoke test checks a successful calculation, read-only root filesystem, blocked network, and timeout. It takes at least five seconds because it intentionally runs an infinite loop in a sandbox.
If `/ready` returns 503, start Docker and rebuild the image with the tag shown in `RUNNER_IMAGE`.

## Limits and security boundary

The runner has no network, no host bind mounts, a read-only root filesystem, and a 16 MiB writable `/tmp` mount. It runs as UID 65534, drops Linux capabilities, prevents privilege gain, uses Docker's built-in seccomp profile, and has 128 MiB memory, 0.5 CPU, 32 process, 5 second wall-time, 8 KiB input, and 16 KiB combined output limits. The executor permits two concurrent runs per API process. A forced cleanup removes containers after timeout or excessive output. Python's `-I` reduces environmental influence; it is **not** the isolation boundary.

The executor requires a bearer token and should be reachable only by the chatbot. **The executor itself has Docker daemon access, which is highly privileged.** Run it on a dedicated host or VM with no unrelated workloads or secrets. Do not expose the executor or Docker socket publicly. This example is a local teaching project, not a hardened multi-tenant service. For hostile public traffic, add authentication at the chatbot, rate limits, concurrency limits, audit logs, stricter container isolation (for example a VM or sandbox runtime), and host-level monitoring. No API keys are passed into the runner.

The model can write arbitrary Python inside its isolated container. Treat stdout and stderr as untrusted text. The chatbot's tool instructions tell the model to treat them as data, and you should not turn model output into privileged commands.
