"""Use /bin/sh on POSIX and the default command shell on Windows."""
import asyncio
import os
import signal
from pathlib import Path
from fox_ai.src import Tool


class Bash:
    schema = Tool("Bash", "Execute a shell command; returns stdout/stderr/returncode. Windows uses cmd.exe.", {
        "type": "object", "properties": {"command": {"type": "string"}, "cwd": {"type": "string"},
        "timeout": {"type": "number", "minimum": 0.1}}, "required": ["command"]})

    def __init__(self, cwd):
        self.cwd = Path(cwd)

    async def execute(self, arguments):
        timeout = float(arguments.get("timeout", 60))
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        process = await asyncio.create_subprocess_shell(arguments["command"],
            cwd=self.cwd / arguments.get("cwd", "."), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, start_new_session=os.name != "nt")
        # Drain both streams while keeping output bounded, even for noisy tests.
        async def drain(stream):
            captured = bytearray()
            while chunk := await stream.read(8192):
                captured.extend(chunk[:max(0, 20000 - len(captured))])
            return captured.decode("utf-8", errors="replace")
        async def collect():
            out, err = await asyncio.gather(drain(process.stdout), drain(process.stderr))
            await process.wait()
            return out, err
        task = asyncio.create_task(collect())
        try:
            out, err = await asyncio.wait_for(asyncio.shield(task), timeout)
        except (TimeoutError, asyncio.CancelledError):
            if os.name == "nt":
                killer = await asyncio.create_subprocess_exec("taskkill", "/PID", str(process.pid), "/T", "/F",
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await killer.wait()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            await task
            raise
        output = f"returncode: {process.returncode}\nstdout:\n{out}\nstderr:\n{err}"
        if process.returncode:
            raise RuntimeError(output)
        return output
