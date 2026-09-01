import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_has_two_stages():
    text = (ROOT / "Dockerfile").read_text()
    assert text.count("FROM ") == 2 and "rtkbuild" in text
    assert "web ./web" in text and "/usr/local/bin/rtkrcv" in text


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
@pytest.mark.slow
def test_docker_image_builds():
    extra = shlex.split(os.environ.get("RTK_DOCKER_BUILD_ARGS", ""))
    r = subprocess.run(["docker", "build", "-q", *extra, "."], cwd=ROOT,
                       capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stderr[-2000:]
