# Guchirin (ぐちりん)

完全ローカルで動くLLMチャットアプリ。家族にも打ち明けられないこと、人生の悩み、なかなか人に理解してもらえない内密な悩み。安心して愚痴る場所としてご活用ください。
Ollama + FastAPI + 素のHTML/JS。

## 必要なもの
- [Ollama](https://ollama.com/) がインストール・起動済みであること
- Python 3.11（chromadbの依存ライブラリがWindowsでビルド不要なバージョン）

## セットアップ

```powershell
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

ollama pull qwen3:4b   # メインチャットモデル（未取得の場合）
ollama pull gemma3:1b  # memory判定・抽出/検索クエリ抽出用の軽量モデル
```

## 起動

```powershell
.venv\Scripts\activate
uvicorn backend.main:app --reload
```

ブラウザで http://localhost:8000 を開く。

## 機能
- **チャット**: 左サイドバーでセッションを管理（新規作成・切替・削除）。履歴はSQLite (`data/chat.db`) に保存。応答中は送信ボタンが停止ボタンに変わり、生成をストップできる
- **Web検索**: 「検索モード」チェックボックスONなら必ずDuckDuckGo検索を実行。OFFの場合はメインモデル(`qwen3:4b`)がfunction callingで必要性を判断し、自律的に`web_search`ツールを呼び出す。検索中は何を検索しているかをステータス表示する
- **Memory**: ユーザーの好み・事実を軽量LLM(`gemma3:1b`)が自動抽出してChromaDB (`data/chroma/`) に保存。応答生成時はメインモデルが`retrieve_memory`ツールを呼ぶか自律的に判断してベクトル検索で参照。右側の「記憶パネル」から一覧・追加・削除が可能。既定で1000件が上限で、9割を超えると警告、満杯になると新規追加は停止し既存記憶の更新のみ行われる
- **プロフィール（経歴）**: 基本情報（氏名・生年月日・現在の勤務先/職位/年収）、職歴（会社・職位・在籍期間・年収・入社/退職理由・補足）、学歴をプロフィールパネルから登録・編集・削除・並び替えできる。職務経歴書やLinkedInのプロフィールテキスト、PDF/DOCXファイルを取り込むと軽量LLMが内容を自動抽出して登録する。登録済みの情報があれば、メインモデルが`retrieve_profile`ツールで参照できる

## 設定
`backend/config.py` でモデル名・容量上限などを変更できる。

## 今後の予定
AndroidはWebViewではなくネイティブアプリ（端末上でのオンデバイス推論）として別途実装予定。今回のAPI設計（`/chat`, `/sessions`, `/memory`, `/profile`）はその際の参考契約として扱う。

---

# Guchirin

A fully local LLM chat app. For things you can't tell your family, life struggles, or private worries that are hard for others to understand. Use it as a safe place to vent.
Ollama + FastAPI + plain HTML/JS.

## Requirements
- [Ollama](https://ollama.com/) installed and running
- Python 3.11 (the version whose chromadb dependencies don't require building from source on Windows)

## Setup

```powershell
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

ollama pull qwen3:4b   # main chat model (if not already pulled)
ollama pull gemma3:1b  # lightweight model used for memory judgment/extraction and search query extraction
```

## Running

```powershell
.venv\Scripts\activate
uvicorn backend.main:app --reload
```

Open http://localhost:8000 in a browser.

## Features
- **Chat**: manage sessions from the left sidebar (create, switch, delete). History is stored in SQLite (`data/chat.db`). While a response is streaming, the send button turns into a stop button so you can cancel generation
- **Web search**: when the "search mode" checkbox is ON, a DuckDuckGo search is always performed. When OFF, the main model (`qwen3:4b`) decides whether a search is needed via function calling and autonomously invokes the `web_search` tool. A status line shows what's being searched while it runs
- **Memory**: user preferences and facts are automatically extracted by a lightweight model (`gemma3:1b`) and stored in ChromaDB (`data/chroma/`). When generating a response, the main model decides on its own whether to call the `retrieve_memory` tool and reference memories via vector search. The "memory panel" on the right lets you list, add, and delete memories. The default capacity is 1000 entries; a warning appears past 90% capacity, and once full, new entries stop being added (existing memories can still be updated)
- **Profile (career)**: basic info (name, birth date, current company/position/salary), career history (company, position, employment period, salary, reasons for joining/leaving, notes), and education can be added, edited, deleted, and reordered from the profile panel. Pasting in resume/LinkedIn profile text, or uploading a PDF/DOCX file, lets the lightweight model auto-extract and register the contents. If profile data is registered, the main model can reference it via the `retrieve_profile` tool

## Configuration
Model names, capacity limits, etc. can be changed in `backend/config.py`.

## Future plans
Android is planned to be implemented separately as a native app (on-device inference) rather than a WebView. The current API design (`/chat`, `/sessions`, `/memory`, `/profile`) is intended to serve as a reference contract for that effort.
