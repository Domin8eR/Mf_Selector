from dataclasses import dataclass, field


@dataclass
class ToolResult:
    narrative_summary: str
    table: list[dict]
    columns: list[str]
    citations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "narrative_summary": self.narrative_summary,
            "table": self.table,
            "columns": self.columns,
            "citations": self.citations,
        }
