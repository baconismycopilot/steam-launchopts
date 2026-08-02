"""Get/set/list per-game Steam launch options from the command line.

Edits ~/.local/share/Steam/userdata/<id>/config/localconfig.vdf, which is
the same file Steam's "Launch Options" field in Properties writes to.
"""

import argparse
import glob
import os
import subprocess
import sys
import time

import vdf

STEAM_ROOT = os.path.expanduser("~/.local/share/Steam")


def find_localconfig():
    matches = glob.glob(os.path.join(STEAM_ROOT, "userdata", "*", "config", "localconfig.vdf"))
    if not matches:
        sys.exit(f"error: no localconfig.vdf found under {STEAM_ROOT}/userdata/*/config/")
    if len(matches) > 1:
        sys.exit(
            "error: multiple Steam accounts found on this machine, pick one with "
            "--file <path>:\n" + "\n".join(matches)
        )
    return matches[0]


def steam_is_running():
    try:
        result = subprocess.run(["pgrep", "-x", "steam"], stdout=subprocess.DEVNULL)
    except FileNotFoundError:
        sys.exit(
            "error: `pgrep` is not on PATH, so this tool cannot tell whether Steam is "
            "running (Steam rewrites localconfig.vdf on exit and would undo the change). "
            "Close Steam yourself, then re-run with --skip-steam-check."
        )
    return result.returncode == 0


def shutdown_steam(timeout=30):
    prompt = (
        "Steam is currently running and needs to be closed before editing launch "
        "options (it rewrites localconfig.vdf on exit, which would clobber this "
        "change). Shut it down now? [y/N] "
    )
    if not sys.stdin.isatty():
        sys.exit(
            "error: Steam is running but stdin is not a terminal, so it cannot be "
            "shut down interactively. Close Steam yourself, then re-run."
        )
    try:
        answer = input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit("aborted: Steam was not shut down")
    if answer.strip().lower() not in ("y", "yes"):
        sys.exit("aborted: Steam was not shut down")

    try:
        result = subprocess.run(
            ["steam", "-shutdown"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except FileNotFoundError:
        sys.exit(
            "error: Steam is running but no `steam` binary is on PATH (Flatpak and Snap "
            "installs work this way). Close Steam yourself, then re-run."
        )
    if result.returncode != 0:
        sys.exit(
            f"error: `steam -shutdown` failed with exit status {result.returncode}, "
            "close Steam manually and try again"
        )

    print("waiting for Steam to close...", end="", flush=True)
    for _ in range(timeout):
        if not steam_is_running():
            print(" done")
            return
        print(".", end="", flush=True)
        time.sleep(1)
    print()
    sys.exit("error: Steam did not shut down in time, try again or close it manually")


def get_apps(data):
    try:
        return data["UserLocalConfigStore"]["Software"]["Valve"]["Steam"]["apps"]
    except KeyError:
        sys.exit(
            "error: unexpected localconfig.vdf structure (Software/Valve/Steam/apps not found)"
        )


def library_paths():
    paths = [STEAM_ROOT]
    libraryfolders = os.path.join(STEAM_ROOT, "steamapps", "libraryfolders.vdf")
    try:
        with open(libraryfolders, encoding="utf-8") as f:
            data = vdf.load(f)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return paths
    for entry in data.get("libraryfolders", {}).values():
        # Current Steam stores {"path": ...}; older releases stored a bare path string.
        path = entry.get("path") if isinstance(entry, dict) else entry
        if isinstance(path, str) and path and path not in paths:
            paths.append(path)
    return paths


def load_app_names():
    names = {}
    for library in library_paths():
        pattern = os.path.join(library, "steamapps", "appmanifest_*.acf")
        for manifest in glob.glob(pattern):
            try:
                with open(manifest, encoding="utf-8") as f:
                    data = vdf.load(f)
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            state = data.get("AppState", {})
            appid, name = state.get("appid"), state.get("name")
            if appid and name:
                names[appid] = name
    return names


def app_label(appid, names):
    name = names.get(appid)
    return f"{name} ({appid})" if name else appid


def launch_options(apps, appid):
    """Return the launch options set for appid, or None if there are none.

    Steam leaves an empty "LaunchOptions" behind when the field is cleared in
    the UI, so an empty value counts as unset.
    """
    entry = apps.get(appid)
    if not isinstance(entry, dict):
        return None
    return entry.get("LaunchOptions") or None


def cmd_get(args, data):
    apps = get_apps(data)
    label = app_label(args.appid, load_app_names())
    opts = launch_options(apps, args.appid)
    if opts is None:
        print(f"{label}: (no launch options set)")
        return
    print(f"{label}: {opts}")


def cmd_list(args, data):
    apps = get_apps(data)
    names = load_app_names()
    found = False
    for appid in apps:
        opts = launch_options(apps, appid)
        if opts:
            found = True
            print(f"{app_label(appid, names)}\t{opts}")
    if not found:
        print("(no games have launch options set)")


def cmd_set(args, data):
    apps = get_apps(data)
    names = load_app_names()
    if args.appid not in apps and args.appid not in names and not args.force:
        sys.exit(
            f"error: appid {args.appid} is not in this account's config and no installed "
            "game has it, so this is most likely a typo. Pass --force to add it anyway."
        )

    label = app_label(args.appid, names)
    if launch_options(apps, args.appid) == args.options:
        print(f"{label} already has these launch options, nothing to do")
        return None

    def apply(data):
        apps = get_apps(data)
        entry = apps.get(args.appid)
        if not isinstance(entry, dict):
            entry = apps[args.appid] = {}
        entry["LaunchOptions"] = args.options

    return apply, f"set LaunchOptions for {label}"


def cmd_clear(args, data):
    apps = get_apps(data)
    label = app_label(args.appid, load_app_names())
    if launch_options(apps, args.appid) is None:
        print(f"{label} has no launch options set, nothing to do")
        return None

    def apply(data):
        entry = get_apps(data).get(args.appid)
        if isinstance(entry, dict):
            entry.pop("LaunchOptions", None)

    return apply, f"cleared LaunchOptions for {label}"


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return vdf.load(f)
    except OSError as e:
        sys.exit(f"error: cannot read {path}: {e.strerror}")
    except (SyntaxError, UnicodeDecodeError) as e:
        sys.exit(f"error: cannot parse {path}: {e}")


def write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        vdf.dump(data, f, pretty=True)
    os.replace(tmp, path)


def appid_arg(value):
    if not (value.isascii() and value.isdigit()):
        raise argparse.ArgumentTypeError(
            f"appid must be a number (as in store.steampowered.com/app/<appid>), got {value!r}"
        )
    return value


def main():
    # Game names hold characters an ASCII stdout (LC_ALL=C, some log capture) cannot
    # encode; degrade them to escapes rather than dying halfway through the output.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")

    parser = argparse.ArgumentParser(description="Get/set Steam per-game launch options.")
    parser.add_argument("--file", help="path to localconfig.vdf (default: auto-detect)")
    parser.add_argument(
        "--skip-steam-check",
        action="store_true",
        help="write without checking whether Steam is running (only safe once it is closed)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_get = sub.add_parser("get", help="print launch options for an appid")
    p_get.add_argument("appid", type=appid_arg)
    p_get.set_defaults(func=cmd_get, mutates=False)

    p_list = sub.add_parser("list", help="list all appids with launch options set")
    p_list.set_defaults(func=cmd_list, mutates=False)

    p_set = sub.add_parser("set", help="set launch options for an appid")
    p_set.add_argument("appid", type=appid_arg)
    p_set.add_argument("options")
    p_set.add_argument(
        "--force", action="store_true", help="accept an appid this machine knows nothing about"
    )
    p_set.set_defaults(func=cmd_set, mutates=True)

    p_clear = sub.add_parser("clear", help="remove launch options for an appid")
    p_clear.add_argument("appid", type=appid_arg)
    p_clear.set_defaults(func=cmd_clear, mutates=True)

    args = parser.parse_args()
    path = args.file or find_localconfig()

    # Read and inspect before touching Steam: a bad path or a no-op command should
    # never cost the user a running game session.
    data = load(path)
    result = args.func(args, data)
    if not args.mutates or result is None:
        return

    apply, message = result
    if not args.skip_steam_check and steam_is_running():
        shutdown_steam()
        # Steam rewrote localconfig.vdf as it exited, so the copy read above is stale.
        data = load(path)

    apply(data)
    write(path, data)
    print(message)


if __name__ == "__main__":
    main()
