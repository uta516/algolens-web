"""AI ナレッジベース: C問題パターン分析 & Weekly Insights."""

import json
import re
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.user import User
from app.schemas.knowledge import PatternAnalysis, ProblemSummary, WeeklyInsights

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

_cache: dict = {}
_CACHE_TTL = 3600


def _get_cached(key: str):
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < _CACHE_TTL:
        return entry["data"]
    return None


def _set_cached(key: str, data):
    _cache[key] = {"data": data, "ts": time.time()}


_API_KEY_HINT = (
    "Google AI Studio (https://aistudio.google.com/app/apikey) で有効なキーを発行し、"
    "backend/.env の GEMINI_API_KEY を更新してから FastAPI を再起動してください。"
)


def _gemini_client():
    key = settings.gemini_api_key.strip()
    if not key:
        raise HTTPException(
            status_code=503,
            detail=f"GEMINI_API_KEY が未設定です。{_API_KEY_HINT}",
        )
    # Google API キーの基本フォーマット検証（AIza で始まる 39 文字）
    if not (key.startswith("AIza") and len(key) == 39):
        raise HTTPException(
            status_code=503,
            detail=f"GEMINI_API_KEY のフォーマットが不正です（現在: {len(key)}文字）。{_API_KEY_HINT}",
        )
    try:
        from google import genai
        return genai.Client(api_key=key)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Gemini クライアント初期化失敗: {e}")


def _call_gemini(client, prompt: str) -> str:
    """Gemini を呼び出してテキストを返す。エラー種別ごとに明示的な HTTPException を返す。"""
    try:
        from google.genai import types
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.3),
        )
        text = response.text
        if not text:
            raise ValueError("Gemini が空のレスポンスを返しました（安全フィルタの可能性）")
        return text
    except HTTPException:
        raise
    except Exception as e:
        msg = str(e)
        if "400" in msg or "API key not valid" in msg or "INVALID_ARGUMENT" in msg:
            raise HTTPException(
                status_code=401,
                detail=f"Gemini API キーが無効です（400 API key not valid）。{_API_KEY_HINT}",
            )
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
            raise HTTPException(
                status_code=429,
                detail="Gemini API の無料枠クォータを超過しました。しばらく待つか、Google AI Studio で使用量を確認してください（https://ai.dev/rate-limit）。",
            )
        if "403" in msg or "permission" in msg.lower():
            raise HTTPException(
                status_code=403,
                detail=f"Gemini API へのアクセス権限がありません。Generative Language API が有効化されているか確認してください。{_API_KEY_HINT}",
            )
        raise HTTPException(status_code=500, detail=f"Gemini API 呼び出し失敗: {type(e).__name__}: {e}")


def _parse_json(text: str) -> dict:
    """マークダウンコードブロックを除去して JSON をパースする。"""
    # ```json ... ``` や ``` ... ``` を剥がす
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# GET /knowledge/ping  ── API キー疎通確認
# ---------------------------------------------------------------------------

@router.get("/ping")
def ping_gemini():
    """Gemini API キーが有効かどうかを確認する診断エンドポイント。"""
    key = settings.gemini_api_key.strip()
    if not key:
        return {"ok": False, "reason": f"GEMINI_API_KEY が未設定です。{_API_KEY_HINT}"}
    if not (key.startswith("AIza") and len(key) == 39):
        return {"ok": False, "reason": f"キーフォーマット不正 ({len(key)}文字)。{_API_KEY_HINT}"}

    try:
        from google import genai
        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents="Reply with the single word: OK",
        )
        return {"ok": True, "response": (response.text or "").strip()}
    except Exception as e:
        msg = str(e)
        if "400" in msg or "API key not valid" in msg:
            reason = f"400 API key not valid — {_API_KEY_HINT}"
        elif "403" in msg:
            reason = f"403 Permission denied — Generative Language API を有効化してください。{_API_KEY_HINT}"
        else:
            reason = f"{type(e).__name__}: {msg}"
        return {"ok": False, "reason": reason}


# ---------------------------------------------------------------------------
# GET /knowledge/patterns
# ---------------------------------------------------------------------------

@router.get("/patterns", response_model=PatternAnalysis)
def get_patterns(db: Session = Depends(get_db)):
    """難易度 0〜799 の C 問題を DB から取得し、Gemini でパターン分析する。"""
    cached = _get_cached("patterns")
    if cached:
        return cached

    problems = (
        db.query(Problem)
        .filter(
            Problem.problem_index == "C",
            Problem.difficulty >= 0,
            Problem.difficulty < 800,
        )
        .order_by(Problem.difficulty)
        .all()
    )

    if not problems:
        raise HTTPException(
            status_code=404,
            detail="C問題データが DB にありません。先に /sync/problems を実行してください。",
        )

    sample = problems[:15]
    problem_lines = "\n".join(
        f"- [{p.title}] difficulty={p.difficulty:.0f} tags={p.tags or '未設定'}"
        for p in sample
    )

    prompt = f"""
以下は AtCoder の C問題（難易度 0〜799・灰〜茶色相当）の一覧（{len(sample)}件）です。

{problem_lines}

これらを分析し、以下の JSON のみを返してください（説明文や追加のテキストは不要）:
{{
  "constraints_tendency": "制約から解法を絞り込むための目安を、以下のような形式のマークダウン箇条書きで列挙してください（日本語）:\\n- N ≦ 100 → O(N^3) の全探索が通る\\n- N ≦ 10^5 → O(N log N) のソート・二分探索\\n- ... （この問題群から読み取れる具体的な目安を5〜8個）",
  "frequent_algorithms": ["アルゴリズム1", "アルゴリズム2"],
  "solving_patterns": "問題文に出てくるキーワードと最適解法の紐付けを、以下のような形式のマークダウン箇条書きで列挙してください（日本語）:\\n- 「最大値の最小化」「最小値の最大化」→ 二分探索\\n- 「条件を満たす通り数」「場合の数」→ DP\\n- ... （この問題群から読み取れる典型パターンを5〜8個）"
}}
"""

    client = _gemini_client()
    raw = _call_gemini(client, prompt)
    parsed = _parse_json(raw)

    result = PatternAnalysis(
        total_problems=len(problems),
        sample_problems=[
            ProblemSummary(title=p.title, difficulty=p.difficulty, url=p.url)
            for p in sample[:10]
        ],
        constraints_tendency=parsed.get("constraints_tendency") or raw[:400],
        frequent_algorithms=parsed.get("frequent_algorithms") or [],
        solving_patterns=parsed.get("solving_patterns") or "",
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

    _set_cached("patterns", result)
    return result


# ---------------------------------------------------------------------------
# GET /knowledge/weekly-insights/{username}
# ---------------------------------------------------------------------------

@router.get("/weekly-insights/{username}", response_model=WeeklyInsights)
def get_weekly_insights(username: str, db: Session = Depends(get_db)):
    """指定ユーザーの直近提出データから Gemini で Weekly Insights を生成する。"""
    cache_key = f"weekly:{username}"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    user = db.query(User).filter(User.atcoder_username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    now = datetime.now(timezone.utc)
    # 直近7日間（先週データが空の場合も拾えるよう範囲を広げる）
    week_end = now
    week_start = now - timedelta(days=7)

    subs = (
        db.query(Submission, Problem)
        .join(Problem, Submission.problem_id == Problem.id)
        .filter(
            Submission.user_id == user.id,
            Submission.submitted_at >= week_start.replace(tzinfo=None),
            Submission.submitted_at <= week_end.replace(tzinfo=None),
        )
        .all()
    )

    # 直近7日で0件なら全提出の直近20件を使う
    if not subs:
        subs = (
            db.query(Submission, Problem)
            .join(Problem, Submission.problem_id == Problem.id)
            .filter(Submission.user_id == user.id)
            .order_by(Submission.submitted_at.desc())
            .limit(15)
            .all()
        )

    total = len(subs)
    ac_count = sum(1 for s, _ in subs if s.status == "AC")

    if total == 0:
        return WeeklyInsights(
            username=username,
            week_start=week_start.strftime("%Y-%m-%d"),
            week_end=week_end.strftime("%Y-%m-%d"),
            total_submissions=0,
            ac_count=0,
            reusable_snippets="提出データがありません。",
            key_learnings="提出データがありません。",
            generated_at=now.isoformat(),
        )

    sub_lines = "\n".join(
        f"- [{s.status}] {p.title} (difficulty={p.difficulty or '不明'}, lang={s.language or '不明'})"
        for s, p in subs
    )

    prompt = f"""
AtCoder ユーザー「{username}」の直近の提出データ（{total}件、AC: {ac_count}件）:

{sub_lines}

このデータを元に、以下の JSON のみを返してください:
{{
  "reusable_snippets": "提出データから読み取れる典型実装パターンを、Notionのチートシートのようなマークダウン形式でまとめてください（日本語）。\\n各パターンは以下のフォーマットで記述してください:\\n### 〇〇の典型\\n- ポイント1\\n- ポイント2\\n\\n（2〜3個のパターンを抽出）",
  "key_learnings": "学びと改善点を200文字程度でまとめる（日本語）"
}}
"""

    client = _gemini_client()
    raw = _call_gemini(client, prompt)
    parsed = _parse_json(raw)

    result = WeeklyInsights(
        username=username,
        week_start=week_start.strftime("%Y-%m-%d"),
        week_end=week_end.strftime("%Y-%m-%d"),
        total_submissions=total,
        ac_count=ac_count,
        reusable_snippets=parsed.get("reusable_snippets") or raw[:400],
        key_learnings=parsed.get("key_learnings") or "",
        generated_at=now.isoformat(),
    )

    _set_cached(cache_key, result)
    return result
