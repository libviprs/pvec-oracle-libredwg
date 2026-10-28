# Two runs, and the ways a run can go wrong. These drive the converter inside the image.
import json
import os
import unittest

from common import convert, converted_ids as fixture_ids, dwg, load_json, run, scratch

VARYING_STATUS_FIELDS = {"wall_time_seconds"}


def strip_status(d):
    return {k: v for k, v in d.items() if k not in VARYING_STATUS_FIELDS}


def normalise_step(text):
    """The one field a Part 21 file is allowed to vary: the FILE_NAME time stamp (second argument)."""
    import re
    return re.sub(r"(FILE_NAME\s*\(\s*'[^']*'\s*,\s*)'[^']*'", r"\1'<TIMESTAMP>'", text)


class TwoRuns(unittest.TestCase):
    def test_two_runs_are_identical_except_the_named_fields(self):
        with scratch() as tmp:
            for fid in fixture_ids():
                with self.subTest(fixture=fid):
                    outs = []
                    for n in (1, 2):
                        step, status = os.path.join(tmp, "%s.%d.step" % (fid, n)), os.path.join(tmp, "%s.%d.status.json" % (fid, n))
                        r = convert(dwg(fid), step, status)
                        self.assertEqual(r.returncode, 0, r.stderr)
                        outs.append((open(step, encoding="utf-8").read(), load_json(status)))
                    self.assertEqual(normalise_step(outs[0][0]), normalise_step(outs[1][0]))
                    a, b = strip_status(outs[0][1]), strip_status(outs[1][1])
                    # the paths differ because the two runs wrote to two names; everything else matches
                    for d in (a, b):
                        d["output"] = dict(d["output"], path="<out>")
                    self.assertEqual(a, b)

    def test_the_named_fields_are_the_only_ones_that_vary(self):
        # Stronger than asked: with SOURCE_DATE_EPOCH unset the whole STEP file is byte identical.
        with scratch() as tmp:
            a, b = os.path.join(tmp, "a.step"), os.path.join(tmp, "b.step")
            fid = "nested-blocks-001"
            self.assertEqual(convert(dwg(fid), a).returncode, 0)
            self.assertEqual(convert(dwg(fid), b).returncode, 0)
            self.assertEqual(open(a, "rb").read(), open(b, "rb").read())


class Failures(unittest.TestCase):
    def malformed_inputs(self, tmp):
        good = open(dwg("line-001"), "rb").read()
        files = {
            "empty.dwg": b"",
            "random.dwg": bytes((i * 7919 + 13) % 251 for i in range(5000)),
            "truncated.dwg": good[:6000],
            "magic-only.dwg": b"AC1032",
            "zeros.dwg": bytes(2000),
        }
        for name, data in files.items():
            with open(os.path.join(tmp, name), "wb") as f:
                f.write(data)
        return sorted(files)

    def test_malformed_dwg_exits_12_and_leaves_no_step(self):
        with scratch() as tmp:
            for name in self.malformed_inputs(tmp):
                with self.subTest(input=name):
                    out, status = os.path.join(tmp, name + ".step"), os.path.join(tmp, name + ".status.json")
                    with open(out, "w") as f:  # a stale output from an earlier run must go too
                        f.write("stale")
                    r = convert(os.path.join(tmp, name), out, status)
                    self.assertEqual(r.returncode, 12, r.stderr)
                    self.assertFalse(os.path.exists(out), "a STEP file was left behind")
                    self.assertEqual([f for f in os.listdir(tmp) if f.startswith(name + ".step")], [])
                    s = load_json(status)
                    self.assertEqual((s["status"], s["exit_code"]), ("ERROR", 12))
                    self.assertEqual(s["error"]["class"], "INPUT_MALFORMED")
                    self.assertEqual(s["error"]["code"], 12)
                    self.assertIsNone(s["output"])

    def test_missing_input_exits_11(self):
        with scratch() as tmp:
            out, status = os.path.join(tmp, "o.step"), os.path.join(tmp, "o.status.json")
            r = convert(os.path.join(tmp, "nope.dwg"), out, status)
            self.assertEqual(r.returncode, 11)
            self.assertFalse(os.path.exists(out))
            self.assertEqual(load_json(status)["error"]["class"], "INPUT_UNREADABLE")

    def test_bad_arguments_exit_10(self):
        with scratch() as tmp:
            status = os.path.join(tmp, "o.status.json")
            r = run(["dwg2step", "--out", os.path.join(tmp, "o.step"), "--status", status])
            self.assertEqual(r.returncode, 10)
            self.assertEqual(load_json(status)["error"]["class"], "BAD_ARGUMENTS")
            self.assertEqual(run(["dwg2step", "--bogus"]).returncode, 10)

    def test_a_dwg_version_libredwg_does_not_read_exits_13(self):
        with scratch() as tmp:
            data = bytearray(open(dwg("line-001"), "rb").read())
            data[0:6] = b"AC1099"
            src = os.path.join(tmp, "future.dwg")
            open(src, "wb").write(bytes(data))
            r = convert(src, os.path.join(tmp, "o.step"), os.path.join(tmp, "o.status.json"))
            self.assertEqual(r.returncode, 13, r.stderr)
            self.assertEqual(load_json(os.path.join(tmp, "o.status.json"))["error"]["class"], "DWG_VERSION_UNSUPPORTED")
            self.assertFalse(os.path.exists(os.path.join(tmp, "o.step")))

    def test_a_failed_run_removes_an_older_output_of_the_same_name(self):
        with scratch() as tmp:
            out = os.path.join(tmp, "o.step")
            self.assertEqual(convert(dwg("line-001"), out).returncode, 0)
            self.assertTrue(os.path.exists(out))
            open(os.path.join(tmp, "bad.dwg"), "wb").write(b"AC1032")
            self.assertEqual(convert(os.path.join(tmp, "bad.dwg"), out).returncode, 12)
            self.assertFalse(os.path.exists(out))

    def test_dwgdump_fails_the_same_way_and_leaves_no_record(self):
        with scratch() as tmp:
            open(os.path.join(tmp, "bad.dwg"), "wb").write(b"AC1032")
            out = os.path.join(tmp, "read.json")
            open(out, "w").write("stale")
            r = run(["dwgdump", "--in", os.path.join(tmp, "bad.dwg"), "--out", out])
            self.assertEqual(r.returncode, 12, r.stderr)
            self.assertFalse(os.path.exists(out))
            self.assertEqual(run(["dwgdump"]).returncode, 10)
            self.assertEqual(run(["dwgdump", "--in", os.path.join(tmp, "nope.dwg"), "--out", out]).returncode, 11)


if __name__ == "__main__":
    unittest.main()
