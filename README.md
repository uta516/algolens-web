# AlgoLens

> AtCoder の提出データを可視化・分析し、弱点特定と学習最適化を支援する Web アプリケーション

---

## 🚀 AlgoLens 概要

### 技術スタック

| レイヤー | 技術 |
|----------|------|
| Backend | Python 3 / FastAPI 0.115 / SQLAlchemy 2.0 / Pydantic 2 |
| Frontend | Streamlit 1.41 / Plotly 5 |
| Database | SQLite（開発）/ Alembic（マイグレーション対応） |
| AI | Google Gemini API (`gemini-2.5-flash-lite`) |
| Testing | pytest 8.3 / pytest-cov |
| Scraping | httpx / BeautifulSoup4 |

### アーキテクチャ

```
algolens-web/
├── backend/
│   ├── app/
│   │   ├── core/          # DB接続・環境設定（pydantic-settings）
│   │   ├── models/        # SQLAlchemy ORM モデル
│   │   ├── schemas/       # Pydantic スキーマ（入出力バリデーション）
│   │   ├── routers/       # FastAPI ルーター（エンドポイント定義）
│   │   ├── services/      # ビジネスロジック層
│   │   └── repositories/  # データアクセス層
│   ├── data/
│   │   └── snippets.json  # マイ・スニペット永続化ストア
│   └── tests/             # pytest テストスイート
└── frontend/
    ├── pages/
    │   ├── 1_Problems.py          # 提出一覧・JST時刻表示
    │   ├── 2_Knowledge_Base.py    # 静的ナレッジベース（チートシート・スニペット）
    │   ├── 3_Sync.py              # データ同期
    │   ├── 4_Analysis.py          # 難易度分析グラフ
    │   └── 5_AI_Knowledge_Base.py # AI ナレッジベース（Gemini連携）
    └── app.py
```

---

## 💻 起動方法・使い方

### セットアップ

```bash
# 仮想環境の作成・有効化
python -m venv .venv
.venv\Scripts\Activate.ps1   # Windows
source .venv/bin/activate    # macOS/Linux

# 依存パッケージのインストール
pip install -r requirements.txt

# 環境変数の設定
cp .env.example .env
# .env に GEMINI_API_KEY を設定
```

### 起動方法

**方法 1: ダブルクリック（Windows）**

`algolens-web.bat` をエクスプローラーからダブルクリックするだけでバックエンド・フロントエンドを同時起動。

**方法 2: PowerShell スクリプト**

```powershell
.\start.ps1
```

**方法 3: 手動起動**

```bash
# バックエンドの起動
cd backend
uvicorn app.main:app --reload

# フロントエンドの起動（別ターミナル）
cd frontend
streamlit run app.py
```

### テストの実行

```bash
cd backend
pytest --cov=app tests/
```

### API エンドポイント一覧

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
| GET | `/analysis/{username}` | 難易度別・タグ別 AC 率分析 |
| GET | `/knowledge/patterns` | Gemini による頻出パターン分析 |
| GET | `/knowledge/weekly-insights/{username}` | 直近提出の Weekly Insights |
| GET | `/knowledge/study_guide/{username}` | AI 学習方針・推奨過去問 |
| GET | `/knowledge/snippets` | スニペット一覧（カテゴリフィルター対応） |
| POST | `/knowledge/snippets` | スニペット追加 |
| PUT | `/knowledge/snippets/{id}` | スニペット更新 |
| DELETE | `/knowledge/snippets/{id}` | スニペット削除 |
| GET | `/knowledge/ping` | Gemini API 疎通確認 |
| GET | `/health` | ヘルスチェック |

---

## ✨ 現在の機能一覧

### バックエンド (FastAPI)

- **ORM モデル**：`User` / `Problem` / `Submission` の3モデル（SQLAlchemy 2.0 `Mapped` 型）
- **REST API**：ユーザー・問題・提出の CRUD + 重複登録時の 409 エラー返却
- **難易度分析**：8色バケット（灰〜赤）による AC 率・問題数集計
- **AI ナレッジ API**：Gemini 連携（パターン分析 / Weekly Insights / 学習方針）、インメモリキャッシュ（TTL 1時間）
- **スニペット CRUD**：UUID 管理・カテゴリ分類・`snippets.json` 永続化
- **データ同期**：AtCoder Problems API から8,500問超の一括 upsert スクリプト

### フロントエンド (Streamlit)

- **1_Problems**：提出一覧・JST 時刻表示・ステータスフィルター
- **2_Knowledge_Base（静的ナレッジベース）**：
  - 解法チートシート
  - 入力チートシート
  - 典型アルゴリズム 12本（bit全探索 / bit DP / Floyd-Warshall / DP / ソート / 二分探索 / 累積和 / いもす法 / 尺取り法 / 貪欲法 / BIT / 繰り返し二乗法 / 素数篩）
  - マイ・スニペット（追加・編集・削除 UI）
- **3_Sync**：ワンクリックデータ同期
- **4_Analysis**：Plotly 難易度別グラフ（AtCoder 公式カラー対応）
- **5_AI_Knowledge_Base**：
  - パターン分析（Gemini）
  - Weekly Insights
  - 今後の学習方針（Next Action Plan）
  - 典型アルゴリズム スニペット集（7パターン）

### 開発・運用ツール

- `algolens-web.bat`：ダブルクリック起動ショートカット（Windows）
- `start.ps1`：バックエンド・フロントエンド同時起動スクリプト
- `scripts/sync_atcoder_data.py`：AtCoder データ一括同期
- `pytest` テストスイート：17テスト（ユーザー7 + 問題10）

---

## 📖 開発ログ（作業履歴）

<details>
<summary>📅 2026-05-04: ABC 自動レポートシステムの構築 &amp; AI プロバイダー移行</summary>

### 🛠 実装内容

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

### ⚠️ 発生したエラーと対策

| エラー | 原因 | 解決策 |
|-------|------|-------|
| `sync.ps1` が実行できない | Claude のツールは `-NonInteractive` モードで動作するため `Read-Host` がブロックされる | `! .\sync.ps1` でユーザー自身がターミナルから直接実行するよう案内 |
| `git push` で `fatal: protocol '[https' is not supported` | リモート URL が `[https://github.com/]` という不正な形式で登録されていた | `git remote set-url origin https://github.com/uta516/algolens-web` で正しい URL に修正 |
| AtCoder-MySolutions への初回プッシュ失敗 | GitHub 上にリポジトリが未作成だった | `github.com/new` でリポジトリ作成後に再プッシュ |

### 💡 技術的なポイント

- Gemini API はシステムプロンプトとユーザーメッセージを**シングルターンで結合**して送信（Claude の `system` / `messages` 分離構造とは異なる）
- `git diff --staged --quiet || git commit` パターンにより、提出がない週の Actions で空コミットが発生しないよう制御
- `--allow-unrelated-histories` による異なる git 系譜のマージはコンフリクトなしで完了（ファイル種別 `.txt` vs `.md/.py/.yml` が重複しなかったため）

### 🚀 次回の目標

- `GEMINI_API_KEY` を GitHub Secrets に登録して自動レポートを初稼働させる
- Streamlit の Analysis・Sync ページ UI 実装（Plotly グラフ）
- AlgoLens の `sync` ルーター：AtCoder スクレイピングによる提出データ自動取得

</details>

<details>
<summary>📅 2026-05-04: バックエンド基盤 &amp; テストスイートの構築</summary>

### 🛠 実装内容

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

### 💡 技術的なポイント

- SQLAlchemy 2.0 の `Mapped` 型アノテーションにより、ORM モデルとPython型ヒントを統一し、IDE補完・mypy 検査の精度を向上
- `analysis` エンドポイントでは Python の `dict` 集計パターンを採用し、N+1 クエリを回避するために JOIN で一括取得してからメモリ上で集計
- テストはクラスベース構成で、各テストメソッドが独立したトランザクションロールバックにより完全に分離

### 🚀 次回の目標

- AtCoder スクレイピング / API 連携による提出データの自動取得（`sync` ルーターの実装）
- Streamlit の Analysis・Problems ページの UI 実装（Plotly グラフ）
- Alembic によるデータベースマイグレーション管理の導入

</details>

<details>
<summary>📅 2026-05-05: 難易度分析グラフ・AI ナレッジベース・データ同期の全面実装</summary>

### 🛠 実装内容

**1. `services/atcoder.py` — 難易度データ取得サービス**

- AtCoder Problems API (`problem-models.json`) から全問題の推定難易度を取得する `fetch_problem_models()` を実装
- 新規パッケージ `google-genai 1.75.0` を `requirements.txt` に追加

**2. `routers/analysis.py` & `schemas/analysis.py` — 難易度集計の完全修正**

- 難易度バケット分類を外部 API 呼び出しからDB保存済みの `prob.difficulty` 直接参照に変更（パフォーマンス改善・オフライン動作対応）
- `DifficultyBucket` スキーマに `ac_rate: float` を追加
- 8色バケット（灰0-399 / 茶400-799 / 緑800-1199 / 水1200-1599 / 青1600-1999 / 黄2000-2399 / 橙2400-2799 / 赤2800+）で集計

**3. `frontend/pages/4_Analysis.py` — Plotly グラフ実装**

- 難易度別 AC 問題数・正答率を `px.bar` で2カラム並列表示
- AtCoder 公式カラー（灰 `#808080` 〜 赤 `#FF0000`）を `color_discrete_map` で各バーに適用
- X 軸を `pd.Categorical` で灰→赤の順に固定
- `@st.cache_data` を削除してDBデータが常に最新反映されるよう修正

**4. `backend/scripts/sync_atcoder_data.py` — hiyokosann 専用同期スクリプト**

- `merged-problems.json` + `problem-models.json` → DB へ一括 upsert（8,508 問）
- hiyokosann のユーザー登録と提出データ（138 件）の取得・保存を自動化
- `os.chdir(backend_dir)` で SQLite 相対パスを正確に解決

**5. `routers/knowledge.py` + `schemas/knowledge.py` — AI ナレッジベース API**

- `GET /knowledge/patterns`：難易度 0〜799 の C 問題（345 件）を Gemini で分析し「制約の傾向・頻出アルゴリズム・解法の定石」を JSON 返却
- `GET /knowledge/weekly-insights/{username}`：直近提出を Gemini で解析し「再利用コードパターン・今週の学び」を返却
- `GET /knowledge/ping`：API キーの疎通を即確認できる診断エンドポイント
- インメモリキャッシュ（TTL 1時間）で Gemini 呼び出しコストを削減

**6. `frontend/pages/5_AI_Knowledge_Base.py` — AI ナレッジページ**

- パターン分析・Weekly Insights を `st.container(border=True)` カード形式で表示
- 頻出アルゴリズムをカラーチップ風 HTML で横並び表示
- エラー種別（401/429/503/接続不可）ごとに対処法を表示

**7. ページ構成の整理**

- `2_Knowledge_Base.py`（静的チートシート）を git 履歴から完全復元
- AI版を `5_AI_Knowledge_Base.py` として独立配置、2 ページが共存

### ⚠️ 発生したエラーと対策

| エラー | 原因 | 解決策 |
|--------|------|--------|
| `sync_atcoder_data.py` の最終行で `UnicodeEncodeError` | Windows の cp932 環境で絵文字（✅）を出力しようとした | 絵文字を `[DONE]` に置換 |
| `knowledge.py` で 500 Internal Server Error | `GenerateContentConfig(response_mime_type="application/json")` が `google-genai 1.75.0` で不安定（空レスポンスを返す） | `response_mime_type` を削除し、`_parse_json()` でマークダウンブロックを除去してからパース |
| `gemini-2.0-flash` で 404 Not Found | 無料枠でのクォータが 0（非対応モデル） | `gemini-1.5-flash`（無料枠 15RPM/100万トークン/日）に切り替え |
| `gemini-2.0-flash` で 429 RESOURCE_EXHAUSTED | 無料枠のクォータが `limit: 0`（完全ゼロ） | `gemini-1.5-flash` に戻す。429 のハンドリングとレート制限案内もフロントエンドに追加 |
| `2_Knowledge_Base.py` が重複削除 | AI版リネーム時に誤って静的ページを削除 | `git show HEAD:...` で完全復元 |
| Streamlit リロードで古いデータが表示される | `@st.cache_data(ttl=60〜120)` がDB同期後も古いレスポンスを保持 | DB直結エンドポイントのキャッシュを削除。Gemini エンドポイントは TTL=3600 を維持 |

### 💡 技術的なポイント

- `google-genai` の `response.text` は安全フィルタ発動時に `None` を返すため、空チェックを必須化
- Gemini のレスポンスは ` ```json ` ブロックで囲まれることがあるため `re.sub` で除去してから `json.loads`
- API キーの形式検証（`AIza` プレフィックス + 39 文字）をクライアント初期化前に実施し、不正キーを早期に 503 で返す

### 🚀 次回の目標

- `GEMINI_API_KEY` の有料プランへの移行または利用量管理
- Analysis ページの Plotly グラフ動作確認（実データでの表示テスト）
- Sync ページからのワンクリックデータ更新フローの完成

</details>

<details>
<summary>📅 2026-05-07: Gemini モデル切り替え &amp; AI プロンプト強化</summary>

### 🛠 実装内容

**1. Gemini 使用モデルの切り替え（`knowledge.py`）**

- `gemini-2.0-flash` → `gemini-2.0-flash-lite` に変更後も 429 が継続
- `client.models.list()` で利用可能な全モデルを列挙し、`generate_content` 呼び出しを直接テスト
- `gemini-2.0-flash` / `gemini-2.0-flash-lite` は両方ともデイリークォータ超過（RESOURCE_EXHAUSTED）
- 唯一応答した **`gemini-2.5-flash-lite`** に変更（`_call_gemini` / `ping_gemini` の2箇所）

**2. フロントエンドのエラー文言修正（`5_AI_Knowledge_Base.py`）**

- 429 エラー時の案内文に `gemini-1.5-flash` というモデル名を直書きしていた箇所を削除
- 「Gemini API の無料枠クォータを超過しています」という汎用表記に統一

**3. AI プロンプトの実戦的な強化（`knowledge.py`）**

- `constraints_tendency`：「傾向を説明」→「N ≦ 100 → O(N^3) の全探索」形式の具体的な目安を 5〜8 個の箇条書きで出力するよう変更
- `solving_patterns`：「解法の定石を説明」→「キーワード → 解法」形式の紐付け（例：「最大値の最小化」→ 二分探索）を 5〜8 個の箇条書きで出力するよう変更
- `reusable_snippets`：「使い回せるパターンを説明」→ `### 〇〇の典型` 見出し＋箇条書きの Notion チートシート形式（2〜3 パターン）で出力するよう変更

### ⚠️ 発生したエラーと対策

| エラー | 原因 | 解決策 |
|--------|------|--------|
| `gemini-2.0-flash-lite` でも 429 継続 | デイリークォータ（RPD）が複数モデルにまたがって枯渇していた | `client.models.list()` + 直接呼び出しテストで生きているモデルを特定し `gemini-2.5-flash-lite` に切り替え |
| `start.ps1` が PowerShell ツールからエンコードエラー | スクリプト内の全角文字が `-NonInteractive` モードで解析エラーになる | スクリプトを経由せず各コマンドを直接インライン実行するワークアラウンドで対処 |

### 💡 技術的なポイント

- 429 の原因が RPM（毎分）ではなく RPD（1日）超過の場合、モデルを変えるだけでは解決しない。`client.models.list()` から候補を列挙し実際に呼んで確認するアプローチが確実
- プロンプトに出力フォーマット（箇条書き・見出し）のサンプルを埋め込むことで、LLM の出力をフロントエンドがそのままマークダウンレンダリングできる形に固定できる

### 🚀 次回の目標

- 新しいプロンプトで生成された AI ナレッジの品質確認（制約目安・キーワード→解法の精度）
- `gemini-2.5-flash-lite` のクォータ監視と、超過時の自動フォールバック実装の検討

</details>

<details>
<summary>📅 2026-05-07 (2): JST 対応・AI 学習方針エンドポイント新設・スニペット集拡充</summary>

### 🛠 実装内容

**1. 全体の時刻表示を UTC → JST に統一**

- `backend/app/routers/knowledge.py`：`JST = timezone(timedelta(hours=9))` を定義し、`datetime.now(timezone.utc)` を `datetime.now(JST)` に置換（`generated_at` フィールド 2 箇所）
- `frontend/pages/5_AI_Knowledge_Base.py`：生成日時の末尾ラベルを `UTC` → `JST` に修正
- `frontend/pages/1_Problems.py`：提出記録の時刻を `pd.to_datetime().dt.tz_localize("UTC").dt.tz_convert("Asia/Tokyo")` で JST 変換してから表示

**2. `GET /knowledge/study_guide/{username}` — AI 学習方針エンドポイント新設**

- `backend/app/routers/knowledge.py`：ユーザーの C 問題提出履歴（直近 15 件）を取得し、WA/TLE 等の失敗パターンを Gemini で分析
- 出力は3フィールド（`current_weakness` 弱点分析 / `required_code_pattern` 習得すべき解法＋サンプルコード / `recommended_practice` 具体的アクションプラン + 推奨過去問）
- `backend/app/schemas/knowledge.py`：`StudyGuide` スキーマを追加
- `frontend/pages/5_AI_Knowledge_Base.py`：セクション③「今後の学習方針 (Next Action Plan)」として3つのカードで結果を表示。再生成ボタン付き

**3. Gemini JSON パース品質の強化**

- Gemini API 呼び出しに `response_mime_type="application/json"` を追加
- `_parse_json()` を多段フォールバック（① 直接 `json.loads` → ② マークダウンブロック除去 → ③ 正規表現で `{...}` 抽出）に強化し、パース失敗を大幅に削減

**4. 典型アルゴリズム スニペット集の拡充**

- `frontend/pages/2_Knowledge_Base.py`：グリッド BFS・ハッシュテーブル・貪欲法・ソート・めぐる式二分探索の5スニペットを新規追加
- `frontend/pages/5_AI_Knowledge_Base.py`：セクション④「典型アルゴリズム スニペット集」として全7パターン（全探索・DP・グリッド BFS・ハッシュテーブル・貪欲法・ソート・二分探索）を `st.expander` で実装

### ⚠️ 発生したエラーと対策

| エラー | 原因 | 解決策 |
|--------|------|--------|
| Gemini レスポンスが `{}` にパースされ空のフィールドが返る | `response_mime_type` 未設定時、Gemini がマークダウンコードブロックで JSON を包んで返すことがある | `response_mime_type="application/json"` を追加 ＋ `_parse_json()` を多段フォールバック化 |
| 提出一覧の時刻が UTC のまま表示される | DB 保存値は UTC ナイーブ文字列だが、変換処理がなかった | `tz_localize("UTC").tz_convert("Asia/Tokyo")` でフロントエンド側で変換 |

### 💡 技術的なポイント

- `response_mime_type="application/json"` はほぼ純粋な JSON を返すが、完全保証ではないため多段フォールバックを残すことで信頼性を二重化
- C 問題の WA/TLE 傾向を分析するプロンプトでは、過去問の URL を含む推奨問題を必ず出力させることで、フロントエンドで clickable なリンクとして表示可能にした

### 🚀 次回の目標

- `study_guide` エンドポイントの実データでの品質確認
- `5_AI_Knowledge_Base.py` の3セクション一括表示の UX チェック

</details>

<details>
<summary>📅 2026-05-12: 起動スクリプトの英語化 &amp; バッチファイル追加</summary>

### 🛠 実装内容

**1. `start.ps1` — コメント・メッセージを英語化**

- スクリプト内の日本語コメント（`# バックエンド` / `# フロントエンド` / `Write-Host "起動しました。"` 等）をすべて英語に統一
- 国際化・チーム共有を意識した可読性向上

**2. `algolens-web.bat` — ダブルクリック起動ショートカット新規追加**

- `powershell -ExecutionPolicy Bypass -File .\start.ps1` を実行する Windows バッチファイルを新規作成
- エクスプローラーからダブルクリックするだけでバックエンド・フロントエンドを同時起動できるように

### 💡 技術的なポイント

- `start.ps1` は LF → CRLF 自動変換の警告が出るため、今後 `.gitattributes` で `text=auto` または `eol=crlf` を明示的に指定することを検討

### 🚀 次回の目標

- `study_guide` エンドポイントの実データでの品質確認
- `5_AI_Knowledge_Base.py` の UX 通し確認
- `.gitattributes` による CRLF 設定の整備

</details>

<details>
<summary>📅 2026-05-13: Knowledge Base 全面強化（スニペット CRUD・典型アルゴリズム12本・タブ再編）</summary>

### 🛠 実装内容

**1. マイ・スニペット機能の新設（`2_Knowledge_Base.py` + FastAPI）**

- `backend/data/snippets.json` を永続化ストアとして新設
- `POST /knowledge/snippets`：スニペット追加エンドポイントを実装
- `GET /knowledge/snippets`：保存済みスニペット一覧を返すエンドポイントを実装
- Streamlit 側に「マイ・スニペット」タブを追加。タイトル・タグ・コード・メモの入力フォームから FastAPI 経由で JSON に保存する UI を実装

**2. スニペット CRUD の完全化（編集・削除・UUID・カテゴリ対応）**

- スニペット ID を整数連番 → UUID 文字列に変更。既存データはロード時に自動マイグレーション
- `category` フィールドを追加し `"my_snippet"` / `"input_cheatsheet"` で分類
- `PUT /knowledge/snippets/{id}`：ID 指定による上書き更新エンドポイントを追加
- `DELETE /knowledge/snippets/{id}`：ID 指定による削除エンドポイントを追加
- `GET /knowledge/snippets?category=xxx`：カテゴリフィルタリングに対応
- `SnippetUpdate` Pydantic モデルを `schemas/knowledge.py` に追加
- Streamlit 側に `render_snippet_card()` 関数を実装。各スニペットに「✏️ 編集」（既存値をプリセットしたフォーム表示）と「🗑️ 削除」ボタンを追加。ボタンキーは `edit_btn_{uuid}` 形式で衝突なし
- 「入力チートシート」タブの下部に「マイ・入力チートシート」セクションを追加し、同様の CRUD UI を配置

**3. 典型アルゴリズムタブの完全書き換え（12本）**

`frontend/pages/2_Knowledge_Base.py` の Tab 3 を以下4カテゴリ・12アルゴリズムで再構成：

| カテゴリ | アルゴリズム |
|---|---|
| N ≦ 20〜50 | bit全探索・bit DP（集合DP/TSP）・Floyd-Warshall |
| N ≦ 2,000 | 二重ループDP（部分和・ナップサック）・ソート（バブル/転倒数含む） |
| N ≦ 10⁵〜10⁶ | 二分探索・累積和/いもす法・尺取り法・貪欲法・BIT（Fenwick Tree） |
| 数学・巨大な制約 | 繰り返し二乗法（`pow(a,n,mod)` + 手書き実装 + nCr）・約数列挙/素因数分解/素数篩 |

各スニペットは `st.info`（計算量・用途）・`st.markdown`（使い分け表・手順）・`st.code`（Pythonテンプレート）・`st.success`（応用例）で統一フォーマット化。変数名に予約語 `list` は一切不使用（`arr`/`A` に統一）

**4. タブ順序の再編**

- 最終的なタブ順：解法チートシート → 入力チートシート → **典型アルゴリズム** → **マイ・スニペット** → リンク集

### ⚠️ 発生したエラーと対策

| エラー | 原因 | 解決策 |
|--------|------|--------|
| スニペットセクションが `study_guide` の前に誤挿入された | `Edit` ツールの `replace_all=false` が `_set_cached(cache_key, result)\n    return result` の最初のマッチ（weekly insights の末尾）を置換した | 機能上は問題なし（FastAPI はルート登録順に依存しない）。以降は一意なコンテキストを含むターゲット文字列を使用 |
| スニペットファイルパスのシミュレーションが不一致 | 相対パスで `Path('backend/app/routers')` を計算し、`__file__` の絶対パスと混同した | `Path(__file__).resolve()` を用いた絶対パスでシミュレーションし、`backend/data/snippets.json` へ正しく解決することを確認 |

### 💡 技術的なポイント

- Streamlit のタブ `with tab:` ブロックはソース内の記述順ではなく変数（`tab3` 等）で描画位置が決まるため、タブ順変更はラベルと変数の対応を変えるだけでよい
- `render_snippet_card()` 内で `st.session_state[f"editing_{uuid}"]` を使うことで、各スニペットの編集モードを独立管理。`st.expander(expanded=is_editing)` により `st.rerun()` 後もフォームが展開状態を維持
- スニペットの UUID マイグレーションは `_load_snippets()` 内で `dirty` フラグを用いて一度だけ実行し、変更があれば即座に再保存することで整合性を保つ

### 🚀 次回の目標

- スニペット機能の実運用テスト（追加・編集・削除のフロー通し確認）
- 典型アルゴリズムの内容レビューと追加（グラフ系・文字列系など）
- テストスイートへのスニペット API テスト追加

</details>

<details>
<summary>📅 2026-05-14: README・CLAUDE.md 整備と典型アルゴリズム例題追加</summary>

### 🛠 実装内容
- `README.md` を新規作成。「概要 / 起動方法 / 機能一覧 / 開発ログ」のハイブリッド構成に再設計し、全 API エンドポイント一覧・現在の機能カテゴリ別リストを追加
- 既存の開発ログ全エントリを `<details>/<summary>` アコーディオン形式に変換（内容は1文字も削除せず保持）
- `CLAUDE.md` を新規作成。「作業終了」カスタムコマンドを手順1〜4で詳細定義（git diff 確認→README追記→push→完了報告）
- `frontend/pages/2_Knowledge_Base.py` の典型アルゴリズム Tab（12本全て）に「例題・入力例・出力例」を追加し、コードスニペットを具体的な入出力付きの実践形式にリファクタリング

### ⚠️ 発生したエラーと対策
- 特になし

### 💡 技術的ポイント
- `<details>` の `<summary>` タグ内に `&`（アンパサンド）を含む場合、GitHub Markdown では `&amp;` にエスケープしないと表示が崩れるケースがあるため、該当箇所（「& テストスイート」等）をエスケープ済みで記述
- `CLAUDE.md` をプロジェクトルートに配置することで Claude Code が自動読み込みし、次セッション以降もカスタムコマンドが有効になる
- 典型アルゴリズムのスニペットは「例題→入力例→出力例→コード」の順にすることで、問題を読んで即座に対応するパターン認識の練習として活用しやすい構成になる

</details>

<details>
<summary>📅 2026-05-14 (2): 開発ログ並び順の変更 &amp; 作業終了ルーティンの更新</summary>

### 🛠 実装内容
- 両 `README.md`（`algolens-web/README.md` と リポジトリルートの `README.md`）の「📖 開発ログ」セクションを、前セッションで降順に並び替えた後、今セッションで**昇順（古い順・05-04 が先頭・05-14 が末尾）**に再変更した
- `../CLAUDE.md` の【作業終了ルーティン】を更新：「開発ログセクションの**先頭**に追記」→「開発ログセクションの**一番下（最後尾）**に追記」に変更し、ログが時系列昇順で自然に積み上がる運用に統一
- 前セッション末尾で失敗していた `git add README.md ../README.md` を正しいパスで再実行し、降順ソートのコミット（`ae0df64`）を完成させた

### ⚠️ 発生したエラーと対策
- `git add "algolens-web/README.md"` が `fatal: pathspec did not match any files` で失敗していた（前セッションの積み残し）。原因は作業ディレクトリが `algolens-web/` なのに `algolens-web/README.md` という二重パスを指定していたため。`git add README.md ../README.md` の形式に修正して解決
- `print()` で絵文字を含む文字列を出力すると Windows の cp932 環境で `UnicodeEncodeError`。`sys.stdout` を `io.TextIOWrapper(encoding='utf-8')` でラップして解決

### 💡 技術的ポイント
- `git add` のパスは**現在の作業ディレクトリからの相対パス**で指定する必要がある。サブディレクトリで作業中に親ディレクトリのファイルを追加する場合は `../file` 形式を使う
- Python スクリプトで日本語・絵文字を含む文字列を標準出力する場合、Windows 環境では `sys.stdout` のエンコーディングを明示的に UTF-8 に設定しないと cp932 エラーが発生する

</details>
