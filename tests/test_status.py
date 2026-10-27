# The status record is written beside the output, ok or not (pvec-gold/converter-status/1).
# Checked against the schema's rules as documented; the converter id is a string, not the old
# cadex/oda enum, because a named open converter is what this record now has to carry.
import os
import re
import unittest

from common import dwg, fixture_ids, load_json, out_path, scratch, convert

TOP = {"schema_version", "converter", "status", "exit_code", "input", "output", "product",
       "declared_schema", "wall_time_seconds", "warnings", "error"}
CLASSES = {10: "BAD_ARGUMENTS", 11: "INPUT_UNREADABLE", 12: "INPUT_MALFORMED", 13: "DWG_VERSION_UNSUPPORTED",
           14: "LICENCE_UNAVAILABLE", 15: "CONVERSION_FAILED", 16: "OUTPUT_NOT_WRITTEN", 17: "SCHEMA_NOT_AP242",
           20: "INTERNAL"}
SHA = re.compile(r"^[0-9a-f]{64}$")


class StatusRecord(unittest.TestCase):
    def check(self, s):
        self.assertEqual(set(s), TOP)
        self.assertEqual(s["schema_version"], "pvec-gold/converter-status/1")
        self.assertEqual(s["converter"], "libredwg-dwg2step")
        self.assertIn(s["status"], ("OK", "ERROR"))
        self.assertIn(s["exit_code"], [0, 10, 11, 12, 13, 14, 15, 16, 17, 20])
        self.assertEqual(set(s["input"]), {"path", "sha256"})
        self.assertTrue(s["input"]["sha256"] is None or SHA.match(s["input"]["sha256"]))
        self.assertEqual(set(s["product"]), {"name", "version"})
        self.assertRegex(s["wall_time_seconds"], r"^[0-9]+\.[0-9]{3}$")
        self.assertIsInstance(s["warnings"], list)
        if s["status"] == "OK":
            self.assertEqual(s["exit_code"], 0)
            self.assertEqual(set(s["output"]), {"path", "sha256"})
            self.assertRegex(s["output"]["sha256"], SHA)
            self.assertIn("AP242", s["declared_schema"])
            self.assertIsNone(s["error"])
        else:
            self.assertIsNone(s["output"])
            self.assertEqual(set(s["error"]), {"code", "class", "message"})
            self.assertEqual(s["error"]["code"], s["exit_code"])
            self.assertEqual(s["error"]["class"], CLASSES[s["exit_code"]])

    def test_every_r0_status_record_matches_the_schema(self):
        for fid in fixture_ids():
            with self.subTest(fixture=fid):
                self.check(load_json(out_path(fid, "secondary.status.json")))

    def test_the_output_hash_in_the_record_is_the_hash_of_the_file(self):
        import hashlib
        for fid in fixture_ids():
            with self.subTest(fixture=fid):
                s = load_json(out_path(fid, "secondary.status.json"))
                self.assertEqual(hashlib.sha256(open(out_path(fid, "secondary.step"), "rb").read()).hexdigest(), s["output"]["sha256"])
                self.assertEqual(hashlib.sha256(open(dwg(fid), "rb").read()).hexdigest(), s["input"]["sha256"])

    def test_an_error_record_matches_the_schema_too(self):
        with scratch() as tmp:
            open(os.path.join(tmp, "x.dwg"), "wb").write(b"junk")
            convert(os.path.join(tmp, "x.dwg"), os.path.join(tmp, "x.step"), os.path.join(tmp, "x.status.json"))
            self.check(load_json(os.path.join(tmp, "x.status.json")))

    def test_the_default_status_name_sits_beside_the_output(self):
        with scratch() as tmp:
            self.assertEqual(convert(dwg("line-001"), os.path.join(tmp, "secondary.step")).returncode, 0)
            self.assertTrue(os.path.exists(os.path.join(tmp, "secondary.status.json")))


if __name__ == "__main__":
    unittest.main()
