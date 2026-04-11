"""Run tool selection evaluation.

Usage:
    python -m tests.eval.run_eval [--mock] [--live] [--queries Q001,Q002,...] [--all]

Options:
    --mock      Use mocked LLM responses (default, no API key required)
    --live      Use real LLM API (requires ANTHROPIC_API_KEY)
    --queries   Comma-separated list of query IDs to evaluate
    --all       Include supplementary queries (default: primary 30 only)
    --report    Print markdown report (default: summary only)
"""

import argparse
import json
import sys

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
    except ImportError:
        print("ERROR: Cannot import ChatSession. Run from project root.", file=sys.stderr)
        sys.exit(1)

    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY required for --live mode.", file=sys.stderr)
        sys.exit(1)

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

    if args.report:
        print(evaluator.generate_report(results))
    else:
        print(f"\nTool Selection Accuracy: {batch['accuracy']:.1%}")
        print(f"  Full match:    {batch['full_match']}/{batch['total']}")
        print(f"  Partial match: {batch['partial_match']}/{batch['total']}")
        print(f"  No match:      {batch['no_match']}/{batch['total']}")

        if batch["worst_queries"]:
            print(f"\nMismatches ({len(batch['worst_queries'])}):")
            for w in batch["worst_queries"][:5]:
                print(f"  {w['id']}: expected {w['expected']}, got {w['actual']}")

    # Exit with non-zero if accuracy < threshold
    if batch["accuracy"] < 0.5:
        sys.exit(1)


if __name__ == "__main__":
    main()
