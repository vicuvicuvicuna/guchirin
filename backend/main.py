import asyncio
import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import history, tools as agent_tools
from backend.config import BASE_DIR
from backend.llm import chat_with_tools, stream_chat
from backend.memory import extractor, store
from backend.search import extract_search_queries, format_search_results, web_search

app = FastAPI(title="Local LLM Chat")

history.init_db()

MAX_TOOL_ITERATIONS = 3

TOOL_STATUS_LABELS = {
    "web_search": "Web検索中",
    "retrieve_memory": "記憶を検索中",
}


def _status_chunk(text: str) -> str:
    return json.dumps({"type": "status", "text": text}, ensure_ascii=False) + "\n"


def _content_chunk(text: str) -> str:
    return json.dumps({"type": "content", "text": text}, ensure_ascii=False) + "\n"


class ChatRequest(BaseModel):
    session_id: str
    message: str
    search_mode: bool = False


class SessionCreate(BaseModel):
    title: str = "新しいチャット"


@app.post("/chat")
async def chat(req: ChatRequest):
    history.maybe_set_title(req.session_id, req.message)
    history.add_message(req.session_id, "user", req.message)

    past_messages = history.get_session_messages(req.session_id)
    messages = [{"role": m["role"], "content": m["content"]} for m in past_messages]

    async def event_stream():
        full_response = ""
        try:
            if req.search_mode:
                # 検索モードON時はLLMの判断を介さず、必ずWeb検索を実行する
                # ただし会話文をそのまま検索するのではなく、検索すべき内容を先に抽出する
                queries = await extract_search_queries(req.message)
                yield _status_chunk("「" + "」「".join(queries) + "」を検索中")
                results = []
                for q in queries:
                    results.extend(web_search(q))
                formatted = format_search_results(results)
                if formatted:
                    messages.append({"role": "tool", "name": "web_search", "content": formatted})
            else:
                # それ以外はLLM自身がツールを呼ぶか判断する（function calling）
                tool_list = agent_tools.available_tools()
                for _ in range(MAX_TOOL_ITERATIONS):
                    reply = await chat_with_tools(messages, tool_list)
                    tool_calls = reply.get("tool_calls") or []
                    if not tool_calls:
                        break
                    messages.append(
                        {"role": "assistant", "content": reply.get("content", ""), "tool_calls": tool_calls}
                    )
                    for call in tool_calls:
                        fn = call.get("function", {})
                        name = fn.get("name", "")
                        yield _status_chunk(TOOL_STATUS_LABELS.get(name, f"{name} 実行中"))
                        result = agent_tools.execute_tool(name, fn.get("arguments", {}) or {})
                        messages.append({"role": "tool", "name": name, "content": result})

            async for chunk in stream_chat(messages):
                full_response += chunk
                yield _content_chunk(chunk)
        finally:
            # 途中で停止(クライアント切断)されても、それまでの応答は保存する
            if full_response:
                history.add_message(req.session_id, "assistant", full_response)
                asyncio.create_task(extractor.extract_and_store(req.message, full_response))

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@app.get("/sessions")
def get_sessions():
    return history.list_sessions()


@app.post("/sessions")
def post_session(req: SessionCreate):
    return history.create_session(req.title)


@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    return history.get_session_messages(session_id)


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    history.delete_session(session_id)
    return {"ok": True}


@app.get("/memory")
def get_memory():
    return store.list_all()


@app.get("/memory/status")
def get_memory_status():
    return store.status()


@app.delete("/memory/{memory_id}")
def delete_memory(memory_id: str):
    store.delete(memory_id)
    return {"ok": True}


class MemoryCreate(BaseModel):
    text: str


@app.post("/memory")
def post_memory(req: MemoryCreate):
    created = store.add(req.text, source="manual")
    if created is None:
        raise HTTPException(status_code=409, detail="Memory capacity is full")
    return created


app.mount("/", StaticFiles(directory=str(BASE_DIR / "frontend"), html=True), name="frontend")
