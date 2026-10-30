import copy
import tempfile
import unittest
from pathlib import Path
from worker import Recorder


def bundle(contract='KXBTC15M-test', stamp=10000, brti=101):
    return {'ready': True, 'errors': [], 'status': 'PAPER_ANALYSIS_WITH_FRESHNESS_OVERRIDE',
            'market': {'snapshot': {'contract': contract, 'timestamp_ms': stamp,
            'brti': brti, 'target': 100, 'yes_bid': .5, 'yes_ask': .51,
            'no_bid': .49, 'no_ask': .5}},
            'charts': {tf: {'bars': [{}, {}, {}]} for tf in ('M1','M5','M15')}}


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'test.sqlite'
        self.r = Recorder(self.path)

    def tearDown(self):
        self.r.db.close()
        self.tmp.cleanup()

    def test_rejection_no_mutation(self):
        for mutate in (lambda x: x.update(ready=False),
                       lambda x: x['market']['snapshot'].update(yes_ask=.1),
                       lambda x: x['market']['snapshot'].update(brti=float('nan')),
                       lambda x: x['market']['snapshot'].update(timestamp_ms=0)):
            b=bundle(); mutate(b)
            with self.assertRaises(ValueError): self.r.accept(b,10001)
        self.assertEqual(self.r.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0],0)

    def test_restart_duplicate_and_cushion(self):
        self.assertEqual(self.r.accept(bundle(),10001),1)
        self.r.db.close(); self.r=Recorder(self.path)
        self.assertEqual(self.r.accept(bundle(),10002),0)
        self.r.accept(bundle(stamp=11000,brti=103),11001)
        self.assertEqual(self.r.db.execute('SELECT cushion_change FROM observations ORDER BY id DESC LIMIT 1').fetchone()[0],2)

    def test_rollover_does_not_compare_cushions(self):
        self.r.accept(bundle(),10001)
        self.r.accept(bundle(contract='KXBTC15M-next',stamp=11000),11001)
        self.assertIsNone(self.r.db.execute('SELECT cushion_change FROM observations ORDER BY id DESC LIMIT 1').fetchone()[0])

    def test_out_of_order(self):
        self.r.accept(bundle(),10001)
        with self.assertRaises(ValueError): self.r.accept(bundle(stamp=9999),10002)


if __name__=='__main__': unittest.main()
