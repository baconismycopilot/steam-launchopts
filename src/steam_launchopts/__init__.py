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
            "error: multiple Steam accounts found on this machine, pass one explicitly:\n"
            + "\n".join(matches)
        )
    return matches[0]


def steam_is_running():
    result = subprocess.run(["pgrep", "-x", "steam"], stdout=subprocess.DEVNULL)
    return result.returncode == 0


def shutdown_steam(timeout=30):
    answer = input(
        "Steam is currently running and needs to be closed before editing launch "
        "options (it rewrites localconfig.vdf on exit, which would clobber this "
        "change). Shut it down now? [y/N] "
    )
    if answer.strip().lower() not in ("y", "yes"):
        sys.exit("aborted: Steam was not shut down")

    subprocess.run(["steam", "-shutdown"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
        sys.exit("error: unexpected localconfig.vdf structure (Software/Valve/Steam/apps not found)")


def library_paths():
    paths = [STEAM_ROOT]
    libraryfolders = os.path.join(STEAM_ROOT, "steamapps", "libraryfolders.vdf")
    try:
        with open(libraryfolders) as f:
            data = vdf.load(f)
    except (OSError, SyntaxError):
        return paths
    for entry in data.get("libraryfolders", {}).values():
        if isinstance(entry, dict) and entry.get("path"):
            paths.append(entry["path"])
    return paths


def load_app_names():
    names = {}
    for library in library_paths():
        pattern = os.path.join(library, "steamapps", "appmanifest_*.acf")
        for manifest in glob.glob(pattern):
            try:
                with open(manifest) as f:
                    data = vdf.load(f)
            except (OSError, SyntaxError):
                continue
            state = data.get("AppState", {})
            appid, name = state.get("appid"), state.get("name")
            if appid and name:
                names[appid] = name
    return names


def app_label(appid, names):
    name = names.get(appid)
    return f"{name} ({appid})" if name else appid


def cmd_get(args, path, data):
    apps = get_apps(data)
    names = load_app_names()
    entry = apps.get(args.appid)
    label = app_label(args.appid, names)
    if entry is None or "LaunchOptions" not in entry:
        print(f"{label}: (no launch options set)")
        return
    print(f"{label}: {entry['LaunchOptions']}")


def cmd_list(args, path, data):
    apps = get_apps(data)
    names = load_app_names()
    found = False
    for appid, entry in apps.items():
        opts = entry.get("LaunchOptions") if isinstance(entry, dict) else None
        if opts:
            found = True
            print(f"{app_label(appid, names)}\t{opts}")
    if not found:
        print("(no games have launch options set)")


def cmd_set(args, path, data):
    apps = get_apps(data)
    entry = apps.setdefault(args.appid, {})
    entry["LaunchOptions"] = args.options
    write(path, data)
    print(f"set LaunchOptions for {app_label(args.appid, load_app_names())}")


def cmd_clear(args, path, data):
    apps = get_apps(data)
    entry = apps.get(args.appid)
    label = app_label(args.appid, load_app_names())
    if entry is None or "LaunchOptions" not in entry:
        print(f"{label} has no launch options set, nothing to do")
        return
    del entry["LaunchOptions"]
    write(path, data)
    print(f"cleared LaunchOptions for {label}")


def write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        vdf.dump(data, f, pretty=True)
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser(description="Get/set Steam per-game launch options.")
    parser.add_argument("--file", help="path to localconfig.vdf (default: auto-detect)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_get = sub.add_parser("get", help="print launch options for an appid")
    p_get.add_argument("appid")
    p_get.set_defaults(func=cmd_get, mutates=False)

    p_list = sub.add_parser("list", help="list all appids with launch options set")
    p_list.set_defaults(func=cmd_list, mutates=False)

    p_set = sub.add_parser("set", help="set launch options for an appid")
    p_set.add_argument("appid")
    p_set.add_argument("options")
    p_set.set_defaults(func=cmd_set, mutates=True)

    p_clear = sub.add_parser("clear", help="remove launch options for an appid")
    p_clear.add_argument("appid")
    p_clear.set_defaults(func=cmd_clear, mutates=True)

    args = parser.parse_args()
    path = args.file or find_localconfig()

    if args.mutates and steam_is_running():
        shutdown_steam()

    with open(path) as f:
        data = vdf.load(f)

    args.func(args, path, data)


if __name__ == "__main__":
    main()
