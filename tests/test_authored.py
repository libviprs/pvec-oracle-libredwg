# What the evaluator read from the converter's STEP, against the mathematics authored before any
# DWG existed (expected.math.json). Stored values (poles, knots, weights, centres, radii, degrees)
# must come back bit for bit. Derived values (an ellipse's axes after a scale, an arc's end) are
# checked with the sanity tolerance in common.py, which is not the numeric policy: the policy
# verdicts belong to the qualification stage, not to this repository.
import math
import unittest

from common import SANITY, close, expected, fixture_ids, scalar, verification

STORED_CLASSES = {"circle", "circular_arc", "ellipse", "elliptical_arc", "bezier", "bspline", "nurbs"}
STORED_KEYS = ("center", "radius", "degree", "control_points", "knots", "weights")
# Every probe's stored values come back bit for bit, the periodic spline included: it is written wrapped
# and closed, and the evaluator unwraps it to the authored unique poles (test_the_periodic_spline_*).
NOT_STORED = set()


def flat(x):
    """Every f64_hex under a geometry value, in order, with multiplicities and integers kept."""
    if isinstance(x, dict):
        if "f64_hex" in x:
            return [x["f64_hex"]]
        out = []
        for k in sorted(x):
            out += flat(x[k])
        return out
    if isinstance(x, list):
        out = []
        for i in x:
            out += flat(i)
        return out
    return [x]


def curve_probes():
    for fid in fixture_ids():
        if fid in NOT_STORED:
            continue
        ex = expected(fid)["entities"]
        # a bulge arc is derived from a polyline's vertices and bulge, so it is not a stored value
        if len(ex) == 1 and ex[0]["structure"] == "CURVE_ONLY" and ex[0]["class"] in STORED_CLASSES:
            yield fid, ex[0]


class StoredValues(unittest.TestCase):
    def test_stored_values_match_authored_bits_on_curve_probes(self):
        seen = 0
        for fid, ex in curve_probes():
            with self.subTest(fixture=fid):
                ev = verification(fid)["entities"]
                curve = [e for e in ev if e["class"] != "unsupported"]
                self.assertEqual(len(curve), 1, "expected one curve, the evaluator read %d" % len(curve))
                common = [k for k in STORED_KEYS if k in ex["geometry"] and k in curve[0]["geometry"]]
                self.assertTrue(common, "nothing to compare")
                for k in common:
                    self.assertEqual(flat(curve[0]["geometry"][k]), flat(ex["geometry"][k]), k)
                if ex["class"] in ("bezier", "bspline", "nurbs"):
                    self.assertIn("control_points", common)
                if ex["class"] in ("bspline", "nurbs"):
                    self.assertIn("knots", common)
                if ex["class"] == "nurbs":
                    self.assertIn("weights", common)
                seen += 1
        self.assertGreaterEqual(seen, 12)

    def test_rational_probes_keep_their_weights_and_are_not_renormalised(self):
        for fid in ("nurbs-d3-001", "nonunit-weight-001", "nurbs-d2-offconic-001"):
            with self.subTest(fixture=fid):
                g = verification(fid)["entities"][0]["geometry"]
                self.assertFalse(g["weights_all_unit"])
                self.assertEqual(flat(g["weights"]), flat(expected(fid)["entities"][0]["geometry"]["weights"]))


class Edges(unittest.TestCase):
    def test_a_polyline_arrives_as_separate_line_and_arc_edges(self):
        for fid in ("polyline-001", "large-coords-001", "lwpolyline-closed-001", "polyline2d-001", "bulge-arc-001", "bulge-arc-neg-001"):
            with self.subTest(fixture=fid):
                ex = [e for e in expected(fid)["entities"] if e["class"] == "polyline"][0]
                bulges = [scalar(b) for b in ex["geometry"]["bulges"]]
                n = len(ex["geometry"]["vertices"])
                closed = ex["closure"]["closed_by_endpoint"]
                segs = n if (closed and ex["closure"].get("closed_by_endpoint")) else n - 1
                classes = sorted(e["class"] for e in verification(fid)["entities"])
                arcs = sum(1 for b in bulges[:segs] if b != 0.0)
                self.assertEqual(classes, sorted(["circular_arc"] * arcs + ["line"] * (segs - arcs)))

    def test_polyline_edges_pass_through_the_authored_vertices(self):
        for fid in ("polyline-001", "large-coords-001", "lwpolyline-closed-001", "polyline2d-001", "bulge-arc-001", "bulge-arc-neg-001"):
            with self.subTest(fixture=fid):
                ex = [e for e in expected(fid)["entities"] if e["class"] == "polyline"][0]
                verts = [[scalar(c) for c in v] for v in ex["geometry"]["vertices"]]
                edges = verification(fid)["entities"]
                for i, e in enumerate(edges):
                    ps = sorted(e["samples"], key=lambda s: scalar(s["parameter"]))
                    a, b = [scalar(c) for c in ps[0]["point"]], [scalar(c) for c in ps[-1]["point"]]
                    for got, want in ((a, verts[i]), (b, verts[(i + 1) % len(verts)])):
                        for g, w in zip(got, want):
                            self.assertTrue(close(g, w, w), "%s edge %d: %r vs %r" % (fid, i, got, want))


class FlattenedInstances(unittest.TestCase):
    def world(self, fid):
        ex = expected(fid)["entities"][0]["world"]
        return ex, verification(fid)["entities"]

    def test_nonuniform_scaled_circle_becomes_the_authored_ellipse(self):
        for fid in ("nonuniform-scale-circle-001", "nonuniform-scale-rotated-001"):
            with self.subTest(fixture=fid):
                want, got = self.world(fid)
                self.assertEqual([e["class"] for e in got], ["ellipse"])
                g, w = got[0]["geometry"], want["geometry"]
                for k in ("center",):
                    for a, b in zip(g[k], w[k]):
                        self.assertTrue(close(scalar(a), scalar(b), scalar(b)), k)
                for k in ("semi_major", "semi_minor"):
                    self.assertTrue(close(scalar(g[k]), scalar(w[k]), scalar(w[k])), k)
                gm, wm = [scalar(c) for c in g["major_axis"]], [scalar(c) for c in w["major_axis"]]
                ng, nw = math.sqrt(sum(c * c for c in gm)), math.sqrt(sum(c * c for c in wm))
                self.assertTrue(abs(abs(sum(a * b for a, b in zip(gm, wm)) / (ng * nw)) - 1.0) < SANITY)

    def test_reflection_reverses_orientation_and_keeps_start_to_start(self):
        want, got = self.world("reflection-001")
        self.assertEqual([e["class"] for e in got], ["circular_arc"])
        g = got[0]
        # the sense about the source normal flips, so the image normal points the other way
        self.assertTrue(scalar(g["geometry"]["normal"][2]) < 0.0)
        src = expected("reflection-001")["entities"][0]["geometry"]
        c = [scalar(x) for x in src["center"]]
        r, a0, sw = scalar(src["radius"]), scalar(src["start_angle"]), scalar(src["sweep_angle"])
        start = (-(c[0] + r * math.cos(a0)), c[1] + r * math.sin(a0))
        end = (-(c[0] + r * math.cos(a0 + sw)), c[1] + r * math.sin(a0 + sw))
        ps = sorted(g["samples"], key=lambda s: scalar(s["parameter"]))
        for got_p, want_p in ((ps[0]["point"], start), (ps[-1]["point"], end)):
            for k in range(2):
                self.assertTrue(close(scalar(got_p[k]), want_p[k], want_p[k]))

    def test_uniform_scale_keeps_a_circle(self):
        self.assertEqual([e["class"] for e in verification("uniform-scale-001")["entities"]], ["circle"])

    def test_the_nested_chain_composes_outermost_on_the_left(self):
        want = expected("nested-blocks-001")["entities"][0]["world"]["geometry"]
        e = verification("nested-blocks-001")["entities"][0]
        ps = sorted(e["samples"], key=lambda s: scalar(s["parameter"]))
        for got_p, w in ((ps[0]["point"], want["start"]), (ps[-1]["point"], want["end"])):
            for a, b in zip(got_p, w):
                self.assertTrue(close(scalar(a), scalar(b), scalar(b)))

    def test_the_periodic_spline_comes_back_periodic_with_the_authored_poles(self):
        e = verification("closed-periodic-001")["entities"][0]
        self.assertEqual(e["closure"], {"closed_by_endpoint": False, "closed_by_knots": True, "periodic": True})

    def test_the_periodic_spline_is_the_same_point_set(self):
        # closed-periodic-001: six unique poles. The first and last sample must coincide (a closed
        # curve) and every sample must lie on the authored cubic B-spline, evaluated here from the
        # authored poles and knots with the Cox-de Boor recurrence.
        ex = expected("closed-periodic-001")["entities"][0]["geometry"]
        poles = [[scalar(c) for c in p] for p in ex["control_points"]]
        knots = [scalar(k["value"]) for k in ex["knots"] for _ in range(k["multiplicity"])]
        n, deg = len(poles), ex["degree"]
        period = knots[-1] - knots[0]

        def knot(i):
            q, r = divmod(i, n)
            return knots[r] + q * period

        def basis(i, d, t):
            if d == 0:
                return 1.0 if knot(i) <= t < knot(i + 1) else 0.0
            out = 0.0
            if knot(i + d) != knot(i):
                out += (t - knot(i)) / (knot(i + d) - knot(i)) * basis(i, d - 1, t)
            if knot(i + d + 1) != knot(i + 1):
                out += (knot(i + d + 1) - t) / (knot(i + d + 1) - knot(i + 1)) * basis(i + 1, d - 1, t)
            return out

        e = verification("closed-periodic-001")["entities"][0]
        lo = knots[0]
        samples = e["samples"]
        for s in samples:
            u = scalar(s["parameter"])
            # the parameter domain of the written curve is the authored one, shifted by nothing
            t = lo + (u - scalar(e["parameter_domain"]["start"]))
            want = [0.0, 0.0, 0.0]
            # pvec's convention (BSpline::from_periodic, ADR 0011): unique pole i is supported by the
            # periodic knots i - deg .. i + 1, so the first pole is the one at the seam
            for i in range(-deg, n + deg):
                b = basis(i - deg, deg, t)
                for k in range(3):
                    want[k] += b * poles[i % n][k]
            for k in range(3):
                self.assertTrue(close(scalar(s["point"][k]), want[k], 3.0), "u=%r k=%d" % (u, k))
        ps = sorted(samples, key=lambda s: scalar(s["parameter"]))
        for k in range(3):
            self.assertTrue(close(scalar(ps[0]["point"][k]), scalar(ps[-1]["point"][k]), 3.0))


if __name__ == "__main__":
    unittest.main()
