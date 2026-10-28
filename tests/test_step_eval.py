# The converter's output is read by the independent evaluator (step_eval, Open CASCADE only).
import os
import unittest

from common import REFUSED, WORK, converted_ids, fixture_ids, load_json, out_path, verification


class EveryR0DwgIsReadByStepEval(unittest.TestCase):
    def test_converter_output_is_read_by_step_eval_for_every_r0_dwg(self):
        ids = fixture_ids()
        self.assertGreaterEqual(len(ids), 30, "the r0-open corpus is not mounted at /corpus")
        for fid in [f for f in ids if f not in REFUSED]:
            with self.subTest(fixture=fid):
                status = load_json(out_path(fid, "secondary.status.json"))
                self.assertEqual(status["exit_code"], 0, status.get("error"))
                self.assertEqual(status["status"], "OK")
                v = verification(fid)
                self.assertEqual(v["schema_version"], "pvec-gold/verification/1")
                self.assertEqual(v["tool"]["name"], "step_eval")
                self.assertGreaterEqual(len(v["entities"]), 1, "step_eval found no curve")
                for e in v["entities"]:
                    self.assertNotEqual(e["class"], "unsupported", "OCCT type %s" % e["geometry"].get("occt_type"))

    def test_the_evaluator_ran_for_every_fixture(self):
        import os
        ran = set(os.listdir(os.path.join(WORK, "verify"))) if os.path.isdir(os.path.join(WORK, "verify")) else set()
        for fid in converted_ids():
            self.assertIn(fid + ".verification.json", ran)


    def test_a_probe_whose_truth_is_no_curve_is_not_converted(self):
        for fid, code in REFUSED.items():
            with self.subTest(fixture=fid):
                status = load_json(out_path(fid, "secondary.status.json"))
                self.assertEqual(status["exit_code"], code)
                self.assertFalse(os.path.exists(out_path(fid, "secondary.step")))


if __name__ == "__main__":
    unittest.main()
