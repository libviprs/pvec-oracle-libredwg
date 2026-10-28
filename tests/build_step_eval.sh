#!/bin/sh
# Builds the evaluator image the tests read the converter's output with, from a pinned commit of
# the fixtures repository's validator sources, as a throw-away local image. Nothing from that
# repository is added here: the sources go into a docker build context and nowhere else.
#
#   tests/build_step_eval.sh PATH_TO_A_CHECKOUT_OF_THE_FIXTURES_REPO PLATFORM IMAGE_TAG
set -eu
commit=f94f7f22b7aaff36eaaf6d5501fafc42054f22f2
src=${1:?path to a checkout of the fixtures repository}
platform=${2:?linux/amd64 or linux/arm64}
tag=${3:?image tag}
ctx=$(mktemp -d)
trap 'rm -rf "$ctx"' EXIT
git -C "$src" archive "$commit" docker/step-validator validator/CMakeLists.txt validator/src | tar -x -C "$ctx"
docker build --platform "$platform" --target runtime -t "$tag" -f "$ctx/docker/step-validator/Dockerfile" "$ctx"
