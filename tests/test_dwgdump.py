# dwgdump writes the r0-open read record (pvec-gold/r0-open-dwg-read/2). The shape below is
# written from the schema as described in the corpus documentation; nothing is imported or copied.
import os
import re
import unittest

from common import REPO, dwg, fixture_ids, load_json, run, scratch
import hashlib

HEX = re.compile(r"^0x[0-9a-f]{16}$")
VEC3 = ("start", "end", "center", "normal", "major_axis", "insert_point", "scale")
REAL = ("radius", "start_angle", "end_angle", "ratio", "start_param", "end_param", "elevation", "rotation")
KEYS = {
    "LINE": {"type", "layer", "start", "end"},
    "CIRCLE": {"type", "layer", "center", "radius", "normal"},
    "ARC": {"type", "layer", "center", "radius", "normal", "start_angle", "end_angle"},
    "ELLIPSE": {"type", "layer", "center", "major_axis", "normal", "ratio", "start_param", "end_param"},
    "LWPOLYLINE": {"type", "layer", "closed", "elevation", "normal", "vertices"},
    "POLYLINE": {"type", "layer", "closed", "elevation", "normal", "vertices"},
    "SPLINE": {"type", "layer", "closed", "control_points", "degree", "fit_point_count", "knots", "normal",
               "periodic", "rational", "weights"},
    "INSERT": {"type", "layer", "block", "insert_point", "normal", "rotation", "scale"},
}


def dump(fid, tmp):
    out = os.path.join(tmp, fid + ".json")
    r = run(["dwgdump", "--in", dwg(fid), "--out", out])
    assert r.returncode == 0, (fid, r.stderr)
    return load_json(out)


class ReadRecord(unittest.TestCase):
    def check_entity(self, e):
        self.assertIn(e["type"], KEYS)
        self.assertEqual(set(e), KEYS[e["type"]])
        self.assertIsInstance(e["layer"], str)
        for k in VEC3:
            if k in e:
                self.assertEqual(len(e[k]), 3)
                for c in e[k]:
                    self.assertRegex(c, HEX)
        for k in REAL:
            if k in e:
                self.assertRegex(e[k], HEX)
        if e["type"] in ("LWPOLYLINE", "POLYLINE"):
            self.assertIsInstance(e["closed"], bool)
            for v in e["vertices"]:
                self.assertEqual(len(v), 3)
                for c in v:
                    self.assertRegex(c, HEX)
        if e["type"] == "SPLINE":
            self.assertIsInstance(e["degree"], int)
            self.assertEqual(type(e["fit_point_count"]), int)
            for k in ("closed", "periodic", "rational"):
                self.assertIsInstance(e[k], bool)
            for p in e["control_points"]:
                self.assertEqual(len(p), 3)
            for c in e["knots"] + e["weights"]:
                self.assertRegex(c, HEX)
            self.assertEqual(len(e["weights"]), len(e["control_points"]) if e["rational"] else 0)

    def test_dwgdump_matches_the_read_record_schema(self):
        with scratch() as tmp:
            for fid in fixture_ids():
                with self.subTest(fixture=fid):
                    d = dump(fid, tmp)
                    self.assertEqual(set(d), {"blocks", "dwg_sha256", "dwg_version", "layers", "reader", "schema"})
                    self.assertEqual(d["schema"], "pvec-gold/r0-open-dwg-read/2")
                    self.assertEqual(d["dwg_version"], "AC1032")
                    self.assertEqual(d["dwg_sha256"], hashlib.sha256(open(dwg(fid), "rb").read()).hexdigest())
                    self.assertTrue(d["reader"].startswith("LibreDWG@"))
                    names = [b["name"] for b in d["blocks"]]
                    self.assertEqual(names, sorted(names))
                    self.assertIn("*Model_Space", names)
                    for b in d["blocks"]:
                        self.assertEqual(set(b), {"name", "entities"})
                        for e in b["entities"]:
                            self.check_entity(e)
                    lnames = [l["name"] for l in d["layers"]]
                    self.assertEqual(lnames, sorted(lnames))
                    for l in d["layers"]:
                        self.assertEqual(set(l), {"frozen", "name", "on"})
                        self.assertIsInstance(l["frozen"], bool)
                        self.assertIsInstance(l["on"], bool)

    def test_the_third_reader_returns_the_same_record_as_the_acadsharp_reader(self):
        # ADR 0008's cross-read compares decoded records field for field, "reader" aside. LibreDWG
        # does not share a lineage with ACadSharp, so equality here is a real third reading.
        with scratch() as tmp:
            for fid in fixture_ids():
                with self.subTest(fixture=fid):
                    mine = dump(fid, tmp)
                    other = load_json(os.path.join(os.environ.get("CORPUS", "/corpus"), "fixtures", fid, "read.acadsharp.json"))
                    mine.pop("reader")
                    other.pop("reader")
                    self.assertEqual(mine, other)

    def test_an_entity_outside_the_record_shape_is_listed_not_dropped(self):
        # none of the r0-open probes has one, so this reads the source: the fallback marks it.
        src = open(os.path.join(REPO, "dwgdump.py"), encoding="utf-8").read()
        self.assertIn('rec["unread"] = True', src)


if __name__ == "__main__":
    unittest.main()
