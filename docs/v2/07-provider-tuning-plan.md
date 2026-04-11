# Plan 7: LLM Provider Optimization

**Objective**: Ensure both Anthropic and OpenAI providers score within 5% of each other on the full 100-query eval suite by tuning tool descriptions, system prompts, and provider-specific hints.

**Scope**: ~250 lines of code, 1-2 focused days.

**Key files touched**:
- `tests/eval/run_eval.py` -- add `--provider` flag, multi-provider comparison mode
- `tests/eval/evaluator.py` -- add provider-aware reporting in `ToolSelectionEvaluator`
- `nl_gis/tools.py` -- add `provider_hints` field to `get_tool_definitions()`
- `nl_gis/llm_provider.py` -- apply provider hints in `OpenAIProvider._convert_tools()`
- `nl_gis/chat.py` -- add provider-specific system prompt sections to `SYSTEM_PROMPT`
- `config.py` -- no changes (already supports `LLM_PROVIDER`, `OPENAI_API_KEY`)

**Prerequisite**: Plan 6 (M1 + M2) must be complete. The 100-query eval suite with parameter scoring is required as the measurement instrument.

---

## Milestone 1: Baseline Provider Comparison

### Epic 1.1: Multi-Provider Eval Runner

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.1.1 | Add `--provider` flag to `run_eval.py` `main()` that accepts `anthropic`, `openai`, or `all`. When `all`, run the eval suite once per provider and output a comparison table. Default: use `Config.LLM_PROVIDER`. | `python -m tests.eval.run_eval --live --provider all` runs eval for each provider sequentially, prints per-provider accuracy. | M |
| T1.1.2 | Update `run_live_evaluation()` in `run_eval.py` to accept a `provider_name` parameter. Before creating `ChatSession`, temporarily set `Config.LLM_PROVIDER` to the requested provider and call `ChatSession()` so it initializes the correct `LLMProvider` via `_init_client()`. Restore the original after the run. | `run_live_evaluation(queries, provider_name="openai")` uses `OpenAIProvider` regardless of the env var. Session correctly calls `create_provider("openai", ...)` in `_init_client()`. | S |
| T1.1.3 | Add a `compare_providers()` function in `run_eval.py` that takes two batch results (one per provider) and returns a dict with: per-category accuracy delta, per-complexity accuracy delta, list of queries where providers disagree on tool selection. | `compare_providers(anthropic_batch, openai_batch)` returns `{"category_deltas": {"routing": -0.12, ...}, "disagreements": [{"query_id": "Q023", "anthropic_tools": [...], "openai_tools": [...]}]}`. | M |

### Epic 1.2: Comparison Report

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T1.2.1 | Add `generate_comparison_report()` to `evaluator.py` that produces a markdown report comparing two provider runs side-by-side. Include: overall accuracy per provider, per-category accuracy table with delta column, top 10 disagreement queries with both providers' tool selections. | Report has `## Provider Comparison` with a table: `| Category | Anthropic | OpenAI | Delta |`. Disagreement section shows the query text and both tool chains. | M |
| T1.2.2 | When `--provider all` is used with `--save-report`, save the comparison report to `tests/eval/reports/comparison_YYYYMMDD_HHMMSS.md`. | Comparison report saved alongside individual provider reports. | XS |

---

## Milestone 2: Provider-Specific Tool Description Tuning

### Epic 2.1: Add `provider_hints` to Tool Definitions

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T2.1.1 | Add an optional `provider_hints` dict field to tool definitions in `get_tool_definitions()` in `nl_gis/tools.py`. Structure: `"provider_hints": {"openai": {"description_suffix": "..."}, "anthropic": {"description_suffix": "..."}}`. Only add hints to tools where M1 baseline shows >10% accuracy gap between providers. | Tool defs include `provider_hints` on targeted tools. Tools without gaps have no hints (no unnecessary bloat). | M |
| T2.1.2 | Update `OpenAIProvider._convert_tools()` in `llm_provider.py` to check each tool for `provider_hints.openai.description_suffix` and append it to the tool description before sending to OpenAI. Keep the base description unchanged for Anthropic. | When provider is OpenAI, tool descriptions include the suffix. When provider is Anthropic, descriptions are unchanged. Test by inspecting the tools list passed to `client.chat.completions.create()`. | S |
| T2.1.3 | Similarly update `AnthropicProvider.create_message()` in `llm_provider.py` to apply `provider_hints.anthropic.description_suffix` if present. This handles cases where Anthropic needs clarification too. | Anthropic-specific hints applied when present. No change when absent. | XS |
| T2.1.4 | Update `GeminiProvider._convert_tools()` to also support `provider_hints.gemini.description_suffix`. Even though Gemini is not the focus of this plan, the mechanism should be provider-agnostic. | Gemini provider applies its hints if present. No hints defined yet (placeholder for future). | XS |

### Epic 2.2: Identify and Tune Problem Tools

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T2.2.1 | From the M1 comparison report, identify the top 5 tools where OpenAI selects the wrong tool most often. For each, analyze the OpenAI tool description interpretation pattern (e.g., OpenAI conflates `search_nearby` with `fetch_osm`, or misses that `closest_facility` handles "nearest N" queries). | Written analysis per tool: what OpenAI gets wrong, why, and proposed description_suffix to fix it. | S |
| T2.2.2 | Write `provider_hints.openai.description_suffix` for each of the top 5 problem tools in `tools.py`. Hints should be short (1-2 sentences) and use OpenAI-friendly phrasing (explicit parameter names, concrete examples). Example: `"IMPORTANT: Use this tool, NOT search_nearby, when the user asks for the N nearest/closest features."` for `closest_facility`. | Hints added to `get_tool_definitions()`. Each hint is under 200 characters. | S |
| T2.2.3 | Re-run `--live --provider openai` eval on the subset of queries that failed in M1. Verify that the hints improve accuracy on those specific queries without regressing others. | Targeted queries show improvement. Overall OpenAI accuracy does not drop. | S |

---

## Milestone 3: Provider-Specific System Prompt Sections

### Epic 3.1: Conditional System Prompt Assembly

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T3.1.1 | Refactor `SYSTEM_PROMPT` in `chat.py` into a base prompt and provider-specific addenda. Create a `get_system_prompt(provider_name: str) -> str` function that concatenates: (1) the base prompt (current `SYSTEM_PROMPT` content), (2) a `PROVIDER_ADDENDA[provider_name]` section if it exists. | `get_system_prompt("anthropic")` returns base + anthropic addendum. `get_system_prompt("openai")` returns base + openai addendum. Unknown providers return base only. | M |
| T3.1.2 | Write the OpenAI-specific addendum in `chat.py` as `OPENAI_ADDENDUM`. Content should address known OpenAI interpretation issues: (1) emphasize tool chaining order (OpenAI tends to parallelize when sequential is needed), (2) reinforce parameter naming conventions (OpenAI may use `location` vs `query` inconsistently), (3) add explicit "DO NOT" rules for common OpenAI misselections identified in M1. | Addendum is 10-20 lines. Each instruction addresses a measured accuracy gap from the M1 comparison. | S |
| T3.1.3 | Write the Anthropic-specific addendum in `chat.py` as `ANTHROPIC_ADDENDUM`. This may be minimal or empty if Anthropic already scores well, but the structure must exist for symmetry and future tuning. | Addendum exists (may be short). Does not regress Anthropic accuracy. | XS |
| T3.1.4 | Update `ChatSession.process_message()` (or `_build_messages()` / wherever the system prompt is passed to the LLM) to call `get_system_prompt(Config.LLM_PROVIDER)` instead of using the raw `SYSTEM_PROMPT` constant. | System prompt passed to `self.client.create_message(system=...)` is provider-aware. Verified by adding a debug log of the system prompt length per provider. | S |

---

## Milestone 4: Parity Validation (Both Providers Within 5%)

### Epic 4.1: Iterative Tuning Loop

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T4.1.1 | Run full 100-query `--live --provider all` eval after M2 and M3 changes. Compute per-category deltas. Identify remaining categories where the gap exceeds 5%. | Comparison report generated. Categories with >5% gap listed. | S |
| T4.1.2 | For each remaining >5% gap category, add targeted `provider_hints` or system prompt refinements. Iterate: tune -> measure -> tune. Maximum 3 iterations. Document what was tried and what worked. | After iteration, all categories are within 5% between providers, or documented explanation of why a specific category cannot reach parity (e.g., a tool that OpenAI's model fundamentally handles differently). | M |
| T4.1.3 | Save the final parity baseline using `--save-baseline` from Plan 6. This becomes the regression baseline for both providers. | `tests/eval/baseline.json` updated with parity results. Both providers' scores stored. | XS |

### Epic 4.2: CI Parity Check

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T4.2.1 | Add `--parity-threshold` flag to `run_eval.py` (default 0.05). When `--provider all` and `--ci` are both set, fail if any category delta exceeds the threshold. | `python -m tests.eval.run_eval --ci --provider all --parity-threshold 0.05` exits 1 if providers diverge >5% in any category. | S |
| T4.2.2 | Note: The CI parity check requires API keys for both providers, so it should be a separate optional CI job (not blocking PRs that only have one key). Add `eval-parity` job to `ci.yml` that runs only when both `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` secrets are available. | CI job conditional on secret availability. Does not block PRs when only one key is set. | S |

---

## Milestone 5: Document Findings Per Provider

### Epic 5.1: Provider Behavior Documentation

| Task | Description | Acceptance Criteria | Effort |
|------|-------------|---------------------|--------|
| T5.1.1 | Add a `PROVIDER_NOTES` dict in `nl_gis/llm_provider.py` documenting observed behavioral differences. Structure: `{"openai": {"strengths": [...], "weaknesses": [...], "tuning_applied": [...]}, "anthropic": {...}}`. This is a code-level reference, not a separate doc. | Dict exists with at least 3 entries per provider based on measured eval results. | S |
| T5.1.2 | Update `generate_comparison_report()` in `evaluator.py` to include a "Provider Behavior Notes" section that pulls from `PROVIDER_NOTES` and appends measured accuracy by query complexity tier. Format: `| Complexity | Anthropic | OpenAI |` table with accuracy percentages. | Comparison report includes per-complexity accuracy table and behavioral notes. | S |
| T5.1.3 | Add a `--provider-summary` flag to `run_eval.py` that prints a concise per-provider capability summary: best/worst category, best/worst complexity tier, overall accuracy, param accuracy. Useful for quick provider selection decisions. | `--provider-summary` outputs a 10-line summary per provider. Includes the specific accuracy numbers. | S |

---

## Dependencies

```
Plan 6 M1+M2 (100 queries + param scoring)
    |
    v
M1 (baseline comparison) ──> M2 (tool description tuning) ──> M4 (parity validation)
                         └──> M3 (system prompt tuning)   ──> M4
                                                               |
                                                               v
                                                          M5 (documentation)
```

M1 produces the data that M2 and M3 use for targeted tuning. M4 validates that M2+M3 achieved parity. M5 documents the final state.

## Risk Mitigations

- **API cost**: Each full `--live` run of 100 queries costs ~$0.50-1.00 (Claude) or ~$0.30-0.80 (OpenAI). Budget for 10-15 runs during tuning (~$10 total). Use `--queries` flag to test subsets during iteration.
- **Non-determinism**: LLM responses vary between runs. Run each provider eval 2-3 times and use the median accuracy to avoid chasing noise. Document variance per category.
- **Over-fitting to eval**: Provider hints and addenda should be general principles, not query-specific hacks. Each hint must address a pattern (e.g., "OpenAI conflates X and Y tools") not a specific query.
- **Gemini out of scope**: Gemini provider exists in `llm_provider.py` but parity is only targeted for Anthropic vs OpenAI. The `provider_hints` mechanism supports Gemini for future work.
- **Provider API changes**: Model updates (e.g., GPT-4.1 -> GPT-4.5) may shift accuracy. The regression detection from Plan 6 M4 catches this automatically.
