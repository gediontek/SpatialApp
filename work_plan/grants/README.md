# grants/ — bootstrap path for applying the framework

Sibling repo: `~/Documents/projects/grants/`. Status of the framework
in that repo: **not yet applied.** This README is the procedure to
follow when ready.

## Step-by-step bootstrap

1. **Copy the framework directory.**

   ```
   cp -r SpatialApp/work_plan/framework  grants/work_plan/framework
   mkdir -p grants/work_plan/grants
   ```

2. **Run profiling ([`framework/05`](../../../cognitive-skill-agent/eval-framework/docs/05-profiling-procedure.md)).**

   - Inventory routes:
     ```
     grep -rE '@.*\.(route|api_route|post|get|put|delete)' grants/    # FastAPI / Flask
     ```
   - Inventory public functions in service / handler modules.
   - Inventory UI handlers in `grants/frontend/` (Next.js / React per
     the directory structure: `grants/frontend/`).
   - Inventory CLI commands (`pyproject.toml` scripts, alembic targets).
   - Inventory external deps:
     ```
     grep -rE 'requests\.|httpx\.|aiohttp\.|psycopg|sqlalchemy|openai\.|anthropic\.' grants/
     ```

3. **Fill in `grants/work_plan/grants/` from the templates.**

   - `01-profile.md` — P1 (the grants domain), P3 (inputs), P5 (deps,
     including any LLM, DB, document-storage), P6 (UI surfaces).
   - `02-capability-catalog.md` — every grant-management verb-on-object:
     create / score / approve / reject / disburse / report etc.
   - `03-domain-criteria.md` — Q1 sub-axes for grants. Likely list:
     - **GR-C1** Eligibility-rule correctness (boolean rule trees match spec).
     - **GR-C2** Amount arithmetic uses Decimal, not float; matches GAAP rounding.
     - **GR-C3** Date-range invariants (`apply_open <= apply_close <= award_date <= disburse_date`).
     - **GR-C4** Document-version pinning (every approval references a frozen document version).
     - **GR-C5** Audit-trail completeness (every state transition has actor, timestamp, reason).
     - **GR-C6** Regulator-mandated disclosures present in outputs.
     - **GR-C7** PII redaction in logs.
     - **GR-C8** Multi-tenant isolation (tenant A cannot read tenant B's grants).
   - `05-workflow-inventory.md` — every screen the user clicks through.

4. **Apply derivation rules
   ([`framework/06`](../../../cognitive-skill-agent/eval-framework/docs/06-test-derivation-rules.md))**
   to produce `grants/work_plan/grants/test-inventory.yaml`.

5. **Lay down `grants/tests/` directories** per
   [`framework/07-tooling.md`](../../../cognitive-skill-agent/eval-framework/docs/07-tooling.md). Tooling
   choices to confirm against the actual stack:

   - Backend: `pytest`, `httpx` for contract tests, `testcontainers`
     for Postgres.
   - Frontend: `vitest` for unit, `Playwright` for workflow.
   - LLM-driven scoring (if applicable): a fixed reference set under
     `tests/eval/`, mirroring SpatialApp's pattern.

6. **Write the execution plan**
   `grants/work_plan/grants/06-execution-plan.md` mirroring
   [`spatialapp/06-execution-plan.md`](../spatialapp/06-execution-plan.md).
   Drive Phase 1 by P0 workflow tests.

## What carries over verbatim

- All eight files in `framework/` (and the `templates/`).
- The matrix structure.
- The derivation rules.
- The governance rules.
- The CI lane structure.

## What does not carry over

- The capability catalog (different domain).
- The domain-criteria file (different Q1 sub-axes).
- Specific workflow rows.
- Tooling specifics where the stack differs (e.g., Next.js test
  runner instead of Playwright Python).

## Cross-project consistency anchors

These should look identical between SpatialApp and grants:

- Folder structure under `tests/` (`unit / api / integration /
  workflows / property / visual / security / chaos / load /
  observability`).
- Pytest markers (`golden`, `slow`, `chaos`, `visual`, `security`).
- Coverage-by-cell badge format.
- PR template line "Capability catalog updated? [Y/N]" enforced by G1.

## When to start

Start applying this to grants/ when:
1. SpatialApp's Phase 1 is complete (P0 cells covered).
2. The auto-extractor (`scripts/extract_catalog.py`) is working —
   re-using it on grants/ saves the manual draft pass.

Until then this folder is a placeholder so the framework's
transferability is not theoretical.
