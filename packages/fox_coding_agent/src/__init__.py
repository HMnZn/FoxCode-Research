"""FoxCode: lightweight harness + context, project memory, evolving skills."""
from .coding_agent import CodingAgent
from .config import Config
from .context import ContextManager, TaskState
from .memory import MemoryStore
from .skills import SkillStore, SkillEvolution

__all__ = ["CodingAgent", "Config", "ContextManager", "TaskState", "MemoryStore",
           "SkillStore", "SkillEvolution"]
