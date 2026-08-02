# Cerberus-AD — local fork setup & workflow

Personal notes for maintaining this fork of ADscan
(upstream: https://github.com/ADScanPro/adscan, BSL 1.1).

Repo: `git@github.com:A9u3ybaCyb3r/Cerberus-AD.git`

## Why this needed its own setup (not just `pip install`)

ADscan ships as two separate things that don't update together automatically:

1. **The launcher** (`adscan_launcher` + `adscan_core`) — a thin host-side
   CLI. This is the part `pipx install --editable .` actually installs. It
   mostly checks for updates and launches a Docker container.
2. **The runtime** (`adscan.py` + `adscan_internal`) — the actual interactive
   shell, all the attack-path/collection/exploitation logic. This is
   deliberately **excluded** from the pip package (`pyproject.toml`'s
   `[tool.setuptools] include` only lists `adscan_core*`/`adscan_launcher*`).
   It only exists baked into a Docker image, built by `Dockerfile.runtime`'s
   `runtime-lite` stage, which `COPY`s `adscan.py`/`adscan_core`/
   `adscan_internal`/`adscan_launcher` straight from this repo's source tree.

So editing anything under `adscan_internal/` has **zero effect** until the
Docker image is rebuilt from this checkout — a `pipx` editable install alone
is not enough.

## One-time setup

### 1. pipx install (editable)

```bash
cd /path/to/Cerberus-AD
pipx install --editable .
```

Installs the `cerberus-ad` command (renamed in `pyproject.toml` from
`adscan` specifically so it can coexist with a normally-installed `adscan`
without either shadowing the other). Launcher-level edits
(`adscan_launcher/**`, `adscan_core/**`) take effect immediately, no
reinstall needed.

### 2. Docker group access

```bash
sudo usermod -aG docker $USER
```

Then either start a fresh login session, or in an existing shell:
```bash
newgrp docker
# or, for a single command without switching group in the current shell:
sg docker -c 'docker ps'
```

### 3. Build the runtime image

```bash
docker build --target runtime-lite -t cerberus-ad:latest -f Dockerfile.runtime .
```

Large multi-stage build (compiles John the Ripper from source the first
time; hashcat uses a prebuilt binary on amd64). Expect it to take a while
cold; later builds reuse cached layers. The image tag matches
`DEFAULT_DOCKER_IMAGE` in `adscan_launcher/docker_commands.py` (also renamed
to `cerberus-ad:latest`), so the launcher resolves it locally without any
env var or `--image` override.

## Ongoing workflow — making a change

1. Edit code, commit as usual.
2. If you touched `adscan_internal/**` or `adscan.py`: rebuild the image
   (step 3 above) — this is the step that's easy to forget.
3. Run it: `cerberus-ad start` (or `cerberus-ad execute ...` for a scripted
   one-shot command).
4. `uv run pytest -m unit` before committing — covers everything under
   `adscan_internal/` without needing Docker or a live target.
5. `git push origin <branch>`.

If you only touched `adscan_launcher/**` or `adscan_core/**`, skip the
rebuild — the editable pipx install already picks those up.

## Switching between the official tool and this fork

Two independent commands, each with its own pipx venv, Docker image, and
`ADSCAN_HOME`/state directory (keyed off the binary name):
- `adscan` — official, if installed via `pipx install adscan`.
- `cerberus-ad` — this repo, editable install.

Running one never affects the other's install, image, or workspace data.

## Setting up a second machine

```bash
git clone git@github.com:A9u3ybaCyb3r/Cerberus-AD.git
cd Cerberus-AD
git checkout feature/bounded-attack-paths   # or whichever branch

pipx install --editable .
docker build --target runtime-lite -t cerberus-ad:latest -f Dockerfile.runtime .
```

That machine needs its own SSH key added to GitHub, or you can copy your
existing key over securely if you're fine reusing one across your own
machines.

## Troubleshooting

- **`docker build` fails with `open /home/<user>/.docker/buildx/.lock:
  permission denied`**: a prior `sudo docker` command left that lock file
  root-owned. Fix once: `sudo rm ~/.docker/buildx/.lock`.
- **`docker ps` / `docker build` says permission denied on the socket**:
  not in the `docker` group yet, or the group membership hasn't been picked
  up in this shell — see step 2 above (`newgrp docker` / `sg docker -c`).
- **Edited `adscan_internal/...` but `cerberus-ad start` still behaves like
  before**: forgot to rebuild the Docker image (ongoing workflow step 2
  above) — pipx editable installs do *not* cover this directory.
- **`pytest` can't import `adscan_internal`**: expected outside this repo's
  `uv` environment — `adscan_internal` is intentionally not part of the pip
  package (see "Why this needed its own setup" above). Run tests via
  `uv run pytest -m unit` from the repo root, not a plain `pytest`.
- **`adscan check`/`start` fails preflight on a missing wordlist or asset**:
  some build-time-only assets (a combined audit wordlist, a cheatsheet PDF)
  aren't included in the public GitHub source and have no runtime download
  path. If you hit one, add a small placeholder file at the expected path
  (repo-root `wordlists/`, `adscan_internal/assets/cheatsheet/`) so the
  existence check/COPY passes — the real content isn't needed for
  attack-path/graph_stats work, only for the specific feature that consumes
  it (password cracking, the printable cheatsheet).
