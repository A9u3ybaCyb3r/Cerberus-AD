# Cerberus-AD usage guide

Cerberus-AD is a personal fork of [ADscan](https://github.com/ADScanPro/adscan)
(BSL 1.1) that fixes an OOM in attack-path discovery and adds tools for
sizing up a graph before running an expensive search. Everything else in
ADscan — collection, Kerberoasting, ADCS, credential harvesting, spraying,
reporting — is untouched and works exactly like the official tool. This
guide covers only what's new or changed here; run `help <command>` inside
the shell for anything not covered below (it works the same as the official
tool for every command this fork didn't touch).

This is **not** the official ADscan distribution. If you also have `adscan`
installed via pipx, that's the real thing — `cerberus-ad` is this fork, kept
deliberately separate (own command name, own Docker image, own state
directory) so the two never collide. See `LOCAL_DEV_SETUP.md` for how that
separation is set up and how to rebuild after making further changes.

## What's different here

`attack_paths <domain> owned` on the official tool can OOM-kill on
non-trivial graphs — the compute-time path cap is unbounded by default, so
nothing stops a fully unbounded DFS from running per owned principal until
the kernel intervenes. This fork fixes that (see `fix: bound attack-path
compute cap by default` in the git log) and adds several new capabilities on
top of the fix:

| Addition | What it does |
|---|---|
| `graph_stats <domain>` | Read-only sizing of the attack graph — no path search |
| `graph_stats ... --list-ous` | List real OUs sorted by *active* usage, cutting through legacy-OU noise |
| `attack_paths ... --target <name>` | Shortest path(s) to one specific node |
| `attack_paths ... --timeout <seconds>` | Wall-clock budget with partial results |
| `attack_paths ... --exclude-edges <rel1,rel2>` | Drop noisy edge types from traversal |
| `attack_paths ... --easy-first` | Sort by "what can I actually go do now," not target importance |
| *(automatic)* | Attack-path results persist to disk, reused across separate command runs |

## Recommended workflow for an unfamiliar or large domain

Don't run `attack_paths <domain> owned` blind on a domain you don't already
know the shape of. Instead:

```
enum_domain_auth_phase1 <domain>      # collection only -- no attack-path discovery yet
graph_stats <domain>                   # see fan-out/reachability before committing to a search
attack_paths <domain> owned --target "Domain Admins"   # or a bounded broad search, see below
```

`enum_domain_auth_phase1` runs collection through Phase 1 only and stops
before attack-path discovery — this is the existing ADscan command that lets
you decouple the two, it's not new to this fork. `graph_stats` (new) reads
the graph that collection just wrote and reports numbers before any DFS runs
against it.

## `graph_stats <domain>` [--from &lt;label&gt;] [--top N]

Node/edge counts, the principals with the highest out-degree (a fan-out
early-warning), and BFS-based reachability estimates per hop depth (1-4).
Does no path enumeration — safe to run on any graph size, including ones
where `attack_paths` would be expensive. Cost is O(V+E) regardless of depth
requested, unlike `attack_paths` whose cost is dominated by the number of
distinct simple paths (which can be combinatorial in fan-out).

Flags:
- `--from <label>`: source node for reachability estimates. Default: all
  owned domain principals.
- `--top N`: how many highest out-degree principals to show. Default: 15.

Examples:
```
graph_stats north.sevenkingdoms.local
graph_stats north.sevenkingdoms.local --from jon.snow
graph_stats north.sevenkingdoms.local --top 25
```

Sample output shape:
```
Graph stats for north.sevenkingdoms.local: 842 nodes, 3105 edges.

Top 15 by out-degree
┌────────────────────┬────────────┬───────────────┐
│ Principal           │ Out-degree │ Top relation  │
├────────────────────┼────────────┼───────────────┤
│ SVC-BACKUP           │        412 │ GenericWrite x398 │
│ ...
└────────────────────┴────────────┴───────────────┘

Reachability estimate from: jon.snow, arya.stark
  depth 1: ~12 nodes reachable
  depth 2: ~58 nodes reachable
  depth 3: ~301 nodes reachable
  depth 4: ~301 nodes reachable

Danger estimate:
  'SVC-BACKUP' controls 412 objects (mostly 'GenericWrite', 398x) -- a
  full-depth attack_paths search through this principal may fan out
  combinatorially. Consider --exclude-edges or a lower --depth.
```

That's the signal to reach for `--exclude-edges GenericWrite` or a smaller
`--depth` before running the full search, instead of finding out the hard
way.

## `graph_stats <domain> --list-ous`

Lists the domain's true OUs (`kind: "OU"` — not BloodHound's generic
`Container` objects, which also cover purely administrative/system LDAP
containers and would just be noise here), sorted by *enabled* descendant
object count rather than raw count. Real domains routinely keep
old/decommissioned OUs around — a former department, a site that got shut
down — full of disabled accounts nobody deleted for process or political
reasons. Sorting by what's actually enabled right now, not by however many
stale objects happen to still be sitting there, surfaces the OU the company
is actually operating out of.

```
graph_stats north.sevenkingdoms.local --list-ous
```

Sample output shape:
```
3 organizational unit(s) found for north.sevenkingdoms.local, sorted by
enabled descendant object count -- an OU with a large gap between 'Total
objects' and 'Enabled' is likely legacy/decommissioned structure kept
around for process reasons, not where the company actually operates.

┌──────────────┬───────┬─────────┬───────────────┬──────────────────────────────────┐
│ OU            │ Depth │ Enabled │ Total objects │ Distinguished name                │
├──────────────┼───────┼─────────┼───────────────┼──────────────────────────────────┤
│ Winterfell     │     1 │     412 │            418 │ OU=Winterfell,DC=north,...        │
│ OldCastleBlack │     1 │       3 │            187 │ OU=OldCastleBlack,DC=north,...    │
│ Domain Contr…  │     1 │       2 │              2 │ OU=Domain Controllers,DC=north,...│
└──────────────┴───────┴─────────┴───────────────┴──────────────────────────────────┘
```

Here `Winterfell` (412 enabled of 418 total) is obviously the real,
actively-used OU; `OldCastleBlack` (3 enabled of 187 total) is exactly the
legacy-cruft case this sorting is meant to catch — high total object count,
almost entirely stale.

The `Depth` column counts nested `OU=` components in the DN (2 for
`OU=Sales,OU=Corp,DC=...`), a rough signal for how deep in the tree an OU
sits. `--list-ous` replaces the normal stats output for that invocation —
it doesn't combine with `--from`/`--top`.

## `attack_paths <domain> [owned|user|user1 user2...] --target <name>`

Shortest-simple-paths-first search toward one specific named node (a group,
computer, or user — anything `attack_paths` would otherwise treat as a
generic terminal) instead of "all paths to any high-value target". Combine
with any of the normal scopes.

Results are shortest-first and bounded by `--max` — the search stops as soon
as enough paths are found at the shallowest length that has them, so it
never pays for an unbounded broad search when you already know the
destination.

Examples:
```
attack_paths north.sevenkingdoms.local owned --target "Domain Admins"
attack_paths north.sevenkingdoms.local jon.snow --target "DC01$"
attack_paths north.sevenkingdoms.local owned --target "Domain Admins" --max 5
```

Multi-word names don't need quoting (the shell greedily consumes tokens up
to the next `--flag`), but quoting still works if you prefer it:
```
attack_paths north.sevenkingdoms.local owned --target Domain Admins
attack_paths north.sevenkingdoms.local owned --target "Domain Admins"
```

## `attack_paths ... --timeout <seconds>`

Wall-clock budget for the whole computation, shared across the entire
scope's sweep (e.g. the whole `owned` run, not reset per principal). Returns
whatever paths were found before the deadline instead of running to
completion or risking an OOM on a pathologically fan-out-heavy graph.
Bypasses the path cache — a timeout-truncated result is never served later
as if it were complete.

```
attack_paths north.sevenkingdoms.local owned --timeout 60
```

If the deadline is hit, you'll see:
```
attack_paths: stopped after 60s timeout -- showing 143 path(s) found before
the deadline. This may be a partial result; re-run with a longer --timeout,
a narrower --depth/--target, or --exclude-edges for a complete search.
```

## `attack_paths ... --exclude-edges <rel1,rel2>`

Drops matching relation types from traversal entirely, before the DFS ever
sees them — not a display filter. Use this to deprioritize noisy,
high-fan-out edge types (often lab noise-generation tooling, or a
`graph_stats`-flagged principal) so search budget isn't wasted fanning out
through them before reaching paths that matter. Comma-separated,
case-insensitive.

```
attack_paths north.sevenkingdoms.local owned --exclude-edges GenericWrite,AddMember
attack_paths north.sevenkingdoms.local owned --exclude-edges genericwrite --target "Domain Admins"
```

Unrecognized relation names get a warning (not an error — a graph can
legitimately contain custom/derived relations) and are still excluded.

## `attack_paths ... --easy-first`

Re-sorts results toward what you can practically go do right now, instead of
the default ordering (target importance first: Tier 0 > high-value > pivot,
*then* path length/effort as a late tiebreaker). Concretely:

1. Paths starting from a credential you already own, first.
2. Then the shortest path (fewest hops).
3. Then the lowest aggregate technique-effort score.
4. Falls back to the normal target-importance tiering only as a final
   tiebreak, so a genuinely critical target still doesn't get buried.

This matters because the default ordering can bury a one-hop path you can
execute *right now* (e.g. ADCS ESC1 — tagged "high effort" in the shared
catalog even though it's often one of the most reliable real-world
techniques) behind a longer, harder multi-hop chain to a target the tool
considers nominally more important.

```
attack_paths north.sevenkingdoms.local owned --easy-first
attack_paths north.sevenkingdoms.local jon.snow --easy-first --max 5
```

Doesn't change what's found, only the order — combine freely with `--target`,
`--timeout`, `--exclude-edges`, `--max`.

## Attack-path results now persist to disk automatically

Previously, computed attack-path results were cached only in memory for the
life of one process. That's close to useless for `cerberus-ad execute
attack_paths ...` (a fresh process every call) or a `ci` re-run — every
invocation recomputed from scratch, no matter how expensive. Results are now
also written to `domains/<domain>/.attack_paths_cache/results/` inside the
workspace, keyed the same way the in-memory cache already is (bound to the
graph and membership-snapshot file's mtime, so a changed graph never serves a
stale disk result). No flag needed — this is on by default. Verified live:
a repeat call against a real collected graph was ~7x faster on the second
(disk-served) run.

Tuning (rarely needed):
- `ADSCAN_ATTACK_PATHS_DISK_CACHE_ENABLED=0` — disable entirely.
- `ADSCAN_ATTACK_PATHS_DISK_CACHE_MAX_FILES=<N>` — how many distinct result
  sets to keep per domain before pruning the oldest (default 200).

## Combining flags

All flags are independent and composable:
```
attack_paths north.sevenkingdoms.local owned \
    --target "Domain Admins" \
    --exclude-edges GenericWrite \
    --timeout 30 \
    --easy-first \
    --max 5
```

## Known memory limitations for very large domains

Beyond the compute-cap fix, two more OOM-relevant issues were found and
fixed in the opt-in `ADSCAN_ATTACK_PATH_WORKERS` parallel-DFS path (off by
default, but the thing you'd reach for specifically to speed up a large
domain): parallel `owned`/principals runs used to ignore the shared
`max_paths` budget entirely (memory could hit `principal_count × max_paths`)
and silently dropped `--timeout`/`--exclude-edges`. Both are fixed — see
`fix: share max_paths budget across parallel-principals workers` in the git
log. The attack-path result cache also got a third eviction budget bounding
total records summed across all cache entries, not just entry count, since a
large domain with many owned principals produces many distinct cache keys
(see `fix: bound total attack-path cache memory by record count`).

Two remaining costs were investigated and are **not** fixed here, by design:

- **Whole-graph JSON loading.** `load_attack_graph` does one `json.load()`
  of the full node/edge graph into full property-bag dicts — no streaming or
  lazy loading. This is an architectural floor of the whole-graph-in-memory
  model, not a small fix; a real fix means a different on-disk graph format.
  The existing maintenance-pass skip (persisted across sessions) already
  avoids redundant O(V+E) work on repeat loads, so there's no cheap win left
  here.
- **Parallel worker graph duplication.** Parallel DFS workers
  (`ADSCAN_ATTACK_PATH_WORKERS`) use Python's `spawn` multiprocessing
  context intentionally, for PyInstaller/cross-platform compatibility — each
  worker gets its own pickled copy of the graph via the pool initializer, so
  peak memory is roughly `(workers + 1) × graph size`. Forcing `fork` to get
  copy-on-write sharing would risk breaking packaged-binary portability for
  a code path that's off by default and, per this repo's own measurements,
  gives no measured speedup on real attack-path graphs anyway. **Leave
  parallel workers off for large-domain runs** — sequential mode (the
  default) is the one that's been hardened here.

## Everything else

`attack_paths <domain> owned` with no new flags still works exactly as
before, just compute-bounded by default now instead of unbounded (see the
compute-cap fix above) — no other behavior change. Every other ADscan
command (`kerberoast`, `search_adcs`, `smb_shares`, `creds`, `spraying`,
`start_auth`, etc.) is untouched by this fork; `help <command>` gives the
authoritative usage for each.
