# AlgoLens

> AtCoder の提出データを可視化・分析し、弱点特定と学習最適化を支援する Web アプリケーション

## 技術スタック

| レイヤー | 技術 |
|----------|------|
| Backend | Python 3 / FastAPI 0.115 / SQLAlchemy 2.0 / Pydantic 2 |
| Frontend | Streamlit 1.41 / Plotly 5 |
| Database | SQLite（開発）/ Alembic（マイグレーション対応） |
| Testing | pytest 8.3 / pytest-cov |
| Scraping | httpx / BeautifulSoup4 |

## アーキテクチャ

```
algolens-web/
├── backend/
│   ├── app/
│   │   ├── core/          # DB接続・環境設定（pydantic-settings）
│   │   ├── models/        # SQLAlchemy ORM モデル
│   │   ├── schemas/       # Pydantic スキーマ（入出力バリデーション）
│   │   ├── routers/       # FastAPI ルーター（エンドポイント定義）
│   │   ├── services/      # ビジネスロジック層（予定）
│   │   └── repositories/  # データアクセス層（予定）
│   └── tests/             # pytest テストスイート
└── frontend/
    └── app.py             # Streamlit ダッシュボード
```

## API エンドポイント

| Method | Path | 説明 |
|--------|------|------|
| POST | `/users/` | ユーザー登録 |
| GET | `/users/{username}` | ユーザー情報取得 |
| POST | `/problems/` | 問題登録 |
| GET | `/problems/` | 問題一覧（contest_id / limit フィルター対応） |
| GET | `/problems/{id}` | 問題詳細取得 |
| POST | `/submissions/` | 提出結果登録 |
| GET | `/submissions/` | 提出一覧（user_id / problem_id / status フィルター対応） |
| GET | `/submissions/{id}` | 提出詳細取得 |
| GET | `/analysis/{username}` | 弱点分析サマリー取得 |
| GET | `/health` | ヘルスチェック |

## セットアップ

```bash
# 仮想環境の作成・有効化
python -m venv .venv
.venv\Scripts\Activate.ps1   # Windows
source .venv/bin/activate    # macOS/Linux

# 依存パッケージのインストール
pip install -r requirements.txt

# 環境変数の設定
cp .env.example .env

# バックエンドの起動
cd backend
uvicorn app.main:app --reload

# フロントエンドの起動（別ターミナル）
cd frontend
streamlit run app.py
```

## テストの実行

```bash
cd backend
pytest --cov=app tests/
```

---

## 開発ログ

### 2026-05-04 — バックエンド基盤 & テストスイートの構築

#### ✅ 実装内容

**1. プロジェクト基盤の整備**

- FastAPI アプリケーション（`app/main.py`）を初期化し、Streamlit フロントエンド（`localhost:8501`）向けに CORS ミドルウェアを設定
- `pydantic-settings` を用いた環境設定管理（`.env` ファイル対応）を実装し、DB URL・APIキー・AtCoderアカウント情報を一元管理

**2. SQLAlchemy 2.0 ORM モデルの設計と実装**

`Mapped` + `mapped_column` を使用した型安全な3モデルを実装：

- **`User`**: AtCoderユーザー名（ユニーク制約）、作成日時、提出データへのリレーション
- **`Problem`**: 問題ID・コンテストID・難易度スコア・タグ（カンマ区切り）・URL
- **`Submission`**: 提出ID・ユーザー/問題FK・ステータス（AC/WA/TLE/RE/CE/MLE）・実行時間・メモリ使用量・メモ欄

**3. REST API ルーターの実装（5ルーター）**

- `users` / `problems` / `submissions`：標準的な CRUD + 重複登録時の 409 エラー返却
- `analysis`：AtCoder Problems の難易度スコアを8色（灰・茶・緑・水・青・黄・橙・赤）にバケット分けし、タグ別 AC 率・難易度別 AC 率を集計して返す分析エンドポイント
- `sync`：AtCoder からのデータ同期（スタブ実装）

**4. Pydantic v2 スキーマの実装**

- `UserCreate` / `UserResponse`、`ProblemCreate` / `ProblemResponse`、`SubmissionCreate` / `SubmissionResponse`
- `AnalysisSummary`（`TagStat` + `DifficultyBucket` のネスト構造）

**5. Streamlit フロントエンドのナビゲーション画面**

Analysis（弱点分析）・Problems（問題一覧）・Sync（データ同期）への導線を持つトップページを実装

**6. pytest テストスイート（合計17テスト）**

- `conftest.py`：テスト用インメモリ SQLite + `TestClient` のフィクスチャを定義
- `test_users.py`（7テスト）：ユーザー登録・取得・重複チェック・404の正常系/異常系を網羅
- `test_problems.py`（10テスト）：問題 CRUD・`contest_id` フィルター・ページネーション・オプションフィールドの null 許容を検証

**7. 開発自動化ツール**

- `sync.ps1`：作業内容を対話形式で入力し `docs/logs/YYYY-MM-DD.md` に記録したうえで GitHub へ自動プッシュするスクリプト
- `CLAUDE.md`：AI 支援開発のガードレール（破壊的変更の事前確認・推測実装の禁止）を定義

#### 🔧 技術的なポイント

- SQLAlchemy 2.0 の `Mapped` 型アノテーションにより、ORM モデルとPython型ヒントを統一し、IDE補完・mypy 検査の精度を向上
- `analysis` エンドポイントでは Python の `dict` 集計パターンを採用し、N+1 クエリを回避するために JOIN で一括取得してからメモリ上で集計
- テストはクラスベース構成で、各テストメソッドが独立したトランザクションロールバックにより完全に分離

#### 🚀 次回の目標

- AtCoder スクレイピング / API 連携による提出データの自動取得（`sync` ルーターの実装）
- Streamlit の Analysis・Problems ページの UI 実装（Plotly グラフ）
- Alembic によるデータベースマイグレーション管理の導入

---

### 2026-05-04 — ABC 自動レポートシステムの構築 & AI プロバイダー移行

#### ✅ 実装内容

**1. AtCoder-MySolutions リポジトリの新規構築**

- `AtCoder-MySolutions/` を新規作成し、`git init` + リモート設定（`uta516/AtCoder-MySolutions`）を実施
- 既存リポジトリ（手書き解法 `.txt` 12本 / ABC447〜ABC456）と `--allow-unrelated-histories` でコンフリクトなくマージ

**2. `scripts/auto_reporter.py` — 完全自動解析スクリプト**

- AtCoder Problems API から `uta516` の当日 ABC 提出を全取得し、問題ごとに**最新の1提出**を採用
- BeautifulSoup4 で問題文・制約・入出力をスクレイピング、提出コードも取得
- 判定結果に応じて AI 解説を生成：
  - `AC` → 計算量最適化済み Python 模範解答 + アルゴリズム解説
  - `WA/TLE/RE` → 不正解原因の分析（エッジケース・計算量）+ 正解模範解答
- `(コンテスト番号)_(MMDD).md` 形式でレポートを自動保存（例：`457_0510.md`）

**3. `.github/workflows/abc_auto_report.yml` — GitHub Actions 定義**

- `cron: '0 14 * * 6'`（毎週土曜 23:00 JST）でスケジュール実行
- `workflow_dispatch` で手動トリガーにも対応
- `permissions: contents: write` を付与し、`GITHUB_TOKEN` で自動コミット・プッシュ
- 生成ファイルがない場合（コンテスト未開催日）は `git diff --staged --quiet` で空コミットを防止

**4. Anthropic → Google Gemini への AI プロバイダー移行**

- `requirements.txt`：`anthropic` を `google-generativeai>=0.8.0` に置き換え
- `generate_ai_explanation()`：`anthropic.Anthropic()` → `genai.GenerativeModel("gemini-1.5-flash")` に書き換え
- GitHub Actions の環境変数：`ANTHROPIC_API_KEY` → `GEMINI_API_KEY`
- README・コメント類の Anthropic 関連記述をすべて Gemini 向けに更新

**5. `CLAUDE.md` カスタムルールの追加**

- 「作業終了」発言をトリガーとする**終了ルーティン**を定義
  1. チャット履歴・git diff から実装内容・エラー・解決策を自動解析
  2. `README.md` 開発ログへ Markdown 形式で追記
  3. `git add .` → `git commit` → `git push origin main` を全自動実行

#### 🐛 発生したエラーと原因・解決策

| エラー | 原因 | 解決策 |
|-------|------|-------|
| `sync.ps1` が実行できない | Claude のツールは `-NonInteractive` モードで動作するため `Read-Host` がブロックされる | `! .\sync.ps1` でユーザー自身がターミナルから直接実行するよう案内 |
| `git push` で `fatal: protocol '[https' is not supported` | リモート URL が `[https://github.com/]` という不正な形式で登録されていた | `git remote set-url origin https://github.com/uta516/algolens-web` で正しい URL に修正 |
| AtCoder-MySolutions への初回プッシュ失敗 | GitHub 上にリポジトリが未作成だった | `github.com/new` でリポジトリ作成後に再プッシュ |

#### 🔧 技術的なポイント

- Gemini API はシステムプロンプトとユーザーメッセージを**シングルターンで結合**して送信（Claude の `system` / `messages` 分離構造とは異なる）
- `git diff --staged --quiet || git commit` パターンにより、提出がない週の Actions で空コミットが発生しないよう制御
- `--allow-unrelated-histories` による異なる git 系譜のマージはコンフリクトなしで完了（ファイル種別 `.txt` vs `.md/.py/.yml` が重複しなかったため）

#### 🚀 次回の目標

- `GEMINI_API_KEY` を GitHub Secrets に登録して自動レポートを初稼働させる
- Streamlit の Analysis・Sync ページ UI 実装（Plotly グラフ）
- AlgoLens の `sync` ルーター：AtCoder スクレイピングによる提出データ自動取得
