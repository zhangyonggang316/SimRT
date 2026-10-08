import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from monitor_rt_soak import check_sample


class SoakSampleTests(unittest.TestCase):
    def sample(self):
        return dict(pid=123,state='RUNNING',sample_monotonic_ns=10000000000,period_ns=1000000,
            model_step_interval_min_ns=950000,model_step_interval_max_ns=1050000,
            interval_tolerance_ns=50000,model_step_interval_early_count=0,model_step_interval_late_count=0,
            deadline_misses=0,skipped_releases=0,cpu_dma_latency_active=True,spin_us=500,
            realtime_kernel=True,memory_locked=True,cpu=3)

    def test_boundaries_and_freshness(self):
        self.assertTrue(all(check_sample(self.sample(),123,11000000000).values()))
        for now in (9999999999,20000000001):
            self.assertFalse(all(check_sample(self.sample(),123,now).values()))

    def test_failure_cannot_look_like_a_pass(self):
        for field, value in [('pid',124),('state','STOPPED'),('cpu',1),
            ('model_step_interval_min_ns',949999),('model_step_interval_max_ns',1050001),
            ('model_step_interval_late_count',1),('model_step_interval_early_count',1),
            ('skipped_releases',1),('deadline_misses',1),('cpu_dma_latency_active',False)]:
            with self.subTest(field=field):
                sample = self.sample()
                sample[field] = value
                self.assertFalse(all(check_sample(sample,123,11000000000).values()))
        self.assertFalse(all(check_sample({},123,11000000000).values()))


if __name__ == '__main__':
    unittest.main()
