#!/bin/sh
# Unpacks the r0-open corpus revision (the 30 DWGs, their authored records and the other readers'
# records) and the numeric policy file to a directory, for the tests to read. The files are test inputs: they are never added
# to this repository (tests/test_provenance.py would catch it).
#
#   tests/fetch_corpus.sh PATH_TO_A_CHECKOUT_OF_THE_FIXTURES_REPO DEST
#
# Read-only on the checkout: it uses git archive, and does not touch the working tree.
set -eu
commit=f94f7f22b7aaff36eaaf6d5501fafc42054f22f2
src=${1:?path to a checkout of the fixtures repository}
dest=${2:?destination directory}
mkdir -p "$dest"
git -C "$src" archive "$commit" corpus/r0-open | tar -x -C "$dest"
mv "$dest/corpus/r0-open/"* "$dest/" && rmdir "$dest/corpus/r0-open" "$dest/corpus"
(cd "$dest" && sha256sum -c SHA256SUMS >/dev/null) || { echo "fetch_corpus.sh: SHA256SUMS does not match" >&2; exit 1; }
# the numeric policy, as data: the converter's NP-19 constant is pinned to it by a test
git -C "$src" show "$commit:policy/pvec-numeric-policy.v1.json" > "$dest/policy.json"
echo "corpus r0-open at $commit in $dest"
