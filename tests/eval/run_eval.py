"""Run tool selection evaluation.

Usage:
    python -m tests.eval.run_eval [--mock] [--live] [--queries Q001,Q002,...] [--all]

Options:
    --mock      Use mocked LLM responses (default, no API key required)
    --live      Use real LLM API (reads Config.LLM_PROVIDER + matching key)
    --queries   Comma-separated list of query IDs to evaluate
    --all       Include supplementary queries (default: primary 30 only)
    --report    Print markdown report (default: summary only)
    --output    Write raw results + batch summary to a JSON file.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from tests.eval.reference_queries import REFERENCE_QUERIES, ALL_QUERIES, get_tool_coverage
from tests.eval.evaluator import ToolSelectionEvaluator
from tests.eval.mock_responses import get_mock_tools, get_mock_params


BASELINE_PATH = Path(__file__).parent / "baseline.json"
REPORTS_DIR = Path(__file__).parent / "reports"

# Default CI thresholds. Configurable via env vars.
_DEFAULT_TOOL_THRESHOLD = 0.80
_DEFAULT_PARAM_THRESHOLD = 0.70
# Regression is flagged when a per-category accuracy drops more than this.
_REGRESSION_DELTA = 0.05


def run_mock_evaluation(queries, query_ids=None):
    """Run evaluation using mock LLM responses.

    Args:
        queries: List of reference query dicts.
        query_ids: Optional list of specific query IDs to evaluate.

    Returns:
        List of result dicts suitable for ToolSelectionEvaluator.evaluate_batch.
    """
    results = []
    for q in queries:
        if query_ids and q["id"] not in query_ids:
            continue
        actual_tools = get_mock_tools(q["id"])
        actual_params = get_mock_params(q["id"])
        results.append({
            "query_id": q["id"],
            "actual_tools": actual_tools,
            "actual_params": actual_params,
        })
    return results


def run_live_evaluation(queries, query_ids=None):
    """Run evaluation using real LLM API.

    Sends each query through ChatSession and extracts tool selections.

    Args:
        queries: List of reference query dicts.
        query_ids: Optional list of specific query IDs to evaluate.

    Returns:
        List of result dicts.
    """
    try:
        from nl_gis.chat import ChatSession
        from config import Config
    except ImportError:
        print("ERROR: Cannot import ChatSession/Config. Run from project root.", file=sys.stderr)
        sys.exit(1)

    if not Config.get_llm_api_key():
        provider = Config.LLM_PROVIDER
        expected_key = {
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "openai": "OPENAI_API_KEY",
        }.get(provider.lower(), f"<key for {provider}>")
        print(
            f"ERROR: LLM_PROVIDER={provider} but {expected_key} is empty. "
            f"Set it in .env to run --live.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        f"  Provider: {Config.LLM_PROVIDER} · Model: {Config.get_llm_model()}",
        file=sys.stderr,
    )

    session = ChatSession()
    results = []

    for q in queries:
        if query_ids and q["id"] not in query_ids:
            continue

        print(f"  Evaluating {q['id']}: {q['query'][:60]}...", file=sys.stderr)

        # Collect tool calls from the chat response
        tool_calls = []
        try:
            for event in session.process_message(q["query"]):
                data = json.loads(event) if isinstance(event, str) else event
                if data.get("type") == "tool_start":
                    tool_calls.append({
                        "name": data.get("tool"),
                        "params": data.get("input", {}),
                    })
        except Exception as e:
            print(f"    ERROR on {q['id']}: {e}", file=sys.stderr)

        actual_tools = [tc["name"] for tc in tool_calls]
        actual_params = {tc["name"]: tc["params"] for tc in tool_calls}

        results.append({
            "query_id": q["id"],
            "actual_tools": actual_tools,
            "actual_params": actual_params,
        })

        # Reset session for next query (fresh context)
        session = ChatSession()

    return results


def main():
    parser = argparse.ArgumentParser(description="Run tool selection evaluation")
    parser.add_argument("--mock", action="store_true", default=True,
                        help="Use mocked LLM responses (default)")
    parser.add_argument("--live", action="store_true",
                        help="Use real LLM API")
    parser.add_argument("--queries", type=str, default=None,
                        help="Comma-separated query IDs (e.g. Q001,Q002)")
    parser.add_argument("--all", action="store_true",
                        help="Include supplementary queries")
    parser.add_argument("--report", action="store_true",
                        help="Print full markdown report")
    parser.add_argument("--output", type=str, default=None,
                        help="Write raw results + batch summary to a JSON file.")
    parser.add_argument("--rank", type=int, nargs="?", const=10, default=None,
                        metavar="N",
                        help="Print top N failure patterns ranked by frequency (default 10).")
    parser.add_argument("--ci", action="store_true",
                        help="CI mode: force mock, enforce thresholds, print a JSON one-liner.")
    parser.add_argument("--save-baseline", action="store_true",
                        help="Persist current scores to tests/eval/baseline.json.")
    parser.add_argument("--check-regression", action="store_true",
                        help="Fail if any category drops more than 5% from baseline.")
    parser.add_argument("--save-report", action="store_true",
                        help="Write a timestamped markdown report to tests/eval/reports/.")

    args = parser.parse_args()

    # CI mode implies mock + report + regression check.
    if args.ci:
        args.live = False
        args.mock = True
        args.all = True

    tool_threshold = float(os.environ.get("EVAL_TOOL_THRESHOLD", _DEFAULT_TOOL_THRESHOLD))
    param_threshold = float(os.environ.get("EVAL_PARAM_THRESHOLD", _DEFAULT_PARAM_THRESHOLD))

    # Select query set
    queries = ALL_QUERIES if args.all else REFERENCE_QUERIES
    query_ids = args.queries.split(",") if args.queries else None

    # Tool coverage check
    covered, uncovered = get_tool_coverage(queries)
    if uncovered:
        print(f"WARNING: {len(uncovered)} tools not covered: {sorted(uncovered)}", file=sys.stderr)

    # Run evaluation
    if args.live:
        print("Running LIVE evaluation...", file=sys.stderr)
        results = run_live_evaluation(queries, query_ids)
    else:
        print("Running MOCK evaluation...", file=sys.stderr)
        results = run_mock_evaluation(queries, query_ids)

    # Evaluate
    evaluator = ToolSelectionEvaluator(queries)
    batch = evaluator.evaluate_batch(results)

    # Optional JSON dump of raw results + batch summary
    if args.output:
        try:
            from config import Config
            provider = Config.LLM_PROVIDER
            model = Config.get_llm_model()
        except ImportError:
            provider = "mock"
            model = "mock"
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": "live" if args.live else "mock",
            "provider": provider if args.live else "mock",
            "model": model if args.live else "mock",
            "query_count": len(results),
            "batch": batch,
        }
        with open(args.output, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        print(f"  Results written to {args.output}", file=sys.stderr)

    if args.report:
        print(evaluator.generate_report(results))
    else:
        print(f"\nTool Selection Accuracy: {batch['accuracy']:.1%}")
        print(f"  Full match:    {batch['full_match']}/{batch['total']}")
        print(f"  Partial match: {batch['partial_match']}/{batch['total']}")
        print(f"  No match:      {batch['no_match']}/{batch['total']}")
        print(
            f"Parameter Accuracy:       {batch['param_accuracy']:.1%} "
            f"({batch['param_matched']}/{batch['param_checked_total']})"
        )
        print(
            f"Chain Accuracy (multi):   {batch['chain_accuracy']:.1%} "
            f"({batch['chain_correct']}/{batch['chain_eligible_total']})"
        )

        if batch["worst_queries"]:
            print(f"\nMismatches ({len(batch['worst_queries'])}):")
            for w in batch["worst_queries"][:5]:
                print(f"  {w['id']}: expected {w['expected']}, got {w['actual']}")

    if args.rank is not None:
        from tests.eval.failure_taxonomy import rank_failure_patterns
        patterns = rank_failure_patterns(batch["evaluations"], top_n=args.rank)
        if not patterns:
            print("\nNo failures to rank.")
        else:
            print(f"\nTop {len(patterns)} Failure Patterns:")
            for p in patterns:
                print(
                    f"\n#{p['rank']}  {p['category']}  "
                    f"[{p['count']} occurrence(s), {p['percentage']}% of failures]"
                )
                if p["confusion_pairs"]:
                    pairs = ", ".join(
                        f"{a} -> {b}" for a, b in p["confusion_pairs"][:3]
                    )
                    print(f"    Confusion: {pairs}")
                elif p["affected_tools"]:
                    print(f"    Tools: {', '.join(p['affected_tools'][:5])}")
                print(f"    Examples: {', '.join(p['example_query_ids'])}")
                print(f"    Fix target: {p['fix_target']}")

    # --- Plan 06 M5: timestamped markdown report ---
    if args.save_report:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        report_path = REPORTS_DIR / f"eval_{stamp}.md"
        with open(report_path, "w") as f:
            f.write(evaluator.generate_report(results))
        print(f"  Report written to {report_path}", file=sys.stderr)

    # --- Plan 06 M4: baseline save ---
    if args.save_baseline:
        baseline = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "accuracy": batch["accuracy"],
            "param_accuracy": batch["param_accuracy"],
            "granular_param_accuracy": batch.get("granular_param_accuracy", 0.0),
            "chain_accuracy": batch["chain_accuracy"],
            "by_category": batch["by_category"],
            "by_complexity": batch["by_complexity"],
        }
        with open(BASELINE_PATH, "w") as f:
            json.dump(baseline, f, indent=2, default=str)
        print(f"  Baseline saved to {BASELINE_PATH}", file=sys.stderr)

    # --- Plan 06 M4: regression check ---
    regression_detected = False
    if args.check_regression:
        if not BASELINE_PATH.exists():
            print(f"WARNING: no baseline at {BASELINE_PATH} — skipping regression check.", file=sys.stderr)
        else:
            with open(BASELINE_PATH) as f:
                baseline = json.load(f)
            regression_detected = _check_regression(batch, baseline)

    # --- Plan 06 M3: CI mode summary + threshold enforcement ---
    if args.ci:
        ci_summary = {
            "accuracy": batch["accuracy"],
            "param_accuracy": batch["param_accuracy"],
            "chain_accuracy": batch["chain_accuracy"],
            "tool_threshold": tool_threshold,
            "param_threshold": param_threshold,
            "pass": (
                batch["accuracy"] >= tool_threshold
                and batch["param_accuracy"] >= param_threshold
                and not regression_detected
            ),
        }
        print(json.dumps(ci_summary))
        sys.exit(0 if ci_summary["pass"] else 1)

    # Non-CI: regression failures still propagate as non-zero exit.
    if regression_detected:
        sys.exit(1)

    # Default behavior: exit non-zero if accuracy is below a sanity floor.
    if batch["accuracy"] < 0.5:
        sys.exit(1)


def _check_regression(batch: dict, baseline: dict) -> bool:
    """Return True if any headline or per-category accuracy dropped more than
    _REGRESSION_DELTA vs the saved baseline. Prints human-readable diagnostics.
    """
    any_regression = False

    for metric in ("accuracy", "param_accuracy", "chain_accuracy"):
        current = batch.get(metric, 0.0)
        prior = baseline.get(metric, 0.0)
        if prior - current > _REGRESSION_DELTA:
            any_regression = True
            print(
                f"REGRESSION: {metric} dropped from {prior:.1%} to {current:.1%} "
                f"(-{(prior - current) * 100:.1f}pp)",
                file=sys.stderr,
            )

    # Category-level check
    baseline_cats = baseline.get("by_category") or {}
    current_cats = batch.get("by_category") or {}
    for cat, prior_data in baseline_cats.items():
        prior = prior_data.get("accuracy", 0.0)
        current_data = current_cats.get(cat) or {}
        current = current_data.get("accuracy", 0.0)
        if prior - current > _REGRESSION_DELTA:
            any_regression = True
            print(
                f"REGRESSION: {cat} dropped from {prior:.1%} to {current:.1%} "
                f"(-{(prior - current) * 100:.1f}pp)",
                file=sys.stderr,
            )

    return any_regression


if __name__ == "__main__":
    main()
