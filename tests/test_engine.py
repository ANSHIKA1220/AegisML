import tempfile
import unittest
from pathlib import Path
from app.engine import Engine


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = Engine(Path(self.temp.name) / 'test.db')

    def tearDown(self):
        self.engine.db.close()
        self.temp.cleanup()

    def test_model_ranks_risk(self):
        low = self.engine.infer(100, 1, 10)
        high = self.engine.infer(9500, 29, 9000)
        self.assertLess(low['score'], .5)
        self.assertGreater(high['score'], .5)

    def test_each_fault_recovers_and_restore_works(self):
        for fault in ['error', 'latency', 'corruption']:
            with self.subTest(fault=fault):
                self.engine.inject(fault)
                self.engine.check()
                self.assertEqual(self.engine.active, 'standby')
                result = self.engine.infer(100, 1, 10)
                self.assertTrue(result['ok'])
                self.assertLess(result['score'], .5)
                with self.assertRaises(ValueError):
                    self.engine.inject('error')
                self.engine.restore()
                self.assertIsNone(self.engine.fault)
                self.assertEqual(self.engine.active, 'primary')

    def test_manual_policy_and_persistence(self):
        self.engine.auto = False
        self.engine.inject('error')
        self.engine.check()
        self.assertEqual(self.engine.active, 'primary')
        self.assertFalse(self.engine.infer(100, 1, 10)['ok'])
        before = self.engine.snapshot()
        other = Engine(Path(self.temp.name) / 'test.db')
        try:
            self.assertEqual(other.snapshot()['total'], before['total'])
            self.assertGreaterEqual(len(other.snapshot()['events']), len(before['events']))
        finally:
            other.db.close()


if __name__ == '__main__':
    unittest.main()
