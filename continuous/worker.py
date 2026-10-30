"""Continuous Pluto observation worker. No order or accounting capabilities."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import sqlite3
import threading
import time
from urllib.request import Request, urlopen
from urllib.parse import urlparse


def validate(bundle, now):
    if bundle.get('ready') is not True or bundle.get('errors'):
        raise ValueError('BUNDLE_NOT_READY')
    snap = bundle['market']['snapshot']
    stamp = snap['timestamp_ms']
    if not 0 <= now - stamp <= 5000:
        raise ValueError('STALE_OR_FUTURE_SNAPSHOT')
    if not snap['contract'].startswith('KXBTC15M-'):
        raise ValueError('WRONG_SERIES')
    for key in ('brti', 'target', 'yes_bid', 'yes_ask', 'no_bid', 'no_ask'):
        value = snap[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('INVALID_NUMBER')
    for side in ('yes', 'no'):
        if not 0 <= snap[side+'_bid'] <= snap[side+'_ask'] <= 1:
            raise ValueError('INVALID_BOOK')
    if not snap['target'] > 0 or not snap['brti'] > 0:
        raise ValueError('INVALID_PRICE')
    # Collector readiness may use a paper-only freshness override. Preserve it;
    # never relabel it verified or use it to authorize unattended execution.
    for tf in ('M1', 'M5', 'M15'):
        if len(bundle['charts'][tf]['bars']) < 3:
            raise ValueError('INSUFFICIENT_BARS')
    return snap


class Recorder:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY, received_ms INTEGER NOT NULL,
            fingerprint TEXT UNIQUE NOT NULL, contract TEXT NOT NULL,
            source_ms INTEGER NOT NULL, cushion REAL NOT NULL,
            cushion_change REAL, status TEXT NOT NULL, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS faults (
            id INTEGER PRIMARY KEY, received_ms INTEGER NOT NULL, code TEXT NOT NULL);
        ''')

    def accept(self, bundle, now):
        snap = validate(bundle, now)
        raw = json.dumps(bundle, sort_keys=True, separators=(',', ':'), allow_nan=False)
        fingerprint = hashlib.sha256(raw.encode()).hexdigest()
        cushion = snap['brti'] - snap['target']
        previous = self.db.execute(
            'SELECT cushion, source_ms FROM observations WHERE contract=? ORDER BY id DESC LIMIT 1',
            (snap['contract'],)).fetchone()
        if previous and snap['timestamp_ms'] < previous[1]:
            raise ValueError('OUT_OF_ORDER_SNAPSHOT')
        with self.db:
            cur = self.db.execute('''INSERT OR IGNORE INTO observations
              (received_ms,fingerprint,contract,source_ms,cushion,cushion_change,status,payload)
              VALUES (?,?,?,?,?,?,?,?)''', (now, fingerprint, snap['contract'],
              snap['timestamp_ms'], cushion, cushion-previous[0] if previous else None,
              bundle.get('status', 'UNSPECIFIED'), raw))
        return cur.rowcount

    def fault(self, code):
        with self.db:
            self.db.execute('INSERT INTO faults(received_ms,code) VALUES (?,?)',
                            (int(time.time()*1000), code))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args()
    root = Path(os.environ.get('PLUTO_DATA_DIR', '/data'))
    root.mkdir(parents=True, exist_ok=True)
    # Prevent competing workers from producing interleaved history on one volume.
    import fcntl
    lock = (root / 'worker.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    recorder = Recorder(root / 'pluto-observations.sqlite3')
    if args.status:
        print(json.dumps({'mode': 'observe-only', 'observations': recorder.db.execute(
            'SELECT COUNT(*) FROM observations').fetchone()[0], 'latest': recorder.db.execute(
            'SELECT received_ms,contract,cushion,status FROM observations ORDER BY id DESC LIMIT 1'
            ).fetchone()}))
        return
    url = os.environ['PLUTO_ORBIT_URL']
    if urlparse(url).scheme != 'https' or urlparse(url).username or urlparse(url).password:
        raise ValueError('HTTPS_ENDPOINT_REQUIRED')
    token = os.environ.get('PLUTO_COLLECTOR_TOKEN')
    interval = float(os.environ.get('PLUTO_POLL_SECONDS', '5'))
    if not math.isfinite(interval) or interval < 1:
        raise ValueError('INVALID_POLL_INTERVAL')
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    while not stopped.is_set():
        try:
            req = Request(url, headers={'Authorization': 'Bearer '+token} if token else {})
            with urlopen(req, timeout=10) as response:
                payload = response.read(16_000_001)
                if len(payload) > 16_000_000:
                    raise ValueError('RESPONSE_TOO_LARGE')
                bundle = json.loads(payload)
            recorder.accept(bundle, int(time.time()*1000))
            print(json.dumps({'state': 'recorded', 'mode': 'observe-only'}), flush=True)
        except Exception as exc:
            # Never print network exceptions: they can expose endpoint credentials.
            code = str(exc) if type(exc) is ValueError and str(exc).isupper() else type(exc).__name__
            recorder.fault(code)
            print(json.dumps({'state': 'paused-data', 'code': code}), flush=True)
        if args.once:
            break
        stopped.wait(interval)
    recorder.db.close()


if __name__ == '__main__':
    main()
