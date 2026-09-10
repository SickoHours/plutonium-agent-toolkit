# Adding a CLI route

1. **Register the contract first.** In the owning `routes.py`, add a `Route` with an honest
   `status="planned"`, the correct `effect`, `requires_windows` and `requires_config`. Run the tests;
   `manifest` now lists it and it answers `not_implemented`.
2. **Write the failure tests before the happy path.** Missing input, existing output, busy,
   timeout, uncertain delivery where relevant. Use synthetic fixtures under `tests/fixtures/`.
3. **Implement** in a module beside `routes.py`. Call `platform.require_windows(...)` before any
   side effect. Create the output directory with `receipts.new_output_dir`. Write a receipt on every
   exit path.
4. **Wire the parser** in `cli.py` for the arguments; keep `--json` accepted.
5. **Document**: one row in `docs/SUPPORT.md`, a paragraph in the user docs, an `Unreleased`
   changelog line.
6. **Qualify on Windows.** Run it natively, sanitize the receipt (see RECORDING-A-RECEIPT.md), link
   it from `docs/SUPPORT.md`, then flip `status` to `available`.

Never mark a route `available` without step 6.
