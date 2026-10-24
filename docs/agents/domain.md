# Domain docs

## Layout and reading rules

This repository uses a single context:

- Root `CONTEXT.md`: domain terminology.
- `docs/adr/`: architectural decisions.

Before exploring a domain area, read `CONTEXT.md` and the ADRs relevant
to that area.

If these files are absent, proceed silently. Do not suggest creating
them upfront. The `grill-with-docs` skill creates them lazily as terms
and decisions are resolved.

## Vocabulary

Use the terms defined in `CONTEXT.md` when naming concepts in issues,
proposals, hypotheses, and tests.

If a needed concept is missing, reconsider whether it belongs to the
domain or note the gap for `grill-with-docs`.

## Architectural conflicts

Explicitly flag proposals that contradict an existing ADR. Identify
the ADR and explain why reopening the decision may be warranted.
