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

### 2026-05-05 — 難易度分析グラフ・AI ナレッジベース・データ同期の全面実装

#### ✅ 実装内容

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

#### 🐛 発生したエラーと原因・解決策

| エラー | 原因 | 解決策 |
|--------|------|--------|
| `sync_atcoder_data.py` の最終行で `UnicodeEncodeError` | Windows の cp932 環境で絵文字（✅）を出力しようとした | 絵文字を `[DONE]` に置換 |
| `knowledge.py` で 500 Internal Server Error | `GenerateContentConfig(response_mime_type="application/json")` が `google-genai 1.75.0` で不安定（空レスポンスを返す） | `response_mime_type` を削除し、`_parse_json()` でマークダウンブロックを除去してからパース |
| `gemini-2.0-flash` で 404 Not Found | 無料枠でのクォータが 0（非対応モデル） | `gemini-1.5-flash`（無料枠 15RPM/100万トークン/日）に切り替え |
| `gemini-2.0-flash` で 429 RESOURCE_EXHAUSTED | 無料枠のクォータが `limit: 0`（完全ゼロ） | `gemini-1.5-flash` に戻す。429 のハンドリングとレート制限案内もフロントエンドに追加 |
| `2_Knowledge_Base.py` が重複削除 | AI版リネーム時に誤って静的ページを削除 | `git show HEAD:...` で完全復元 |
| Streamlit リロードで古いデータが表示される | `@st.cache_data(ttl=60〜120)` がDB同期後も古いレスポンスを保持 | DB直結エンドポイントのキャッシュを削除。Gemini エンドポイントは TTL=3600 を維持 |

#### 🔧 技術的なポイント

- `google-genai` の `response.text` は安全フィルタ発動時に `None` を返すため、空チェックを必須化
- Gemini のレスポンスは ` ```json ` ブロックで囲まれることがあるため `re.sub` で除去してから `json.loads`
- API キーの形式検証（`AIza` プレフィックス + 39 文字）をクライアント初期化前に実施し、不正キーを早期に 503 で返す

#### 🚀 次回の目標

- `GEMINI_API_KEY` の有料プランへの移行または利用量管理
- Analysis ページの Plotly グラフ動作確認（実データでの表示テスト）
- Sync ページからのワンクリックデータ更新フローの完成

---

### 2026-05-07 (2) — JST 対応・AI 学習方針エンドポイント新設・スニペット集拡充

#### ✅ 実装内容

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

#### 🐛 発生したエラーと原因・解決策

| エラー | 原因 | 解決策 |
|--------|------|--------|
| Gemini レスポンスが `{}` にパースされ空のフィールドが返る | `response_mime_type` 未設定時、Gemini がマークダウンコードブロックで JSON を包んで返すことがある | `response_mime_type="application/json"` を追加 ＋ `_parse_json()` を多段フォールバック化 |
| 提出一覧の時刻が UTC のまま表示される | DB 保存値は UTC ナイーブ文字列だが、変換処理がなかった | `tz_localize("UTC").tz_convert("Asia/Tokyo")` でフロントエンド側で変換 |

#### 🔧 技術的なポイント

- `response_mime_type="application/json"` はほぼ純粋な JSON を返すが、完全保証ではないため多段フォールバックを残すことで信頼性を二重化
- C 問題の WA/TLE 傾向を分析するプロンプトでは、過去問の URL を含む推奨問題を必ず出力させることで、フロントエンドで clickable なリンクとして表示可能にした

#### 🚀 次回の目標

- `study_guide` エンドポイントの実データでの品質確認
- `5_AI_Knowledge_Base.py` の3セクション一括表示の UX チェック

---

### 2026-05-12 — 起動スクリプトの英語化 & バッチファイル追加

#### ✅ 実装内容

**1. `start.ps1` — コメント・メッセージを英語化**

- スクリプト内の日本語コメント（`# バックエンド` / `# フロントエンド` / `Write-Host "起動しました。"` 等）をすべて英語に統一
- 国際化・チーム共有を意識した可読性向上

**2. `algolens-web.bat` — ダブルクリック起動ショートカット新規追加**

- `powershell -ExecutionPolicy Bypass -File .\start.ps1` を実行する Windows バッチファイルを新規作成
- エクスプローラーからダブルクリックするだけでバックエンド・フロントエンドを同時起動できるように

#### 🔧 技術的なポイント

- `start.ps1` は LF → CRLF 自動変換の警告が出るため、今後 `.gitattributes` で `text=auto` または `eol=crlf` を明示的に指定することを検討

#### 🚀 次回の目標

- `study_guide` エンドポイントの実データでの品質確認
- `5_AI_Knowledge_Base.py` の UX 通し確認
- `.gitattributes` による CRLF 設定の整備

---

### 2026-05-07 — Gemini モデル切り替え & AI プロンプト強化

#### ✅ 実装内容

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

#### 🐛 発生したエラーと原因・解決策

| エラー | 原因 | 解決策 |
|--------|------|--------|
| `gemini-2.0-flash-lite` でも 429 継続 | デイリークォータ（RPD）が複数モデルにまたがって枯渇していた | `client.models.list()` + 直接呼び出しテストで生きているモデルを特定し `gemini-2.5-flash-lite` に切り替え |
| `start.ps1` が PowerShell ツールからエンコードエラー | スクリプト内の全角文字が `-NonInteractive` モードで解析エラーになる | スクリプトを経由せず各コマンドを直接インライン実行するワークアラウンドで対処 |

#### 🔧 技術的なポイント

- 429 の原因が RPM（毎分）ではなく RPD（1日）超過の場合、モデルを変えるだけでは解決しない。`client.models.list()` から候補を列挙し実際に呼んで確認するアプローチが確実
- プロンプトに出力フォーマット（箇条書き・見出し）のサンプルを埋め込むことで、LLM の出力をフロントエンドがそのままマークダウンレンダリングできる形に固定できる

#### 🚀 次回の目標

- 新しいプロンプトで生成された AI ナレッジの品質確認（制約目安・キーワード→解法の精度）
- `gemini-2.5-flash-lite` のクォータ監視と、超過時の自動フォールバック実装の検討

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
