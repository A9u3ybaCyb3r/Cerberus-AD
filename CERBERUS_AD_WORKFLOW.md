# Cerberus-AD: complete start-to-finish workflow

This is the full "install it, run it, use every part of it" guide. It
complements two other docs in this repo, each with a narrower job:

- **`CERBERUS_AD_GUIDE.md`** — deep-dives *only* the features this fork added
  or changed vs. official ADscan (`graph_stats`, `attack_paths` flags, the
  disk-backed cache). Read that for the *why* behind each one.
- **`LOCAL_DEV_SETUP.md`** — for *developing* this fork (editing code,
  rebuilding the Docker image, troubleshooting the build). Read that if
  you're changing code, not just running the tool.

This document is for *using* the finished tool end to end on a fresh
machine, with every command it has, organized by when you'd reach for it.
The full command list below was pulled directly from source
(`grep "def do_" adscan.py`), not written from memory, so it's accurate as
of this fork's current state — not aspirational.

Every example below that touches a live domain uses `simply.cyber`
(`192.168.19.155`), a lab domain, and every numbered result you see quoted
(node counts, path counts, timings) is from an actual verified run against
it during this fork's development, not a fabricated sample.

---

## 0. The one thing to get right: this is not `adscan`

If you also have the official ADscan installed (`pipx install adscan`), the
two tools are designed to never collide, but only if you install *this
repo* and end up with the `cerberus-ad` command — not `adscan`.

| | Official ADscan | Cerberus-AD (this fork) |
|---|---|---|
| Repo | `github.com/ADScanPro/adscan` | `github.com/A9u3ybaCyb3r/Cerberus-AD` |
| pipx command | `adscan` | `cerberus-ad` |
| Docker image | `adscan/adscan-lite:latest` (real registry) | `cerberus-ad:latest` (local-only, never resolves to any registry — even the legacy fallback image names were repointed to this local tag specifically so an image pull can never silently fetch the official image under a different name) |
| State/workspace dir | `~/.adscan` | `~/.cerberus-ad` (set automatically the moment you run `cerberus-ad`, not something you have to configure — see `_default_adscan_home_for_fork_entrypoint` in `adscan_launcher/cli.py`) |

**Never run `pipx install adscan`** if your intent is to get this fork —
that installs the real thing. Always install *from this repo* (steps below).

**A caution on `cerberus-ad update`/`upgrade`**: those commands exist in the
official tool to pull the newest launcher/image from PyPI and the official
registry. For this fork, the Docker pull step is a structural no-op (the
image name doesn't exist on any registry, so it can only fail closed, never
silently swap in the official image), but don't rely on that as your update
path. To update this fork: `git pull` in your clone, then rebuild per
`LOCAL_DEV_SETUP.md`. Don't run `cerberus-ad update` expecting it to do
anything useful here.

---

## 1. Install on a fresh machine

```bash
git clone git@github.com:A9u3ybaCyb3r/Cerberus-AD.git
cd Cerberus-AD
git checkout feature/bounded-attack-paths   # or main, once merged

pipx install --editable .
```

That installs the launcher — the `cerberus-ad` command. This alone does
**not** get you the interactive shell or attack-path logic; that only exists
inside the Docker image, built from this same checkout:

```bash
# One-time: make sure your user can talk to the Docker daemon
sudo usermod -aG docker $USER
newgrp docker        # or open a new terminal session

# Build the runtime image (~10-15 min cold, mostly cached on rebuilds)
docker build --target runtime-lite -t cerberus-ad:latest -f Dockerfile.runtime .
```

If the build fails on a missing file under `wordlists/` or
`adscan_internal/assets/cheatsheet/`, see `LOCAL_DEV_SETUP.md`'s
troubleshooting section — a couple of build-time-only assets aren't in the
public GitHub source and need small placeholder files (already committed in
this repo as of this fork, so a fresh clone shouldn't hit this, but a future
upstream sync could reintroduce it).

### Verify the install actually landed correctly

```bash
which cerberus-ad          # should print a pipx venv path, NOT touch any `adscan` install
cerberus-ad --version       # prints launcher version + confirms image = cerberus-ad:latest
docker images cerberus-ad   # confirms the local image exists
```

Then confirm the state-directory isolation is actually in effect (this is
the property that keeps the two tools' workspace data from ever mixing):

```bash
cerberus-ad version          # any command triggers ADSCAN_HOME's default
ls ~/.cerberus-ad             # should now exist (logs/, state/)
```

If you also have `adscan` installed, `ls ~/.adscan` should show **only** data
from real `adscan` runs — never anything written by `cerberus-ad`.

Docker-mode also needs one authorization step the first time you run
anything that talks to Docker, in a session where `sudo` hasn't been used
yet:

```bash
sudo -v
cerberus-ad check   # should report "Docker-mode execution probe succeeded."
```

---

## 1.5 Quick start — the two ways to run it

Once install is confirmed, there are exactly two ways to actually use the
tool. Pick whichever matches what you're doing right now; both are covered
in full depth later (Parts 3 and 4).

**Option 1 — One shot, fully automated.** Good for "just compromise this
domain and show me everything," no manual steps in between:

```bash
export ADSCAN_HOME=~/.cerberus-ad
cerberus-ad ci auth --type ctf --interface eth0 \
    --domain simply.cyber --dc-ip 192.168.19.155 \
    -u alice.wonderland -p 'P@ssw0rd!' \
    -w SimplyCyber --keep-workspace
```

**Option 2 — Interactive shell.** Good for working a domain step by step,
inspecting results between phases, or running any of the ~140 commands in
Part 5 individually:

```bash
cerberus-ad start
```

then inside the shell:

```
start_auth simply.cyber --dc-ip 192.168.19.155 -u alice.wonderland -p 'P@ssw0rd!'
graph_stats simply.cyber
attack_paths simply.cyber owned
attack_paths simply.cyber owned --easy-first
```

Both were verified live against `simply.cyber` on this machine
(`Domain compromised ✓`, `11 attack paths identified`, `23 credentials
currently stored in workspace`).

---

## 2. The launcher commands (run on your host, not inside a domain session)

These are `cerberus-ad <command>`, not something you type inside the
interactive shell:

| Command | What it does |
|---|---|
| `install` | Install ADscan (Docker mode) — pulls/builds the image |
| `check` | Verify Docker-mode prerequisites (daemon reachable, host-helper, memory) |
| `doctor` | Fast one-shot health check: DNS, connectivity, auth, posture |
| `start` | Start the interactive shell (the REPL — where most of Part 4 below happens) |
| `ci` | Fully automated end-to-end scan, no prompts — see Part 3 |
| `demo` | Deterministic 60-second demo scan producing a real PDF |
| `execute` | Run exactly one REPL verb non-interactively (scripting/smoke-tests — a curated safe subset, not every REPL command; `cerberus-ad execute --list` shows which) |
| `deliver` | Full Client Deliverable Kit (4 PDFs + ZIP) — paid tier |
| `cheatsheet` | Free pentester cheatsheet PDF |
| `mitre-navigator` | MITRE ATT&CK Navigator layer (JSON) |
| `version` | Show launcher version |
| `update` / `upgrade` | Update — **see the caution in Part 0**, don't use this for updating the fork itself |
| `welcome` | The editorial welcome screen (default with no command) |

---

## 3. Fastest path to a full result: `ci` (fully automated)

For a lab/CTF engagement where you just want collection through
attack-path discovery done end to end, `ci` is the one-shot path — this is
what was used to produce every real number quoted in this document.

```bash
cerberus-ad ci auth --type ctf --interface eth0 \
    --domain simply.cyber --dc-ip 192.168.19.155 \
    -u alice.wonderland -p 'P@ssw0rd!' \
    -w SimplyCyber --keep-workspace
```

- `--type ctf` vs `--type audit`: CTF mode is allowed to actually execute
  attacks (get a shell, dump a hash) to prove compromise, not just report
  theoretical paths — appropriate for a lab, not a client engagement without
  explicit authorization for active exploitation.
- `--interface eth0`: the NIC that reaches the target subnet (check with
  `ip -4 addr show`).
- `-w SimplyCyber --keep-workspace`: names the workspace and keeps it after
  the run (otherwise it's an ephemeral one-off).

**Actual verified output from this run:**
```
Session Summary
  Domain compromised ✓
  11 attack paths identified
  2 new credentials obtained
  23 credentials currently stored in workspace
```

That's a real end-to-end result: collection, attack-graph construction, and
attack-path discovery/execution all worked correctly on this fork, on a live
domain, with the OOM-hardening fixes in place (no crash, no hang, on a graph
that ended up at 289 nodes / 206 edges).

---

## 4. The manual, step-by-step workflow (inside `cerberus-ad start`)

If you want to work a domain incrementally rather than one automated `ci`
sweep — the normal flow for a real engagement — this is the recommended
order. Everything after "start the shell" happens inside the REPL.

```bash
cerberus-ad start
```

### Step 1 — Authenticate / start collection

```
start_auth simply.cyber --dc-ip 192.168.19.155 -u alice.wonderland -p 'P@ssw0rd!'
```

Or `start_unauth <domain>` for unauthenticated recon first. `enum_domain_auth`
(and its phase-scoped variants) let you run collection *without* triggering
attack-path discovery yet — useful specifically so you can size the graph
before committing to a search (next step).

### Step 2 — Size the graph before searching it (this fork's addition)

```
graph_stats simply.cyber
```

**Actual verified output against this lab:**
```
node_count: 289  edge_count: 206
top_out_degree (first 5):
  ACCOUNT OPERATORS@SIMPLY.CYBER   60   {'ADCSESC9': 1, 'GenericAll': 59}
  DOMAIN USERS@SIMPLY.CYBER        11   {'ADCSESC1': 1, 'ADCSESC13': 1, ...}
  ALICE.WONDERLAND@SIMPLY.CYBER     7   {'CanPSRemote': 1, 'MemberOf': 6}
  HARLEY.QUINN@SIMPLY.CYBER         6   {'ADCSESC9': 1, 'GenericAll': 1, ...}
  ADMINISTRATOR@SIMPLY.CYBER        5   {'MemberOf': 5}
reachability_by_depth: {1: 8, 2: 17, 3: 21, 4: 23}
danger_notes: ['No high-fan-out principals or large reachable sets detected
  from these sources -- attack_paths should be safe to run at the default
  depth.']
```

This is a small lab graph, so the danger note correctly says it's safe to
run unrestricted — on a large real domain, this is where you'd see a warning
about a high-fan-out principal (the 100+ out-degree threshold) and know to
reach for `--exclude-edges` or a smaller `--depth` *before* running the full
search, instead of finding out from an OOM kill.

On a domain with a deep or messy OU tree — real companies routinely leave
old/decommissioned OUs in place, full of disabled leftover accounts —
`graph_stats <domain> --list-ous` lists the true OUs (not BloodHound's
generic Container noise) sorted by *actively enabled* object count, not raw
count, so a legacy graveyard OU doesn't outrank the one the company is
actually using:
```
graph_stats simply.cyber --list-ous
```

### Step 3 — Run attack-path discovery

```
attack_paths simply.cyber owned
```

**Actual verified output** (sequential mode, no flags, starting from
`alice.wonderland` — the owned credential used for `start_auth`):
```
3 paths found:
  alice.wonderland -> DC$
  alice.wonderland -> Domain Users -> Domain Admins -> Administrators -> simply.cyber
  alice.wonderland -> Domain Users -> Domain Controllers -> simply.cyber
```

Now the flags this fork adds, all independent and composable:

```
attack_paths simply.cyber owned --target "Domain Admins"          # shortest path(s) to one specific node
attack_paths simply.cyber owned --timeout 60                       # wall-clock budget, partial results on cutoff
attack_paths simply.cyber owned --exclude-edges GenericWrite       # drop noisy edge types from traversal
attack_paths simply.cyber owned --easy-first                       # prioritize practical over theoretical
attack_paths simply.cyber owned --easy-first --max 5 --timeout 30  # combine freely
```

**`--easy-first` verified live**, on a broader multi-user pull (21 total
paths found across several owned users):

```
DEFAULT order (target-importance first):
  len=2  alice.wonderland  -> simply.cyber (MemberOf, ADCSESC8, DCSync)
  len=1  barry.allen       -> simply.cyber (MemberOf x3, DCSync)
  ...

EASY-FIRST order (practical first):
  len=1  harley.quinn -> Everyone           (GenericAll, MemberOf)
  len=1  bob.builder  -> HR                 (MemberOf, WriteOwner)
  len=1  alice.wonderland -> DC$            (CanPSRemote)
  len=1  alice.wonderland -> Collectable Computers (MemberOf, CanPSRemote)
  len=1  barry.allen  -> simply.cyber       (MemberOf x3, DCSync)
```

Same underlying paths, reordered so the one-hop, already-actionable options
surface first instead of being buried behind a longer full-domain-compromise
chain that the default view treats as more "important."

See `CERBERUS_AD_GUIDE.md` for the full reasoning behind each flag.

### Step 4 — Everything else, as needed

`attack_paths` results now also get cached to disk automatically
(`domains/<domain>/.attack_paths_cache/results/`), so re-running the same
query later — even in a brand-new `cerberus-ad execute` process — reuses the
computation instead of paying for it again. Verified: a repeat call against
this same lab graph was **~7x faster** served from disk (0.029s → 0.004s)
with identical results. No flag needed, it's automatic; disable with
`ADSCAN_ATTACK_PATHS_DISK_CACHE_ENABLED=0` if you ever need to force a clean
recompute for debugging.

---

## 5. Full command reference

Every REPL command this build has, grouped by purpose. Descriptions for
commands this fork didn't touch are intentionally omitted here — `help
<command>` inside the shell is the authoritative source and works
identically to official ADscan for all of them. Commands **this fork
modified** are marked with a star and cross-reference `CERBERUS_AD_GUIDE.md`.

**Session & workspace**
`workspace`, `session`, `sessions`, `set`, `get_flags`, `info`, `help`,
`exit`, `clear`, `clear_all`, `jobs`, `export`, `download`, `upload`, `cd`,
`ls`, `cat`, `cp`, `mv`, `mkdir`, `rm`, `system`, `ask`, `update`

**Auth & scan entry points**
`start_auth`, `start_unauth`, `unauth_scan`, `add_auths`, `clear_auths`,
`clear_creds_and_auths`, `sync_clock_with_pdc`, `update_resolv_conf`,
`check_dns`, `extract_base_dn`, `extract_netbios`

**Domain enumeration & inventory**
`enum_domain_auth` (+ phase-scoped forms), `enum_authenticated`,
`enum_with_users`, `refresh_inventory`, `update_domain_data`,
`inventory_diff`, `host_inventory`, `identity_inventory`, `computers_all`,
`computers_with_laps`, `computers_without_laps`, `all_users`,
`admin_users`, `privileged_users`, `stale_enabled_users`, `pwdneverexpires`,
`passnotreq`, `obsolete_os_audit`, `is_computer_dc`, `is_user_dc`,
`password_policy`, `enum_configs`, `enum_trusts`, `posture`

**LDAP / ACL enumeration**
`ldap_active_users`, `ldap_anonymous`, `ldap_computers`,
`ldap_security_audit`, `enum_cross_domain_acl`, `enumerate_user_aces`,
`enum_all_user_privs`, `enum_all_user_postauth_access`,
`user_postauth_access`, `kerberos_enum_users`, `rid_cycling`

**Credential harvesting & roasting**
`kerberoast`, `kerberoast_preauth`, `asreproast`, `timeroast`, `dcsync`,
`krbtgt`, `harvest`, `creds`, `cracking`, `cracking_history`, `spraying`,
`gpp_passwords`, `gpp_autologin`, `check_autologon`,
`check_firefox_credentials`, `check_powershell_transcripts`,
`check_winrm_sensitive_data`, `show_powershell_history`

**SMB & shares**
`smb_shares`, `smb_scan`, `smb_auth_shares`, `smb_guest_shares`,
`smb_null_enum_users`, `smb_user_descriptions`, `open_smb`,
`capture_ntlm_share_drop`, `stop_writeshare`

**Poisoning & relay**
`poisoning`, `stop_poisoning`, `clear_poisoning`, `relay_ldap`,
`relay_rbcd`, `generate_relay_list`, `check_ntlm_auth`,
`check_dc_ntlm_auth_type`

**Host access & dumping**
`dump_host`, `dump_lsa`, `dump_lsass`, `dump_sam`, `dump_dpapi`,
`dump_registries`, `secretsdump_registries`, `deploy_binary`,
`mssql_check_impersonate`, `mssql_impersonate`, `exploit_gpo_abuse`,
`exploit_gpo_rollback`, `raise_child`, `session`, `dc_access`

**ADCS**
`search_adcs`, `enum_adcs_privs`, `show_adcs_cache`

**Attack graph & paths** ★
`attack_paths` ★ (`--target`/`--timeout`/`--exclude-edges`/`--easy-first`),
`graph_stats` ★ (new command), `attack_path_discovery`, `attack_steps`,
`paths_execute`, `paths_inspect`, `reset_attack_path_statuses`,
`validate_attack_graph`, `users`

**CVEs**
`cves`, `enum_cve_all`, `enum_cve_dcs`

**Reporting**
`generate_report`, `initialize_report`, `massdns_report`, `show_timeline`,
`deliver`

**Pivoting**
`ligolo`

**Misc**
`benchmark`, `binary_ops`, `cheat`, `cheatsheet`

For anything not covered above: `help <command>` inside the shell.

---

## 6. Troubleshooting

Docker/pipx/build issues → `LOCAL_DEV_SETUP.md`'s troubleshooting section.
Feature-specific behavior (why a flag exists, what it changes) →
`CERBERUS_AD_GUIDE.md`. If `cerberus-ad check` reports the host-helper needs
sudo, that's expected on a fresh shell session — run `sudo -v` once and
retry.
