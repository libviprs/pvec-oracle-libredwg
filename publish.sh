#!/bin/sh
# publish.sh: build the image for amd64 and arm64 and publish it by digest.
#
#   ./publish.sh                 dry run (the default): prints what it would do and runs no docker command
#   ./publish.sh --push          builds both platforms and pushes the manifest list by digest, untagged
#
# Environment: PUBLISH_REPO (default ghcr.io/libviprs/pvec-oracle-libredwg), PUBLISH_PLATFORMS
# (default linux/amd64,linux/arm64). Logging in to the registry is done beforehand with the docker
# CLI; this script never reads, takes or writes a credential.
#
# Consumers pin the printed reference (name@sha256:...), never a tag, and read only the files the
# container writes. See README.md for the boundary.
#
# Copyright (C) the pvec-oracle-libredwg authors.
# SPDX-License-Identifier: GPL-3.0-or-later
set -eu

here=$(cd "$(dirname "$0")" && pwd)
repo=${PUBLISH_REPO:-ghcr.io/libviprs/pvec-oracle-libredwg}
platforms=${PUBLISH_PLATFORMS:-linux/amd64,linux/arm64}
push=no
for a in "$@"; do
  case $a in
    --push) push=yes ;;
    --dry-run) push=no ;;
    *) echo "usage: publish.sh [--dry-run|--push]" >&2; exit 10 ;;
  esac
done

# 1. The inputs must be pinned, or there is nothing reproducible to publish.
grep -Eq '^ARG BASE=debian:bookworm-slim@sha256:[0-9a-f]{64}$' "$here/Dockerfile" \
  || { echo "publish.sh: the base image in the Dockerfile is not pinned by digest" >&2; exit 1; }
grep -Eq '^ARG LIBREDWG_SHA256=[0-9a-f]{64}$' "$here/Dockerfile" \
  || { echo "publish.sh: the LibreDWG tarball in the Dockerfile is not pinned by sha256" >&2; exit 1; }

# 2. A push comes from a clean tree, so the digest says what the repository says.
if [ "$push" = yes ] && command -v git >/dev/null 2>&1 && [ -d "$here/.git" ]; then
  [ -z "$(git -C "$here" status --porcelain)" ] \
    || { echo "publish.sh: the working tree is not clean" >&2; exit 1; }
fi

meta="${TMPDIR:-/tmp}/pvec-oracle-libredwg-publish.$$.json"
build="docker buildx build --platform $platforms --provenance=false --output type=image,name=$repo,push-by-digest=true,name-canonical=true,push=true --metadata-file $meta $here"

if [ "$push" = no ]; then
  echo "dry run: nothing is built or pushed"
  echo "would run: $build"
  echo "would then read containerimage.digest from $meta and verify both platforms with:"
  echo "  docker buildx imagetools inspect $repo@sha256:<digest>"
  echo "would print the pinned reference: $repo@sha256:<digest of the manifest list>"
  exit 0
fi

trap 'rm -f "$meta"' EXIT
# shellcheck disable=SC2086
$build
digest=$(grep -o '"containerimage.digest": *"sha256:[0-9a-f]\{64\}"' "$meta" | grep -o 'sha256:[0-9a-f]\{64\}')
[ -n "$digest" ] || { echo "publish.sh: the build reported no digest" >&2; exit 1; }
docker buildx imagetools inspect "$repo@$digest"
echo "$repo@$digest"
