# The sandbox

Model-written code is untrusted. Every scene renders in a container that has:

- no network;
- a read-only root filesystem, with a small in-memory `/tmp`;
- no Linux capabilities, and no way to gain privileges;
- the host user's id, not root;
- limits on memory (4 GB), CPUs (2), processes (256) and file size (4 GB);
- one writable folder: the sample's own.

A render that passes its time limit is stopped by killing the container by
name. The first megabyte of output is kept and the rest is discarded.

## The Manim version

`sandbox/runtime.yaml` is the one place the Manim version is set. It names the
official `manimcommunity/manim` image for that release and pins it by digest,
so a tag that is moved later cannot change results.

To move to a new Manim release:

```bash
manimbench sandbox update 0.23.0
```

That pulls the image, checks that it really reports that version, and rewrites
the file. Then run `python -m pytest`: the container tests render the
reference scenes for every task on the new version. The version is part of the
prompt, so answers written for the old version become stale and results on
different versions are never mixed.

`manimbench sandbox info` shows what is pinned. `manimbench sandbox pull`
fetches it.

## What the harness does

`src/manimbench/sandbox/harness.py` runs inside the container. It renders the
scene through Manim's own command line and, after every animation, records the
text on screen and where it is. The host reads that record to score layout.
