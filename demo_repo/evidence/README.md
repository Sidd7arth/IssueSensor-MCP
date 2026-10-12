# Demo evidence fixture

`discount-bug.png` is a locally generated mock checkout screenshot for the ReproMCP Visual demo. It intentionally shows a ₹100 subtotal where a 20% discount incorrectly produces ₹120 instead of ₹80. It contains no real customer data or credentials.

Pass `evidence/discount-bug.png` to the `screenshot_path` argument of `analyze_issue` while `REPROMCP_WORKSPACE` points at `demo_repo`.
