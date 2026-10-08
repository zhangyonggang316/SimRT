import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from validate_rt_update import jitter_checks, placement_checks


class JitterAcceptanceTests(unittest.TestCase):
    def metrics(self):
        return dict(model_step_interval_min_ns=950000,model_step_interval_max_ns=1050000,
            interval_tolerance_ns=50000,model_step_interval_early_count=0,model_step_interval_late_count=0,
            deadline_misses=0,skipped_releases=0,cpu_dma_latency_active=True,spin_us=500)

    def test_inclusive_50us_boundaries(self):
        self.assertTrue(all(jitter_checks(self.metrics(), 500).values()))

    def test_missing_metrics_cannot_pass(self):
        self.assertFalse(any(jitter_checks({}, 500).values()))

    def test_outliers_and_incorrect_configuration_fail(self):
        for field, value in [('model_step_interval_min_ns',949999),('model_step_interval_max_ns',1050001),
            ('model_step_interval_early_count',1),('model_step_interval_late_count',1),
            ('deadline_misses',1),('skipped_releases',1),('interval_tolerance_ns',100000),
            ('spin_us',50),('cpu_dma_latency_active',False)]:
            with self.subTest(field=field):
                metrics = self.metrics()
                metrics[field] = value
                self.assertFalse(all(jitter_checks(metrics,500).values()))

    def test_isolated_model_and_housekeeping_threads_required(self):
        metrics = dict(cpu=3,priority=40)
        threads = [dict(policy='SCHED_FIFO',affinity=[3],priority=40),
                   dict(policy='SCHED_OTHER',affinity=[0,1],priority=0)]
        self.assertTrue(all(placement_checks(metrics, threads).values()))
        for invalid in ([], threads[:1], threads[1:],
                        [threads[0], dict(policy='SCHED_OTHER',affinity=[2,3])],
                        [dict(policy='SCHED_FIFO',affinity=[1],priority=40),threads[1]]):
            self.assertFalse(all(placement_checks(metrics,invalid).values()))


if __name__ == '__main__':
    unittest.main()
