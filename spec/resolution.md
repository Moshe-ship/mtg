# Resolution semantics

MTG defines three modes for how violations affect tool-call flow. v0.1.0 ships `advisory` only.

## `advisory` (v0.1.0 ships this)

- All violations are recorded on the receipt.
- Tool call proceeds unchanged.
- Downstream consumers (ToolProof, scorecards, analytics) decide what to do with the violation log.
- `surface` is always authoritative — the `analysis` block is metadata.

Use this mode when:
- Measuring baseline violation rates on real agents.
- Producing diagnostic reports.
- Integrating MTG into an existing pipeline without altering behavior.

## `reconciled` (defined, not shipped in v0.1.0)

- High-severity pre-call violations pause the call.
- The agent is re-prompted with the violation detail appended as a hint.
- If the second attempt also violates, the call proceeds in advisory mode with both attempts logged.
- Post-call violations trigger a response rewrite attempt (agent decides whether to accept the rewrite).

In v0.1.0 the reference validator raises `NotImplementedError("reconciled mode not shipped in v0.1.0; see spec/resolution.md")` with a link back to this doc.

## `enforced` (defined, not shipped in v0.1.0)

- Any high-severity violation rejects the call outright.
- Medium-severity violations reject only if `dialect_enforcement: strict`.
- Receipts carry `outcome: "fail"`.

In v0.1.0 the reference validator raises `NotImplementedError("enforced mode not shipped in v0.1.0; see spec/resolution.md")`.

## Why advisory-only for v0.1.0

Enforcement policy requires confidence in the signal. Dialect classifiers and morphological backends have real error rates (CAMeL Tools disagrees with Farasa on 15–25% of dialectal inputs; commodity dialect classifiers are 70–85% accurate on short tool-call inputs). Shipping enforced mode before measuring baseline violation rates means blocking real calls on noisy signal.

Advisory-only first, measure the violation distribution, then enable enforcement once the data supports it.

## Backward compatibility

The `x-mtg` extension is strictly additive. Tools without the extension behave exactly as today. Adapters that do not understand `x-mtg` are expected to ignore the field per the JSON Schema spec's rules on extension keywords.
