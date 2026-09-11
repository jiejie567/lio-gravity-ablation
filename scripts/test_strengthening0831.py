"""Fail-closed orchestration checks; never launch an estimator."""
import json
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

import batch_fastlio_repro0831 as fast
import batch_liosam_strengthening0831 as sam
import supervise_strengthening0831 as supervisor
import collect_strengthening_audited0831 as audited_collector
import audit_liosam_tuhh0831 as tuhh_audit


class CampaignSafetyTests(unittest.TestCase):
    def test_matrix_matches_preregistered_counts(self):
        existing = sum(sam.reused_control(d, v, l, r) is not None
                       for d in sam.WEIGHTS for r in (1, 2, 3)
                       for v in sam.VARIANTS for l in sam.LEVELS)
        self.assertEqual(existing, 18)
        self.assertEqual(len(sam.WEIGHTS) * 3 * 2 * 4 - existing, 30)
        self.assertEqual(len(sam.HOLDOUTS) * 4, 8)
        self.assertEqual(len(fast.SEQUENCES) * 2, 24)

    def test_partial_fastlio_output_is_not_resumed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "results/example/A_repro0831"
            run.mkdir(parents=True)
            with patch.object(fast, "ROOT", root), patch.object(fast.subprocess, "run") as launch:
                with self.assertRaisesRegex(RuntimeError, "partial output"):
                    fast.run_one("example", "A", {})
                launch.assert_not_called()

    def test_failed_fastlio_output_is_not_resumed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "results/example/A_repro0831"
            run.mkdir(parents=True)
            (run / "campaign_completion.json").write_text(json.dumps({"returncode": 1}))
            with patch.object(fast, "ROOT", root), patch.object(fast.subprocess, "run") as launch:
                with self.assertRaisesRegex(RuntimeError, "failed existing attempt"):
                    fast.run_one("example", "A", {})
                launch.assert_not_called()

    def test_partial_liosam_output_is_not_resumed(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(sam.subprocess, "run") as launch:
                with self.assertRaisesRegex(RuntimeError, "partial run"):
                    sam.run_one(["must-not-run"], Path(directory), {})
                launch.assert_not_called()

    def test_nonfinite_csv_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.csv"
            pd.DataFrame({"t": np.arange(12), "x": [0.0] * 11 + [np.nan]}).to_csv(path, index=False)
            with self.assertRaisesRegex(RuntimeError, "truncated or non-finite"):
                fast.load_complete(path)

    def test_exact_timestamps_are_not_replaced_by_float_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.csv"
            stamps = [f"16600000{i:02d}.123456789" for i in range(12)]
            pd.DataFrame({"t": stamps, "x": np.arange(12)}).to_csv(path, index=False)
            frame = fast.load_complete(path)
            self.assertEqual(frame.attrs["timestamp_text"], stamps)

    def check_supervisor(self, returncodes, after_audit=False, after_tuhh=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "report").mkdir()
            (root / "report/summary.json").write_text("{}")
            campaign = root / "campaign"
            campaign.mkdir()
            children = [MagicMock(pid=100 + i) for i in range(len(returncodes))]
            for child, code in zip(children, returncodes):
                child.wait.return_value = code
            with patch.object(supervisor, "ROOT", root), patch.object(supervisor, "CAMPAIGN", campaign), \
                 patch.object(supervisor.os, "getppid", return_value=1), patch.object(supervisor.os, "chdir"), \
                 patch.dict(os.environ), patch.object(supervisor.sys, "argv", ["supervisor"] + (["--after-tuhh-audit"] if after_tuhh else (["--after-hall-audit"] if after_audit else []))), \
                 patch.object(supervisor.subprocess, "run"), \
                 patch.object(supervisor.subprocess, "Popen", side_effect=children) as launch:
                if any(returncodes):
                    with self.assertRaisesRegex(RuntimeError, "stage failed"):
                        supervisor.main()
                else:
                    supervisor.main()
            status = json.loads((campaign / "supervisor_status.json").read_text())
            self.assertFalse((campaign / ".supervisor.lock").exists())
            if after_tuhh:
                self.assertTrue(all(call.args[0][-1] == "--after-tuhh-audit" for call in launch.call_args_list))
            return status, launch.call_count

    def test_supervisor_runs_exactly_three_serial_stages(self):
        status, calls = self.check_supervisor([0, 0, 0])
        self.assertEqual(calls, 3)
        self.assertEqual(status["status"], "complete")
        self.assertEqual([r["script"] for r in status["stages"]], list(supervisor.STAGES))

    def test_supervisor_does_not_retry_or_continue_after_failure(self):
        status, calls = self.check_supervisor([7])
        self.assertEqual(calls, 1)
        self.assertEqual(status["status"], "stopped_for_audit")
        self.assertEqual(status["stages"][0]["returncode"], 7)

    def test_audited_resume_uses_only_the_remainder_and_failure_aware_collector(self):
        status, calls = self.check_supervisor([0, 0], after_audit=True)
        self.assertEqual(calls, 2)
        self.assertEqual([r["script"] for r in status["stages"]],
                         ["batch_liosam_afteraudit0831.py", "collect_strengthening_audited0831.py"])

    def test_launchd_is_one_shot_not_keepalive(self):
        with (fast.ROOT / "configs/strengthening0831_launchd.plist").open("rb") as handle:
            config = plistlib.load(handle)
        self.assertIs(config["KeepAlive"], False)
        self.assertIs(config["RunAtLoad"], True)
        self.assertNotIn("StartInterval", config)
        self.assertNotIn("StartCalendarInterval", config)
        self.assertIn("--after-tuhh-audit", config["ProgramArguments"])

    def test_tuhh_resume_propagates_the_audited_mode_to_both_stages(self):
        status, calls = self.check_supervisor([0, 0], after_tuhh=True)
        self.assertEqual(calls, 2)
        self.assertEqual(status["status"], "complete")

    def test_arc_excursion_is_flagged_but_not_silently_excluded(self):
        self.assertEqual(tuhh_audit.classify_arc("FG-BA_s0p5", 1.641), tuhh_audit.ARC_WARNING)
        self.assertEqual(tuhh_audit.classify_arc("GE-BA_s0p5", 1.654), tuhh_audit.ARC_WARNING)
        self.assertEqual(tuhh_audit.classify_arc("FG-BA_s0p5", .59), tuhh_audit.ARC_WARNING)
        self.assertEqual(tuhh_audit.classify_arc("FG-BA_s0p5", 1.6), "admitted_accuracy")
        with self.assertRaises(RuntimeError):
            tuhh_audit.classify_arc("FG-BA_s0p5", float("nan"))

    def test_arc_warnings_keep_metrics_and_remain_visible(self):
        valid = {"status": "admitted_accuracy", "metrics": {"rmse_z_m": 1.0, "ate_rmse_m": 2.0}}
        hall = {"cells": {f"r{r}/{v}_{l}": valid for r in (1, 2, 3) for v in sam.VARIANTS for l in sam.LEVELS}}
        tuhh = {r: {"cells": {f"{v}_{l}": valid for v in sam.VARIANTS for l in sam.LEVELS}} for r in (1, 2, 3)}
        for r in tuhh:
            tuhh[r]["cells"][tuhh_audit.REVIEWED_CELL] = {
                "status": tuhh_audit.ARC_WARNING, "metrics": {"rmse_z_m": 3.0, "ate_rmse_m": 4.0}}
        result = audited_collector.weight_results(hall, tuhh)
        cell = result["sequences"][1]["cells"][tuhh_audit.REVIEWED_CELL]
        self.assertEqual((cell["accuracy_repeats"], cell["failed_repeats"], cell["requested_repeats"]), (3, 0, 3))
        self.assertEqual(cell["arc_warning_repeats"], 3)
        self.assertEqual(cell["rmse_z_m"]["median"], 3.0)
        self.assertEqual(cell["delta_ate_pct_vs_off"]["median"], 100.0)
        tuhh[2]["cells"]["GE-BA_s5"] = {"status": tuhh_audit.ARC_FAILURE}
        with self.assertRaisesRegex(RuntimeError, "unreviewed exclusion"):
            audited_collector.weight_results(hall, tuhh)

    def test_failed_repeat_is_counted_but_not_given_an_accuracy_value(self):
        cells = {}
        for repeat in (1, 2, 3):
            for variant in sam.VARIANTS:
                for level in sam.LEVELS:
                    cells[f"r{repeat}/{variant}_{level}"] = {
                        "status": "admitted_accuracy", "metrics": {"rmse_z_m": 1.0, "ate_rmse_m": 2.0}}
        cells["r3/FG-BA_s5"] = {"status": "observed_estimator_failure_not_accuracy_run", "fatal_markers": {"Large velocity": 56}}
        tuhh_runs = {f"{v}_{l}": {"rmse_z_m": 1.0, "ate_rmse_m": 2.0} for v in sam.VARIANTS for l in sam.LEVELS}
        def read(path):
            return {"passed": True} if path.name == "validation.json" else {"runs": tuhh_runs}
        with patch.object(audited_collector.original, "read", side_effect=read):
            result = audited_collector.weight_results({"cells": cells})
            cell = result["sequences"][0]["cells"]["FG-BA_s5"]
            self.assertEqual((cell["accuracy_repeats"], cell["failed_repeats"], cell["requested_repeats"]), (2, 1, 3))
            self.assertEqual(len(cell["rmse_z_m"]["values"]), 2)
            self.assertNotIn("metrics", cell["failures"][0])
            cells["r3/FG-BA_s0p5"] = {"status": "instrument_timestamp_mismatch_not_accuracy_run"}
            with self.assertRaisesRegex(RuntimeError, "unreviewed exclusion"):
                audited_collector.weight_results({"cells": cells})


if __name__ == "__main__":
    unittest.main()
