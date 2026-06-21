import json
import re

from backend.config import MAIN_MODEL, MEMORY_MERGE_SIMILARITY_THRESHOLD
from backend.llm import chat_once
from backend.memory import store

# 軽量モデル(LIGHT_MODEL)は雑談からも事実っぽい文を誤抽出しやすいため、
# 記憶の質を優先してMAIN_MODELを使う（非同期タスクなので速度は重視しない）
_EXTRACT_PROMPT = (
    "次の会話から、ユーザー本人について今後も変わらず使える事実だけを抽出してください。\n"
    "対象: 氏名・年齢・職業・居住地・家族構成・恒常的な好み/嫌い・確定した設定や予定など。\n"
    "対象外: 一時的な感情や状態（疲れた、寒い等）、相手への質問、推測や不確かな情報、"
    "あいさつ・相づちのみの発言、抽象的すぎる感想。\n"
    "確信が持てない場合や、当てはまる事実が無い場合は出力しないでください。\n"
    "各事実は短い日本語の一文とし、会話文の引用や要約ではなく事実そのものを書いてください。\n"
    "出力はJSON配列のみ。説明文は一切書かないでください。\n\n"
    "例:\n"
    "会話:\n"
    "ユーザー: 私の名前は田中です。猫が好きです。\n"
    "アシスタント: 田中さん、こんにちは！\n"
    "出力: [\"ユーザーの名前は田中\", \"ユーザーは猫が好き\"]\n\n"
    "会話:\n"
    "ユーザー: 今日は寒いね。\n"
    "アシスタント: そうですね、暖かくしてくださいね。\n"
    "出力: []\n\n"
    "会話:\n"
    "ユーザー: ねえ、おすすめの本ある？\n"
    "アシスタント: ジャンルを教えてください。\n"
    "出力: []\n\n"
    "会話:\n"
    "ユーザー: {user_message}\n"
    "アシスタント: {assistant_message}\n"
    "出力:"
)

_MIN_FACT_LENGTH = 4
_MAX_FACT_LENGTH = 100


def _parse_json_array(text: str) -> list[str]:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return [str(item).strip() for item in data if str(item).strip()]


def _is_plausible_fact(fact: str) -> bool:
    """抽出ノイズ(短すぎ/長すぎ/疑問文/会話の引用っぽい文)を除外する"""
    if not (_MIN_FACT_LENGTH <= len(fact) <= _MAX_FACT_LENGTH):
        return False
    if fact.endswith(("?", "？")):
        return False
    if fact.startswith(("ユーザー:", "アシスタント:", "ユーザー：", "アシスタント：")):
        return False
    return True


async def extract_and_store(user_message: str, assistant_message: str) -> None:
    """直近のやりとりから記憶すべき事実を抽出し、既存メモリとマージ/追加する"""
    try:
        raw = await chat_once(
            [
                {
                    "role": "user",
                    "content": _EXTRACT_PROMPT.format(
                        user_message=user_message, assistant_message=assistant_message
                    ),
                }
            ],
            model=MAIN_MODEL,
        )
    except Exception:
        return

    facts = [f for f in _parse_json_array(raw) if _is_plausible_fact(f)]
    for fact in facts:
        similar = store.find_similar(fact, top_k=1)
        if similar and (1 - similar[0]["distance"]) >= MEMORY_MERGE_SIMILARITY_THRESHOLD:
            store.update_text(similar[0]["id"], fact)
        else:
            store.add(fact, source="auto")
