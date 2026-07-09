from fastapi import APIRouter
from pydantic import BaseModel
from .agent import run_research_chat

router = APIRouter(prefix="/api/research-chat", tags=["research-chat"])


class ResearchChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class TablePayload(BaseModel):
    columns: list[str]
    rows: list[dict]


class ResearchChatResponse(BaseModel):
    reply: str
    table: TablePayload | None = None
    tool_trace: list[dict] = []


@router.post("", response_model=ResearchChatResponse)
async def research_chat(
    req: ResearchChatRequest,
) -> ResearchChatResponse:
    result = await run_research_chat(req.message)
    table = None
    if result.get("table"):
        table = TablePayload(
            columns=result["table"]["columns"],
            rows=result["table"]["rows"],
        )
    return ResearchChatResponse(
        reply=result["reply"],
        table=table,
        tool_trace=result.get("tool_trace", []),
    )
