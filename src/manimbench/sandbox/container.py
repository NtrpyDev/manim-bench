from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from manimbench.models import RenderResult
from manimbench.runtime.manimce import ManimCERuntime, discover_media_files, probe_media


class ContainerSandbox:
    """Official benchmark sandbox using Docker or Podman."""

    name = "container"
    official = True

    def __init__(
        self,
        image: str = "manimbench-manimce:latest",
        engine: str | None = None,
        memory: str = "4g",
        cpus: str = "2",
        pids_limit: int = 256,
        tmpfs_size: str = "512m",
    ):
        self.image = image
        self.engine = engine or shutil.which("docker") or shutil.which("podman") or "docker"
        self.memory = memory
        self.cpus = cpus
        self.pids_limit = pids_limit
        self.tmpfs_size = tmpfs_size

    def render(
        self,
        run_dir: Path,
        solution_path: Path,
        runtime: ManimCERuntime,
        timeout_seconds: int,
        fps: int,
        scene_class: str,
    ) -> RenderResult:
        del runtime
        media_dir = run_dir / "media"
        logs_dir = run_dir / "logs"
        media_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)

        container_solution = f"/work/{solution_path.relative_to(run_dir)}"
        container_media = "/work/media"
        render_command = [
            "python",
            "-m",
            "manim",
            "-qh",
            "--fps",
            str(fps),
            "--media_dir",
            container_media,
            "--output_file",
            "result",
            "--disable_caching",
            "--flush_cache",
            "--progress_bar",
            "none",
            container_solution,
            scene_class,
        ]
        command = [
            self.engine,
            "run",
            "--rm",
            "--network",
            "none",
            "--cpus",
            self.cpus,
            "--memory",
            self.memory,
            "--pids-limit",
            str(self.pids_limit),
            "--read-only",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,size={self.tmpfs_size}",
            "-v",
            f"{run_dir}:/work:rw",
            "-w",
            "/work",
            "-e",
            "OPENBLAS_NUM_THREADS=1",
            "-e",
            "OMP_NUM_THREADS=1",
            "-e",
            "MKL_NUM_THREADS=1",
            "-e",
            "NUMEXPR_NUM_THREADS=1",
            "-e",
            "XDG_CACHE_HOME=/tmp",
            "-e",
            "MPLCONFIGDIR=/tmp/matplotlib",
            self.image,
            *render_command,
        ]

        timed_out = False
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=run_dir,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as error:
            timed_out = True
            exit_code = None
            stdout = error.stdout or ""
            stderr = error.stderr or ""
        elapsed = time.monotonic() - started

        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")

        (logs_dir / "stdout.log").write_text(stdout, encoding="utf-8")
        (logs_dir / "stderr.log").write_text(stderr, encoding="utf-8")
        (logs_dir / "render.log").write_text(
            "\n".join(
                [
                    "$ " + " ".join(command),
                    "",
                    "## stdout",
                    stdout,
                    "",
                    "## stderr",
                    stderr,
                ]
            ),
            encoding="utf-8",
        )

        media_files = discover_media_files(media_dir)
        metadata = {
            "sandbox": self.name,
            "official": self.official,
            "container_image": self.image,
            "container_image_digest": self._image_digest(),
            "container_engine": self.engine,
            "network": "none",
            "elapsed_seconds": elapsed,
            "memory": self.memory,
            "cpus": self.cpus,
            "pids_limit": self.pids_limit,
            "tmpfs_size": self.tmpfs_size,
            "media": {str(path.relative_to(run_dir)): probe_media(path) for path in media_files},
        }
        return RenderResult(
            backend=self.name,
            official=self.official,
            command=command,
            exit_code=exit_code,
            timed_out=timed_out,
            stdout=stdout,
            stderr=stderr,
            media_files=[str(path.relative_to(run_dir)) for path in media_files],
            metadata=metadata,
        )

    def _image_digest(self) -> str | None:
        try:
            completed = subprocess.run(
                [self.engine, "image", "inspect", self.image, "--format", "{{.Id}}"],
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.strip() or None
