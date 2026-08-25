# Running Verbal in Docker — quick reference

Short version of `DOCKER_GUIDE.md`, focused on **running on a server** and the
**do-I-need-sudo** question. One image holds Python + node/bun/deno; the engine
versions are pinned and verified at container start.

## 0. First-time setup on the server

```bash
git clone https://projects.cispa.saarland/c01abal/verbal.git
cd verbal
git clone https://github.com/reallyTG/fandango-slight-change.git fandango   # forked Fandango (prereq)
docker compose build
```

## 1. Do I need `sudo`?

It depends only on how the Docker daemon is exposed to your account — not on the
Dockerfile. Run this first:

```bash
docker info >/dev/null 2>&1 && echo "no sudo needed" || echo "need sudo / group / rootless"
docker info --format '{{.SecurityOptions}}' 2>/dev/null   # look for 'rootless'
```

| Situation | What to do |
|---|---|
| You're in the `docker` group | Nothing — `docker compose build` works as-is. Check: `id -nG \| tr ' ' '\n' \| grep -x docker` |
| Daemon runs as root, you're not in the group | Prefix everything: `sudo docker compose build`, `sudo docker compose run …` |
| Rootless Docker (security options show `rootless`) | Nothing — runs as you, no sudo |
| Only **Podman** is installed | `podman build -t verbal:latest .`; for compose use `podman compose …` (or `podman-compose`) |

Notes:
- Being added to the `docker` group is **root-equivalent** on the host. On a shared
  research server admins often won't grant it — expect `sudo`-per-command, rootless
  Docker, or Podman instead. Ask the admin which model they run.
- `sudo usermod -aG docker $USER` adds you to the group, but needs sudo once and a
  re-login (or `newgrp docker`) to take effect.

## 2. Run experiments

The entrypoint prints `engine pins OK: node=26.5.0, bun=1.3.14, deno=2.9.1` and
aborts (exit 1) if the engines ever drift. Prefix with `sudo` if section 1 says so.

```bash
# interactive shell
docker compose run --rm verbal bash

# end-to-end sanity check (tiny fixtures, isolated temp dir)
docker compose run --rm verbal tests/smoke_test.sh

# generation pipeline
docker compose run --rm verbal python src/main.py \
  -g -n 2 -r ./data/uniq-regexes-8.json -f -fn 50 -u -un 20 -d -dn 20

# differential eval (parallel + resumable) — set workers to your allotted cores
docker compose run --rm verbal python eval/run_eval.py --workers 12 --resume
```

## 3. Where outputs go

`results/` and `results-archive/` are bind-mounted to the host, so outputs land in
your checkout and survive the container. `data/` is mounted read-only. `--workers`
defaults to the host CPU count — pass it explicitly inside a CPU-limited container so
it doesn't oversubscribe. Keep `results/` on a native volume (not a slow network/bind
mount): a full eval writes ~373k harness files there and is I/O-sensitive.

## 4. If you can't get Docker access at all

Everything still runs bare-metal — Docker only isolates the toolchain. You then need
node **v26.5.0**, bun **1.3.14**, deno **2.9.1** first on `PATH`, plus the forked
Fandango installed (`pip install ./fandango`) and `pip install -r requirements.txt`.
The engine pins are not enforced outside Docker, so double-check `node --version`
etc. before trusting results.
