"""Disk telemetry stays available when Windows exposes no disk counters."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from serve.telemetry import Telemetry


class DiskCounterAvailabilityTest(unittest.TestCase):
    def test_missing_counters_do_not_break_sampler_and_recovery_resets_rate(self):
        meter = object.__new__(Telemetry)
        meter.ps = Mock()
        meter._disk_prev = (1.0, 100, 200)
        meter.ps.disk_io_counters.side_effect = [
            None,
            SimpleNamespace(read_bytes=1024, write_bytes=2048),
            SimpleNamespace(read_bytes=1024 + 2**20, write_bytes=2048 + 2 * 2**20),
        ]
        self.assertEqual(meter._disk(), (None, None))
        with patch("serve.telemetry.time.time", side_effect=[10.0, 11.0]):
            self.assertEqual(meter._disk(), (None, None))
            self.assertEqual(meter._disk(), (1.0, 2.0))


if __name__ == "__main__":
    unittest.main()
