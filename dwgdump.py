#!/usr/bin/env python3
# pvec-oracle-libredwg: dwgdump, the third cross-read.
#
# Copyright (C) the pvec-oracle-libredwg authors.
# SPDX-License-Identifier: GPL-3.0-or-later
#
#   dwgdump.py --in source.dwg --out read.libredwg.json
#
# Writes one DWG read record, schema "pvec-gold/r0-open-dwg-read/2": the blocks with their
# entities, the layers, the DWG version and the SHA-256 of the input, every real as the hex of its
# binary64 bits. It is the same record the other two open readers write, so the cross-read rule of
# ADR 0008 can take a third reader that does not share their lineage.
#
# Exit codes are the converters' (0 ok, 10 bad arguments, 11 input unreadable, 12 malformed,
# 13 version unsupported, 20 internal). The record is written under a temporary name and moved
# into place only when it is complete, so a failed run leaves no record, not even a stale one.
import json
import os
import sys

import libredwg_json as lj
from libredwg_json import Failure, f64_hex, vec

SCHEMA = "pvec-gold/r0-open-dwg-read/2"
SKIPPED_BLOCK_PREFIXES = ("*Paper_Space",)


def hx(v):
    return [f64_hex(c) for c in v]


def entity_record(dwg, e):
    kind = e.get("entity")
    rec = {"type": kind, "layer": dwg.layer_name(e)}
    normal = vec(e["extrusion"]) if "extrusion" in e else [0.0, 0.0, 1.0]
    if kind == "LINE":
        rec["start"], rec["end"] = hx(vec(e["start"])), hx(vec(e["end"]))
    elif kind == "CIRCLE":
        rec["center"], rec["radius"], rec["normal"] = hx(vec(e["center"])), f64_hex(e["radius"]), hx(normal)
    elif kind == "ARC":
        rec["center"], rec["radius"], rec["normal"] = hx(vec(e["center"])), f64_hex(e["radius"]), hx(normal)
        rec["start_angle"], rec["end_angle"] = f64_hex(e["start_angle"]), f64_hex(e["end_angle"])
    elif kind == "ELLIPSE":
        rec["center"], rec["major_axis"], rec["normal"] = hx(vec(e["center"])), hx(vec(e["sm_axis"])), hx(normal)
        rec["ratio"] = f64_hex(e["axis_ratio"])
        rec["start_param"], rec["end_param"] = f64_hex(e["start_angle"]), f64_hex(e["end_angle"])
    elif kind == "LWPOLYLINE":
        pts, bulges = e.get("points", []), e.get("bulges", [])
        rec["closed"] = bool(int(e.get("flag", 0)) & 512)
        rec["elevation"] = f64_hex(e.get("elevation", 0.0))
        rec["normal"] = hx(normal)
        rec["vertices"] = [hx([p[0], p[1], bulges[i] if i < len(bulges) else 0.0]) for i, p in enumerate(pts)]
    elif kind == "POLYLINE_2D":
        rec["type"] = "POLYLINE"
        rec["closed"] = bool(int(e.get("flag", 0)) & 1)
        rec["elevation"] = f64_hex(e.get("elevation", 0.0))
        rec["normal"] = hx(normal)
        rec["vertices"] = [hx([v["point"][0], v["point"][1], v.get("bulge", 0.0)]) for v in dwg.vertices_2d(e)]
    elif kind == "SPLINE":
        pts = e.get("ctrl_pts", [])
        rational = bool(int(e.get("rational", 0)))
        rec["degree"] = int(e["degree"])
        rec["control_points"] = [hx([p["x"], p["y"], p["z"]]) for p in pts]
        rec["knots"] = hx(e.get("knots", []))
        rec["weights"] = [f64_hex(p.get("w", 1.0)) for p in pts] if rational else []
        rec["rational"] = rational
        rec["closed"] = bool(int(e.get("closed_b", 0)))
        rec["periodic"] = bool(int(e.get("periodic", 0)))
        rec["fit_point_count"] = len(e.get("fit_pts", []))
        rec["normal"] = hx([0.0, 0.0, 1.0])
    elif kind == "INSERT":
        rec["block"] = dwg.block_name(e)
        rec["insert_point"], rec["normal"] = hx(vec(e["ins_pt"])), hx(normal)
        rec["rotation"], rec["scale"] = f64_hex(e.get("rotation", 0.0)), hx(vec(e.get("scale", [1, 1, 1])))
    else:
        # Outside the shape the record defines. It is listed, so a reader that skips something
        # does not look the same as a drawing that has nothing there.
        rec["unread"] = True
    return rec


def record_for(path):
    dwg = lj.load(path)
    blocks = []
    for name in sorted(dwg.blocks):
        if name.startswith(SKIPPED_BLOCK_PREFIXES):
            continue
        ents = [e for e in dwg.entities(name)]
        blocks.append({"name": name, "entities": [entity_record(dwg, e) for e in ents]})
    layers = sorted(dwg.layers, key=lambda l: l["name"])
    return {
        "blocks": blocks,
        "dwg_sha256": lj.sha256_file(path),
        "dwg_version": dwg.version,
        "layers": [{"frozen": l["frozen"], "name": l["name"], "on": l["on"]} for l in layers],
        "reader": lj.READER_ID,
        "schema": SCHEMA,
    }


def main(argv):
    src = out = None
    i = 0
    while i < len(argv):
        if argv[i] == "--in" and i + 1 < len(argv):
            src, i = argv[i + 1], i + 2
        elif argv[i] == "--out" and i + 1 < len(argv):
            out, i = argv[i + 1], i + 2
        else:
            src = out = None
            break
    if not src or not out:
        sys.stderr.write("usage: dwgdump.py --in source.dwg --out read.libredwg.json\n")
        return lj.BAD_ARGUMENTS
    if os.path.lexists(out):
        os.remove(out)
    tmp = "%s.partial.%d" % (out, os.getpid())
    try:
        rec = record_for(src)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, out)
        return 0
    except Failure as e:
        sys.stderr.write("dwgdump: %s\n" % e.message)
        return e.code
    except Exception as e:  # a bug here must not leave a half record
        sys.stderr.write("dwgdump: internal error: %s: %s\n" % (type(e).__name__, e))
        return lj.INTERNAL
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
