# Sandbox

Build the official ManimBench runtime image:

```bash
cd manimbench
docker build -t manimbench-manimce:latest -f sandbox/Dockerfile .
```

Official benchmark runs should use the container backend. The runner starts the
container with network disabled, a read-only root filesystem, a single writable
`/work` mount for the per-task run directory, CPU and memory limits, process
limits, and a timeout.

The local sandbox is only a development fallback and is marked non-official in
result metadata.
