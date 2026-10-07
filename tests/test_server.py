import asyncio
import json
import socket
from contextlib import asynccontextmanager
import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from openai import AsyncOpenAI
from fox_ai.src import AssistantMessage, Done, TextDelta
from fox_ai.src.openai_provider import stream
from fox_coding_agent.src import Config
from fox_serve.app import create_app


async def answer(*args):
    yield TextDelta("hello")
    yield Done(AssistantMessage("hello"))


def frames(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_configuration_state_reset_and_memory(tmp_path):
    app = create_app(stream_fn=answer, static_dir=tmp_path / "absent")
    with TestClient(app) as client:
        assert not client.get("/api/state").json()["configured"]
        assert client.post("/api/run", json={"prompt": "hi"}).status_code == 400
        result = client.post("/api/config", json={"cwd": str(tmp_path), "model": "qwen", "api_key": "private-key"})
        assert result.status_code == 200 and "private-key" not in result.text
        assert "api_key" not in result.json()
        assert client.post("/api/config", json={"cwd": "/not-a-project", "model": "qwen"}).status_code == 400
        assert client.get("/api/state").json()["model"] == "qwen"
        assert client.post("/api/memory", json={"content": "pytest is the project test command"}).status_code == 200
        events = frames(client.post("/api/run", json={"prompt": "pytest project"}))
        assert events[-1]["data"]["status"] == "completed"
        state = client.get("/api/state").json()
        assert len(state["memory"]["retrieved"]) == 1
        assert client.post("/api/reset").json()["memory"]["counts"] == {"semantic": 1}
        assert client.post("/api/skills/validate", json={"name": "missing", "trajectory_id": "missing", "useful": True}).status_code == 400


def test_configuration_uses_project_dotenv_key(monkeypatch, tmp_path):
    monkeypatch.delenv("FOX_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (tmp_path / ".env").write_text("FOX_API_KEY=project-secret\n", encoding="utf-8")
    keys = []

    async def capture(model, context, options):
        keys.append(options.api_key)
        async for event in answer():
            yield event

    app = create_app(stream_fn=capture, static_dir=tmp_path / "absent")
    with TestClient(app) as client:
        response = client.post("/api/config", json={"cwd": str(tmp_path), "model": "fake"})
        assert response.status_code == 200
        assert "project-secret" not in response.text
        events = frames(client.post("/api/run", json={"prompt": "hello"}))
        assert events[-1]["data"]["status"] == "completed"
        assert keys == ["project-secret"]
        assert "project-secret" not in client.get("/api/state").text


@asynccontextmanager
async def live_server(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        sock.close()


async def test_live_sse_stop_and_busy_guard(tmp_path):
    started = asyncio.Event()
    async def slow(*args):
        yield TextDelta("first chunk")
        started.set()
        await asyncio.sleep(60)
        yield Done(AssistantMessage("done"))
    app = create_app(Config(cwd=tmp_path, model="fake"), stream_fn=slow)
    async with live_server(app) as url, httpx.AsyncClient(base_url=url, timeout=3) as client:
        async with client.stream("POST", "/api/run", json={"prompt": "wait"}) as response:
            lines = response.aiter_lines()
            received = []
            while not any(event["type"] == "text_delta" for event in received):
                line = await anext(lines)
                if line.startswith("data: "):
                    received.append(json.loads(line[6:]))
            # The model is still blocked when the browser receives its first delta.
            assert started.is_set()
            assert (await client.post("/api/run", json={"prompt": "another"})).status_code == 409
            assert (await client.post("/api/reset")).status_code == 409
            assert (await client.post("/api/stop")).status_code == 200
            async for line in lines:
                if line.startswith("data: "):
                    received.append(json.loads(line[6:]))
            assert received[-1]["type"] == "run_end"
            assert received[-1]["data"]["status"] == "cancelled"
        assert not (await client.get("/api/state")).json()["running"]
    trajectory = json.loads((tmp_path / ".foxcode/research/trajectories.jsonl").read_text())
    assert trajectory["status"] == "cancelled"


async def test_http_to_sdk_to_tool_to_sse(tmp_path):
    endpoint = FastAPI()
    requests = []
    @endpoint.post("/v1/chat/completions")
    async def model(request: Request):
        body = await request.json()
        requests.append(body)
        if body["messages"][-1]["role"] == "tool":
            assert body["messages"][-1]["content"] == "Wrote answer.py"
            delta = {"content": "File created"}
            finish = "stop"
        else:
            delta = {"tool_calls": [{"index": 0, "id": "write1", "type": "function",
                "function": {"name": "Write", "arguments": json.dumps({"file_path": "answer.py", "content": "print(42)"})}}]}
            finish = "tool_calls"
        async def chunks():
            for value in [{"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                          {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
                          {"choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 4, "total_tokens": 24}}]:
                value.update(id="chat1", object="chat.completion.chunk", created=1, model="test")
                yield f"data: {json.dumps(value)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(chunks(), media_type="text/event-stream")
    async def adapter(model, context, options):
        async with AsyncOpenAI(api_key="test", base_url="http://model/v1", max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.ASGITransport(app=endpoint))) as sdk:
            async for event in stream(model, context, options, client=sdk):
                yield event
    app = create_app(Config(cwd=tmp_path, model="test"), stream_fn=adapter)
    async with live_server(app) as url, httpx.AsyncClient(base_url=url) as client:
        response = await client.post("/api/run", json={"prompt": "Create answer.py"})
        events = frames(response)
        assert [e["type"] for e in events].count("tool_end") == 1
        assert events[-1]["data"]["status"] == "completed"
        assert (tmp_path / "answer.py").read_text() == "print(42)"
        assert len(requests) == 2 and len(requests[0]["tools"]) == 5
        assert (await client.get("/api/state")).json()["memory"]["counts"] == {"episodic": 1}


def test_memory_revisions_and_skill_history_rollback_api(tmp_path):
    from fox_coding_agent.src.skills import Skill, SkillStore

    config = Config(cwd=tmp_path, model='fake')
    config.data_dir.mkdir(parents=True)
    store = SkillStore(config.data_dir / 'skills.sqlite')
    skill = Skill('edit', 'Edit recovery', 'Edit failure', 'Read before Edit', source_trajectory=['origin'])
    store.propose(skill)
    for source in ['t1', 't2']:
        store.record('edit', success=True, evidence_id=source)
    skill.instructions = 'Read before Edit and re-read after Edit'
    skill.source_trajectory = ['revision-source']
    store.propose(skill)
    for source in ['t3', 't4']:
        store.record('edit', success=True, evidence_id=source)
    store.close()
    with TestClient(create_app(config, stream_fn=answer, static_dir=tmp_path / 'absent')) as client:
        first = client.post('/api/memory', json={'content': 'Run pytest', 'key': 'check'}).json()['id']
        second = client.post('/api/memory', json={'content': 'Run unittest', 'key': 'check'}).json()['id']
        assert first != second
        assert client.get('/api/state').json()['memory']['statuses']['superseded'] == 1
        assert client.post('/api/memory/invalidate', json={'id': second, 'reason': 'obsolete'}).json()['status'] == 'invalidated'
        assert client.post('/api/memory/invalidate', json={'id': 9999, 'reason': 'missing'}).status_code == 404
        history = client.get('/api/skills/edit/history').json()
        assert len(history['versions']) == 2
        assert client.post('/api/skills/rollback', json={'name': 'edit', 'version': 1, 'reason': 'external report'}).json()['champion_version'] == 1
        assert client.get('/api/skills/edit/history').json()['events'][-1]['action'] == 'rollback'
        assert client.get('/api/skills/missing/history').status_code == 404
