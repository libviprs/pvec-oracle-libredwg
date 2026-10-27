# What this repository is made of: GPL code only, nothing taken from the permissive repositories,
# the LibreDWG source pinned, and the boundary stated.
import hashlib
import os
import re
import subprocess
import unittest

from common import REPO, dwg, load_json, run

LIBREDWG_DOCS = "/usr/share/doc/pvec-oracle-libredwg"


def tracked_files():
    """Files of this repository, without .git."""
    out = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d != ".git"]
        for f in files:
            out.append(os.path.join(root, f))
    return sorted(out)


def read(path):
    with open(os.path.join(REPO, path), encoding="utf-8") as f:
        return f.read()


class NothingIsCopied(unittest.TestCase):
    def test_no_file_in_this_repo_is_copied_from_a_permissive_repo(self):
        known = {}
        with open(os.path.join(REPO, "tests", "permissive-hashes.txt"), encoding="utf-8") as f:
            for line in f:
                h, _, where = line.strip().partition(" ")
                known[h] = where
        self.assertGreater(len(known), 1000, "the hash list is missing or truncated")
        self.assertTrue(any(w.startswith("pvec-gold-fixtures@") for w in known.values()))
        self.assertTrue(any(w.startswith("pvec@") for w in known.values()))
        for p in tracked_files():
            if os.path.relpath(p, REPO) == os.path.join("tests", "permissive-hashes.txt") or os.path.getsize(p) < 64:
                continue
            with open(p, "rb") as f:
                h = hashlib.sha256(f.read()).hexdigest()
            self.assertNotIn(h, known, "%s is byte for byte %s" % (os.path.relpath(p, REPO), known.get(h)))

    def test_nothing_is_imported_from_or_built_against_the_permissive_repos(self):
        pat = re.compile(r"(from|import)\s+(runner|schema|validator)\b|pvec-gold-fixtures/|libviprs/pvec/|git\s+(clone|submodule)", re.I)
        for p in tracked_files():
            rel = os.path.relpath(p, REPO)
            if rel.startswith("tests/permissive-hashes") or rel in ("README.md", "docs/qualification.md") or rel.startswith("tests/test_provenance"):
                continue
            if rel.endswith((".py", ".sh", "Dockerfile")):
                self.assertIsNone(pat.search(read(rel)), rel)
        self.assertFalse(os.path.exists(os.path.join(REPO, ".gitmodules")))

    def test_the_dockerfile_copies_only_from_this_repository(self):
        for line in read("Dockerfile").splitlines():
            if line.startswith("COPY ") and "--from=" not in line:
                for src in line.split()[1:-1]:
                    self.assertTrue(os.path.exists(os.path.join(REPO, src)), src)
                    self.assertFalse(src.startswith(("/", "..")), src)

    def test_every_source_file_names_the_licence(self):
        for rel in ("dwg2step.py", "dwgdump.py", "libredwg_json.py"):
            self.assertIn("SPDX-License-Identifier: GPL-3.0-or-later", read(rel), rel)

    def test_the_licence_file_is_gpl_3(self):
        t = read("LICENSE")
        self.assertIn("GNU GENERAL PUBLIC LICENSE", t)
        self.assertIn("Version 3", t)

    def test_nothing_here_names_how_the_work_was_produced(self):
        words = ["Cla" + "ude", "Anthro" + "pic", "Co-Authored" + "-By", "Generated " + "with", "language " + "model"]
        for p in tracked_files():
            rel = os.path.relpath(p, REPO)
            if rel.startswith("tests/permissive-hashes"):
                continue
            try:
                t = open(p, encoding="utf-8").read()
            except UnicodeDecodeError:
                continue
            if rel == "LICENSE":
                continue
            for w in words:
                self.assertNotIn(w.lower(), t.lower(), "%s mentions %s" % (rel, w))
            self.assertNotIn("—", t, "%s has an em dash" % rel)


class Pinned(unittest.TestCase):
    def test_the_inputs_of_the_build_are_pinned(self):
        d = read("Dockerfile")
        self.assertRegex(d, r"ARG BASE=debian:bookworm-slim@sha256:[0-9a-f]{64}")
        sha = re.search(r"ARG LIBREDWG_SHA256=([0-9a-f]{64})", d)
        self.assertIsNotNone(sha)
        self.assertIn('sha256sum -c -', d)
        self.assertRegex(d, r"ARG LIBREDWG_URL=https://ftp\.gnu\.org/gnu/libredwg/libredwg-\$\{LIBREDWG_VERSION\}\.tar\.xz")

    def test_the_source_that_travels_in_the_image_is_the_pinned_tarball(self):
        sha = re.search(r"ARG LIBREDWG_SHA256=([0-9a-f]{64})", read("Dockerfile")).group(1)
        ver = re.search(r"ARG LIBREDWG_VERSION=(\S+)", read("Dockerfile")).group(1)
        tar = os.path.join(LIBREDWG_DOCS, "source", "libredwg-%s.tar.xz" % ver)
        self.assertEqual(hashlib.sha256(open(tar, "rb").read()).hexdigest(), sha)
        self.assertTrue(os.path.exists(os.path.join(LIBREDWG_DOCS, "source", "patches", "0001-json-doubles-17-significant-digits.patch")))
        self.assertIn("GNU GENERAL PUBLIC LICENSE", open(os.path.join(LIBREDWG_DOCS, "COPYING.libredwg"), encoding="utf-8").read())
        self.assertIn("GNU GENERAL PUBLIC LICENSE", open(os.path.join(LIBREDWG_DOCS, "COPYING"), encoding="utf-8").read())

    def test_the_binaries_report_the_pinned_version(self):
        ver = re.search(r"ARG LIBREDWG_VERSION=(\S+)", read("Dockerfile")).group(1)
        for exe in ("dwgread", "dwgread-exact"):
            r = run([exe, "--version"])
            self.assertIn(ver, r.stdout + r.stderr, exe)

    def test_stock_json_loses_bits_the_patched_build_keeps(self):
        # arc-seam-001 stores an end angle whose 14-decimal print is not the stored double
        src = dwg("arc-seam-001")
        import tempfile, json, struct
        want = load_json(os.path.join(os.path.dirname(src), "read.acadsharp.json"))["blocks"][0]["entities"][0]["end_angle"]
        got = {}
        with tempfile.TemporaryDirectory() as tmp:
            for exe in ("dwgread", "dwgread-exact"):
                out = os.path.join(tmp, exe + ".json")
                self.assertEqual(run([exe, "-O", "JSON", "-o", out, src]).returncode, 0)
                arc = [o for o in load_json(out)["OBJECTS"] if o.get("entity") == "ARC"][0]
                got[exe] = "0x%016x" % struct.unpack(">Q", struct.pack(">d", float(arc["end_angle"])))[0]
        self.assertNotEqual(got["dwgread"], want)
        self.assertEqual(got["dwgread-exact"], want)


class Boundary(unittest.TestCase):
    def test_the_readme_states_the_boundary(self):
        t = read("README.md")
        for needle in ("GPL-3.0-or-later", "GNU LibreDWG", "files", "process", "digest"):
            self.assertIn(needle, t)
        self.assertRegex(t.lower(), r"nothing .*(copied|imported)")


if __name__ == "__main__":
    unittest.main()
