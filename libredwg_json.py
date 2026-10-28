# pvec-oracle-libredwg: read a DWG through GNU LibreDWG's `dwgread -O JSON`.
#
# Copyright (C) the pvec-oracle-libredwg authors.
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Both dwg2step.py and dwgdump.py go through this module, so they see one decoder and one
# way of walking the object graph. It runs the patched dwgread (reals with 17 significant
# digits, see patches/0001) as a child process and parses the JSON it writes.
import hashlib
import json
import os
import re
import struct
import subprocess
import tempfile

DWGREAD = os.environ.get("DWGREAD", "dwgread-exact")
LIBREDWG_VERSION = os.environ.get("LIBREDWG_VERSION", "0.14")
READER_ID = "LibreDWG@%s+patch0001" % LIBREDWG_VERSION

# Exit codes shared by the converters (the status record's vocabulary).
BAD_ARGUMENTS, INPUT_UNREADABLE, INPUT_MALFORMED, VERSION_UNSUPPORTED = 10, 11, 12, 13
CONVERSION_FAILED, OUTPUT_NOT_WRITTEN, SCHEMA_NOT_AP242, INTERNAL = 15, 16, 17, 20
CLASS_OF = {
    10: "BAD_ARGUMENTS", 11: "INPUT_UNREADABLE", 12: "INPUT_MALFORMED", 13: "DWG_VERSION_UNSUPPORTED",
    15: "CONVERSION_FAILED", 16: "OUTPUT_NOT_WRITTEN", 17: "SCHEMA_NOT_AP242", 20: "INTERNAL",
}


class Failure(Exception):
    """A run that ends with one of the shared exit codes."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def f64_hex(x):
    """The bit pattern of a binary64 value, the way the read records spell it."""
    return "0x%016x" % struct.unpack(">Q", struct.pack(">d", float(x)))[0]


def _magic(path):
    with open(path, "rb") as f:
        return f.read(6)


def run_dwgread(path):
    """Decode a DWG. Returns (JSON tree, decoder warnings). Raises Failure with 11, 12 or 13 when it cannot."""
    if not (os.path.isfile(path) and os.access(path, os.R_OK)):
        raise Failure(INPUT_UNREADABLE, "cannot read input")
    magic = _magic(path).decode("latin-1")
    with tempfile.TemporaryDirectory(prefix="dwgread-") as tmp:
        out = os.path.join(tmp, "out.json")
        try:
            r = subprocess.run([DWGREAD, "-O", "JSON", "-o", out, path], capture_output=True, timeout=600)
        except FileNotFoundError:
            raise Failure(INTERNAL, "%s is not installed" % DWGREAD)
        except subprocess.TimeoutExpired:
            raise Failure(CONVERSION_FAILED, "dwgread timed out")
        err = r.stderr.decode("utf-8", "replace")
        if r.returncode != 0 or not os.path.exists(out):
            tail = " ".join(err.split())[-300:]
            if "unimplemented DWG version" in err and re.fullmatch(r"AC10\d\d|AC1\.\d+|AC2\.\d+", magic):
                raise Failure(VERSION_UNSUPPORTED, "DWG version %s is not read by LibreDWG" % magic)
            if "0x1000" in err and "ERROR 0x1000" in err:
                raise Failure(INPUT_UNREADABLE, "dwgread could not open the input")
            raise Failure(INPUT_MALFORMED, "dwgread: " + tail)
        try:
            with open(out, "r", encoding="utf-8") as f:
                tree = json.load(f)
        except (ValueError, OSError) as e:
            raise Failure(INPUT_MALFORMED, "dwgread wrote JSON that does not parse: %s" % e)
    # what the decoder says about what it skipped or could not read; SUCCESS and blank lines are not
    warnings = []
    for line in err.splitlines():
        line = line.strip()
        if line and line != "SUCCESS" and line not in warnings:
            warnings.append("dwgread: " + line)
    return tree, warnings


def num(x):
    """JSON integers and floats alike become floats."""
    return float(x)


def vec(v, n=3):
    out = [num(c) for c in v]
    return (out + [0.0] * n)[:n]


class Drawing:
    """Handles resolved: block table, layer table, entity lists per block."""

    def __init__(self, tree, warnings=()):
        self.tree = tree
        self.decoder_warnings = list(warnings)
        self.version = tree.get("FILEHEADER", {}).get("version")
        if not self.version:
            raise Failure(INPUT_MALFORMED, "no file header in the decoded tree")
        self.by_handle = {}
        for o in tree.get("OBJECTS", []):
            h = o.get("handle")
            if h:
                self.by_handle[h[2]] = o
        self.layers = []
        self.blocks = {}  # name -> block header object, in table order
        for o in tree.get("OBJECTS", []):
            if o.get("object") == "LAYER":
                flag = int(o.get("flag0", 0))
                self.layers.append({"name": o["name"], "frozen": bool(flag & 1), "on": not (flag & 2)})
            elif o.get("object") == "BLOCK_HEADER":
                self.blocks[o["name"]] = o

    def ref(self, r):
        """The object a handle reference [code, size, value, absolute] points at."""
        if not r or len(r) < 4 or r[3] == 0:
            return None
        return self.by_handle.get(r[3])

    def layer_name(self, entity):
        o = self.ref(entity.get("layer"))
        return o["name"] if o is not None else "0"

    def block_name(self, insert):
        o = self.ref(insert.get("block_header"))
        if o is None:
            raise Failure(CONVERSION_FAILED, "INSERT points at no block")
        return o["name"]

    def chain(self, first, last, stop_at=None):
        """R2000 has no entity arrays: a block header names its first and last entity and every entity names the next
        one. Follows next_entity from first, and gives up at a null link, at last, or on a loop."""
        out, seen = [], set()
        o = self.ref(first)
        while o is not None and o["handle"][2] not in seen:
            seen.add(o["handle"][2])
            out.append(o)
            if last and o["handle"][2] == last[3]:
                break
            o = self.ref(o.get("next_entity"))
        return out

    def entities(self, block_name):
        """Entities of one block in the order the block lists them."""
        hdr = self.blocks[block_name]
        if "entities" not in hdr and "first_entity" in hdr:
            return self.chain(hdr["first_entity"], hdr.get("last_entity"))
        out = []
        for r in hdr.get("entities", []):
            o = self.ref(r)
            if o is not None:
                out.append(o)
        return out

    def vertices_2d(self, polyline):
        if "vertex" not in polyline and "first_vertex" in polyline:
            return [o for o in self.chain(polyline["first_vertex"], polyline.get("last_vertex")) if o.get("entity") == "VERTEX_2D"]
        out = []
        for r in polyline.get("vertex", []):
            o = self.ref(r)
            if o is not None and o.get("entity") == "VERTEX_2D":
                out.append(o)
        return out


def load(path):
    return Drawing(*run_dwgread(path))
