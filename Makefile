PYTHON ?= .venv/bin/python
PYTEST = $(PYTHON) -m pytest

# Pre-audit ritual. Run this after every implementation, before asking
# an external auditor for a fresh pass. Bundles three layers of evidence:
#   1. golden     — chat→tool→render workflow tests (mocked, fast, CI-safe)
#   2. harness    — adversarial security/isolation regression guards
#   3. eval-tools — LLM tool-selection accuracy (mocked corpus)
#
# `make eval` is the single command the user asked for: "after each
# implementation I want to be able to run the eval, before an external
# auditor reviews your implementation."

.PHONY: eval golden harness eval-tools eval-live test

eval: golden harness eval-tools
	@echo ""
	@echo "================================================================"
	@echo " ✅  Pre-audit eval complete: golden + harness + tool-selection"
	@echo "================================================================"

golden:
	@echo "→ Golden workflow tests (mocked Gemini/Overpass server-side + mocked SSE browser render)"
	$(PYTEST) tests/golden/ -v --tb=short

harness:
	@echo "→ Adversarial harness (security/isolation regression guards)"
	$(PYTEST) tests/harness/ -v --tb=short

eval-tools:
	@echo "→ LLM tool-selection accuracy (mocked corpus, strict --ci thresholds)"
	# Audit N21: previously this used `--mock || true`, which silently
	# swallowed regressions. --ci runs the same mocked corpus but
	# enforces tool/param/chain accuracy thresholds and exits non-zero
	# on regression, so `make eval` is now an honest pre-audit gate.
	$(PYTHON) -m tests.eval.run_eval --ci

# Optional: live mode requires GEMINI_API_KEY and a working Chromium.
# Not part of `make eval` because it costs API tokens.
eval-live:
	SPATIALAPP_GOLDEN_LIVE=1 $(PYTEST) tests/test_golden_path.py -v -m golden

# Full unit + harness suite (mirrors CI).
test:
	$(PYTEST) tests/ -v --tb=short -k "not e2e"
