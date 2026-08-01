# steam-launchopts

Get, set, and clear per-game Steam launch options from the command line —
the same setting Steam's UI exposes under a game's *Properties → Launch
Options*.

It edits `~/.local/share/Steam/userdata/<id>/config/localconfig.vdf`
directly, using the `vdf` library to parse Valve's KeyValues format safely.
Game names are resolved by cross-referencing `appmanifest_<appid>.acf`
files across all of your Steam library folders, so output shows
`Game Name (appid)` instead of a bare number for installed games.

## Install

```console
$ uv tool install .
```

This puts a `steam-launchopts` command on your `PATH` (via `uv tool`'s
shim directory).

Or run it without installing, from inside the project:

```console
$ uv run steam-launchopts list
```

## Usage

List every game that currently has launch options set:

```console
$ steam-launchopts list
HELLDIVERS™ 2 (553850)	PROTON_ENABLE_WAYLAND=1 PROTON_ENABLE_HDR=1 PROTON_USE_NTSYNC=1  %command%
```

Look up a single game by its Steam appid:

```console
$ steam-launchopts get 553850
HELLDIVERS™ 2 (553850): PROTON_ENABLE_WAYLAND=1 PROTON_ENABLE_HDR=1 PROTON_USE_NTSYNC=1  %command%

$ steam-launchopts get 200510
200510: (no launch options set)
```

Set launch options for a game:

```console
$ steam-launchopts set 553850 "PROTON_ENABLE_WAYLAND=1 %command% -show-fps"
set LaunchOptions for HELLDIVERS™ 2 (553850)
```

Clear launch options for a game:

```console
$ steam-launchopts clear 553850
cleared LaunchOptions for HELLDIVERS™ 2 (553850)
```

Point at a specific `localconfig.vdf` (useful if more than one Steam
account has logged in on this machine):

```console
$ steam-launchopts --file /path/to/localconfig.vdf list
```

### Finding an appid

Appids are visible in a game's Steam store URL
(`store.steampowered.com/app/<appid>/...`), in `steam://` links, or via
`steam-launchopts list`/a browsed `appmanifest_*.acf` file for anything
already installed.

## Steam and file safety

Steam owns `localconfig.vdf` and rewrites it whenever it exits, which
would silently undo an edit made while it's running. To avoid that,
`set` and `clear` check whether Steam is running first:

- If it's running, you're prompted to confirm a shutdown. On yes, the
  tool runs `steam -shutdown` (a clean IPC shutdown, not a kill) and
  waits for the process to exit before writing.
- `get` and `list` are read-only and work regardless of whether Steam is
  running.

## Development

```console
$ uv sync
$ uv run steam-launchopts --help
```
