#!/bin/sh
# Runs the whole suite against a built image, on one platform. Only docker runs anything.
#
#   tests/run.sh IMAGE EVALUATOR_IMAGE PLATFORM CORPUS WORK
#
# CORPUS and WORK are directories or named volumes; REPO_MOUNT (optional) is the repository, the same way.
#
# 1. converts every DWG of the corpus with the image (dwg2step and dwgdump),
# 2. reads every STEP file with the evaluator image,
# 3. runs the unittest suite inside the converter image with the repository, the corpus and the
#    outputs mounted read-only (the work directory for step 1 and 2 is the only writable mount).
set -eu
image=${1:?converter image}
evaluator=${2:?evaluator image}
platform=${3:?platform}
corpus=${4:?corpus directory}
work=${5:?work directory}
# REPO_MOUNT may be a named volume (a docker host that cannot see this directory, such as a VM).
repo=${REPO_MOUNT:-$(cd "$(dirname "$0")/.." && pwd)}
case $work in */*) mkdir -p "$work" ;; esac

docker run --rm --platform "$platform" -v "$corpus:/corpus:ro" -v "$work:/work" "$image" sh -c '
  for d in /corpus/fixtures/*/; do
    id=$(basename "$d"); mkdir -p "/work/out/$id"
    dwg2step --in "$d/source.dwg" --out "/work/out/$id/secondary.step" --status "/work/out/$id/secondary.status.json" 2>"/work/out/$id/secondary.stderr" || true
    dwgdump --in "$d/source.dwg" --out "/work/out/$id/read.libredwg.json" 2>"/work/out/$id/dwgdump.stderr" || true
  done'

docker run --rm --platform "$platform" -v "$work:/work" "$evaluator" sh -c '
  mkdir -p /work/verify
  for f in /work/out/*/secondary.step; do
    id=$(basename "$(dirname "$f")")
    step_eval --in "$f" --out "/work/verify/$id.verification.json" --policy-version unstamped >"/work/verify/$id.log" 2>&1 || true
  done'

docker run --rm --platform "$platform" -e CORPUS=/corpus -e WORK=/work -e REPO=/repo \
  -v "$repo:/repo:ro" -v "$corpus:/corpus:ro" -v "$work:/work:ro" "$image" \
  python3 -m unittest discover -s /repo/tests -v
