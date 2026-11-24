# Academic Assistant development workflow

Use the existing checkout for this task. Read [PROJECT_PLAN.md](PROJECT_PLAN.md) before planning a feature. Follow any scoped repository instructions when editing files.

## Orchestrator

The primary agent orchestrates. Use the repository's `developer` and `reviewer` profiles when Codex exposes custom roles. Otherwise, pass the corresponding instructions below to separate built-in subagents.

- Turn the request into independently verifiable tasks. Give each task a scope, acceptance criteria, dependencies, expected checks, and an owner.
- Keep a task ledger in the working plan with status, evidence, dependencies, and open issues. Update it after implementation and review.
- When separate agents are available, assign implementation to a developer and review to a distinct agent that did not implement the change. Give parallel developers disjoint write scopes. Integrate their changes before reviewing the combined diff.
- Record the baseline and the exact revision or working-tree diff under review. Include new files and any applicable generated artifacts. Changes to the reviewed code require review of the updated diff.

## Developer

- Implement the assigned scope, preserve unrelated changes, and document decisions with consequences for callers or maintainers.
- Add tests for the acceptance criteria and relevant regressions. Run the tests, debug failures, and retry recoverable steps. Report commands, results, and any checks that could not run.
- Hand off the baseline, changed paths, test evidence, implementation decisions, and known limitations. Apply fixes in response to review and rerun affected checks.

## Independent reviewer

- Inspect the actual diff, relevant surrounding code, tests, and acceptance criteria. Check correctness, architecture, security, and test coverage. Flag missing requirements and claims that the code or observed checks do not support.
- Keep implementation files read-only. Run targeted checks when practical. Report findings in severity order with a file and line, observed behavior, expected behavior, and a reproducible command or concrete triggering input. State the review scope and any checks that could not run. Explicitly report when there are no findings.
- The orchestrator may report independent review only when a separate reviewer actually inspected the relevant changes. A self-review, test run, or reviewer assignment alone does not count.

## Feedback and approval

- Use up to three implementation/review cycles per requested change, including the initial pass. Return actionable findings to the developer, rerun affected checks, and send the revised diff back for independent review.
- At the limit, escalate unresolved findings with their impact, evidence, and the decision needed. Mark the work pending if review or necessary verification is unavailable.
- Obtain human approval before deploying, accessing sensitive accounts, or making irreversible changes. Continue unrelated, reversible work while approval is pending.
- If subagents are unavailable, prepare the branch and PR description with acceptance criteria, baseline, checks, and known risks. Use a GitHub pull request when authorized and request a reviewer who did not implement the changes. Apply fixes in the same PR and request re-review of the latest diff. Without GitHub access or a reviewer, provide a local diff and PR-ready handoff and mark independent review pending.

## Final report

List the completed work, tests actually run and their outcomes, independent reviewer and reviewed scope, findings and dispositions, outstanding risks or blockers, and decisions requiring human input. Distinguish pending, skipped, failed, and passing checks.
