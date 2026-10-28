#!/usr/bin/env python3
# Writes tests/permissive-hashes.txt: the SHA-256 of every tracked file of 64 bytes or more in the
# given checkouts of permissively licensed repositories. The hashes are the whole record; none of
# those files, and nothing derived from them, is kept here.
#
#   python3 tests/make_permissive_hashes.py OUT CHECKOUT [CHECKOUT ...]
#
# The checkout's directory name is the repository name; its HEAD commit is written beside it.
import hashlib
import os
import subprocess
import sys

MIN_BYTES = 64


def main(out, checkouts):
    lines = []
    for co in checkouts:
        repo = os.path.basename(os.path.abspath(co))
        head = subprocess.check_output(["git", "-C", co, "rev-parse", "--short=12", "HEAD"], text=True).strip()
        files = subprocess.check_output(["git", "-C", co, "ls-files", "-z"], text=True).split("\0")
        for rel in sorted(f for f in files if f):
            p = os.path.join(co, rel)
            if not os.path.isfile(p) or os.path.islink(p) or os.path.getsize(p) < MIN_BYTES:
                continue
            with open(p, "rb") as fh:
                lines.append("%s %s@%s:%s" % (hashlib.sha256(fh.read()).hexdigest(), repo, head, rel))
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("%d hashes from %d repositories" % (len(lines), len(checkouts)))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: make_permissive_hashes.py OUT CHECKOUT [CHECKOUT ...]")
    main(sys.argv[1], sys.argv[2:])
