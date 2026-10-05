"""修正コードの確認: サンプル・愚直解との比較・最大サイズの入力での実行と、確認用コードの保存。

LLM が書いたコードを手元で動かすため、どれも別プロセスの Python を -I（環境変数・ユーザー site を無視）で
起動し、作業ディレクトリは一時ディレクトリにする。

確認用コード（愚直解・小さい入力を作るコード・最大サイズの入力を作るコード）は問題ごとに
data/editorials/{problem_id}/checkers.json に保存し、同じ問題の 2 回目以降は作り直さない。
"""

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from app.core.config import settings

SAMPLE_TIME_LIMIT_SEC = 2.0
DEFAULT_TIME_LIMIT_SEC = 2.0   # 問題ページから制限時間を読めなかったとき
CPYTHON_TIME_FACTOR = 5        # PyPy がないとき、CPython では制限時間をこの倍率で緩める
GENERATOR_TIME_LIMIT_SEC = 10.0
MAX_INPUT_BYTES = 64 * 1024 * 1024
BRUTE_CASES = 30               # 愚直解と比べる小さい入力の数
SMALL_CASE_TIME_LIMIT_SEC = 5.0
_FLOAT_TOL = 1e-6

PYTHON = [sys.executable, "-I", "-X", "utf8"]


# ---------------------------------------------------------------------------
# 1 回の実行
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RunResult:
    status: str  # ok / TLE / RE
    stdout: str = ""
    stderr: str = ""


def run_python(code: str, stdin: str, time_limit: float, args: tuple[str, ...] = ()) -> RunResult:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "main.py"
        path.write_text(code, encoding="utf-8")
        try:
            proc = subprocess.run(
                [*PYTHON, str(path), *args],
                input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=time_limit, cwd=tmp,
            )
        except subprocess.TimeoutExpired:
            return RunResult("TLE")
    if proc.returncode != 0:
        return RunResult("RE", proc.stdout, proc.stderr[-2000:])
    return RunResult("ok", proc.stdout)


# ---------------------------------------------------------------------------
# サンプル
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CaseResult:
    index: int
    status: str  # AC / WA / TLE / RE
    input: str
    expected: str
    actual: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class SampleCheck:
    passed: bool | None  # サンプルがなければ None
    cases: list[CaseResult] = field(default_factory=list)

    def first_failure(self) -> CaseResult | None:
        return next((c for c in self.cases if c.status != "AC"), None)


def _tokens_equal(expected: str, actual: str) -> bool:
    if expected == actual:
        return True
    try:
        e, a = float(expected), float(actual)
    except ValueError:
        return False
    if math.isnan(e) or math.isnan(a):
        return False
    return math.isclose(e, a, rel_tol=_FLOAT_TOL, abs_tol=_FLOAT_TOL)


def outputs_match(expected: str, actual: str) -> bool:
    """空白区切りのトークン単位で比較する。小数は 1e-6 までの誤差を許す。"""
    e, a = expected.split(), actual.split()
    return len(e) == len(a) and all(_tokens_equal(x, y) for x, y in zip(e, a))


def _judge(index: int, stdin: str, expected: str, run: RunResult) -> CaseResult:
    base = dict(index=index, input=stdin, expected=expected)
    if run.status == "TLE":
        return CaseResult(status="TLE", **base)
    if run.status == "RE":
        return CaseResult(status="RE", actual=run.stdout, stderr=run.stderr, **base)
    return CaseResult(status="AC" if outputs_match(expected, run.stdout) else "WA", actual=run.stdout, **base)


def run_samples(code: str, samples: list[dict], time_limit: float = SAMPLE_TIME_LIMIT_SEC) -> SampleCheck:
    """コードを各サンプルに対して実行する。サンプルがなければ passed=None。"""
    if not samples:
        return SampleCheck(passed=None)
    cases = [
        _judge(i, s["input"], s["output"], run_python(code, s["input"], time_limit))
        for i, s in enumerate(samples, 1)
    ]
    return SampleCheck(passed=all(c.status == "AC" for c in cases), cases=cases)


# ---------------------------------------------------------------------------
# 愚直解との比較
# ---------------------------------------------------------------------------

BRUTE_OK = "ok"
BRUTE_MISMATCH = "mismatch"
BRUTE_SKIPPED = "skipped"


@dataclass(frozen=True)
class BruteCases:
    """小さい入力と愚直解の答え。1 回の解説で 1 度だけ作り、やり直しのたびに使い回す。"""

    cases: list[tuple[str, str]]
    note: str = ""  # 作れなかった理由


@dataclass(frozen=True)
class BruteCheck:
    status: str            # BRUTE_OK / BRUTE_MISMATCH / BRUTE_SKIPPED
    total: int = 0         # 比べた入力の数
    matched: int = 0
    failure: CaseResult | None = None   # 最初に答えが違った入力（expected は愚直解の答え）
    note: str = ""


def prepare_brute_cases(brute_code: str, small_generator: str, n: int = BRUTE_CASES) -> BruteCases:
    """小さい入力を種 1..n で作り、愚直解の答えを求める。愚直解が止まった入力は使わない。"""
    if not brute_code.strip() or not small_generator.strip():
        return BruteCases([], "愚直解か小さい入力を作るコードがありません")
    cases = []
    for seed in range(1, n + 1):
        gen = run_python(small_generator, "", GENERATOR_TIME_LIMIT_SEC, args=(str(seed),))
        if gen.status != "ok" or not gen.stdout.strip():
            return BruteCases(cases, f"小さい入力を作るコードが失敗しました（種 {seed}）: {gen.stderr[-300:]}")
        expected = run_python(brute_code, gen.stdout, SMALL_CASE_TIME_LIMIT_SEC)
        if expected.status == "ok":
            cases.append((gen.stdout, expected.stdout))
    if len(cases) < n // 2:
        return BruteCases(cases, f"愚直解が小さい入力の半分以上で止まりました（{n} 件中 {n - len(cases)} 件）")
    return BruteCases(cases)


def compare_with_brute(code: str, brute: BruteCases) -> BruteCheck:
    """用意した小さい入力でコードを実行し、愚直解の答えと比べる。最初に違った入力で止める。"""
    if brute.note or not brute.cases:
        return BruteCheck(BRUTE_SKIPPED, note=brute.note or "比べる入力がありません")
    for i, (stdin, expected) in enumerate(brute.cases, 1):
        result = _judge(i, stdin, expected, run_python(code, stdin, SMALL_CASE_TIME_LIMIT_SEC))
        if result.status != "AC":
            return BruteCheck(BRUTE_MISMATCH, total=i, matched=i - 1, failure=result)
    return BruteCheck(BRUTE_OK, total=len(brute.cases), matched=len(brute.cases))


# ---------------------------------------------------------------------------
# 最大サイズの入力
# ---------------------------------------------------------------------------

STRESS_OK = "ok"
STRESS_TLE = "TLE"
STRESS_SKIPPED = "skipped"


@dataclass(frozen=True)
class StressCheck:
    status: str          # STRESS_OK / STRESS_TLE / STRESS_SKIPPED
    interpreter: str     # "PyPy" / "CPython"
    time_limit: float    # 実際に使った制限時間（CPython なら緩めた値）
    seconds: float | None = None   # 実行できた入力のうち一番遅かった時間
    input_bytes: int = 0
    inputs: int = 0      # 実行できた入力の数
    note: str = ""       # 飛ばした入力・飛ばした理由


def find_pypy() -> str | None:
    """PyPy の実行ファイル。.env / 環境変数の PYPY_PATH か、PATH 上の pypy3 / pypy を探す。"""
    for path in (settings.pypy_path, os.environ.get("PYPY_PATH")):
        if path and Path(path).is_file():
            return path
    return shutil.which("pypy3") or shutil.which("pypy")


def stress_interpreter(problem_time_limit: float) -> tuple[list[str], str, float]:
    """(起動コマンド, 名前, 制限時間)。PyPy がなければ CPython で制限時間を緩める。"""
    pypy = find_pypy()
    if pypy:
        return [pypy, "-I"], "PyPy", problem_time_limit
    return list(PYTHON), "CPython", problem_time_limit * CPYTHON_TIME_FACTOR


def _generate_to_file(generator: str, input_path: Path, cwd: str) -> str:
    """generator の出力をファイルに書く（メモリに溜めない）。失敗なら理由、成功なら空文字。"""
    gen_path = Path(cwd) / "gen.py"
    gen_path.write_text(generator, encoding="utf-8")
    with open(input_path, "wb") as out:
        try:
            gen = subprocess.run(
                [*PYTHON, str(gen_path)], stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.PIPE,
                timeout=GENERATOR_TIME_LIMIT_SEC, cwd=cwd,
            )
        except subprocess.TimeoutExpired:
            return f"入力を作るコードが {GENERATOR_TIME_LIMIT_SEC:g} 秒以内に終わりませんでした"
    size = input_path.stat().st_size
    if gen.returncode != 0:
        return f"入力を作るコードがエラーで止まりました: {gen.stderr.decode('utf-8', 'replace')[-300:]}"
    if size == 0:
        return "入力を作るコードの出力が空でした"
    if size > MAX_INPUT_BYTES:
        return f"作った入力が大きすぎます（{size / 1024 / 1024:.0f} MB）"
    return ""


def check_generator(generator: str) -> str:
    """最大サイズの入力を作るコードが使えるか。使えなければ理由を返す。"""
    with tempfile.TemporaryDirectory() as tmp:
        return _generate_to_file(generator, Path(tmp) / "input.txt", tmp)


def run_stress(
    code: str, generators: list[str] | str, problem_time_limit: float = DEFAULT_TIME_LIMIT_SEC
) -> StressCheck:
    """各 generator で最大サイズの入力を作り、コードがどれも制限時間内に終わるかを測る。

    generator が失敗した、またはコードがエラーで止まった（入力が形式どおりでない可能性がある）入力は
    飛ばす。1 つも実行できなければ STRESS_SKIPPED、1 つでも時間切れなら STRESS_TLE。
    """
    if isinstance(generators, str):
        generators = [generators]
    command, name, limit = stress_interpreter(problem_time_limit)
    notes: list[str] = []
    slowest: float | None = None
    size = ran = 0
    for k, generator in enumerate(g for g in generators if g.strip()):
        with tempfile.TemporaryDirectory() as tmp:
            input_path, main_path = Path(tmp) / "input.txt", Path(tmp) / "main.py"
            error = _generate_to_file(generator, input_path, tmp)
            if error:
                notes.append(f"入力 {k + 1}: {error}")
                continue
            main_path.write_text(code, encoding="utf-8")
            with open(input_path, "rb") as stdin:
                started = time.perf_counter()
                try:
                    proc = subprocess.run(
                        [*command, str(main_path)], stdin=stdin, stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE, timeout=limit, cwd=tmp,
                    )
                except subprocess.TimeoutExpired:
                    return StressCheck(STRESS_TLE, name, limit, input_bytes=input_path.stat().st_size,
                                       inputs=ran + 1, note=f"入力 {k + 1} で時間切れ")
                seconds = time.perf_counter() - started
            if proc.returncode != 0:
                err = proc.stderr.decode("utf-8", "replace")[-300:]
                notes.append(f"入力 {k + 1}: エラーで止まりました（入力が形式どおりでない可能性があります）: {err}")
                continue
            ran += 1
            if slowest is None or seconds > slowest:
                slowest, size = seconds, input_path.stat().st_size
    if ran == 0:
        return StressCheck(STRESS_SKIPPED, name, limit, note=" / ".join(notes) or "最大サイズの入力を作るコードがありません")
    return StressCheck(STRESS_OK, name, limit, seconds=slowest, input_bytes=size, inputs=ran, note=" / ".join(notes))


# ---------------------------------------------------------------------------
# 確認用コードの保存
# ---------------------------------------------------------------------------

@dataclass
class ProblemCheckers:
    """問題ごとの確認用コード。空のものは次の LLM 呼び出しで（同じ呼び出しの中で）頼む。"""

    brute_code: str = ""
    small_generator: str = ""
    max_generators: list[str] = field(default_factory=list)

    @property
    def has_brute(self) -> bool:
        return bool(self.brute_code and self.small_generator)


class CheckerStore(Protocol):
    def load(self, problem_id: str) -> ProblemCheckers: ...
    def save(self, problem_id: str, checkers: ProblemCheckers) -> None: ...


class MemoryCheckerStore:
    """保存しない（その場限り）。テストと、保存先を渡さないときに使う。"""

    def __init__(self):
        self.data: dict[str, ProblemCheckers] = {}

    def load(self, problem_id: str) -> ProblemCheckers:
        c = self.data.get(problem_id)
        return ProblemCheckers(c.brute_code, c.small_generator, list(c.max_generators)) if c else ProblemCheckers()

    def save(self, problem_id: str, checkers: ProblemCheckers) -> None:
        self.data[problem_id] = ProblemCheckers(checkers.brute_code, checkers.small_generator, list(checkers.max_generators))


class FileCheckerStore:
    """{base_dir}/{problem_id}/checkers.json に保存する。"""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)

    def _path(self, problem_id: str) -> Path:
        return self.base_dir / problem_id / "checkers.json"

    def load(self, problem_id: str) -> ProblemCheckers:
        path = self._path(problem_id)
        if not path.exists():
            return ProblemCheckers()
        data = json.loads(path.read_text(encoding="utf-8"))
        return ProblemCheckers(
            brute_code=data.get("brute_code", ""),
            small_generator=data.get("small_generator", ""),
            max_generators=list(data.get("max_generators", [])),
        )

    def save(self, problem_id: str, checkers: ProblemCheckers) -> None:
        path = self._path(problem_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(checkers), ensure_ascii=False, indent=2), encoding="utf-8")
