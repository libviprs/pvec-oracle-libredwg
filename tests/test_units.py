# Drawing units and fit-point splines (pvec-gold-fixtures issue 68).
#
# Inches and feet are scaled to metre and declared metre, so the values in the STEP file are the stored ones times 0.0254
# or 0.3048, each rounded once from the exact product. Millimetre, centimetre and kilometre are declared and left alone.
# A spline that has fit points and no control points is left out for that entity, with a warning, and the rest of the
# drawing converts. The units are set by editing HEADER.INSUNITS in the JSON of a real corpus DWG and writing it back
# with dwgwrite, so the decoder under test reads a real file. The fit-point checks on real drawings need REALWORLD
# (a directory with <id>/source.dwg for the pvec-gold-fixtures real-world set) and skip without it.
import json
import os
import re
import unittest
from fractions import Fraction

from common import convert, dwg, load_json, run, scratch

REALWORLD = os.environ.get("REALWORLD")
LINE_START = (0.5, 0.25, 0.0)   # line-001's authored start point
LINE_END = (3.75, 2.5, 0.0)


def with_units(tmp, insunits):
    src = os.path.join(tmp, "in.json")
    assert run(["dwgread-exact", "-O", "JSON", "-o", src, dwg("line-001")]).returncode == 0
    tree = load_json(src)
    tree["HEADER"]["INSUNITS"] = insunits
    edited = os.path.join(tmp, "edited.json")
    with open(edited, "w") as f:
        json.dump(tree, f)
    made = os.path.join(tmp, "units.dwg")
    r = run(["dwgwrite-exact", "--as", "r2004", "-o", made, edited])
    assert r.returncode == 0, r.stderr
    return made


def convert_units(insunits):
    """(exit code, STEP text or None, status record) for line-001 with the given INSUNITS."""
    with scratch() as tmp:
        out, st = os.path.join(tmp, "o.step"), os.path.join(tmp, "o.json")
        r = convert(with_units(tmp, insunits), out, st)
        text = open(out).read() if os.path.exists(out) else None
        return r.returncode, text, json.load(open(st))


def points(text):
    return [tuple(float(x) for x in m.group(1).split(",")) for m in re.finditer(r"CARTESIAN_POINT\('',\(([^)]*)\)\)", text)]


def length_unit(text):
    return re.search(r"LENGTH_UNIT\(\)NAMED_UNIT\(\*\)SI_UNIT\(([^)]*)\)", text).group(1)


def scaled(p, num, den):
    return tuple(float(Fraction(c) * Fraction(num, den)) for c in p)


class Units(unittest.TestCase):
    def test_inches_are_scaled_to_metre_with_one_rounding_and_declared_metre(self):
        code, text, st = convert_units(1)
        self.assertEqual(code, 0, st.get("error"))
        self.assertEqual(length_unit(text), "$,.METRE.")
        self.assertIn(scaled(LINE_START, 254, 10000), points(text))
        self.assertTrue(any("inches" in w and "0.0254" in w for w in st["warnings"]), st["warnings"])

    def test_feet_are_scaled_to_metre_with_one_rounding_and_declared_metre(self):
        code, text, st = convert_units(2)
        self.assertEqual(code, 0, st.get("error"))
        self.assertEqual(length_unit(text), "$,.METRE.")
        self.assertIn(scaled(LINE_START, 3048, 10000), points(text))
        self.assertTrue(any("feet" in w and "0.3048" in w for w in st["warnings"]), st["warnings"])

    def test_the_line_length_follows_the_scale(self):
        code, text, _ = convert_units(2)
        self.assertEqual(code, 0)
        pts = points(text)
        self.assertIn(scaled(LINE_START, 3048, 10000), pts)
        # the trim runs over the scaled length
        trims = re.findall(r"PARAMETER_VALUE\(([^)]*)\)", text)
        got = float(trims[1])
        want = ((LINE_END[0] - LINE_START[0]) ** 2 + (LINE_END[1] - LINE_START[1]) ** 2) ** 0.5 * 0.3048
        self.assertAlmostEqual(got, want, places=12)

    def test_millimetre_centimetre_and_kilometre_are_declared_and_not_rescaled(self):
        for n, decl in ((4, ".MILLI.,.METRE."), (5, ".CENTI.,.METRE."), (7, ".KILO.,.METRE.")):
            with self.subTest(insunits=n):
                code, text, st = convert_units(n)
                self.assertEqual(code, 0, st.get("error"))
                self.assertEqual(length_unit(text), decl)
                self.assertIn(LINE_START, points(text))

    def test_metre_is_declared_and_unitless_is_metre_with_a_warning(self):
        code, text, st = convert_units(6)
        self.assertEqual(code, 0)
        self.assertEqual(length_unit(text), "$,.METRE.")
        self.assertFalse(any("INSUNITS" in w for w in st["warnings"]))
        code, text, st = convert_units(0)
        self.assertEqual(code, 0)
        self.assertEqual(length_unit(text), "$,.METRE.")
        self.assertIn(LINE_START, points(text))
        self.assertTrue(any("unitless" in w for w in st["warnings"]), st["warnings"])

    def test_a_unit_that_is_not_supported_is_refused_by_name_and_leaves_no_step(self):
        code, text, st = convert_units(3)   # miles
        self.assertEqual(code, 15)
        self.assertIsNone(text)
        self.assertEqual(st["error"]["class"], "CONVERSION_FAILED")
        self.assertIn("drawing unit 3", st["error"]["message"])


@unittest.skipUnless(REALWORLD, "REALWORLD not set")
class RealWorld(unittest.TestCase):
    def run_on(self, fid):
        with scratch() as tmp:
            out, st = os.path.join(tmp, "o.step"), os.path.join(tmp, "o.json")
            r = convert(os.path.join(REALWORLD, fid, "source.dwg"), out, st)
            return r.returncode, (open(out).read() if os.path.exists(out) else None), json.load(open(st))

    def test_a_fit_point_only_spline_is_skipped_for_that_entity_and_the_rest_converts(self):
        code, text, st = self.run_on("general-sample-ac1032-001")
        self.assertEqual(code, 0, st.get("error"))
        fit = [w for w in st["warnings"] if w.startswith("skipped SPLINE") and "fit points only" in w]
        self.assertEqual(len(fit), 1, [w for w in st["warnings"] if "SPLINE" in w])
        self.assertGreater(len(points(text)), 10)

    def test_an_inch_drawing_is_scaled_to_metre(self):
        code, text, st = self.run_on("blocks-dynamic-linear-001")
        self.assertEqual(code, 0, st.get("error"))
        self.assertEqual(length_unit(text), "$,.METRE.")
        self.assertTrue(any("inches" in w for w in st["warnings"]), st["warnings"])

    def test_a_drawing_with_no_curve_in_model_space_is_still_refused(self):
        code, text, st = self.run_on("arch-aecobjects-001")
        self.assertEqual(code, 15)
        self.assertIsNone(text)
        self.assertEqual(st["error"]["message"], "the drawing holds no curve this converter writes")


if __name__ == "__main__":
    unittest.main()
