"""
Drawing-reader scorecard: read real SLDs and check the extraction against
known answers.

    python -m scripts.eval_drawings --cases <cases.json> --docs <drawings dir> \
        [--models claude-opus-4-8 claude-opus-5] [--only name ...] [--out <dir>]

Needs ANTHROPIC_API_KEY. Every run calls the API once per case per model and
costs real money (the estimate is printed at the end).

The cases file is kept outside this (public) repo — drawing names identify
clients. Each case:

    {"name": "mvs-msb", "file": "501-T6 SLD ....pdf", "pages": [1],
     "checks": {
        "min_runs": 1, "max_runs": 4,
        "must_include": [{"rating": 1250, "material": "AL",
                          "run_type": ["RISER", "MSB-Riser"], "earth": 50}],
        "forbid_ratings": [2000],
        "forbid_run_types": ["TX-MSB"],
        "all_material": "AL",
        "piu_includes": [60],
        "flag_contains": ["existing"]
     }}

A run matches a must_include entry when every key given matches (run_type
may be a list of allowed types). Score = checks passed / checks run.
"""

import argparse
import json
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.services import drawing_reader

# $/1M tokens (input, output) — for the cost estimate only.
PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-fable-5-1": (10.0, 50.0),
}

# Token usage per worker thread — read_drawing doesn't return it, so
# _call_claude is wrapped to record it for whichever case the thread is on.
_usage = threading.local()


def _install_usage_capture() -> None:
    original = drawing_reader._call_claude

    def wrapped(client, model, content):
        message = original(client, model, content)
        _usage.value = {"input": message.usage.input_tokens, "output": message.usage.output_tokens}
        return message

    drawing_reader._call_claude = wrapped


def _run_matches(run, want: dict) -> bool:
    if "rating" in want and run.rating_a != want["rating"]:
        return False
    if "material" in want and run.material != want["material"]:
        return False
    if "earth" in want and run.earth_pct != want["earth"]:
        return False
    if "run_type" in want:
        allowed = want["run_type"] if isinstance(want["run_type"], list) else [want["run_type"]]
        if run.run_type not in allowed:
            return False
    return True


def score(extraction, checks: dict) -> list[tuple[str, bool]]:
    runs = extraction.runs
    results = []
    if "min_runs" in checks:
        results.append((f">={checks['min_runs']} runs (got {len(runs)})", len(runs) >= checks["min_runs"]))
    if "max_runs" in checks:
        results.append((f"<={checks['max_runs']} runs (got {len(runs)})", len(runs) <= checks["max_runs"]))
    for want in checks.get("must_include", []):
        results.append((f"has run {want}", any(_run_matches(r, want) for r in runs)))
    for bad in checks.get("forbid_ratings", []):
        results.append((f"no {bad}A run", all(r.rating_a != bad for r in runs)))
    for bad in checks.get("forbid_run_types", []):
        results.append((f"no {bad} run", all(r.run_type != bad for r in runs)))
    if "all_material" in checks:
        results.append((f"all runs {checks['all_material']}",
                        bool(runs) and all(r.material == checks["all_material"] for r in runs)))
    pius = {p for r in runs for p in r.piu_ratings}
    for p in checks.get("piu_includes", []):
        results.append((f"PIU {p}A found", p in pius))
    flags = " ".join(extraction.global_flags + [f for r in runs for f in r.flags]).lower()
    for text in checks.get("flag_contains", []):
        results.append((f"flag mentions '{text}'", text.lower() in flags))
    return results


def _n_checks(checks: dict) -> int:
    return sum(len(v) if isinstance(v, list) else 1 for v in checks.values())


def run_case(case: dict, docs: Path, model: str, out: Path) -> dict:
    _usage.value = {"input": 0, "output": 0}
    work = Path(tempfile.mkdtemp())
    src = work / Path(case["file"]).name
    shutil.copy(docs / case["file"], src)
    t0 = time.time()
    try:
        extraction = drawing_reader.read_drawing(src, pages=case.get("pages"), model=model)
        error = None
    except Exception as e:  # a failed read scores 0 but doesn't stop the run
        extraction, error = None, str(e)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    elapsed = time.time() - t0

    checks = score(extraction, case["checks"]) if extraction else []
    (out / f"{case['name']}__{model}.json").write_text(json.dumps({
        "error": error, "seconds": round(elapsed),
        "checks": [{"check": c, "ok": ok} for c, ok in checks],
        "extraction": extraction.model_dump() if extraction else None,
    }, indent=2), encoding="utf-8")
    return {
        "name": case["name"], "model": model, "error": error, "seconds": elapsed,
        "passed": sum(ok for _, ok in checks),
        "total": len(checks) if checks else _n_checks(case["checks"]),
        "failed": [c for c, ok in checks if not ok],
        "usage": _usage.value,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True, type=Path)
    ap.add_argument("--docs", required=True, type=Path)
    ap.add_argument("--models", nargs="+", default=["claude-opus-4-8"])
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--out", type=Path, default=Path("eval-results"))
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if args.only:
        cases = [c for c in cases if c["name"] in args.only]
    args.out.mkdir(parents=True, exist_ok=True)
    _install_usage_capture()

    pairs = [(c, m) for m in args.models for c in cases]
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(lambda p: run_case(p[0], args.docs, p[1], args.out), pairs))

    for model in args.models:
        rows = [r for r in results if r["model"] == model]
        p, t = sum(r["passed"] for r in rows), sum(r["total"] for r in rows)
        pin, pout = PRICES.get(model, (0, 0))
        cost = sum(r["usage"]["input"] * pin + r["usage"]["output"] * pout for r in rows) / 1e6
        print(f"\n=== {model}: {p}/{t} checks ({100 * p / max(t, 1):.0f}%)  "
              f"~${cost:.2f}  avg {sum(r['seconds'] for r in rows) / len(rows):.0f}s/read")
        for r in rows:
            status = f"ERROR {r['error'][:120]}" if r["error"] else f"{r['passed']}/{r['total']}"
            print(f"  {r['name']:<14} {status:<8} {round(r['seconds']):>4}s  " + "; ".join(r["failed"]))
    (args.out / "summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
