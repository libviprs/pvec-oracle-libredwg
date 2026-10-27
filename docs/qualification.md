# Qualification of the LibreDWG converter image

This is what I measured with this image on 2026-10-26 and 2026-10-27, what I
could not measure, and where the image differs from the plan it was built for. Every number below comes
from a run I did; where I did not run something, I say so.

Results are labelled native x64 (mars, x86_64) or native arm64 (mercury, Apple silicon, Colima).
Nothing here ran under emulation.

## What was run

- Converter image: `Dockerfile` in this repository at the commit that added `dwg2step`, `dwgdump` and
  `publish.sh`. LibreDWG 0.14, Debian bookworm, Python 3.11.2. Image IDs: x64
  `sha256:1042fc46ebb380edda421ff2291c2ab24995849ccb15060a40c35829def2b79b`, arm64 `4a9b9d087770`. Neither
  was pushed anywhere, so there is no registry digest yet (see "Not measured").
- Evaluator image: the Open CASCADE `step_eval` (OCCT 7.6.3) built from the fixtures repository's validator
  sources at commit f94f7f2 (`tests/build_step_eval.sh`), throw-away local tags, one per architecture.
- Corpus: the 30 DWGs of corpus revision r0-open at that same commit, checked against its `SHA256SUMS`
  (`tests/fetch_corpus.sh`). The brief said 26; the revision holds 30 DWGs (and three more probes, shear,
  general affine and singular, that no DWG can carry and that have no file).
- Suite: `tests/run.sh`, 46 tests.

## Inputs and pins

| Input | Pin |
|---|---|
| Base image | `debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587` (the multi-arch index) |
| LibreDWG | release 0.14, `https://ftp.gnu.org/gnu/libredwg/libredwg-0.14.tar.xz`, sha256 `62ebb73b984f865960f20ed26619ea5f8789d5e3fd088fa40a2598384da81275` |
| Patch | `patches/0001-json-doubles-17-significant-digits.patch`, one line in `src/out_json.c` |

I checked the tarball three ways before pinning it: the GNU server and the GitHub release asset give the
same sha256, and the detached signature verifies against Reini Urban's key
(`38A4167B0DB69E49C5F7216CB8C28866AB27A7A2`, fetched from a keyserver, so the signature proves the file
matches that key, not that I know whose key it is). The build stops if the downloaded file does not match.

## The JSON precision finding

`dwgread -O JSON` in LibreDWG 0.14 prints every double with `"%.14f"` (`src/out_json.c`, `FORMAT_RD`).
That is 14 digits after the decimal point, so it cannot carry a binary64 value: pi/2 comes out as
`1.5707963267949`, and anything below about 1e-14 in absolute terms is lost. The DWG stores the full 64
bits and the decoder returns them, so this is a printing limit and not a reading limit. I measured it
instead of assuming it: reading all 30 DWGs with the stock `dwgread` and with the patched one and turning
each into a read record, 625 stored reals are in those records and 6 differ, in 5 DWGs (`arc-seam-001`,
`ellipse-001` twice, `elliptical-arc-001`, `nested-blocks-001`, `nonuniform-scale-rotated-001`). The other
25 survive because their values are short decimals.

So the image carries two binaries built from the same release source: `dwgread` (stock, unmodified) and
`dwgread-exact` (the patch: `%.17g`, which round-trips every binary64). The converters use the patched one.
`tests/test_provenance.py::test_stock_json_loses_bits_the_patched_build_keeps` keeps the evidence in the
suite. This is a deviation from "over `dwgread -O JSON`" in the issue only in that the JSON comes from a
one-line patched build; the structure, key names and everything else are the stock output.

## Results per architecture

| Check | native x64 (mars) | native arm64 (mercury) |
|---|---|---|
| Image builds from pinned inputs | yes | yes |
| Suite (46 tests) | OK | OK |
| `dwg2step` exit 0 on the 30 r0-open DWGs | 30 of 30, no warnings | 30 of 30, no warnings |
| `step_eval` reads the output | 30 of 30, no `unsupported` entity | 30 of 30 |
| `dwgdump` record equals the ACadSharp read record, field for field except `reader` | 30 of 30 | 30 of 30 |
| Two consecutive runs | STEP byte for byte identical, 30 of 30 | same |

Across the two architectures: the 30 `secondary.step` files are byte for byte identical (sha256), the 30
`read.libredwg.json` records are identical, and the 30 status records are identical except
`wall_time_seconds`. The converter is Python over a C decoder compiled with `-ffp-contract=off`, and the
exact rational arithmetic in the flattening does not depend on the platform.

The evaluator is a different matter, and it is the evaluator's, not the converter's: running `step_eval`
over those identical files on both architectures, 737 of 7308 reported reals differ. Every stored value
(poles, knots, weights, centres, radii) is bit for bit the same. The differences are derived values (sample
points, tangents, curvatures, a line's end point, an ellipse's major axis): 531 of them within 2 ulp, the
largest relative difference for values above 1e-3 is 3.8e-14 (a curvature of 146.2 at a sample of
`nonunit-weight-001`), and the rest are values that are zero up to rounding. That is the same kind of
noise the evaluator's own cross-platform note describes. Nothing downstream may compare derived samples bit
for bit across architectures.

### What the evaluator read

One row per probe, the classes `step_eval` reported for `secondary.step` (30 of 30 OK):

| probe | classes read |
|---|---|
| line-001, translation-001, rotation-irrational-001, nested-blocks-001, near-singular-001 | line |
| polyline-001, polyline2d-001, lwpolyline-closed-001 | line x4 |
| large-coords-001, layer-state-001 | line x3 |
| bulge-arc-001, bulge-arc-neg-001, arc-seam-001, reflection-001 | circular_arc |
| circle-001, tiny-radius-001, uniform-scale-001 | circle |
| ellipse-001, nonuniform-scale-circle-001, nonuniform-scale-rotated-001 | ellipse |
| elliptical-arc-001 | elliptical_arc |
| bezier-d3-001, bspline-d3-001, bspline-d5-001, repeated-knot-c0-001, closed-by-endpoint-001, closed-periodic-001 | bspline |
| nurbs-d3-001, nurbs-d2-offconic-001, nonunit-weight-001 | nurbs |

What the suite asserts about them: on the 13 curve probes whose geometry is stored verbatim, the evaluator's
poles, knots with multiplicities, weights, centres, radii and degrees equal the authored bits (the
`f64_hex` of `expected.math.json`); a circle under a non-uniform scale is read back as the authored ellipse
(centre, both semi-axes and the major axis direction within the test's sanity tolerance of 1e-9); a
reflected arc keeps start to start with its normal flipped; the three-deep nested chain lands on the
authored world points, so the order is outermost on the left; polylines arrive as separate line and arc
edges through the authored vertices; and the periodic spline matches the authored cubic B-spline
evaluated by Cox-de Boor from the authored poles and knots. The 1e-9 tolerance is mine, for derived values
only, and is not the numeric policy: verdicts under the policy belong to the qualification stage.

## What LibreDWG could not read on AC1032, and why

On these 30 files, nothing it needed. All 30 decode with exit 0 and `SUCCESS`, and the records of the
probe entities equal ACadSharp's field for field, including SPLINE weights, ELLIPSE parameters, the
periodic spline's knot vector and a three-deep INSERT chain (the points the plan listed as unverified).

What it does say on every file, on stderr, is `Warning: TODO TABLESTYLE r2010+ missing fields`. The decoder
knows it does not read all fields of that object type for R2010 and later. The probes never use it, it is
not fatal, and nothing I convert depends on it. It is the same kind of gap LibreDWG's README describes for
advanced R2010+ objects, and I would expect it to bite a real drawing with table styles before it bites
these.

The limits of that statement, because "nothing it needed" is easy to over-read:

- All 30 files come from one writer (acadrust, AC1032). I had no DWG written by AutoCAD or another
  vendor tool, so I have shown that LibreDWG reads this writer's AC1032, not AC1032 in general.
- Fit-point splines (scenario 2, no control points) exit 15: no probe has one, and I do not convert fit
  points to poles.
- Entity types outside the eight in the record are not converted: `dwg2step` lists each skipped entity in
  the status record's `warnings`, and `dwgdump` marks it `"unread": true`. No probe has one, so neither
  path has been exercised on a drawing.
- `dwgread` returns other versions only as far as its decoder goes. An unreadable header is exit 12, a
  well-formed AC10xx version code it does not implement is exit 13. Both are tested with crafted files, not
  with real old or new DWGs.

## What the converter does and does not decide

`dwg2step` carries a transform as an exact rational matrix and rounds each output once; it never decides
two numbers are equal within a tolerance. Stored values (poles, knots, weights, centres) are copied, so
they are bit for bit what the DWG held. Derived values (a bulge arc's centre and radius, an ellipse's
semi-minor axis, a line's unit direction and length, a flattened circle's axes) are rounded results and are
for the policy to judge.

- A circle under a transform that is a rotation times a uniform scale (decided from the INSERT's own scale
  components, never by comparing numbers) stays a circle with radius times the factor. Anything else
  becomes an ellipse, even when the plane happens to preserve the circle.
- A singular instance (an exactly zero determinant) is refused with exit 15 and writes no geometry.
  `near-singular-001` has a scale of 1e-12, which is not zero, so a line is written for it. The probe's
  expected outcome is a rejection (no curve), so I expect the qualification stage to mark it
  `UNEXPECTED_GEOMETRY` for this converter. A guard would need the policy's threshold for "near"; this
  repository holds no threshold and I did not invent one.
- Layer state has no STEP form: off and frozen layers are converted like any other (`layer-state-001`
  yields its three lines).
- A periodic spline cannot go through OCCT as periodic. It is written as an unclamped B-spline of
  n + degree poles (copies of the unique poles, in the order the continued knot vector needs) with the
  knot vector continued by the period, so its parameter domain is the authored one and it closes
  geometrically, not by equal end poles. I expect `closed-periodic-001` to classify as
  `GEOMETRIC_EXACT_REPARAMETERIZED` at best, as the plan says.
- `closed_curve` is always `.F.` in a B-spline. With `.T.` the OCCT 7.6.3 reader builds a periodic curve
  and drops the last pole, which changes a stored value. I found this on the first x64 run of
  `closed-by-endpoint-001`, where the evaluator returned six poles for the authored seven.

## Determinism

The STEP file is byte for byte identical across runs and across architectures, not only identical except
named fields. The one field a Part 21 file may vary (the `FILE_NAME` time stamp) is fixed to the epoch
unless `SOURCE_DATE_EPOCH` is set, and the status record's only varying field is `wall_time_seconds`.
`PYTHONHASHSEED` is fixed in the image anyway; nothing in the converter iterates an unordered collection
into the output.

## Not measured

- Two consecutive image builds from the same inputs giving the same image digest. I built once per
  architecture and did not compare layers; the base image and the tarball are pinned by digest and hash,
  the apt packages in the build and runtime stages (compiler, Python 3.11.2) are not version-pinned, and
  none of them ends up in the output beyond the compiled `dwgread` binaries and the interpreter.
- The published multi-arch manifest digest. `publish.sh` has only been run as a dry run (and against a fake
  `docker` in the tests); nothing was pushed, so there is no `ghcr.io/libviprs/pvec-oracle-libredwg@sha256:...`
  to pin yet.
- The numeric policy classification of any probe. This repository has no policy and the evaluator runs
  here are stamped `unstamped`.
- The Docker-less behaviour of whoever consumes the image: that is the consumer's side of the boundary.
- A licence scan of the image history for credentials (there is none to find; the build takes no secret).

## Deviations from the issue and the plan

1. LibreDWG 0.14, not 0.14.1: the plan named 0.14.1 (2026-07-25), but the latest release on the GNU server
   and on GitHub is 0.14 (tagged 2026-06-27, tarball signed 2026-08-31); there are only nightly 0.14.xxxx
   tags after it.
2. The JSON comes from a patched build (above), with the stock binary shipped beside it.
3. The status record's `converter` is the string `libredwg-dwg2step`. The schema in the fixtures repository
   still has `enum ["cadex","oda"]`; the plan has that generalised to a string id in its first work
   package, and until it is, this record does not validate against the old enum.
4. The corpus has 30 DWGs, not 26.
5. The sanity tolerance (1e-9) in the tests for derived values, which is not the numeric policy.
6. The test image uses the full `python3` package rather than `python3-minimal`, because `unittest` is not
   in the minimal one.
