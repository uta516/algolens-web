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
