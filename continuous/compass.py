"""Editable rule validation and qualification; not an execution engine.

The worker does not import this module yet. qualification != TAKE: the future
ledger must atomically accept a simulated entry before publishing TAKE.
"""
import hashlib
import json
import math

KEYS = {'schema_version', 'rules_version', 'entries_enabled', 'enabled_setups',
        'entry_cutoff_seconds', 'max_abs_cushion_usd', 'max_entry_ask',
        'max_spread', 'max_snapshot_age_ms', 'require_completed_candles'}
LIMITS = {'entry_cutoff_seconds': (0, 900), 'max_abs_cushion_usd': (0, 1e9),
          'max_entry_ask': (0, 1), 'max_spread': (0, 1),
          'max_snapshot_age_ms': (1, 5000)}
REQUIRED = ('entry_cutoff_seconds', 'max_abs_cushion_usd', 'max_entry_ask', 'max_spread')


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_settings(settings):
    if not isinstance(settings, dict) or set(settings) != KEYS:
        raise ValueError('SETTINGS_KEYS_INVALID')
    if type(settings['schema_version']) is not int or settings['schema_version'] != 1:
        raise ValueError('SCHEMA_VERSION_INVALID')
    version = settings['rules_version']
    if not isinstance(version, str) or not version.strip() or len(version) > 100:
        raise ValueError('RULES_VERSION_INVALID')
    for key in ('entries_enabled', 'require_completed_candles'):
        if type(settings[key]) is not bool:
            raise ValueError('BOOLEAN_REQUIRED:'+key)
    setups = settings['enabled_setups']
    if (not isinstance(setups, list) or not setups or
        any(not isinstance(x, str) or x not in ('continuation', 'reversal_reprice') for x in setups)
        or len(set(setups)) != len(setups)):
        raise ValueError('SETUPS_INVALID')
    for key, (low, high) in LIMITS.items():
        value = settings[key]
        if value is None and key in REQUIRED and not settings['entries_enabled']:
            continue
        if not numeric(value) or not low <= value <= high:
            raise ValueError('RANGE_INVALID:'+key)
    if settings['entries_enabled'] and settings['max_entry_ask'] <= 0:
        raise ValueError('ENTRY_ASK_MUST_BE_POSITIVE')
    return settings


def load_settings(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('DUPLICATE_SETTING:'+key)
            result[key] = value
        return result
    with open(path, encoding='utf-8') as source:
        return validate_settings(json.load(source, object_pairs_hook=unique))


def qualify(settings, facts, now_ms):
    """Consume normalized, independently verified chart evidence, not raw bars.

    Returns PASS or QUALIFIED. QUALIFIED cannot be displayed as TAKE until a
    future ledger validates stake/exit policy and commits the paper entry.
    Missing chart evidence never defaults to a positive finding.
    """
    try:
        validate_settings(settings)
    except (ValueError, TypeError):
        return {'action': 'PASS', 'reasons': ['INVALID_CONFIGURATION']}
    digest = hashlib.sha256(json.dumps(settings, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    base = {'rules_version': settings['rules_version'], 'rules_hash': digest}
    reasons = []
    if not settings['entries_enabled']:
        reasons.append('ENTRIES_DISABLED')
    if not isinstance(facts, dict):
        return dict(base, action='PASS', reasons=reasons+['INVALID_EVIDENCE'])
    stamp = facts.get('source_ms')
    if not numeric(now_ms) or not numeric(stamp) or not 0 <= now_ms-stamp <= settings['max_snapshot_age_ms']:
        reasons.append('STALE_OR_FUTURE_EVIDENCE')
    if facts.get('data_ready') is not True:
        reasons.append('DATA_NOT_READY')
    if not isinstance(facts.get('contract'), str) or not facts['contract'].startswith('KXBTC15M-'):
        reasons.append('WRONG_SERIES')
    if facts.get('direction') not in ('OVER', 'UNDER'):
        reasons.append('DIRECTION_UNESTABLISHED')
    if facts.get('setup') not in settings['enabled_setups']:
        reasons.append('SETUP_DISABLED_OR_UNKNOWN')
    for name in ('h4_assessed', 'setup_sequence_confirmed', 'invalidation_defined',
                 'reprice_room_supported', 'opposing_evidence_assessed', 'arcade_compared'):
        if facts.get(name) is not True:
            reasons.append('EVIDENCE_REQUIRED:'+name)
    if settings['require_completed_candles'] and facts.get('completed_candles') is not True:
        reasons.append('COMPLETED_CANDLES_REQUIRED')
    bid, ask = facts.get('bid'), facts.get('ask')
    book_ok = numeric(bid) and numeric(ask) and 0 <= bid <= ask <= 1 and ask > 0
    if not book_ok:
        reasons.append('INVALID_BOOK')
    remaining, cushion = facts.get('remaining_seconds'), facts.get('cushion_usd')
    if not numeric(remaining) or not 0 < remaining <= 900:
        reasons.append('INVALID_REMAINING_TIME')
    elif settings['entry_cutoff_seconds'] is not None and remaining <= settings['entry_cutoff_seconds']:
        reasons.append('ENTRY_CUTOFF')
    if not numeric(cushion):
        reasons.append('INVALID_CUSHION')
    elif settings['max_abs_cushion_usd'] is not None and abs(cushion) > settings['max_abs_cushion_usd']:
        reasons.append('CUSHION_LIMIT')
    if book_ok:
        if settings['max_entry_ask'] is not None and ask > settings['max_entry_ask']:
            reasons.append('ENTRY_PRICE_LIMIT')
        if settings['max_spread'] is not None and ask-bid > settings['max_spread']+1e-12:
            reasons.append('SPREAD_LIMIT')
    return dict(base, action='PASS' if reasons else 'QUALIFIED',
                reasons=reasons or ['SETUP_AND_ENTRY_GATES_MET'],
                source_ms=stamp, contract=facts.get('contract'))
