"""Verify the bounded local performance benchmark report."""

from __future__ import annotations

import unittest

from mediassist_healthcare.performance_benchmark import (
    _percentile,
    run_benchmarks,
)


class PerformanceBenchmarkTests(unittest.TestCase):
    def test_percentile_uses_nearest_rank(self) -> None:
        self.assertEqual(_percentile([4.0, 1.0, 3.0, 2.0], 0.95), 4.0)

    def test_local_report_contains_measured_safe_operations(self) -> None:
        report = run_benchmarks(iterations=1, include_aiven=False)

        self.assertIn("service-level targets", report["note"])
        measurements = report["measurements"]
        self.assertEqual(len(measurements), 3)
        for measurement in measurements:
            self.assertEqual(measurement["iterations"], 1)
            self.assertGreaterEqual(measurement["p50_ms"], 0)
            self.assertGreaterEqual(measurement["p95_ms"], 0)
            self.assertGreaterEqual(measurement["throughput_per_second"], 0)
        self.assertNotIn("Aiven", str(measurements))


if __name__ == "__main__":
    unittest.main()
