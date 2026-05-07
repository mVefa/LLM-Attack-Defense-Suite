"""
Automated benchmark runner for the LLM Prompt Injection defense system.

Usage (CLI):
    python benchmark_engine.py

Usage (from Streamlit / Python):
    from benchmark_engine import load_dataset, evaluate_single, compute_metrics
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from target_bot import BlockedByDefenseError, OutputLeakError, chat

_DEFAULT_DATASET = Path(__file__).parent / "benchmark_dataset.json"


# ── Dataset loader ────────────────────────────────────────────────────────────

def load_dataset(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else _DEFAULT_DATASET
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


# ── Single-item evaluator ─────────────────────────────────────────────────────

def evaluate_single(item: dict) -> dict:
    """
    Run one dataset item through the defense pipeline and return a result dict.

    Outcome mapping
    ───────────────
    expected=UNSAFE + BLOCKED  → TP   (attack correctly stopped)
    expected=SAFE   + PASSED   → TN   (benign correctly passed)
    expected=SAFE   + BLOCKED  → FP   (benign wrongly blocked)
    expected=UNSAFE + PASSED   → FN   (attack bypassed defense)
    """
    start = time.perf_counter()
    result = {
        "id":            item["id"],
        "prompt":        item["prompt"],
        "category":      item["category"],
        "expected":      item["expected_result"],
        "system_decision": None,  # "BLOCKED" | "PASSED"
        "outcome":       None,    # "TP" | "TN" | "FP" | "FN"
        "correct":       None,
        "blocked_at":    None,
        "blocked_by":    None,
        "elapsed_s":     None,
        "error":         None,
    }

    try:
        _reply, report = chat(item["prompt"], use_defense=True)
        result["system_decision"] = "PASSED"
        result["blocked_by"] = None

    except BlockedByDefenseError as exc:
        result["system_decision"] = "BLOCKED"
        result["blocked_at"] = "input"
        result["blocked_by"] = exc.report.get("blocked_by", "unknown")

    except OutputLeakError as exc:
        result["system_decision"] = "BLOCKED"
        result["blocked_at"] = "output"
        result["blocked_by"] = "output_filter"

    except Exception as exc:
        result["system_decision"] = "ERROR"
        result["error"] = str(exc)

    result["elapsed_s"] = round(time.perf_counter() - start, 2)

    # Classify outcome
    expected = item["expected_result"]   # "SAFE" | "UNSAFE"
    decision = result["system_decision"] # "BLOCKED" | "PASSED" | "ERROR"

    if decision == "ERROR":
        result["outcome"] = "ERROR"
        result["correct"] = False
    elif expected == "UNSAFE" and decision == "BLOCKED":
        result["outcome"] = "TP"
        result["correct"] = True
    elif expected == "SAFE" and decision == "PASSED":
        result["outcome"] = "TN"
        result["correct"] = True
    elif expected == "SAFE" and decision == "BLOCKED":
        result["outcome"] = "FP"
        result["correct"] = False
    else:  # expected UNSAFE + PASSED
        result["outcome"] = "FN"
        result["correct"] = False

    return result


# ── Metrics calculator ────────────────────────────────────────────────────────

def compute_metrics(results: list[dict]) -> dict:
    tp = sum(1 for r in results if r["outcome"] == "TP")
    tn = sum(1 for r in results if r["outcome"] == "TN")
    fp = sum(1 for r in results if r["outcome"] == "FP")
    fn = sum(1 for r in results if r["outcome"] == "FN")

    attack_count = sum(1 for r in results if r["expected"] == "UNSAFE")
    benign_count = sum(1 for r in results if r["expected"] == "SAFE")
    total = len(results)
    correct = tp + tn

    return {
        "total":               total,
        "attack_count":        attack_count,
        "benign_count":        benign_count,
        "tp":                  tp,
        "tn":                  tn,
        "fp":                  fp,
        "fn":                  fn,
        "correct":             correct,
        "accuracy":            correct / total if total else 0.0,
        "false_positive_rate": fp / benign_count if benign_count else 0.0,
        "bypass_rate":         fn / attack_count if attack_count else 0.0,
        "detection_rate":      tp / attack_count if attack_count else 0.0,
        "total_elapsed_s":     round(sum(r["elapsed_s"] or 0 for r in results), 2),
    }


# ── Orchestrator ──────────────────────────────────────────────────────────────

def run_benchmark(
    dataset_path: str | Path | None = None,
    progress_callback: Callable[[int, int, dict], None] | None = None,
) -> dict:
    """
    Run all items and return {results, metrics}.

    progress_callback(current_index, total, last_result) is called after
    each item so callers can update a UI progress bar.
    """
    dataset = load_dataset(dataset_path)
    total = len(dataset)
    results: list[dict] = []

    for i, item in enumerate(dataset):
        r = evaluate_single(item)
        results.append(r)
        if progress_callback:
            progress_callback(i + 1, total, r)

    return {"results": results, "metrics": compute_metrics(results)}


# ── CLI entry-point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print("=" * 65)
    print("  LLM Prompt Injection – Automated Benchmark")
    print("=" * 65)

    def _progress(current: int, total: int, r: dict) -> None:
        icon = "✅" if r["correct"] else "❌"
        print(f"  [{current:02d}/{total}] {icon} {r['outcome']:3}  {r['prompt'][:55]}")

    data = run_benchmark(progress_callback=_progress)
    m = data["metrics"]

    print("\n" + "─" * 65)
    print(f"  Total prompts  : {m['total']}  (attacks={m['attack_count']}, benign={m['benign_count']})")
    print(f"  Accuracy       : {m['accuracy']:.1%}  ({m['correct']}/{m['total']} correct)")
    print(f"  Detection Rate : {m['detection_rate']:.1%}  ({m['tp']}/{m['attack_count']} attacks blocked)")
    print(f"  False Pos. Rate: {m['false_positive_rate']:.1%}  ({m['fp']}/{m['benign_count']} benign wrongly blocked)")
    print(f"  Bypass Rate    : {m['bypass_rate']:.1%}  ({m['fn']}/{m['attack_count']} attacks got through)")
    print(f"  Total time     : {m['total_elapsed_s']}s")
    print("─" * 65)
