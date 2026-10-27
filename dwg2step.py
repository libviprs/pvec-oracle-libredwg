#!/usr/bin/env python3
# pvec-oracle-libredwg: dwg2step, DWG to STEP AP242 on top of GNU LibreDWG.
#
# Copyright (C) the pvec-oracle-libredwg authors.
# SPDX-License-Identifier: GPL-3.0-or-later
#
#   dwg2step.py --in source.dwg --out secondary.step [--status secondary.status.json]
#
# Reads the drawing through `dwgread -O JSON` (see libredwg_json.py), flattens every INSERT chain of
# model space into world coordinates and writes a small, explicit Part 21 subset:
#
#   LINE, CIRCLE, ELLIPSE, TRIMMED_CURVE, B_SPLINE_CURVE_WITH_KNOTS and the RATIONAL_B_SPLINE_CURVE
#   complex entity, AXIS2_PLACEMENT_3D, GEOMETRIC_CURVE_SET
#
# with every real written at 17 significant digits. It links no geometry kernel. Nothing here
# decides two numbers are equal within a tolerance: the only comparisons are exact ones on the
# values the DWG stored, and a transform is carried as an exact rational matrix and rounded once.
#
# Flattening rule: the world matrix of a nested instance is M0 * M1 * ... * Mn, outermost first,
# the parent on the left. STEP carries a uniform scale only, so a non-uniform scale is applied to
# the curve: a circle becomes an ellipse, a pole maps exactly under any affine map, a reflection
# reverses orientation (the circle's normal flips, so it stays counter-clockwise about its own
# normal) and nothing is written as a transform.
#
# A status record (pvec-gold/converter-status/1) is written beside the output whether the run
# worked or not, and a failed run leaves no STEP file, not even a stale one. Exit codes: 0 ok,
# 10 bad arguments, 11 input missing or unreadable, 12 input malformed, 13 DWG version unsupported,
# 15 conversion failed, 16 output not produced, 17 declared schema is not AP242, 20 internal error.
import json
import math
import os
import re
import sys
import time
from decimal import Decimal, getcontext
from fractions import Fraction

import libredwg_json as lj
from libredwg_json import Failure, vec

getcontext().prec = 80

CONVERTER_ID = "libredwg-dwg2step"
PRODUCT_NAME = "pvec-oracle-libredwg dwg2step"
PRODUCT_VERSION = "1 (LibreDWG %s+patch0001)" % lj.LIBREDWG_VERSION
SCHEMA_ID = "AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF { 1 0 10303 442 1 1 4 }"
TAU = 2.0 * math.pi
MAX_DEPTH = 32
# NP-19 of the PVec numeric policy refuses an affine map whose |ad - bc| <= REL * big^2, with a, b, c, d
# the plane entries of the matrix and big the largest of them. REL is the policy's own constant
# (constants.REL in pvec-numeric-policy.v1.json); this is a named copy, pinned to the policy file by
# tests/test_near_singular.py, not a number of mine.
NP19_REL = Fraction(1, 10 ** 10)

# ---- exact helpers --------------------------------------------------------------------------


def fr(x):
    return Fraction(x)


def to_f(q):
    return float(q)  # int/int true division in Python is correctly rounded


def fsqrt(q):
    """Square root of a non-negative Fraction, rounded once to binary64."""
    q = Fraction(q)
    if q < 0:
        raise Failure(lj.INTERNAL, "square root of a negative number")
    return float((Decimal(q.numerator) / Decimal(q.denominator)).sqrt())


def dot(a, b):
    return sum((x * y for x, y in zip(a, b)), Fraction(0))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def unit_f(v):
    """Unit vector of a Fraction vector, as floats (each component rounded once)."""
    n = Decimal(dot(v, v).numerator) / Decimal(dot(v, v).denominator)
    n = n.sqrt()
    if n == 0:
        raise Failure(lj.CONVERSION_FAILED, "zero-length axis")
    return tuple(float(Decimal(c.numerator) / Decimal(c.denominator) / n) for c in v)


def fvec(v):
    return tuple(fr(c) for c in v)


def fl_vec(v):
    return tuple(to_f(c) for c in v)


class Aff:
    """x -> A x + t over exact rationals. sim is the similarity factor when the matrix is a
    rotation times a uniform scale by construction (never found by comparing numbers)."""

    def __init__(self, A, t, sim, det_sign):
        self.A, self.t, self.sim, self.det_sign = A, t, sim, det_sign

    @staticmethod
    def identity():
        z, o = Fraction(0), Fraction(1)
        return Aff([[o, z, z], [z, o, z], [z, z, o]], (z, z, z), Fraction(1), 1)

    def point(self, p):
        return tuple(sum((self.A[i][j] * p[j] for j in range(3)), Fraction(0)) + self.t[i] for i in range(3))

    def vector(self, v):
        return tuple(sum((self.A[i][j] * v[j] for j in range(3)), Fraction(0)) for i in range(3))

    def then(self, inner):
        """self applied after inner: parent on the left."""
        A = [[sum((self.A[i][k] * inner.A[k][j] for k in range(3)), Fraction(0)) for j in range(3)] for i in range(3)]
        t = tuple(a + b for a, b in zip(self.vector(inner.t), self.t))
        sim = self.sim * inner.sim if (self.sim is not None and inner.sim is not None) else None
        return Aff(A, t, sim, self.det_sign * inner.det_sign)

    def det(self):
        A = self.A
        return (A[0][0] * (A[1][1] * A[2][2] - A[1][2] * A[2][1])
                - A[0][1] * (A[1][0] * A[2][2] - A[1][2] * A[2][0])
                + A[0][2] * (A[1][0] * A[2][1] - A[1][1] * A[2][0]))


def near_singular(m):
    """NP-19 on the x/y entries of an exact matrix. Exact arithmetic, so no rounding decides it."""
    a, b, c, d = m.A[0][0], m.A[0][1], m.A[1][0], m.A[1][1]
    big = max(abs(a), abs(b), abs(c), abs(d))
    return abs(a * d - b * c) <= NP19_REL * big * big


def ocs_axes(normal):
    """The arbitrary axis algorithm: the OCS x and y axes for an extrusion direction."""
    n = tuple(normal)
    ln = math.sqrt(sum(c * c for c in n))
    if ln == 0:
        raise Failure(lj.CONVERSION_FAILED, "zero extrusion vector")
    n = tuple(c / ln for c in n) if ln != 1.0 else n
    if abs(n[0]) < 1.0 / 64 and abs(n[1]) < 1.0 / 64:
        ax = cross((Fraction(0), Fraction(1), Fraction(0)), fvec(n))
    else:
        ax = cross((Fraction(0), Fraction(0), Fraction(1)), fvec(n))
    ax = unit_f(ax)
    ay = fl_vec(cross(fvec(n), fvec(ax)))
    return ax, ay, n


def ocs_to_wcs(frame, p):
    ax, ay, n = frame
    return tuple(ax[i] * p[0] + ay[i] * p[1] + n[i] * p[2] for i in range(3))


def insert_affine(ins, base_pt):
    sx, sy, sz = vec(ins.get("scale", [1, 1, 1]))
    rot = float(ins.get("rotation", 0.0))
    frame = ocs_axes(vec(ins["extrusion"]) if "extrusion" in ins else [0.0, 0.0, 1.0])
    c, s = (1.0, 0.0) if rot == 0.0 else (math.cos(rot), math.sin(rot))
    F = [[fr(frame[j][i]) for j in range(3)] for i in range(3)]  # columns are ax, ay, n
    RS = [[fr(c) * fr(sx), -fr(s) * fr(sy), Fraction(0)],
          [fr(s) * fr(sx), fr(c) * fr(sy), Fraction(0)],
          [Fraction(0), Fraction(0), fr(sz)]]
    A = [[sum((F[i][k] * RS[k][j] for k in range(3)), Fraction(0)) for j in range(3)] for i in range(3)]
    ip = fvec(vec(ins["ins_pt"]))
    t0 = tuple(sum((F[i][k] * ip[k] for k in range(3)), Fraction(0)) for i in range(3))
    base = fvec(base_pt)
    t = tuple(t0[i] - sum((A[i][k] * base[k] for k in range(3)), Fraction(0)) for i in range(3))
    sim = abs(fr(sx)) if (abs(sx) == abs(sy) == abs(sz)) else None
    sign = (1 if sx > 0 else -1) * (1 if sy > 0 else -1) * (1 if sz > 0 else -1)
    return Aff(A, t, sim, sign)


# ---- curves (all in world coordinates, floats) ---------------------------------------------
# line     {"t": "line", "p0", "p1"}
# circle   {"t": "circle", "c", "n", "x", "r", "t0", "t1"}
# ellipse  {"t": "ellipse", "c", "n", "x", "a", "b", "t0", "t1"}
# spline   {"t": "spline", "degree", "poles", "weights" (None or list), "knots" (expanded), "closed"}


def line(p0, p1):
    return {"t": "line", "p0": tuple(p0), "p1": tuple(p1)}


def arc_end(a0, a1):
    return a1 if a1 > a0 else a1 + TAU


def from_dwg_conic(frame, e, kind):
    """CIRCLE, ARC and ELLIPSE entities in their own coordinates."""
    if kind == "ELLIPSE":
        n = tuple(vec(e["extrusion"])) if "extrusion" in e else (0.0, 0.0, 1.0)
        m = fvec(vec(e["sm_axis"]))
        a = fsqrt(dot(m, m))
        if a == 0.0:
            raise Failure(lj.CONVERSION_FAILED, "ELLIPSE with a zero major axis")
        t0, t1 = float(e.get("start_angle", 0.0)), float(e.get("end_angle", TAU))
        return {"t": "ellipse", "c": tuple(vec(e["center"])), "n": n, "x": unit_f(m),
                "a": a, "b": a * float(e["axis_ratio"]), "t0": t0, "t1": arc_end(t0, t1)}
    ax, _ay, n = frame
    c = ocs_to_wcs(frame, vec(e["center"]))
    if kind == "CIRCLE":
        return {"t": "circle", "c": c, "n": n, "x": ax, "r": float(e["radius"]), "t0": 0.0, "t1": TAU}
    t0, t1 = float(e["start_angle"]), float(e["end_angle"])
    return {"t": "circle", "c": c, "n": n, "x": ax, "r": float(e["radius"]), "t0": t0, "t1": arc_end(t0, t1)}


def from_polyline(frame, points, bulges, closed, elevation):
    """Separate line and arc edges. A bulge b is tan(sweep/4); positive is counter-clockwise."""
    out = []
    n = len(points)
    last = n if closed else n - 1
    for i in range(last):
        p0, p1 = points[i], points[(i + 1) % n]
        b = bulges[i] if i < len(bulges) else 0.0
        w0 = ocs_to_wcs(frame, (p0[0], p0[1], elevation))
        w1 = ocs_to_wcs(frame, (p1[0], p1[1], elevation))
        if p0[0] == p1[0] and p0[1] == p1[1]:
            continue  # a zero-length segment has no direction
        if b == 0.0:
            out.append(line(w0, w1))
            continue
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        chord = math.hypot(dx, dy)
        k = (chord / 2.0) * (1.0 - b * b) / (2.0 * b)
        mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
        cx, cy = mid[0] + (-dy / chord) * k, mid[1] + (dx / chord) * k
        r = math.hypot(k, chord / 2.0)
        sweep = 4.0 * math.atan(abs(b))
        wc = ocs_to_wcs(frame, (cx, cy, elevation))
        xdir = unit_f(fvec(tuple(a - c for a, c in zip(w0, wc))))
        n_w = frame[2] if b > 0 else tuple(-c for c in frame[2])
        out.append({"t": "circle", "c": wc, "n": n_w, "x": xdir, "r": r, "t0": 0.0, "t1": sweep})
    return out


def from_spline(e):
    pts = e.get("ctrl_pts", [])
    knots = [float(k) for k in e.get("knots", [])]
    if not pts or not knots:
        raise Failure(lj.CONVERSION_FAILED, "SPLINE without control points and knots (fit-point spline)")
    deg = int(e["degree"])
    poles = [(float(p["x"]), float(p["y"]), float(p["z"])) for p in pts]
    rational = bool(int(e.get("rational", 0)))
    weights = [float(p.get("w", 1.0)) for p in pts] if rational else None
    n = len(poles)
    if bool(int(e.get("periodic", 0))) and len(knots) == n + 1:
        # A periodic spline stores the unique poles and one knot per pole plus one. STEP via OCCT
        # reads it as non-periodic, so the wrap is written out: n + deg poles (copies of the unique
        # ones) and the knot vector continued by the period on both sides. Only the continued
        # knots are derived, each rounded once from an exact sum; the written curve's parameter
        # domain is the authored one.
        period = fr(knots[-1]) - fr(knots[0])
        ext = []
        for i in range(-deg, n + deg + 1):
            if i < 0:
                ext.append(to_f(fr(knots[i + n]) - period))
            elif i <= n:
                ext.append(knots[i])
            else:
                ext.append(to_f(fr(knots[i - n]) + period))
        # pole j of the written curve is influenced by knots j-deg .. j+1 of the periodic vector, so
        # it is unique pole (j - deg) mod n
        order = [(j - deg) % n for j in range(n + deg)]
        poles = [poles[i] for i in order]
        weights = [weights[i] for i in order] if weights is not None else None
        knots = ext
    if len(knots) != len(poles) + deg + 1:
        raise Failure(lj.CONVERSION_FAILED, "SPLINE knot count %d does not fit %d poles of degree %d" % (len(knots), len(poles), deg))
    return {"t": "spline", "degree": deg, "poles": poles, "weights": weights, "knots": knots}


# ---- transforms of curves ------------------------------------------------------------------


def apply_affine(curve, m):
    t = curve["t"]
    if t == "line":
        return line(fl_vec(m.point(fvec(curve["p0"]))), fl_vec(m.point(fvec(curve["p1"]))))
    if t == "spline":
        poles = [fl_vec(m.point(fvec(p))) for p in curve["poles"]]
        return dict(curve, poles=poles)
    c = m.point(fvec(curve["c"]))
    x, n = fvec(curve["x"]), fvec(curve["n"])
    y = cross(n, x)
    if t == "circle":
        r = fr(curve["r"])
        if m.sim is not None:
            u, v = m.vector(tuple(r * k for k in x)), m.vector(tuple(r * k for k in y))
            ux = unit_f(m.vector(x))
            nrm = unit_f(cross(u, v))
            return {"t": "circle", "c": fl_vec(c), "n": nrm, "x": ux, "r": fsqrt(r * r * m.sim * m.sim),
                    "t0": curve["t0"], "t1": curve["t1"]}
        a = b = r
    else:
        a, b = fr(curve["a"]), fr(curve["b"])
    u, v = m.vector(tuple(a * k for k in x)), m.vector(tuple(b * k for k in y))
    w = cross(u, v)
    if w == (0, 0, 0):
        raise Failure(lj.CONVERSION_FAILED, "an instance flattens a curve onto a line (singular in the curve's plane)")
    uf, vf = fl_vec(u), fl_vec(v)
    uu, vv, uv = to_f(dot(u, u)), to_f(dot(v, v)), to_f(dot(u, v))
    t_off = 0.5 * math.atan2(2.0 * uv, uu - vv)
    ct, st = math.cos(t_off), math.sin(t_off)
    av = tuple(uf[i] * ct + vf[i] * st for i in range(3))
    bv = tuple(-uf[i] * st + vf[i] * ct for i in range(3))
    la, lb = math.sqrt(sum(k * k for k in av)), math.sqrt(sum(k * k for k in bv))
    if la >= lb:
        major, minor, shift = av, bv, t_off
    else:
        major, minor, shift = bv, tuple(-k for k in av), t_off + math.pi / 2.0
    lmaj, lmin = math.sqrt(sum(k * k for k in major)), math.sqrt(sum(k * k for k in minor))
    if lmin == 0.0:
        raise Failure(lj.CONVERSION_FAILED, "an instance flattens a curve onto a line")
    nrm = unit_f(cross(fvec(major), fvec(minor)))
    return {"t": "ellipse", "c": fl_vec(c), "n": nrm, "x": unit_f(fvec(major)), "a": lmaj, "b": lmin,
            "t0": curve["t0"] - shift, "t1": curve["t1"] - shift}


# ---- walking the drawing --------------------------------------------------------------------


def flatten(dwg, block, m, stack, curves, warnings):
    if len(stack) > MAX_DEPTH:
        raise Failure(lj.CONVERSION_FAILED, "INSERT nesting deeper than %d" % MAX_DEPTH)
    if block in stack:
        raise Failure(lj.CONVERSION_FAILED, "INSERT cycle through block %s" % block)
    identity = m is None
    for e in dwg.entities(block):
        kind = e.get("entity")
        frame = None
        if kind in ("CIRCLE", "ARC", "LWPOLYLINE", "POLYLINE_2D"):
            frame = ocs_axes(vec(e["extrusion"]) if "extrusion" in e else [0.0, 0.0, 1.0])
        out = []
        if kind == "LINE":
            out = [line(vec(e["start"]), vec(e["end"]))]
        elif kind in ("CIRCLE", "ARC"):
            out = [from_dwg_conic(frame, e, kind)]
        elif kind == "ELLIPSE":
            out = [from_dwg_conic(None, e, kind)]
        elif kind == "LWPOLYLINE":
            out = from_polyline(frame, [(p[0], p[1]) for p in e.get("points", [])], e.get("bulges", []),
                                bool(int(e.get("flag", 0)) & 512), float(e.get("elevation", 0.0)))
        elif kind == "POLYLINE_2D":
            vs = dwg.vertices_2d(e)
            out = from_polyline(frame, [(v["point"][0], v["point"][1]) for v in vs], [v.get("bulge", 0.0) for v in vs],
                                bool(int(e.get("flag", 0)) & 1), float(e.get("elevation", 0.0)))
        elif kind == "SPLINE":
            out = [from_spline(e)]
        elif kind == "INSERT":
            name = dwg.block_name(e)
            if name not in dwg.blocks:
                raise Failure(lj.CONVERSION_FAILED, "INSERT of unknown block %s" % name)
            level = insert_affine(e, vec(dwg.blocks[name].get("base_pt", [0, 0, 0])))
            if level.det() == 0:
                raise Failure(lj.CONVERSION_FAILED, "INSERT of %s has a singular matrix; no geometry is written for it" % name)
            total = level if identity else m.then(level)
            if near_singular(total):
                raise Failure(lj.CONVERSION_FAILED, "NEAR_SINGULAR_TRANSFORM: INSERT of %s maps the plane with |ad - bc| <= REL * big^2 (NP-19); no curve is written" % name)
            flatten(dwg, name, total, stack + [block], curves, warnings)
            continue
        else:
            warnings.append("skipped %s (handle %d) in block %s" % (kind, e["handle"][2], block))
            continue
        for c in out:
            curves.append(c if identity else apply_affine(c, m))


# ---- Part 21 --------------------------------------------------------------------------------


def real(x):
    x = float(x)
    if math.isnan(x) or math.isinf(x):
        raise Failure(lj.CONVERSION_FAILED, "a coordinate is not a finite number")
    s = "%.17g" % x
    if "e" in s:
        mant, exp = s.split("e")
        if "." not in mant:
            mant += "."
        return "%sE%s" % (mant, exp)
    return s if "." in s else s + "."


def tup(v):
    return "(" + ",".join(real(c) for c in v) + ")"


def runs(values):
    """Distinct consecutive values and their multiplicities, equal meaning the same bits."""
    vs, ms = [], []
    for k in values:
        if vs and vs[-1] == k:
            ms[-1] += 1
        else:
            vs.append(k)
            ms.append(1)
    return vs, ms


class Writer:
    def __init__(self):
        self.body = []
        self.n = 100
        self.curve_ids = []

    def add(self, text):
        i = self.n
        self.n += 1
        self.body.append("#%d=%s;" % (i, text))
        return i

    def point(self, p):
        return self.add("CARTESIAN_POINT('',%s)" % tup(p))

    def direction(self, d):
        return self.add("DIRECTION('',%s)" % tup(d))

    def axis(self, c, n, x):
        return self.add("AXIS2_PLACEMENT_3D('',#%d,#%d,#%d)" % (self.point(c), self.direction(n), self.direction(x)))

    def trimmed(self, basis, t0, t1):
        return self.add("TRIMMED_CURVE('',#%d,(PARAMETER_VALUE(%s)),(PARAMETER_VALUE(%s)),.T.,.PARAMETER.)" % (basis, real(t0), real(t1)))

    def curve(self, c):
        t = c["t"]
        if t == "line":
            d = fvec(tuple(b - a for a, b in zip(c["p0"], c["p1"])))
            length = fsqrt(dot(d, d))
            if length == 0.0:
                return False
            p = self.point(c["p0"])
            vec_id = self.add("VECTOR('',#%d,1.)" % self.direction(unit_f(d)))
            self.curve_ids.append(self.trimmed(self.add("LINE('',#%d,#%d)" % (p, vec_id)), 0.0, length))
        elif t == "circle":
            basis = self.add("CIRCLE('',#%d,%s)" % (self.axis(c["c"], c["n"], c["x"]), real(c["r"])))
            self.curve_ids.append(self.trimmed(basis, c["t0"], c["t1"]))
        elif t == "ellipse":
            basis = self.add("ELLIPSE('',#%d,%s,%s)" % (self.axis(c["c"], c["n"], c["x"]), real(c["a"]), real(c["b"])))
            self.curve_ids.append(self.trimmed(basis, c["t0"], c["t1"]))
        else:
            self.spline(c)
        return True

    def spline(self, c):
        pts = [self.point(p) for p in c["poles"]]
        plist = "(" + ",".join("#%d" % i for i in pts) + ")"
        ks, ms = runs(c["knots"])
        # closed_curve stays .F. even when the first and last pole are the same point: with .T. the
        # OCCT reader makes the curve periodic and drops the last pole, which would change a stored
        # value. Closure by endpoint is a property of the poles, and the evaluator reads it there.
        closed = ".F."
        klist = "(" + ",".join(str(m) for m in ms) + "),(" + ",".join(real(k) for k in ks) + ")"
        if c["weights"] is None:
            i = self.add("B_SPLINE_CURVE_WITH_KNOTS('',%d,%s,.UNSPECIFIED.,%s,.F.,%s,.UNSPECIFIED.)" % (c["degree"], plist, closed, klist))
        else:
            i = self.add("(BOUNDED_CURVE()B_SPLINE_CURVE(%d,%s,.UNSPECIFIED.,%s,.F.)B_SPLINE_CURVE_WITH_KNOTS(%s,.UNSPECIFIED.)"
                         "CURVE()GEOMETRIC_REPRESENTATION_ITEM()RATIONAL_B_SPLINE_CURVE(%s)REPRESENTATION_ITEM(''))"
                         % (c["degree"], plist, closed, klist, tup(c["weights"])))
        self.curve_ids.append(i)


def step_text(name, curves):
    w = Writer()
    for c in curves:
        w.curve(c)
    if not w.curve_ids:
        raise Failure(lj.CONVERSION_FAILED, "the drawing holds no curve this converter writes")
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(int(os.environ.get("SOURCE_DATE_EPOCH", "0"))))
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    head = [
        "ISO-10303-21;", "HEADER;",
        "FILE_DESCRIPTION(('dwg2step: %s'),'2;1');" % safe,
        "FILE_NAME('%s.step','%s',(''),(''),'%s','LibreDWG %s','');" % (safe, stamp, PRODUCT_NAME, lj.LIBREDWG_VERSION),
        "FILE_SCHEMA(('%s'));" % SCHEMA_ID,
        "ENDSEC;", "DATA;",
        "#1=APPLICATION_CONTEXT('managed model based 3d engineering');",
        "#2=APPLICATION_PROTOCOL_DEFINITION('international standard','ap242_managed_model_based_3d_engineering',2011,#1);",
        "#3=PRODUCT_CONTEXT('',#1,'mechanical');",
        "#4=PRODUCT('%s','%s','',(#3));" % (safe, safe),
        "#5=PRODUCT_DEFINITION_CONTEXT('part definition',#1,'design');",
        "#6=PRODUCT_DEFINITION_FORMATION('',' ',#4);",
        "#7=PRODUCT_DEFINITION('design','',#6,#5);",
        "#8=PRODUCT_DEFINITION_SHAPE('','',#7);",
        "#9=SHAPE_DEFINITION_REPRESENTATION(#8,#10);",
        "#10=GEOMETRICALLY_BOUNDED_WIREFRAME_SHAPE_REPRESENTATION('',(#11,#20),#30);",
        "#11=AXIS2_PLACEMENT_3D('',#12,#13,#14);",
        "#12=CARTESIAN_POINT('',(0.,0.,0.));",
        "#13=DIRECTION('',(0.,0.,1.));",
        "#14=DIRECTION('',(1.,0.,0.));",
        "#20=GEOMETRIC_CURVE_SET('',(%s));" % ",".join("#%d" % i for i in w.curve_ids),
        "#30=(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#31))GLOBAL_UNIT_ASSIGNED_CONTEXT((#32,#33,#34))"
        "REPRESENTATION_CONTEXT('Context3D','3D Context with UNIT and UNCERTAINTY'));",
        "#31=UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),#32,'distance_accuracy_value','confusion accuracy');",
        "#32=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT($,.METRE.));",
        "#33=(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.));",
        "#34=(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT());",
    ]
    return "\n".join(head + w.body + ["ENDSEC;", "END-ISO-10303-21;", ""])


def declared_schema(text):
    m = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']*)'", text)
    return m.group(1) if m else None


# ---- the run --------------------------------------------------------------------------------


def write_status(path, code, src, out, in_sha, out_sha, declared, wall, warnings, message):
    ok = code == 0
    rec = {
        "schema_version": "pvec-gold/converter-status/1",
        "converter": CONVERTER_ID,
        "status": "OK" if ok else "ERROR",
        "exit_code": code,
        "input": {"path": src, "sha256": in_sha},
        "output": {"path": out, "sha256": out_sha} if ok else None,
        "product": {"name": PRODUCT_NAME, "version": PRODUCT_VERSION},
        "declared_schema": declared,
        "wall_time_seconds": "%.3f" % wall,
        "warnings": warnings,
        "error": None if ok else {"code": code, "class": lj.CLASS_OF[code], "message": message},
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".partial.%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def parse(argv):
    src = out = status = None
    i = 0
    while i < len(argv):
        if argv[i] in ("--in", "--out", "--status") and i + 1 < len(argv):
            val = argv[i + 1]
            if argv[i] == "--in":
                src = val
            elif argv[i] == "--out":
                out = val
            else:
                status = val
            i += 2
        else:
            return None, None, status
    return src, out, status


def main(argv):
    start = time.monotonic()
    src, out, status = parse(argv)
    if status is None and out:
        status = re.sub(r"\.step$", "", out) + ".status.json"
    warnings, in_sha, out_sha, declared = [], None, None, None
    code, message = 0, ""
    if out and os.path.lexists(out):
        os.remove(out)  # never leave a stale output behind a failed run
    tmp = (out + ".partial.%d" % os.getpid()) if out else None
    try:
        if not src or not out:
            raise Failure(lj.BAD_ARGUMENTS, "usage: dwg2step.py --in source.dwg --out secondary.step [--status file]")
        if not (os.path.isfile(src) and os.access(src, os.R_OK)):
            raise Failure(lj.INPUT_UNREADABLE, "cannot read input")
        in_sha = lj.sha256_file(src)
        dwg = lj.load(src)
        if "*Model_Space" not in dwg.blocks:
            raise Failure(lj.INPUT_MALFORMED, "no model space block in the decoded drawing")
        warnings.extend(dwg.decoder_warnings)
        curves = []
        flatten(dwg, "*Model_Space", None, [], curves, warnings)
        text = step_text(os.path.basename(src).rsplit(".", 1)[0], curves)
        declared = declared_schema(text)
        if not declared or "AP242" not in declared.upper():
            raise Failure(lj.SCHEMA_NOT_AP242, "declared schema is %s" % declared)
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        if not os.path.getsize(tmp):
            raise Failure(lj.OUTPUT_NOT_WRITTEN, "the STEP file is empty")
        os.replace(tmp, out)
        out_sha = lj.sha256_file(out)
    except Failure as e:
        code, message = e.code, e.message
    except Exception as e:  # a bug here must not leave a half file or a record that says OK
        code, message = lj.INTERNAL, "%s: %s" % (type(e).__name__, e)
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
    if code != 0 and out and os.path.lexists(out):
        os.remove(out)
    if status:
        try:
            write_status(status, code, src or "", out or "", in_sha, out_sha, declared, time.monotonic() - start, warnings, message)
        except OSError as e:
            sys.stderr.write("dwg2step: cannot write the status record: %s\n" % e)
            code = code or lj.OUTPUT_NOT_WRITTEN
    if code:
        sys.stderr.write("dwg2step: %s\n" % message)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
