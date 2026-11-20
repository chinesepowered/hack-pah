# CapyTeam on Firedrill

| File | What it is |
|---|---|
| `library/persona.owner.json` | The simulated user: the busy owner of Lumen Trail Supply Co. (Firedrill's synthetic company) |
| `library/eval.*.json` | `firedrill.native-evaluation.v2` rubrics with exact checks on hosted tool calls (e.g. `stripe refunds.create eq 1`) |
| `library/scenario.*.json` | Goodwill refund, owner asks twice, Stripe outage (`dependency_unavailable` at turn 0), large refund needs approval, invoice + "did it go out?" |
| `generated/` | Drills written by CapyTeam's night school from failed shifts (one scenario + evaluation per failure) |
| `setup.py` | Registers the agent (descriptor: http.v1 driver, Stripe/QuickBooks/Gmail synthetic dependencies), saves the library, saves the catalog tools, saves the world |
| `run.py` | `plan` (review + credit estimate), `go --version vN --approve` (apply, run locally, import verdicts into SingleStore + Amplitude), `import` |
| `tool_drills.py` | Runs CapyTeam's drills directly against a Firedrill tool session (synthetic Stripe/QuickBooks/Gmail via `firedrill tools access`) with exact checks read back from those services |

The agent reads its tool addresses from `STRIPE_INVOKE_URL`, `QUICKBOOKS_INVOKE_URL` and `GMAIL_INVOKE_URL`, which Firedrill's CLI sets per drill (`dependency_env` with `"url": "invoke"`). CapyTeam's practice yard serves the same `{"operation", "arguments"}` contract, so the agent code is identical in both.

Machine-specific state (descriptor with root identity, local plan with absolute paths, ids) is written to `.local/` and is gitignored.
