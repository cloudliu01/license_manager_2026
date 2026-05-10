# lmstat Full Real Format Design

## Goal

Generated workload snapshots should look like the full real FlexNet-style examples in `tests/sample.decrypted.txt`, while keeping simulator feature names such as `alpha`, `beta`, and `gamma`.

## Scope

Update the simulated `lmstat` raw stdout format and tests. Do not implement the real FlexNet wire protocol or rename generated workload features.

## Output Format

The renderer keeps the full real-output section layout:

- `lmstat - Copyright ...`
- `Flexible License Manager status on ...`
- `License server status: <port>@<server>`
- indented `License file(s) on <server>: /path/to/license.dat:`
- `<server>: license server UP (MASTER) v11.19.5`
- `Vendor daemon status (on <server>):`
- indented daemon status line
- `Feature usage info:`
- one `Users of <feature>:` block per feature
- quoted feature metadata, `floating license`, and indented checkout rows when details are requested

## Parsing And Storage

`parse_lmstat_output` should continue extracting feature usage and checkout rows from the full format. `samples.raw_output` stores the exact stdout captured from `lmstat` for each sample.

## Verification

Add or tighten tests for renderer format, parser coverage, and workload SQLite raw-output storage. Run `pytest -q` and `ruff check .` after changes.
