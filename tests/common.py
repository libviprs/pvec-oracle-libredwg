# Shared helpers for the tests. They run inside the converter image (python3 -m unittest), with
#   /repo    this repository, read-only
#   /corpus  a checkout of the r0-open corpus revision, read-only (tests/fetch_corpus.sh)
#   /work    outputs of tests/run.sh: out/<id>/secondary.step, secondary.status.json,
#            read.libredwg.json and verify/<id>.verification.json written by the step_eval image
import json
import math
import os
import struct
import subprocess
import tempfile

REPO = os.environ.get("REPO", "/repo")
CORPUS = os.environ.get("CORPUS", "/corpus")
WORK = os.environ.get("WORK", "/work")
SANITY = 1e-9  # for derived values only; stored values are compared bit for bit


def fixture_ids():
    d = os.path.join(CORPUS, "fixtures")
    return sorted(n for n in os.listdir(d) if os.path.isfile(os.path.join(d, n, "source.dwg")))


# Probes whose expected outcome is "no curve": the converter must refuse them (exit 15).
REFUSED = {"near-singular-001": 15}


def converted_ids():
    return [f for f in fixture_ids() if f not in REFUSED]


def dwg(fid):
    return os.path.join(CORPUS, "fixtures", fid, "source.dwg")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def expected(fid):
    return load_json(os.path.join(CORPUS, "fixtures", fid, "expected.math.json"))


def verification(fid):
    return load_json(os.path.join(WORK, "verify", fid + ".verification.json"))


def out_path(fid, name):
    return os.path.join(WORK, "out", fid, name)


def hex_to_float(h):
    return struct.unpack(">d", struct.pack(">Q", int(h, 16)))[0]


def scalar(s):
    return hex_to_float(s["f64_hex"])


def run(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def convert(src, out, status=None):
    cmd = ["dwg2step", "--in", src, "--out", out]
    if status:
        cmd += ["--status", status]
    return run(cmd)


def scratch():
    return tempfile.TemporaryDirectory(prefix="pvec-oracle-test-")


def close(a, b, scale=1.0):
    return math.isclose(a, b, rel_tol=0.0, abs_tol=SANITY * max(1.0, abs(scale)))
