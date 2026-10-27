# pvec-oracle-libredwg

An open DWG to STEP converter image built on [GNU LibreDWG](https://www.gnu.org/software/libredwg/),
the second of the two open converters behind the pvec corpus pipeline. It lives in a repository of its
own because LibreDWG is GPL-3.0-or-later, and I wanted that licence to stop at a hard edge.

## What is in here, and the licence

Everything in this repository is GPL-3.0-or-later (the `LICENSE` file is the GPLv3 text):

- `Dockerfile` builds LibreDWG 0.14 from the release tarball on GNU's server, pinned by sha256, on a
  `debian:bookworm-slim` base pinned by digest.
- `patches/0001-json-doubles-17-significant-digits.patch` is the only change I make to LibreDWG's
  source: `dwgread -O JSON` prints every double with `%.14f`, which cannot carry a binary64 value, so
  the patched build prints `%.17g`. The unmodified `dwgread` ships beside it as `dwgread`; the patched one is
  `dwgread-exact`. The numbers are in `docs/qualification.md`.
- `dwg2step.py` reads a DWG through `dwgread-exact -O JSON`, flattens every INSERT chain and writes a small
  AP242 Part 21 subset (`LINE`, `CIRCLE`, `ELLIPSE`, `TRIMMED_CURVE`, `B_SPLINE_CURVE_WITH_KNOTS` and the
  rational complex entity, `AXIS2_PLACEMENT_3D`, `GEOMETRIC_CURVE_SET`) plus a status record.
- `dwgdump.py` writes the DWG read record (`pvec-gold/r0-open-dwg-read/2`), the third cross-read of
  ADR 0008, from the same decoder.
- `libredwg_json.py` is the part both of them share, `publish.sh` publishes the image by digest, and
  `tests/` is the suite.

The image carries the corresponding source with it: the pinned tarball, the patch and the licence texts
sit under `/usr/share/doc/pvec-oracle-libredwg/`.

## The boundary

Nothing is copied or imported across it, in either direction.

- No file here comes from `pvec`, `pvec-gold-fixtures` or any other permissively licensed repository, and
  none of their code is imported or linked. `tests/test_provenance.py` hashes every file in this
  repository against a list of the files in those repositories and fails on a match. I wrote the converter
  from the published schemas and the file shapes (status record, read record, exit codes, the Part 21
  subset and the flattening rule), not from the other converter's code, which I did not read.
- No GPL code goes the other way. Those repositories never build this one, never import it and never run
  it as a library.

The only thing that crosses is the container image and the files it writes. A consumer pulls the image
by digest, starts it as a process with a bind-mounted scratch directory, and reads the output files. In
the corpus pipeline those are `secondary.step`, `secondary.status.json` and `read.libredwg.json`. Plain
files are not a derivative work of the program that wrote them, and that is the whole reason this is a
separate repository: the licensing question is answered by the process boundary, not by anybody's
judgement about linking.

## Using the image

```
docker run --rm --platform linux/amd64 -v "$PWD:/work" IMAGE@sha256:... \
    dwg2step --in /work/source.dwg --out /work/secondary.step --status /work/secondary.status.json
docker run --rm --platform linux/amd64 -v "$PWD:/work" IMAGE@sha256:... \
    dwgdump --in /work/source.dwg --out /work/read.libredwg.json
```

Always pin the digest, never a tag. Exit codes are shared with the other converter: 0 ok, 10 bad
arguments, 11 input unreadable, 12 input malformed, 13 DWG version unsupported, 15 conversion failed,
16 output not written, 17 declared schema is not AP242, 20 internal. A failed run leaves no STEP file,
not even an older one, and still writes the status record.

`publish.sh` is a dry run unless you pass `--push`. It builds amd64 and arm64, pushes the manifest list
without a tag and prints `repo@sha256:...`. It never reads a credential, so log in beforehand.

## Tests

`tests/run.sh IMAGE EVALUATOR_IMAGE PLATFORM CORPUS_DIR WORK_DIR` runs everything on one platform, and only
docker executes anything. The evaluator image is the Open CASCADE one built by `tests/build_step_eval.sh`
and the corpus is `tests/fetch_corpus.sh`. The results per architecture are in `docs/qualification.md`.
