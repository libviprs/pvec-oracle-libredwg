# near-singular-001 has an expected outcome of "no curve" (expect: reject, NEAR_SINGULAR_TRANSFORM,
# QUARANTINE). The rule is NP-19 of the numeric policy: refuse an affine map whose |ad - bc| is at
# most REL * big^2, where a, b, c, d are the plane entries of the matrix and big is the largest of them.
import importlib.util
import os
import unittest
from fractions import Fraction

from common import CORPUS, REFUSED, dwg, load_json, run, scratch


def converter():
    spec = importlib.util.spec_from_file_location("dwg2step_under_test", "/usr/local/bin/dwg2step.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def scale_matrix(m, sx, sy, sz):
    z, f = Fraction(0), Fraction
    return m.Aff([[f(sx), z, z], [z, f(sy), z], [z, z, f(sz)]], (z, z, z), None, 1)


class NearSingular(unittest.TestCase):
    def test_near_singular_001_is_refused_with_exit_15_and_no_step(self):
        with scratch() as tmp:
            out, status = os.path.join(tmp, "o.step"), os.path.join(tmp, "o.status.json")
            open(out, "w").write("stale")
            r = run(["dwg2step", "--in", dwg("near-singular-001"), "--out", out, "--status", status])
            self.assertEqual(r.returncode, REFUSED["near-singular-001"], r.stderr)
            self.assertFalse(os.path.exists(out))
            s = load_json(status)
            self.assertEqual((s["status"], s["exit_code"]), ("ERROR", 15))
            self.assertEqual(s["error"]["class"], "CONVERSION_FAILED")
            self.assertIn("NEAR_SINGULAR_TRANSFORM", s["error"]["message"])
            self.assertIsNone(s["output"])

    def test_the_constant_is_the_policy_value(self):
        # the number lives in the policy; this repository carries a named copy and pins it to the data
        policy = load_json(os.path.join(CORPUS, "policy.json"))
        self.assertEqual(converter().NP19_REL, Fraction(str(policy["constants"]["REL"])))
        self.assertEqual(policy["rules"]["affine_transforms"], "NP-19")

    def test_the_rule_is_abs_ad_minus_bc_at_most_rel_times_big_squared(self):
        m = converter()
        rel = m.NP19_REL
        self.assertTrue(m.near_singular(scale_matrix(m, 1, "1e-12", 1)))
        self.assertTrue(m.near_singular(scale_matrix(m, 1, rel, 1)))  # the bound itself is refused
        self.assertFalse(m.near_singular(scale_matrix(m, 1, rel * 2, 1)))
        # big is the largest entry: scaled up by 1e6 the same ratio is refused at 1e6 * 1e-5 * ... = det 10 <= 100
        self.assertTrue(m.near_singular(scale_matrix(m, 10 ** 6, "1e-5", 1)))
        self.assertFalse(m.near_singular(scale_matrix(m, 10 ** 6, 1, 1)))
        self.assertFalse(m.near_singular(scale_matrix(m, 2, 3, 0)))  # a z collapse leaves the plane alone

    def test_every_other_probe_is_still_converted(self):
        with scratch() as tmp:
            for fid in ("translation-001", "uniform-scale-001", "nonuniform-scale-circle-001", "reflection-001"):
                r = run(["dwg2step", "--in", dwg(fid), "--out", os.path.join(tmp, fid + ".step")])
                self.assertEqual(r.returncode, 0, fid + r.stderr)


if __name__ == "__main__":
    unittest.main()
