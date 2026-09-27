#!/usr/bin/env python3
"""
Pluto BTC Live — minimal read-only bridge for Kalshi KXBTC15M.
Public endpoints only. No auth, no trading, no keys.
"""

from datetime import datetime, timezone
from flask import Flask, jsonify
import requests

app = Flask(__name__)

KALSHI_BASE = "https://external-api.kalshi.com/trade-api/v2"
SERIES = "KXBTC15M"


def fetch_active_market():
    """Return the currently active KXBTC15M market or None."""
    now = datetime.now(timezone.utc)
    resp = requests.get(
        f"{KALSHI_BASE}/markets",
        params={"series_ticker": SERIES, "status": "open", "limit": 20},
        timeout=10,
    )
    resp.raise_for_status()
    markets = resp.json().get("markets", [])

    for m in markets:
        open_t = datetime.fromisoformat(m["open_time"].replace("Z", "+00:00"))
        close_t = datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
        if open_t <= now < close_t:
            return m, now
    return None, now


def format_remaining(seconds: float) -> str:
    if seconds <= 0:
        return "0:00"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"


@app.route("/")
def root():
    return jsonify({"status": "Pluto BTC Live is running", "endpoint": "/market"})


@app.route("/market")
def market():
    try:
        m, now = fetch_active_market()
        if m is None:
            return jsonify({
                "error": "no_active_market",
                "message": "No currently active KXBTC15M contract found",
                "current_utc_time": now.isoformat().replace("+00:00", "Z"),
            }), 404

        close_t = datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
        remaining = (close_t - now).total_seconds()
        if remaining < 0:
            remaining = 0.0

        target = m.get("floor_strike")
        if target is not None:
            target = float(target)

        def to_float(v):
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        payload = {
            "current_utc_time": now.isoformat().replace("+00:00", "Z"),
            "market_ticker": m.get("ticker"),
            "market_status": m.get("status"),
            "open_time": m.get("open_time"),
            "close_time": m.get("close_time"),
            "time_remaining_seconds": round(remaining, 1),
            "time_remaining_formatted": format_remaining(remaining),
            "target_price": target,
            "yes_bid": to_float(m.get("yes_bid_dollars")),
            "yes_ask": to_float(m.get("yes_ask_dollars")),
            "no_bid": to_float(m.get("no_bid_dollars")),
            "no_ask": to_float(m.get("no_ask_dollars")),
            "last_price": to_float(m.get("last_price_dollars")),
        }
        return jsonify(payload)
    except requests.RequestException as e:
        return jsonify({"error": "kalshi_fetch_failed", "message": str(e)}), 502
    except Exception as e:
        return jsonify({"error": "internal", "message": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
