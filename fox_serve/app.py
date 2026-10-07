"""Single-agent local HTTP/SSE server. No session tree or transport framework."""
import asyncio
import contextlib
import json
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from fox_ai.src import stream
from fox_coding_agent.src import CodingAgent, Config


class RunRequest(BaseModel):
    prompt: str = Field(min_length=1)
    trial_skill: str | None = None
    learn: bool | None = None


class ConfigureRequest(BaseModel):
    cwd: str = "."
    model: str
    base_url: str = "https://api.openai.com/v1"
    api_key: str | None = Field(default=None, repr=False)
    context_budget: int = 12000
    context_window: int = 32768
    max_tokens: int = 4096
    max_turns: int = 30


class MemoryRequest(BaseModel):
    content: str = Field(min_length=1)
    memory_type: str = "semantic"
    verify: bool = True
    key: str = ""
    ttl_days: float | None = Field(default=None, gt=0)


class InvalidateRequest(BaseModel):
    id: int
    reason: str = Field(min_length=1)


class RollbackRequest(BaseModel):
    name: str
    version: int = Field(ge=1)
    reason: str = Field(min_length=1)


class ValidationRequest(BaseModel):
    name: str
    trajectory_id: str
    useful: bool
    saved_calls: int = Field(default=0, ge=0)


def create_app(config=None, *, stream_fn=stream, static_dir=None):
    coding = CodingAgent(config, stream_fn=stream_fn) if config else None
    active = None

    async def stop():
        if active and not active.done():
            active.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await active

    @asynccontextmanager
    async def lifespan(app):
        yield
        await stop()
        if coding:
            coding.close()

    app = FastAPI(title="FoxCode Research", lifespan=lifespan)

    def require_agent():
        if coding is None:
            raise HTTPException(400, "Configure a model and project directory first")
        return coding

    def require_idle():
        if active and not active.done():
            raise HTTPException(409, "A task is running; stop it before changing configuration")

    @app.get("/api/state")
    async def state():
        return {"configured": coding is not None, **(coding.snapshot() if coding else {})}

    @app.post("/api/config")
    async def configure(request: ConfigureRequest):
        nonlocal coding
        require_idle()
        values = request.model_dump()
        try:
            if values["api_key"] is None:
                # Empty form keeps the current/environment/.env key; never sent back.
                if coding:
                    values["api_key"] = coding.config.api_key
                else:
                    env = Config.env_values(request.cwd)
                    values["api_key"] = env.get("FOX_API_KEY", env.get("OPENAI_API_KEY", ""))
            replacement = CodingAgent(Config(**values), stream_fn=stream_fn)
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
        if coding:
            coding.close()
        coding = replacement
        return {"configured": True, **coding.snapshot()}

    @app.post("/api/run")
    async def run(request: RunRequest):
        nonlocal active
        engine = require_agent()
        require_idle()
        if not request.prompt.strip():
            raise HTTPException(400, "Prompt cannot be empty")
        queue = asyncio.Queue()

        async def produce():
            try:
                async for event in engine.run(request.prompt, trial_skill=request.trial_skill, learn=request.learn):
                    await queue.put({"type": event.type, "data": event.data})
            except asyncio.CancelledError:
                await queue.put({"type": "run_end", "data": {"status": "cancelled"}})
            except Exception as exc:
                await queue.put({"type": "error", "data": {"error": str(exc)}})
                await queue.put({"type": "run_end", "data": {"status": "error"}})
            finally:
                await queue.put(None)

        task = active = asyncio.create_task(produce())
        # Enter produce before a concurrent stop can cancel it.
        await asyncio.sleep(0)

        async def events():
            try:
                while True:
                    event = await queue.get()
                    if event is None:
                        break
                    yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
            finally:
                if not task.done():
                    task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/stop")
    async def stop_run():
        await stop()
        return {"stopped": True}

    @app.post("/api/reset")
    async def reset():
        nonlocal coding
        require_idle()
        old = require_agent()
        coding = CodingAgent(old.config, stream_fn=stream_fn)
        old.close()
        return {"configured": True, **coding.snapshot()}

    @app.post("/api/memory")
    async def remember(request: MemoryRequest):
        engine = require_agent()
        try:
            id = engine.memory.add(request.content, memory_type=request.memory_type,
                                   scope=engine.scope, source="user", confidence=1, verify=request.verify,
                                   key=request.key, ttl_days=request.ttl_days)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"id": id}

    @app.post("/api/memory/invalidate")
    async def invalidate(request: InvalidateRequest):
        engine = require_agent()
        require_idle()
        try:
            return asdict(engine.memory.invalidate(request.id, request.reason))
        except KeyError as exc:
            raise HTTPException(404, "Unknown memory") from exc

    @app.get("/api/skills/{name}/history")
    async def skill_history(name: str):
        engine = require_agent()
        if not engine.skills.get(name):
            raise HTTPException(404, "Unknown skill")
        return engine.skills.history(name)

    @app.post("/api/skills/rollback")
    async def rollback(request: RollbackRequest):
        engine = require_agent()
        require_idle()
        try:
            skill = engine.skills.rollback(request.name, request.version, reason=request.reason)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {**asdict(skill), "utility": skill.utility}

    @app.post("/api/skills/validate")
    async def validate(request: ValidationRequest):
        engine = require_agent()
        require_idle()
        try:
            skill = engine.validate_skill(request.name, request.trajectory_id,
                                          request.useful, request.saved_calls)
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {**asdict(skill), "utility": skill.utility}

    directory = Path(static_dir) if static_dir else Path(__file__).resolve().parent.parent / "desktop" / "dist"
    if directory.is_dir():
        app.mount("/", StaticFiles(directory=directory, html=True), name="frontend")
    return app
