import io
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import docx
from pypdf import PdfReader

from backend.config import CHAT_DB_PATH, MAIN_MODEL
from backend.llm import chat_once


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect():
    conn = sqlite3.connect(CHAT_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_column(conn, table: str, column: str, col_type: str = "TEXT") -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS career_history (
                id TEXT PRIMARY KEY,
                company TEXT NOT NULL,
                position TEXT,
                start_date TEXT,
                end_date TEXT,
                salary TEXT,
                reason_for_joining TEXT,
                reason_for_leaving TEXT,
                note TEXT,
                created_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS education_history (
                id TEXT PRIMARY KEY,
                degree TEXT,
                field TEXT,
                school TEXT,
                graduated_year TEXT,
                note TEXT,
                created_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS profile_basic (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        _ensure_column(conn, "career_history", "note")
        _ensure_column(conn, "education_history", "note")
        _ensure_column(conn, "career_history", "sort_order", "INTEGER")
        _backfill_career_sort_order(conn)


def _backfill_career_sort_order(conn) -> None:
    rows = conn.execute(
        "SELECT id FROM career_history WHERE sort_order IS NULL ORDER BY created_at ASC"
    ).fetchall()
    if not rows:
        return
    next_order = (conn.execute("SELECT MAX(sort_order) AS m FROM career_history").fetchone()["m"] or 0) + 1
    for row in rows:
        conn.execute("UPDATE career_history SET sort_order = ? WHERE id = ?", (next_order, row["id"]))
        next_order += 1


def _next_career_sort_order(conn) -> int:
    return (conn.execute("SELECT MAX(sort_order) AS m FROM career_history").fetchone()["m"] or 0) + 1


BASIC_INFO_KEYS = ["name", "birth_date", "current_company", "current_position", "current_salary"]


def get_basic_info() -> dict:
    with _connect() as conn:
        rows = conn.execute("SELECT key, value FROM profile_basic").fetchall()
        return {r["key"]: r["value"] for r in rows}


def set_basic_info(data: dict) -> dict:
    now = _now()
    with _connect() as conn:
        for key, value in data.items():
            if key not in BASIC_INFO_KEYS or not str(value).strip():
                continue
            conn.execute(
                """INSERT INTO profile_basic (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
                (key, value, now),
            )
    return get_basic_info()


def list_career() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM career_history ORDER BY sort_order DESC, created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def move_career(entry_id: str, direction: str) -> None:
    """現在の表示順の中でentry_idを一つ上/下に動かす(direction: 'up' または 'down')"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, sort_order FROM career_history ORDER BY sort_order DESC, created_at DESC"
        ).fetchall()
        ids = [r["id"] for r in rows]
        orders = [r["sort_order"] for r in rows]
        if entry_id not in ids:
            return
        idx = ids.index(entry_id)
        swap_idx = idx - 1 if direction == "up" else idx + 1
        if swap_idx < 0 or swap_idx >= len(ids):
            return
        conn.execute("UPDATE career_history SET sort_order = ? WHERE id = ?", (orders[swap_idx], entry_id))
        conn.execute("UPDATE career_history SET sort_order = ? WHERE id = ?", (orders[idx], ids[swap_idx]))


def add_career(entry: dict) -> dict:
    record = {
        "id": str(uuid.uuid4()),
        "company": entry.get("company", ""),
        "position": entry.get("position", ""),
        "start_date": entry.get("start_date", ""),
        "end_date": entry.get("end_date", ""),
        "salary": entry.get("salary", ""),
        "reason_for_joining": entry.get("reason_for_joining", ""),
        "reason_for_leaving": entry.get("reason_for_leaving", ""),
        "note": entry.get("note", ""),
        "created_at": _now(),
    }
    with _connect() as conn:
        record["sort_order"] = _next_career_sort_order(conn)
        conn.execute(
            """INSERT INTO career_history
            (id, company, position, start_date, end_date, salary, reason_for_joining, reason_for_leaving, note,
             sort_order, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record["id"], record["company"], record["position"], record["start_date"],
                record["end_date"], record["salary"], record["reason_for_joining"],
                record["reason_for_leaving"], record["note"], record["sort_order"], record["created_at"],
            ),
        )
    return record


CAREER_FIELDS = [
    "company", "position", "start_date", "end_date", "salary",
    "reason_for_joining", "reason_for_leaving", "note",
]


def update_career(entry_id: str, entry: dict) -> dict | None:
    fields = {k: v for k, v in entry.items() if k in CAREER_FIELDS}
    if not fields:
        return None
    with _connect() as conn:
        conn.execute(
            f"UPDATE career_history SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
            (*fields.values(), entry_id),
        )
        row = conn.execute("SELECT * FROM career_history WHERE id = ?", (entry_id,)).fetchone()
        return dict(row) if row else None


def delete_career(entry_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM career_history WHERE id = ?", (entry_id,))


def list_education() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM education_history ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def add_education(entry: dict) -> dict:
    record = {
        "id": str(uuid.uuid4()),
        "degree": entry.get("degree", ""),
        "field": entry.get("field", ""),
        "school": entry.get("school", ""),
        "graduated_year": entry.get("graduated_year", ""),
        "note": entry.get("note", ""),
        "created_at": _now(),
    }
    with _connect() as conn:
        conn.execute(
            """INSERT INTO education_history (id, degree, field, school, graduated_year, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (record["id"], record["degree"], record["field"], record["school"],
             record["graduated_year"], record["note"], record["created_at"]),
        )
    return record


EDUCATION_FIELDS = ["degree", "field", "school", "graduated_year", "note"]


def update_education(entry_id: str, entry: dict) -> dict | None:
    fields = {k: v for k, v in entry.items() if k in EDUCATION_FIELDS}
    if not fields:
        return None
    with _connect() as conn:
        conn.execute(
            f"UPDATE education_history SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
            (*fields.values(), entry_id),
        )
        row = conn.execute("SELECT * FROM education_history WHERE id = ?", (entry_id,)).fetchone()
        return dict(row) if row else None


def delete_education(entry_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM education_history WHERE id = ?", (entry_id,))


_IMPORT_PROMPT = (
    "次のテキストは職務経歴書またはLinkedInのプロフィールです。"
    "そこから読み取れる基本情報・職歴・学歴を、以下の形式のJSONオブジェクトとして出力してください。\n"
    "{{\n"
    '  "basic": {{"name": "氏名", "birth_date": "生年月日(あれば)",'
    ' "current_company": "現在の勤務先", "current_position": "現在の職位",'
    ' "current_salary": "現在の年収(記載があれば)"}},\n'
    '  "career": [\n'
    '    {{"company": "会社名", "position": "職位", "start_date": "YYYY-MM", "end_date": "YYYY-MM または 現在なら空文字",'
    ' "salary": "年収などの記載があれば", "reason_for_joining": "入社理由の記載があれば",'
    ' "reason_for_leaving": "退職理由の記載があれば", "note": "その他補足があれば自由記述"}}\n'
    "  ],\n"
    '  "education": [\n'
    '    {{"degree": "学士/修士/博士など", "field": "専攻", "school": "学校名", "graduated_year": "YYYY",'
    ' "note": "その他補足があれば自由記述"}}\n'
    "  ]\n"
    "}}\n"
    "記載が無い項目は空文字にしてください。説明文は書かず、JSONオブジェクトのみを出力してください。\n\n"
    "テキスト:\n{text}\n\n"
    "出力:"
)


def _parse_json_object(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


def extract_text_from_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_text_from_docx(data: bytes) -> str:
    document = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in document.paragraphs)


def extract_text_from_file(filename: str, data: bytes) -> str:
    """ファイル名の拡張子からPDF/DOCXを判別してテキストを抽出する"""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return extract_text_from_pdf(data)
    if lower.endswith(".docx"):
        return extract_text_from_docx(data)
    raise ValueError(f"対応していないファイル形式です: {filename}")


async def import_profile_text(text: str) -> dict:
    """職務経歴書/LinkedInテキストから基本情報・職歴・学歴を抽出し、DBに保存する"""
    raw = await chat_once(
        [{"role": "user", "content": _IMPORT_PROMPT.format(text=text)}], model=MAIN_MODEL
    )
    parsed = _parse_json_object(raw)

    basic = parsed.get("basic", {})
    if isinstance(basic, dict):
        set_basic_info(basic)

    created_career = [add_career(entry) for entry in parsed.get("career", []) if isinstance(entry, dict)]
    created_education = [
        add_education(entry) for entry in parsed.get("education", []) if isinstance(entry, dict)
    ]
    return {"basic": get_basic_info(), "career": created_career, "education": created_education}


def format_profile_summary() -> str:
    """チャットのtool callingから呼び出す用: 基本情報・職歴・学歴を読みやすいテキストにまとめる"""
    basic = get_basic_info()
    career = list_career()
    education = list_education()

    if not basic and not career and not education:
        return ""

    lines = []
    if basic:
        lines.append("[基本情報]")
        for key, value in basic.items():
            lines.append(f"{key}: {value}")
    if career:
        lines.append("[職歴]")
        for c in career:
            period = f"{c['start_date']}〜{c['end_date'] or '現在'}"
            lines.append(
                f"- {c['company']} / {c['position']} ({period}) "
                f"収入: {c['salary'] or '不明'} "
                f"入社理由: {c['reason_for_joining'] or '不明'} "
                f"退職理由: {c['reason_for_leaving'] or '不明'}"
                + (f" 補足: {c['note']}" if c.get("note") else "")
            )
    if education:
        lines.append("[学歴]")
        for e in education:
            lines.append(
                f"- {e['school']} {e['field']} {e['degree']} ({e['graduated_year']}卒)"
                + (f" 補足: {e['note']}" if e.get("note") else "")
            )
    return "\n".join(lines)
