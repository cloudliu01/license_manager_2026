# Quickstart: License Manager Technical Specification

## Purpose

Provide a minimal end-to-end setup for validating server, agent, and both GUIs
in a single-node environment.

## Prerequisites

- Linux host with RHEL7-compatible environment
- TimescaleDB instance reachable from the server
- Local admin access on the client host for agent operations

## Setup Overview

1. Configure the server bootstrap file with API listen address, DB connection,
   retention policy, and log paths.
2. Configure the client bootstrap file with server binding, agent identity, and
   lmgrd/lmstat paths.
3. Start the server core (headless) and verify health.
4. Start the agent and confirm the server sees the client as connected.
5. Launch the Server GUI desktop app to view fleet status.
6. Launch the Client GUI desktop app to verify local status and operations.

## Validation Steps

- Issue a control action from the Server GUI and verify audit records.
- Perform an offline local change in the Client GUI, then reconnect and verify
  server history reflects the change.
- Confirm idempotent behavior by re-sending a control request ID and receiving
  the same outcome.

## Troubleshooting

- If the agent rejects commands, confirm the server_id binding matches.
- If sync fails, confirm journal entries remain queued and retry on reconnect.
- If edits are rejected, verify lease validity and base revision.
