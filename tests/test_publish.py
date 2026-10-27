# publish.sh is only ever exercised here against a fake docker that records its arguments. No
# registry is contacted and no credential is involved.
import os
import stat
import subprocess
import unittest

from common import REPO, scratch

FAKE = """#!/bin/sh
echo "$@" >> "$FAKE_LOG"
case "$1 $2" in
  "buildx build")
    while [ $# -gt 0 ]; do [ "$1" = "--metadata-file" ] && meta=$2; shift; done
    echo '{"containerimage.digest": "sha256:%s"}' > "$meta" ;;
esac
""" % ("ab" * 32)


def publish(*args, tmp):
    bindir = os.path.join(tmp, "bin")
    os.makedirs(bindir, exist_ok=True)
    fake = os.path.join(bindir, "docker")
    with open(fake, "w") as f:
        f.write(FAKE)
    os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR)
    log = os.path.join(tmp, "calls.log")
    env = dict(os.environ, PATH=bindir + ":" + os.environ["PATH"], FAKE_LOG=log, TMPDIR=tmp)
    r = subprocess.run(["sh", os.path.join(REPO, "publish.sh")] + list(args), capture_output=True, text=True, env=env)
    calls = open(log).read().splitlines() if os.path.exists(log) else []
    return r, calls


class Publish(unittest.TestCase):
    def test_the_default_is_a_dry_run_that_runs_no_docker_command(self):
        with scratch() as tmp:
            r, calls = publish(tmp=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(calls, [])
            self.assertIn("dry run", r.stdout)
            self.assertIn("@sha256:<digest", r.stdout)
            r2, calls2 = publish("--dry-run", tmp=tmp)
            self.assertEqual((r2.returncode, calls2), (0, []))

    def test_a_dry_run_names_both_architectures_and_pushes_by_digest(self):
        with scratch() as tmp:
            r, _ = publish(tmp=tmp)
            self.assertIn("linux/amd64,linux/arm64", r.stdout)
            self.assertIn("push-by-digest=true", r.stdout)
            self.assertNotIn(":latest", r.stdout)

    def test_a_push_builds_once_and_prints_a_digest_reference_never_a_tag(self):
        with scratch() as tmp:
            r, calls = publish("--push", tmp=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            builds = [c for c in calls if c.startswith("buildx build")]
            self.assertEqual(len(builds), 1)
            self.assertIn("--platform linux/amd64,linux/arm64", builds[0])
            self.assertIn("push-by-digest=true", builds[0])
            self.assertNotIn("--tag", builds[0])
            self.assertEqual(r.stdout.strip().splitlines()[-1], "ghcr.io/libviprs/pvec-oracle-libredwg@sha256:" + "ab" * 32)
            self.assertTrue(any(c.startswith("buildx imagetools inspect ghcr.io/libviprs/pvec-oracle-libredwg@sha256:") for c in calls))

    def test_bad_arguments_exit_10_and_run_nothing(self):
        with scratch() as tmp:
            r, calls = publish("--latest", tmp=tmp)
            self.assertEqual((r.returncode, calls), (10, []))

    def test_it_reads_no_credential(self):
        src = open(os.path.join(REPO, "publish.sh"), encoding="utf-8").read()
        for word in ("GITHUB_TOKEN", "GH_TOKEN", "docker login", "--password", "config.json"):
            self.assertNotIn(word, src.replace("Logging in to the registry is done beforehand with the docker", ""))


if __name__ == "__main__":
    unittest.main()
