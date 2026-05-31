from __future__ import annotations

import os
import resource
import subprocess
import time
from pathlib import Path

from manimbench.models import RenderResult
from manimbench.runtime.manimce import ManimCERuntime, discover_media_files, probe_media


class LocalSandbox:
    """Development-only subprocess sandbox.

    This backend isolates directories and applies best-effort Linux resource
    limits, but it is not strong isolation. Results are always non-official.
    """

    name = "local"
    official = False

    def __init__(self, memory_mb: int = 4096, cpu_seconds: int = 180, process_limit: int = 2048):
        self.memory_mb = memory_mb
        self.cpu_seconds = cpu_seconds
        self.process_limit = process_limit

    def render(
        self,
        run_dir: Path,
        solution_path: Path,
        runtime: ManimCERuntime,
        timeout_seconds: int,
        fps: int,
        scene_class: str,
    ) -> RenderResult:
        media_dir = run_dir / "media"
        logs_dir = run_dir / "logs"
        media_dir.mkdir(parents=True, exist_ok=True)
        logs_dir.mkdir(parents=True, exist_ok=True)

        command = runtime.command(
            solution_path=solution_path,
            media_dir=media_dir,
            fps=fps,
            scene_class=scene_class,
        )
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
                env=self._environment(),
                preexec_fn=self._limit_resources if os.name == "posix" else None,
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
            "elapsed_seconds": elapsed,
            "limits": {
                "memory_mb": self.memory_mb,
                "cpu_seconds": self.cpu_seconds,
                "timeout_seconds": timeout_seconds,
                "processes": self.process_limit,
            },
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

    def _limit_resources(self) -> None:
        memory_bytes = self.memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (self.cpu_seconds, self.cpu_seconds + 5))
        resource.setrlimit(resource.RLIMIT_NPROC, (self.process_limit, self.process_limit))

    def _environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "OPENBLAS_NUM_THREADS": "1",
                "OMP_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
                "NUMEXPR_NUM_THREADS": "1",
                "XDG_CACHE_HOME": str(Path.cwd() / ".cache"),
                "MPLCONFIGDIR": str(Path.cwd() / ".cache" / "matplotlib"),
            }
        )
        return env
