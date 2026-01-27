# Quickstart

## Goal

Build bottom-up in gated phases: simulator → client → server → database → GUIs, with tests passing before each phase transition.

## Phase Order and Gates

1. **Simulator**: Deterministic lmgrd/lmstat simulation passes its test suite.
2. **Client**: Agent and local operations pass offline/online sync tests.
3. **Server**: Aggregation and audit behavior pass API and parsing tests.
4. **Database**: Storage model and retention behavior pass data validation tests.
5. **GUIs**: Admin and local UI flows pass acceptance scenarios.

## Validation Checklist

- Fleet visibility works for up to 100 endpoints.
- Operational actions return outcomes within 2 minutes (95% of attempts).
- Offline actions sync within 10 minutes of reconnection.
- JSON export is available for usage and audit data.
