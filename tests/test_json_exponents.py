# The patched JSON writer prints doubles with %.17g. LibreDWG's own _VALUE_RD then strips trailing
# '0' characters from any printed number that contains a '.', which was harmless with %.14f and cuts
# into the exponent with %.17g: 1.5e-10 would come out as 1.5e-1. Written here as a DWG round trip
# through the real decoder, with values the corpus does not hold.
import json
import os
import struct
import unittest

from common import dwg, load_json, run, scratch

VALUES = [1.5e-10, 1.2345e-20, 2.5e+20, 7.7e-30, 1e-10, 1e+20, 9.9999999999999998e-13, 1.25, 0.1, 123456789.125]


def bits(x):
    return struct.unpack(">Q", struct.pack(">d", x))[0]


class Exponents(unittest.TestCase):
    def test_tiny_and_huge_values_survive_the_patched_json_writer(self):
        with scratch() as tmp:
            src = os.path.join(tmp, "in.json")
            self.assertEqual(run(["dwgread-exact", "-O", "JSON", "-o", src, dwg("line-001")]).returncode, 0)
            tree = load_json(src)
            lines = [o for o in tree["OBJECTS"] if o.get("entity") == "LINE"]
            self.assertEqual(len(lines), 1)
            lines[0]["start"] = VALUES[0:3]
            lines[0]["end"] = VALUES[3:6]
            with open(os.path.join(tmp, "edited.json"), "w") as f:
                json.dump(tree, f)
            made = os.path.join(tmp, "made.dwg")
            r = run(["dwgwrite-exact", "--as", "r2000", "-o", made, os.path.join(tmp, "edited.json")])
            self.assertEqual(r.returncode, 0, r.stderr)
            back = os.path.join(tmp, "back.json")
            self.assertEqual(run(["dwgread-exact", "-O", "JSON", "-o", back, made]).returncode, 0)
            got = [o for o in load_json(back)["OBJECTS"] if o.get("entity") == "LINE"][0]
            self.assertEqual([bits(float(x)) for x in got["start"] + got["end"]], [bits(x) for x in VALUES[:6]])

    def test_the_other_values_too(self):
        with scratch() as tmp:
            src = os.path.join(tmp, "in.json")
            self.assertEqual(run(["dwgread-exact", "-O", "JSON", "-o", src, dwg("line-001")]).returncode, 0)
            tree = load_json(src)
            line = [o for o in tree["OBJECTS"] if o.get("entity") == "LINE"][0]
            line["start"] = VALUES[6:9]
            line["end"] = [VALUES[9], 0.0, 1.0]
            with open(os.path.join(tmp, "edited.json"), "w") as f:
                json.dump(tree, f)
            made = os.path.join(tmp, "made.dwg")
            self.assertEqual(run(["dwgwrite-exact", "--as", "r2000", "-o", made, os.path.join(tmp, "edited.json")]).returncode, 0)
            back = os.path.join(tmp, "back.json")
            self.assertEqual(run(["dwgread-exact", "-O", "JSON", "-o", back, made]).returncode, 0)
            got = [o for o in load_json(back)["OBJECTS"] if o.get("entity") == "LINE"][0]
            self.assertEqual([bits(float(x)) for x in got["start"]], [bits(x) for x in VALUES[6:9]])
            self.assertEqual(bits(float(got["end"][0])), bits(VALUES[9]))


if __name__ == "__main__":
    unittest.main()
