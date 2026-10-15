import asyncio
import json
import shutil
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    def to_response(self) -> dict[str, Any]:
        parsed: Any = None
        if self.stdout.strip():
            try:
                parsed = json.loads(self.stdout)
            except json.JSONDecodeError:
                parsed = None

        return {
            "ok": self.returncode == 0,
            "command": self.command,
            "returncode": self.returncode,
            "data": parsed,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


class OkxCliAdapter:
    def __init__(self, binary: str = "okx", timeout_seconds: float = 20.0):
        self.binary = binary
        self.timeout_seconds = timeout_seconds

    async def inspect(self) -> dict[str, Any]:
        path = shutil.which(self.binary)
        if not path:
            return {
                "installed": False,
                "binary": self.binary,
                "path": None,
                "hint": "Install with: npm install -g @okx_ai/okx-trade-cli",
            }

        version = await self._run_raw(["--version"])
        return {
            "installed": True,
            "binary": self.binary,
            "path": path,
            "version": version.to_response(),
        }

    async def run(self, args: list[str]) -> dict[str, Any]:
        result = await self._run_raw(args)
        return result.to_response()

    async def _run_raw(self, args: list[str]) -> CommandResult:
        command = [self.binary, *args]
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError:
            return CommandResult(command, 127, "", f"Command not found: {self.binary}")
        except asyncio.TimeoutError:
            return CommandResult(command, 124, "", f"Command timed out after {self.timeout_seconds}s")

        return CommandResult(
            command=command,
            returncode=proc.returncode or 0,
            stdout=stdout_bytes.decode("utf-8", errors="replace").strip(),
            stderr=stderr_bytes.decode("utf-8", errors="replace").strip(),
        )

