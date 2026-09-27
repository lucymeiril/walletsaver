# Pinned verification delegation

2026-09-27 pass148 pilot: Sol integrator applied 30 reviewed titles (27 assigned, 3 held) and found 3 ham-shelf conflicts before certification. Parent supplied only the rejection decision; the integrator executed guarded revisions. Luna high then ran one pinned certification attempt successfully: +27 products/listings, +53 observations, unresolved 1751. Main did not run the full test suite or poll its process. Runner focused tests and the changed baking module were executed by the worker. This demonstrates execution handoff, not a measured token/quota saving.

After source edits are complete, use `py tools/catalog_executor.py --create-plan <new-run-id>` to write a new ignored plan with the current baseline and full code hashes. Then use `py tools/catalog_executor.py <plan-path>` for one certification attempt. The plan is JSON with exactly these fields:

```json
{
  "action": "certify",
  "run_id": "initial-catalog-unique-new-name",
  "baseline": ".debug-artifacts/current-certified-baseline",
  "code_sha256": {"repository/relative/file": "sha256-hex"}
}
```

`baseline` must equal `docs/catalog-state.json` at invocation. `code_sha256` must equal the full map from `catalog_harness.code_hashes(ROOT)`; the example is schematic, not a valid shortened map. The creation command writes `.debug-artifacts/catalog-verify-plans/<run_id>.json` exclusively and never starts certification. Use a fresh run ID. The runner rejects stale pins and existing output or log directories before starting, calls the existing harness preflight then run once, and writes a compact report under `.debug-artifacts/catalog-verify-logs/<run_id>/report.json`. Harness output remains in exclusive-create logs there. Success requires the harness's `checks-passed.json` with matching run ID, baseline and code hashes. A failed run is preserved for diagnosis; prepare a new run ID after a source fix. This runner does not checkpoint or approve any DB.

The experimental `.codex/agents/catalog_verifier.toml` profile specifies GPT-6 Luna high and a single plan-path invocation. Profile registration or OS isolation must be verified independently; the script itself is the workflow guard.

For integration, `.codex/agents/catalog_integrator.toml` specifies GPT-6 Sol low. Give it the reviewed job path and a compact parent decision. Its bounded procedure is job inspect → apply → classifier diagnostics for assigned rows in the new rules. Only the job's declared new numbered review files may be written. Revisions require an explicit parent packet, rejected leaf, number assignments and reason, then the hash-pinned `hold-draft`/`revise-path` commands. The main agent dispatches certification separately.
