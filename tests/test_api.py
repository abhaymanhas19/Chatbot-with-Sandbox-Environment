from fastapi.testclient import TestClient
from types import SimpleNamespace
import httpx

from chatbot import app as chatbot_app
from executor import app as executor_app


def test_executor_requires_secret(monkeypatch):
    monkeypatch.setenv("EXECUTOR_TOKEN", "test-secret")
    client = TestClient(executor_app.app)
    assert client.post("/execute", json={"code": "print(1)"}).status_code == 401
    assert client.post("/execute", headers={"Authorization": "Bearer wrong"},
                       json={"code": "print(1)"}).status_code == 401


def test_executor_dispatches_to_sandbox(monkeypatch):
    monkeypatch.setenv("EXECUTOR_TOKEN", "test-secret")
    received = []
    monkeypatch.setattr(executor_app, "run_code", lambda code: received.append(code) or
                        {"stdout": "2\n", "stderr": "", "exit_code": 0,
                         "timed_out": False, "output_truncated": False})
    response = TestClient(executor_app.app).post(
        "/execute", headers={"Authorization": "Bearer test-secret"},
        json={"code": "print(1+1)"})
    assert response.status_code == 200
    assert received == ["print(1+1)"]
    assert response.json()["stdout"] == "2\n"


def test_demo_calls_executor(monkeypatch):
    received = []
    monkeypatch.setattr(chatbot_app, "call_executor", lambda code: received.append(code) or
                        {"stdout": "4\n", "stderr": "", "exit_code": 0,
                         "timed_out": False, "output_truncated": False})
    response = TestClient(chatbot_app.app).post(
        "/chat", json={"message": "What is 2 + 2?", "mode": "demo",
                       "code": "print(2+2)"})
    assert response.status_code == 200
    assert response.json()["answer"] == "4\n"
    assert received == ["print(2+2)"]


def test_demo_requires_explicit_code():
    response = TestClient(chatbot_app.app).post(
        "/chat", json={"message": "Hi", "mode": "demo"})
    assert response.status_code == 422


def test_chatbot_sends_authenticated_http_request(monkeypatch):
    monkeypatch.setenv("EXECUTOR_TOKEN", "test-secret")
    monkeypatch.setenv("EXECUTOR_URL", "http://executor.local")

    def handler(request):
        assert request.url.path == "/execute"
        assert request.headers["Authorization"] == "Bearer test-secret"
        assert request.content == b'{"code":"print(5)"}'
        return httpx.Response(200, json={"stdout": "5\n", "stderr": "",
                                         "exit_code": 0, "timed_out": False,
                                         "output_truncated": False})

    real_client = httpx.Client
    monkeypatch.setattr(chatbot_app.httpx, "Client",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handler),
                                                     **kwargs))
    assert chatbot_app.call_executor("print(5)")["stdout"] == "5\n"


def test_executor_readiness_requires_runner_image(monkeypatch):
    monkeypatch.setattr(executor_app.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=1))
    assert TestClient(executor_app.app).get("/ready").status_code == 503
    monkeypatch.setattr(executor_app.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=0))
    assert TestClient(executor_app.app).get("/ready").json()["status"] == "ready"


def test_openai_tool_result_goes_back_to_model(monkeypatch):
    import openai

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls = []
    tool_call = SimpleNamespace(type="function_call", name="run_python",
                                arguments='{"code":"print(6 * 7)"}', call_id="call_1")
    first = SimpleNamespace(output=[tool_call], id="response_1", output_text="")
    second = SimpleNamespace(output=[], id="response_2", output_text="The answer is 42.")

    class FakeResponses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return first if len(calls) == 1 else second

    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs:
                        SimpleNamespace(responses=FakeResponses()))
    monkeypatch.setattr(chatbot_app, "call_executor", lambda code:
                        {"stdout": "42\n", "stderr": "", "exit_code": 0,
                         "timed_out": False, "output_truncated": False})
    response = TestClient(chatbot_app.app).post(
        "/chat", json={"message": "Calculate 6 * 7", "mode": "openai"})
    assert response.status_code == 200
    assert response.json()["answer"] == "The answer is 42."
    assert calls[1]["previous_response_id"] == "response_1"
    assert calls[1]["input"][0]["call_id"] == "call_1"
    assert "42\\n" in calls[1]["input"][0]["output"]
