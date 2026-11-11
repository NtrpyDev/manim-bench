"""Render a scene inside a locked-down container.

Model-written code is untrusted. It runs with no network, a read-only root
filesystem, no Linux capabilities, as the host user, with CPU, memory and
process limits. The only place it can write is the sample's own folder.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

from manimbench.media import probe_video
from manimbench.models import RenderResult
from manimbench.paths import HARNESS_PATH
from manimbench.sandbox.settings import SandboxSettings, docker_executable, load_sandbox_settings

VIDEO_NAME = "result.mp4"
LAYOUT_NAME = "layout.json"
MAX_LOG_BYTES = 1_000_000
MAX_FILE_BYTES = 4 * 1024**3


class SandboxError(RuntimeError):
    """The sandbox itself is unusable (no engine, no image). Not a model failure."""


class ContainerSandbox:
    name = "container"

    def __init__(
        self,
        settings: SandboxSettings | None = None,
        *,
        engine: str | None = None,
        memory: str = "4g",
        cpus: str = "2",
        pids_limit: int = 256,
        tmpfs_size: str = "1g",
        harness_path: Path = HARNESS_PATH,
    ):
        self.settings = settings or load_sandbox_settings()
        self.engine = engine or docker_executable()
        self.memory = memory
        self.cpus = cpus
        self.pids_limit = pids_limit
        self.tmpfs_size = tmpfs_size
        self.harness_path = harness_path

    def ensure_image(self) -> None:
        """Fail early, with a useful message, if the pinned image is not present."""
        completed = subprocess.run(
            [self.engine, "image", "inspect", self.settings.reference, "--format", "{{.Id}}"],
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        if completed.returncode != 0:
            raise SandboxError(
                f"Sandbox image {self.settings.reference} is not available locally. "
                f"Run `manimbench sandbox pull` first. ({completed.stderr.strip()})"
            )

    def pull(self) -> None:
        completed = subprocess.run(
            [self.engine, "pull", self.settings.reference], text=True, capture_output=True, timeout=3600, check=False
        )
        if completed.returncode != 0:
            raise SandboxError(f"Could not pull {self.settings.reference}: {completed.stderr.strip()}")

    def metadata(self) -> dict[str, object]:
        return {
            "name": self.name,
            "engine": Path(self.engine).name,
            "image": self.settings.image,
            "image_digest": self.settings.digest,
            "manim_version": self.settings.manim_version,
            "python_version": self.settings.python_version,
            "network": "none",
            "read_only_root": True,
            "capabilities": "none",
            "memory": self.memory,
            "cpus": self.cpus,
            "pids_limit": self.pids_limit,
            "tmpfs_size": self.tmpfs_size,
        }

    def command(self, sample_dir: Path, container_name: str, *, quality: str, fps: int, scene_class: str) -> list[str]:
        return [
            self.engine,
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--cpus",
            self.cpus,
            "--memory",
            self.memory,
            "--memory-swap",
            self.memory,
            "--pids-limit",
            str(self.pids_limit),
            "--ulimit",
            f"fsize={MAX_FILE_BYTES}",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,size={self.tmpfs_size}",
            "-e",
            "HOME=/tmp/home",
            "-e",
            "XDG_CACHE_HOME=/tmp/cache",
            "-e",
            "MPLCONFIGDIR=/tmp/matplotlib",
            "-e",
            "OPENBLAS_NUM_THREADS=1",
            "-e",
            "OMP_NUM_THREADS=1",
            "-v",
            f"{sample_dir}:/work:rw",
            "-v",
            f"{self.harness_path}:/harness/harness.py:ro",
            "-w",
            "/work",
            self.settings.reference,
            "python",
            "/harness/harness.py",
            "solution.py",
            "--scene",
            scene_class,
            "--quality",
            quality,
            "--fps",
            str(fps),
            "--media-dir",
            "/work/media",
            "--layout",
            f"/work/{LAYOUT_NAME}",
        ]

    def render(
        self,
        sample_dir: Path,
        *,
        timeout_seconds: int,
        quality: str,
        fps: int,
        scene_class: str,
    ) -> RenderResult:
        """Render ``sample_dir/solution.py``. Everything it writes stays in ``sample_dir``."""
        sample_dir = sample_dir.resolve()
        if not (sample_dir / "solution.py").exists():
            raise FileNotFoundError(f"No solution.py in {sample_dir}")
        logs_dir = sample_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        container_name = f"manimbench-{uuid.uuid4().hex[:16]}"
        command = self.command(sample_dir, container_name, quality=quality, fps=fps, scene_class=scene_class)

        timed_out = False
        started = time.monotonic()
        process = subprocess.Popen(command, cwd=sample_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        captured: dict[str, bytes] = {}
        pumps = [
            threading.Thread(target=_pump, args=(process.stdout, "stdout", captured), daemon=True),
            threading.Thread(target=_pump, args=(process.stderr, "stderr", captured), daemon=True),
        ]
        for pump in pumps:
            pump.start()
        try:
            exit_code: int | None = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = None
            # Stopping the client does not stop the container, so kill it by name.
            subprocess.run([self.engine, "kill", container_name], capture_output=True, timeout=60, check=False)
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for pump in pumps:
            pump.join(timeout=10)
        elapsed = time.monotonic() - started

        (logs_dir / "stdout.log").write_bytes(captured.get("stdout", b""))
        (logs_dir / "stderr.log").write_bytes(captured.get("stderr", b""))

        video = self._find_video(sample_dir)
        layout = sample_dir / LAYOUT_NAME
        return RenderResult(
            exit_code=exit_code,
            timed_out=timed_out,
            elapsed_seconds=round(elapsed, 3),
            video=str(video.relative_to(sample_dir)) if video else None,
            probe=probe_video(video) if video else {},
            layout_path=LAYOUT_NAME if layout.exists() else None,
            command=_portable_command(command, sample_dir, self.harness_path),
            sandbox=self.metadata(),
        )

    @staticmethod
    def _find_video(sample_dir: Path) -> Path | None:
        """The finished video only. Partial clips Manim leaves behind are ignored."""
        candidates = [
            path
            for path in (sample_dir / "media" / "videos").glob(f"**/{VIDEO_NAME}")
            if "partial_movie_files" not in path.parts
        ]
        return sorted(candidates)[0] if candidates else None


def _pump(stream, name: str, captured: dict[str, bytes]) -> None:
    """Keep the first part of a stream and drain the rest, so output cannot fill memory or disk."""
    kept = bytearray()
    while True:
        chunk = stream.read(65536)
        if not chunk:
            break
        if len(kept) < MAX_LOG_BYTES:
            kept.extend(chunk[: MAX_LOG_BYTES - len(kept)])
    captured[name] = bytes(kept)


def _portable_command(command: list[str], sample_dir: Path, harness_path: Path) -> list[str]:
    """The command with this machine's paths replaced, so results can be published."""
    return [part.replace(str(sample_dir), "<sample>").replace(str(harness_path), "<harness>") for part in command]
