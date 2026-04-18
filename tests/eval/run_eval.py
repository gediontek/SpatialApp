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
import sys
from datetime import datetime, timezone

from tests.eval.reference_queries import REFERENCE_QUERIES, ALL_QUERIES, get_tool_coverage
from tests.eval.evaluator import ToolSelectionEvaluator
from tests.eval.mock_responses import get_mock_tools, get_mock_params


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

    args = parser.parse_args()

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

    # Exit with non-zero if accuracy < threshold
    if batch["accuracy"] < 0.5:
        sys.exit(1)


if __name__ == "__main__":
    main()
