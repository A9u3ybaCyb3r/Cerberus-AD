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
compute cap by default` in the git log) and adds four new capabilities on
top of the fix:

| Addition | What it does |
|---|---|
| `graph_stats <domain>` | Read-only sizing of the attack graph — no path search |
| `attack_paths ... --target <name>` | Shortest path(s) to one specific node |
| `attack_paths ... --timeout <seconds>` | Wall-clock budget with partial results |
| `attack_paths ... --exclude-edges <rel1,rel2>` | Drop noisy edge types from traversal |

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

## Combining flags

All four are independent and composable:
```
attack_paths north.sevenkingdoms.local owned \
    --target "Domain Admins" \
    --exclude-edges GenericWrite \
    --timeout 30 \
    --max 5
```

## Everything else

`attack_paths <domain> owned` with no new flags still works exactly as
before, just compute-bounded by default now instead of unbounded (see the
compute-cap fix above) — no other behavior change. Every other ADscan
command (`kerberoast`, `search_adcs`, `smb_shares`, `creds`, `spraying`,
`start_auth`, etc.) is untouched by this fork; `help <command>` gives the
authoritative usage for each.
