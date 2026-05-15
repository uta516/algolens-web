"""AtCoder Problems API からデータを同期するエンドポイント。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.user import User
from app.services.atcoder_fetcher import (
    fetch_problem_models,
    fetch_problem_tags,
    fetch_problems,
    fetch_user_submissions,
    normalize_submission,
)

router = APIRouter(prefix="/sync", tags=["sync"])

# ---------------------------------------------------------------------------
# タグ推定ヘルパー（シードデータ）
# ---------------------------------------------------------------------------

# タイトルキーワード → タグのマッピング（大文字小文字無視）
# 各エントリ: ([マッチキーワード, ...], "タグ名")
_TITLE_TAG_MAP: list[tuple[list[str], str]] = [
    # ── 探索・ソート系 ───────────────────────────────────────────────────
    (["binary search", "二分探索", "bisect", "lower bound", "upper bound", "parametric"],   "二分探索"),
    (["sort", "ソート"],                                                                     "ソート"),
    (["brute force", "全探索", "exhaustive", "enumerate all"],                               "全探索"),
    (["bitmask", "submask", "subset enumeration"],                                           "bit全探索"),
    (["greedy", "貪欲法"],                                                                   "グリーディ"),
    (["two pointer", "two-pointer", "sliding window", "尺取", "しゃくとり"],                 "尺取り法"),
    (["divide and conquer", "分割統治"],                                                      "分割統治"),
    # ── DP系 ────────────────────────────────────────────────────────────
    (["dp", "knapsack", "ナップサック", "部分和", "dynamic programming", "memoization", "動的計画法"], "DP"),
    (["digit dp", "桁dp", "桁DP"],                                                           "桁DP"),
    (["tree dp", "木dp", "木DP", "rerooting", "全方位木"],                                   "木DP"),
    (["interval dp", "区間dp", "区間DP"],                                                     "区間DP"),
    # ── グラフ探索 ──────────────────────────────────────────────────────
    (["bfs", "breadth first", "幅優先"],                                                      "BFS"),
    (["dfs", "depth first", "深さ優先"],                                                      "DFS"),
    (["graph", "グラフ", "vertex", "vertices", "connected component", "cycle detection"],     "グラフ"),
    (["dijkstra", "ダイクストラ", "shortest path", "最短経路", "最短距離"],                   "ダイクストラ"),
    (["floyd warshall", "warshall floyd", "ワーシャルフロイド", "all pairs shortest"],         "ワーシャルフロイド"),
    (["bellman ford", "ベルマンフォード", "negative cycle", "負閉路"],                         "ベルマンフォード"),
    (["topological sort", "トポロジカルソート", "directed acyclic graph"],                     "トポロジカルソート"),
    (["scc", "strongly connected component", "強連結成分", "tarjan", "kosaraju"],              "強連結成分"),
    (["max flow", "maximum flow", "最大流", "dinic", "ford fulkerson", "network flow"],        "最大フロー"),
    (["bipartite", "二部グラフ", "bipartite matching"],                                        "二部グラフ"),
    (["minimum spanning tree", "mst", "kruskal", "prim", "最小全域木"],                        "最小全域木"),
    (["lca", "lowest common ancestor", "最近共通祖先", "heavy light decomposition"],            "木"),
    # ── データ構造 ──────────────────────────────────────────────────────
    (["union find", "dsu", "disjoint set", "union-find"],                                      "Union-Find"),
    (["segment tree", "segtree", "セグメント木", "セグ木"],                                    "セグメント木"),
    (["fenwick tree", "binary indexed tree", "フェニック木"],                                  "フェニック木"),
    (["priority queue", "heap", "優先度付きキュー", "ヒープ", "min heap"],                     "優先度付きキュー"),
    (["monotone stack", "単調スタック", "monotone queue", "単調キュー"],                       "スタック"),
    (["sparse table", "スパーステーブル", "range minimum query"],                              "スパーステーブル"),
    (["trie", "トライ木", "prefix tree"],                                                      "トライ木"),
    # ── 配列・累積系 ────────────────────────────────────────────────────
    (["prefix sum", "累積和", "cumulative sum"],                                               "累積和"),
    (["difference array", "いもす法", "imos"],                                                 "いもす法"),
    (["coordinate compression", "座標圧縮", "discretization"],                                 "座標圧縮"),
    # ── 文字列 ──────────────────────────────────────────────────────────
    (["palindrome", "パリンドローム", "文字列", "substring", "anagram"],                       "文字列"),
    (["longest common subsequence", "最長共通部分列"],                                          "LCS"),
    (["longest increasing subsequence", "最長増加部分列"],                                      "LIS"),
    (["z-algorithm", "kmp", "rolling hash", "ローリングハッシュ",
      "suffix array", "suffix automaton", "aho corasick"],                                      "高度な文字列"),
    # ── 数学 ────────────────────────────────────────────────────────────
    (["prime", "素数", "sieve", "エラトステネス", "primality"],                                "素数"),
    (["gcd", "lcm", "greatest common divisor", "最大公約数", "最小公倍数", "euclidean"],        "GCD/LCM"),
    (["combination", "permutation", "組み合わせ", "nCr", "binomial", "factorial", "階乗"],     "組み合わせ"),
    (["matrix exponentiation", "行列累乗", "matrix power"],                                     "行列累乗"),
    (["geometry", "幾何", "convex hull", "凸包", "polygon", "線分", "line intersection"],       "幾何"),
    (["modular inverse", "mod inverse", "逆元", "fermat little theorem"],                       "数学"),
    # ── その他 ──────────────────────────────────────────────────────────
    (["game theory", "nim", "sprague grundy", "grundy", "ゲーム理論"],                         "ゲーム理論"),
    (["grid", "グリッド", "maze", "迷路", "board"],                                            "グリッド"),
    (["hashing", "rolling hash", "ハッシュ"],                                                  "ハッシュ"),
    (["simulation", "シミュレーション", "simulate"],                                            "シミュレーション"),
]


def _infer_tags_from_title(title: str) -> list[str]:
    t = title.lower()
    return [tag for keywords, tag in _TITLE_TAG_MAP if any(kw.lower() in t for kw in keywords)]


def _seed_tags_by_difficulty(difficulty: float | None) -> list[str]:
    """難易度帯ごとに頻出アルゴリズムタグ5種を返す（タイトル推定が効かない場合のフォールバック）。"""
    if difficulty is None:
        return ["実装", "全探索", "シミュレーション"]
    if difficulty < 400:   # 灰
        return ["実装", "全探索", "シミュレーション", "ソート", "文字列"]
    if difficulty < 800:   # 茶
        return ["全探索", "ソート", "グリーディ", "文字列", "累積和"]
    if difficulty < 1200:  # 緑
        return ["二分探索", "DP", "累積和", "グリーディ", "尺取り法"]
    if difficulty < 1600:  # 水
        return ["DP", "BFS", "DFS", "グラフ", "Union-Find"]
    if difficulty < 2000:  # 青
        return ["DP", "ダイクストラ", "セグメント木", "フェニック木", "数学"]
    if difficulty < 2400:  # 黄
        return ["セグメント木", "数学", "組み合わせ", "最小全域木", "フェニック木"]
    if difficulty < 2800:  # 橙
        return ["数学", "最大フロー", "分割統治", "ゲーム理論", "幾何"]
    return ["幾何", "ゲーム理論", "最大フロー", "高度な文字列", "強連結成分"]  # 赤


@router.post("/problems")
def sync_problems(db: Session = Depends(get_db)):
    """問題マスタと難易度データを一括取得してDBに保存する。"""
    problems_raw = fetch_problems()
    models_raw = fetch_problem_models()

    upserted = 0
    for p in problems_raw:
        pid = f"{p['contest_id']}_{p['id']}".lower()
        difficulty = models_raw.get(p["id"], {}).get("difficulty")

        existing = db.query(Problem).filter(Problem.atcoder_problem_id == pid).first()
        if existing:
            existing.difficulty = difficulty
            existing.title = p.get("title", existing.title)
        else:
            db.add(
                Problem(
                    atcoder_problem_id=pid,
                    contest_id=p["contest_id"].lower(),
                    problem_index=p["id"][-1].upper(),
                    title=p.get("title", ""),
                    difficulty=difficulty,
                    url=f"https://atcoder.jp/contests/{p['contest_id']}/tasks/{p['id']}",
                )
            )
            upserted += 1

    db.commit()
    return {"upserted": upserted, "total": len(problems_raw)}


@router.post("/tags")
def sync_tags(db: Session = Depends(get_db)):
    """問題タグを同期する。
    1. AtCoder Problems の problem-tags.json から取得を試みる。
    2. API タグが取得できなかった問題（および API 失敗時の全問題）は、
       タイトルキーワードと難易度からシードタグを強制上書きする。
       ※ 既存タグの有無に関わらず全問題を対象とする。
    """
    tags_map = fetch_problem_tags()
    api_updated = 0
    seed_updated = 0
    api_tagged_pids: set[str] = set()

    # --- API タグを適用（取得成功時のみ）---
    if tags_map:
        problems = db.query(Problem).filter(
            Problem.atcoder_problem_id.in_(list(tags_map.keys()))
        ).all()
        for p in problems:
            new_tags = tags_map.get(p.atcoder_problem_id, [])
            if new_tags:
                p.tags = ",".join(new_tags)
                api_updated += 1
                api_tagged_pids.add(p.atcoder_problem_id)
        db.commit()

    # --- 全問題にシードタグを強制上書き（API タグ取得済みの問題を除く）---
    # untagged のみではなく all() で取得し、既存の旧タグも置き換える
    all_problems = db.query(Problem).all()
    for p in all_problems:
        if p.atcoder_problem_id in api_tagged_pids:
            continue  # API タグ適用済みはスキップ
        title_tags = _infer_tags_from_title(p.title)
        diff_tags = _seed_tags_by_difficulty(p.difficulty)
        merged = list(dict.fromkeys(title_tags + diff_tags))[:5]
        if merged:
            p.tags = ",".join(merged)
            seed_updated += 1
    db.commit()

    total_tagged = db.query(Problem).filter(Problem.tags != None).count()  # noqa: E711
    print(f"[INFO] sync_tags: api_updated={api_updated}, seed_updated={seed_updated}, total_tagged={total_tagged}")
    return {
        "api_source": bool(tags_map),
        "api_updated": api_updated,
        "seed_updated": seed_updated,
        "total_tagged": total_tagged,
    }


@router.post("/submissions/{username}")
def sync_submissions(username: str, from_second: int = 0, db: Session = Depends(get_db)):
    """指定ユーザーの提出データを取得してDBに保存する。"""
    user = db.query(User).filter(User.atcoder_username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found. Register the user first.")

    raw_subs = fetch_user_submissions(username, from_second=from_second)

    inserted = skipped = 0
    for raw in raw_subs:
        normalized = normalize_submission(raw)
        atcoder_sid = normalized["atcoder_submission_id"]

        if atcoder_sid and db.query(Submission).filter(
            Submission.atcoder_submission_id == atcoder_sid
        ).first():
            skipped += 1
            continue

        pid_str = normalized.pop("_atcoder_problem_id")
        problem = db.query(Problem).filter(Problem.atcoder_problem_id == pid_str).first()
        if not problem:
            skipped += 1
            continue

        db.add(Submission(user_id=user.id, problem_id=problem.id, **normalized))
        inserted += 1

    db.commit()
    return {"inserted": inserted, "skipped": skipped}
