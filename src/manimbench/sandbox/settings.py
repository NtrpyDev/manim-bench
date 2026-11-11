"""The pinned Manim image: read it, and move it to a new release."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

from manimbench.paths import SANDBOX_RUNTIME_PATH

_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

_HEADER = """\
# The Manim release every scene is rendered with. To move to a new release,
# run `manimbench sandbox update <version>`: it pulls that image and rewrites
# this file. Results record these values, so runs on different Manim versions
# are never mixed up.
"""


@dataclass(frozen=True)
class SandboxSettings:
    manim_version: str
    image: str
    digest: str
    python_version: str

    @property
    def tag_reference(self) -> str:
        return f"{self.image}:v{self.manim_version}"

    @property
    def reference(self) -> str:
        """The image pinned by content, so a moved tag cannot change results."""
        return f"{self.image}@{self.digest}"


def load_sandbox_settings(path: Path = SANDBOX_RUNTIME_PATH) -> SandboxSettings:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    settings = SandboxSettings(
        manim_version=str(data.get("manim_version", "")),
        image=str(data.get("image", "")),
        digest=str(data.get("digest", "")),
        python_version=str(data.get("python_version", "")),
    )
    if not _VERSION.match(settings.manim_version):
        raise ValueError(f"{path}: manim_version must look like 0.22.1")
    if not settings.image:
        raise ValueError(f"{path}: image is required")
    if not _DIGEST.match(settings.digest):
        raise ValueError(f"{path}: digest must be a sha256 image digest")
    return settings


def docker_executable() -> str:
    found = shutil.which("docker") or shutil.which("podman")
    if not found:
        raise FileNotFoundError("Neither docker nor podman is installed")
    return found


def update_sandbox(version: str, path: Path = SANDBOX_RUNTIME_PATH, *, engine: str | None = None) -> SandboxSettings:
    """Pull the image for a Manim release and pin it in the settings file."""
    if not _VERSION.match(version):
        raise ValueError("Version must look like 0.22.1")
    current = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    image = str(current.get("image", "manimcommunity/manim"))
    engine = engine or docker_executable()
    tag = f"{image}:v{version}"
    _run([engine, "pull", tag], timeout=3600)
    digests = _run([engine, "image", "inspect", tag, "--format", "{{json .RepoDigests}}"], timeout=60)
    match = re.search(re.escape(image) + r"@(sha256:[0-9a-f]{64})", digests)
    if not match:
        raise RuntimeError(f"Could not read a registry digest for {tag}: {digests.strip()}")
    digest = match.group(1)
    reference = f"{image}@{digest}"
    reported = _run([engine, "run", "--rm", "--network", "none", reference, "manim", "--version"], timeout=120)
    if version not in reported:
        raise RuntimeError(f"Image {tag} reports {reported.strip()!r}, expected Manim {version}")
    python_version = _run(
        [engine, "run", "--rm", "--network", "none", reference, "python", "-c", "import platform; print(platform.python_version())"],
        timeout=120,
    ).strip()
    settings = SandboxSettings(manim_version=version, image=image, digest=digest, python_version=python_version)
    path.write_text(
        _HEADER
        + f'manim_version: "{settings.manim_version}"\n'
        + f"image: {settings.image}\n"
        + f"digest: {settings.digest}\n"
        + f'python_version: "{settings.python_version}"\n',
        encoding="utf-8",
    )
    return settings


def _run(command: list[str], *, timeout: int) -> str:
    completed = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed: {(completed.stderr or completed.stdout).strip()}")
    return completed.stdout
