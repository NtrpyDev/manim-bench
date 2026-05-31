# Deploying manimbench.site

The public site lives in `website/`. Benchmark runs publish fresh data into a deploy bundle via `manimbench build-site`.

## Cloudflare Pages (recommended)

1. Push this repository to GitHub.
2. In Cloudflare Dashboard → **Workers & Pages** → **Create application** → **Pages** → **Connect to Git**.
3. Select the ManimBench repository.
4. Build settings:
   - **Production branch:** `main`
   - **Build command:** *(leave empty, static site)*
   - **Build output directory:** `website`
5. After nameserver propagation, add custom domain **manimbench.site** under **Custom domains**.
6. The `website/CNAME` file is included for GitHub Pages compatibility; Cloudflare uses dashboard DNS instead.

## Publish after a benchmark run

From the repo root:

```bash
manimbench report --run-dir runs/<run_id>
manimbench build-site \
  --report-dir reports/<run_id> \
  --output-dir website/dist
```

Deploy `website/dist/` (or copy `data/leaderboard.json` and `videos/` into `website/` and redeploy).

For model workspace runs, `./run_benchmark.sh` already calls `build-site` into `site/<run_id>/`.

## Local preview

Any static file server works:

```bash
cd website
python -m http.server 8080
```

Open http://localhost:8080
