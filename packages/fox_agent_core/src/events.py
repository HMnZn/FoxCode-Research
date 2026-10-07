from dataclasses import dataclass, field


@dataclass
class AgentEvent:
    type: str
    data: dict = field(default_factory=dict)
