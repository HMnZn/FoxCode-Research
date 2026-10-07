"""One explicit config; environment variables are the CLI/server defaults."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from fox_ai.src import Model, StreamOptions


@dataclass
class Config:
    cwd: Path = field(default_factory=Path.cwd)
    model: str = ""
    base_url: str = "https://api.openai.com/v1"
    api_key: str = field(default="", repr=False)
    context_budget: int = 12000
    max_turns: int = 30
    data_dir: Path | None = None
    context_window: int = 32768
    max_tokens: int = 4096

    def __post_init__(self):
        self.cwd = Path(self.cwd).expanduser().resolve()
        if not self.cwd.is_dir():
            raise ValueError(f"Working directory does not exist: {self.cwd}")
        if not self.model.strip():
            raise ValueError("Set FOX_MODEL or pass --model")
        if self.context_budget < 512 or self.max_tokens <= 0 or self.max_turns <= 0:
            raise ValueError("context_budget >= 512, max_tokens > 0 and max_turns > 0 are required")
        if self.context_budget + self.max_tokens > self.context_window:
            raise ValueError("context_budget + max_tokens exceeds context_window")
        self.data_dir = Path(self.data_dir or self.cwd / ".foxcode" / "research").expanduser().resolve()

    @classmethod
    def from_env(cls, **overrides):
        values = dict(model=os.getenv("FOX_MODEL", ""),
                      base_url=os.getenv("FOX_BASE_URL", "https://api.openai.com/v1"),
                      api_key=os.getenv("FOX_API_KEY", os.getenv("OPENAI_API_KEY", "")),
                      context_budget=int(os.getenv("FOX_CONTEXT_BUDGET", "12000")))
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)

    def model_config(self):
        return Model(self.model, self.base_url, self.context_window)

    def stream_options(self):
        return StreamOptions(api_key=self.api_key, max_tokens=self.max_tokens)
