import json
from pathlib import Path
import unittest
from compass import validate_settings, qualify

class CompassTests(unittest.TestCase):
    def setUp(self):
        self.s = json.loads(Path(__file__).with_name('compass.settings.json').read_text())
        self.s.update(entries_enabled=True, entry_cutoff_seconds=180,
                      max_abs_cushion_usd=20, max_entry_ask=.6, max_spread=.05)
        self.f = dict(source_ms=1000, data_ready=True, contract='KXBTC15M-test',
                      direction='UNDER', setup='continuation', h4_assessed=True,
                      setup_sequence_confirmed=True, invalidation_defined=True,
                      reprice_room_supported=True, opposing_evidence_assessed=True,
                      arcade_compared=True, completed_candles=True,
                      bid=.49, ask=.5, remaining_seconds=181, cushion_usd=-20)
    def test_draft_disabled(self):
        s=json.loads(Path(__file__).with_name('compass.settings.json').read_text())
        self.assertIn('ENTRIES_DISABLED',qualify(s,self.f,1001)['reasons'])
    def test_qualifies_but_never_calls_take(self):
        result=qualify(self.s,self.f,1001)
        self.assertEqual(result['action'],'QUALIFIED')
        self.assertEqual(len(result['rules_hash']),64)
    def test_cutoff_boundary(self):
        self.f['remaining_seconds']=180
        self.assertIn('ENTRY_CUTOFF',qualify(self.s,self.f,1001)['reasons'])
    def test_invalid_config_and_no_implicit_values(self):
        for key,value in [('max_spread',float('nan')),('entry_cutoff_seconds',None),
                          ('entries_enabled','true'),('unexpected',1)]:
            s=dict(self.s);s[key]=value
            self.assertEqual(qualify(s,self.f,1001)['action'],'PASS')
    def test_missing_false_stale_future_and_invalid_book(self):
        for key,value in [('completed_candles',False),('arcade_compared',None),
                          ('source_ms',-5000),('source_ms',1002),('ask',.1),
                          ('cushion_usd',float('nan'))]:
            f=dict(self.f);f[key]=value
            self.assertEqual(qualify(self.s,f,1001)['action'],'PASS')
    def test_version_changes_hash(self):
        first=qualify(self.s,self.f,1001)['rules_hash']
        self.s['max_spread']=.04
        self.assertNotEqual(first,qualify(self.s,self.f,1001)['rules_hash'])

if __name__=='__main__': unittest.main()
