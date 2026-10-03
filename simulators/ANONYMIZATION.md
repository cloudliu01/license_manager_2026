# Simulator sample-data anonymization

Capture-derived identifiers in the simulator's source comments, documentation
and test fixtures use consistent synthetic aliases. This is static fixture
anonymization, **not** runtime masking of arbitrary client traffic.

## Alias conventions

| Category | Synthetic examples | Preserved structure |
|---|---|---|
| Short feature | `QZ`, `QY` | Two uppercase letters |
| Feature family | `DEMO_AX`, `DEMO_SIM` | Uppercase family, underscore, uppercase suffix |
| Other feature family | `SYN_READER`, `SYN_STAMP` | Uppercase family, underscore, uppercase suffix |
| Numeric feature | `222` | Three digits; unrelated numeric ports are unchanged |
| Vendor daemon | `vendmock`, `vendyy` | Lowercase ASCII, original field byte length |
| Host | `qa-ls`, `qa-srv47`, `qa-gui32`, `qa-jobmaster` | Lowercase segments, hyphen, same digit widths |
| FQDN | `qa-srv47.placeholder.invalid` | Valid lowercase DNS labels, unchanged total byte length |
| User | `userx`, `sample.user`, `guest.accountx`, `jobadmin` | Lowercase letters, same lengths and dot positions |
| Private test IP | `10.20.64.75`, `10.20.64.212`, `10.20.86.79`, `10.32.9.217` | IPv4 syntax, private address space, same octet digit widths |

The `.invalid` top-level domain is reserved and must not resolve to a real
organization. Its label boundaries deliberately differ from the original
organization domain, while the entire FQDN retains its original byte length.

## Compatibility rules

- Use one alias consistently in payloads, expected decoded values, SQL queries,
  correlations and comments. Distinct identifiers must not collapse to one alias.
- Retain byte lengths in binary fixture strings so declared lengths, greeting
  slots and binary-tail offsets remain unchanged.
- Do not alter protocol keywords, opcodes, regexes, frame layouts, delimiters,
  ports, epochs, checkout IDs or signature/handle syntax as part of identifier
  replacement.
- Keep existing generic synthetic data such as `alpha`, `beta`, `gamma`,
  `vendorA`, `vend`, `node0`, `alice`, `bob` and `client.example.com`.
- Keep operational addresses such as `127.0.0.1` and `0.0.0.0`, and existing
  minimal synthetic packet-builder addresses.
- The shape-only native handshake uses the eight-byte `DAEMON_NAME` alias
  `vendmock`; clients use that shared constant rather than a captured vendor name.

## Scope and limitations

Only `simulators/` was sanitized. Historical Git content, captures, screenshots,
logs, databases and other directories are not rewritten. Runtime monitor output
still contains actual wire identities and raw bytes; this change must not be
used as a production data-redaction or irreversible anonymization guarantee.
PIDs, timestamps, handles and signature-like fixture values retain their test
semantics and are outside this identifier-replacement scope.

Validate with the existing suite, including real loopback capture where allowed:

```bash
RUN_RAW_CAPTURE_TEST=1 PYTHONPATH=simulators/src python -m pytest simulators/tests -ra
```

Post-change verification: **113 passed in 22.43s**, including all five real
AF_PACKET capture integration tests. Modified files retained their byte lengths
and line counts; Python AST structure outside string/byte literals was unchanged.
`git diff --check -- simulators` also passed.
