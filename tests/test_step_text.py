# The Part 21 subset, read from the file itself.
import re
import unittest

from common import fixture_ids, out_path

ALLOWED = {
    "APPLICATION_CONTEXT", "APPLICATION_PROTOCOL_DEFINITION", "PRODUCT_CONTEXT", "PRODUCT",
    "PRODUCT_DEFINITION_CONTEXT", "PRODUCT_DEFINITION_FORMATION", "PRODUCT_DEFINITION", "PRODUCT_DEFINITION_SHAPE",
    "SHAPE_DEFINITION_REPRESENTATION", "GEOMETRICALLY_BOUNDED_WIREFRAME_SHAPE_REPRESENTATION",
    "AXIS2_PLACEMENT_3D", "CARTESIAN_POINT", "DIRECTION", "VECTOR", "LINE", "CIRCLE", "ELLIPSE",
    "TRIMMED_CURVE", "B_SPLINE_CURVE_WITH_KNOTS", "GEOMETRIC_CURVE_SET", "UNCERTAINTY_MEASURE_WITH_UNIT",
    # complex entities (an instance written as a parenthesised list of parts)
    "GEOMETRIC_REPRESENTATION_CONTEXT", "GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT", "GLOBAL_UNIT_ASSIGNED_CONTEXT",
    "REPRESENTATION_CONTEXT", "LENGTH_UNIT", "NAMED_UNIT", "SI_UNIT", "PLANE_ANGLE_UNIT", "SOLID_ANGLE_UNIT",
    "BOUNDED_CURVE", "B_SPLINE_CURVE", "CURVE", "GEOMETRIC_REPRESENTATION_ITEM", "RATIONAL_B_SPLINE_CURVE",
    "REPRESENTATION_ITEM", "LENGTH_MEASURE", "PARAMETER_VALUE",
}


def text(fid):
    return open(out_path(fid, "secondary.step"), encoding="utf-8").read()


class Subset(unittest.TestCase):
    def test_only_the_subset_is_written(self):
        for fid in fixture_ids():
            with self.subTest(fixture=fid):
                t = text(fid)
                self.assertTrue(t.startswith("ISO-10303-21;"))
                self.assertTrue(t.rstrip().endswith("END-ISO-10303-21;"))
                self.assertIn("AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF", t)
                names = set(re.findall(r"\b([A-Z][A-Z0-9_]{2,})\s*\(", t.split("DATA;", 1)[1]))
                self.assertEqual(names - ALLOWED, set())
                self.assertIn("GEOMETRIC_CURVE_SET", names)

    def test_no_instance_or_transform_entity_is_written(self):
        # flattened: STEP carries a uniform scale only, so no placement chain stands in for an INSERT
        for fid in fixture_ids():
            with self.subTest(fixture=fid):
                t = text(fid)
                for banned in ("CARTESIAN_TRANSFORMATION_OPERATOR", "MAPPED_ITEM", "REPRESENTATION_MAP", "ITEM_DEFINED_TRANSFORMATION"):
                    self.assertNotIn(banned, t)

    def test_reals_are_written_at_17_significant_digits(self):
        self.assertIn("1.0000000000000001E-05", text("tiny-radius-001"))
        self.assertIn("2.6000000000000001", text("closed-periodic-001"))

    def test_every_reference_resolves(self):
        for fid in fixture_ids():
            with self.subTest(fixture=fid):
                t = text(fid).split("DATA;", 1)[1]
                defined = set(re.findall(r"^#(\d+)=", t, re.M))
                used = set(re.findall(r"#(\d+)", re.sub(r"^#\d+=", "", t, flags=re.M)))
                self.assertEqual(used - defined, set())


if __name__ == "__main__":
    unittest.main()
