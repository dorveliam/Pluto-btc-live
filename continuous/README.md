# Continuous Pluto: observation milestone

This is an independent read-only worker for the existing collector's `/orbit`
endpoint. It never places orders, changes the collector, restores bankrolls,
simulates fills, or treats a paper freshness override as verified live data.
It does not change the existing Flask bridge or its deployment command.

## Run

Python 3.12; no third-party dependencies. On Linux:

    export PLUTO_ORBIT_URL=https://YOUR-COLLECTOR/orbit
    export PLUTO_DATA_DIR=/path/to/persistent-volume
    python continuous/worker.py --once
    python continuous/worker.py

Set `PLUTO_COLLECTOR_TOKEN` privately if the collector requires bearer auth.
Never commit it. `PLUTO_POLL_SECONDS` defaults to 5. Run one replica with a
mounted persistent volume; an ordinary container directory will not survive
replacement. For Railway select `continuous/Dockerfile` with repository root
as build context, attach `/data`, and configure the variables above.

SIGTERM/SIGINT stops polling. `python continuous/worker.py --status` reports
stored record count/latest observation when the worker is stopped. No public
dashboard or unauthenticated control endpoint is introduced.

## Evidence and reliability

SQLite WAL/FULL stores full bundles, receipt and source timestamps, collector
status, computed signed cushion, and same-contract cushion changes. Contract
rollover resets the comparison. Replay of identical bundles is deduplicated;
out-of-order, stale/future snapshots, invalid quotes and ready=false are rejected.
Faults are recorded without printing endpoint/token values. Restart uses the same
database; one process holds the volume lock. Back up the database with SQLite's
backup API (not a copy of the main file while WAL is active). Set storage alerts;
retention is intentionally not automatic. A database error must be investigated.

## Validation

    cd continuous
    python -m unittest -v

Tests cover invalid readiness/quotes/numbers/time, restart persistence, identical
bundle replay, same-contract cushion changes, rollover and out-of-order snapshots.
These tests do not establish upstream candle freshness or hosting reliability.

## Next acceptance gates

1. Deploy as a separate observation service; verify health, full bundles, one
   contract rollover, and persistence through restart. No trading in this stage.
2. Translate Rotation Master setup families into explicit reviewed conditions.
   H4 location, completed M1 patterns, M5 opposition and cushion evolution must be
   represented. Numeric thresholds remain research parameters, not proven rules.
3. Add a transactional paper ledger with signal deduplication, position recovery,
   observed-bid exits, unresolved expiry handling, fees/liquidity assumptions and
   Rotation controls. Never manufacture fills from missed observations.
4. Add authenticated dashboard, alerts and same-stage Arcade comparisons. Existing
   chat balance is not imported automatically. One system, no parallel portfolios.

This milestone is runnable observation infrastructure, not an autonomous Pluto
trader. No background service is started merely by creating this code.
