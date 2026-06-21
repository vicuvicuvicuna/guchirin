import json
import re
from collections.abc import AsyncIterator

from backend.llm import stream_chat
from backend.search import extract_search_queries

_PLAN_PROMPT = (
    "あなたは、ユーザーに回答する前に必要な情報をツールで集めるアシスタントです。\n"
    "次のユーザーの発言を読み、回答の前に実行すべきツール呼び出しの計画を立ててください。\n"
    "ユーザー自身の経歴・収入・年齢など個人的な文脈に依存する質問であれば、"
    "Web検索より先にretrieve_profile/retrieve_memoryで必要な個人情報を取得する計画にしてください。\n\n"
    "利用可能なツール:\n{tool_catalog}\n\n"
    "{search_mode_note}"
    "出力は次の形式のJSON配列のみとし、説明文は書かないでください。\n"
    "[{{\"name\": \"<ツール名>\", \"arguments\": {{<引数オブジェクト>}}}}, ...]\n"
    "ツールが不要なら空配列 [] を出力してください。\n\n"
    "ユーザーの発言: {message}\n"
    "出力:"
)

_SEARCH_MODE_NOTE = (
    "ユーザーは検索モードをONにしているため、計画には必ずweb_searchの呼び出しを1つ以上含めてください。\n\n"
)


def _build_tool_catalog(tool_list: list[dict]) -> str:
    lines = []
    for tool in tool_list:
        fn = tool["function"]
        params = ", ".join(fn.get("parameters", {}).get("properties", {}).keys())
        lines.append(f"- {fn['name']}({params}): {fn['description']}")
    return "\n".join(lines)


def _parse_plan(text: str) -> list[dict]:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    plan = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            plan.append({"name": item["name"], "arguments": item.get("arguments") or {}})
    return plan


async def build_plan(
    message: str, tool_list: list[dict], search_mode: bool, model: str
) -> AsyncIterator[tuple[str, str | list]]:
    """ユーザー発言とツール一覧から実行計画(ツール名+引数のリスト)を生成する。
    (種別, データ)を順次yieldする。種別は'thinking'(データ:str)、最後に必ず'plan'(データ:list)"""
    valid_names = {t["function"]["name"] for t in tool_list}
    prompt = _PLAN_PROMPT.format(
        tool_catalog=_build_tool_catalog(tool_list),
        search_mode_note=_SEARCH_MODE_NOTE if search_mode else "",
        message=message,
    )

    raw = ""
    async for kind, text in stream_chat([{"role": "user", "content": prompt}], model=model):
        if kind == "thinking":
            yield ("thinking", text)
        else:
            raw += text

    plan = [step for step in _parse_plan(raw) if step["name"] in valid_names]

    if search_mode and not any(step["name"] == "web_search" for step in plan):
        queries = await extract_search_queries(message)
        plan.extend({"name": "web_search", "arguments": {"query": q}} for q in queries)

    yield ("plan", plan)
