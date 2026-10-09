#!/usr/bin/env python3
"""pes-gani - read PES (Fox Engine) MTAR/gani animation files.

Single entry point for the whole pipeline:

    pes-gani list    <mtar>                     what clips are in this file
    pes-gani names   <mtar>                     attach real names via StrCode32
    pes-gani info    <mtar> --name run_3_3      one clip's channels / frames
    pes-gani export  <mtar> --name run_3_3      decode a clip to JSON
    pes-gani export  <mtar> --all -o out/       decode every named clip

No dependencies beyond the standard library.

Getting the .mtar files in the first place is a separate step - the CPK that
holds them is CRI's archive format, and unpacking it is not this tool's job.
See README.md.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import foxhash
import pesmtar

__version__ = "0.1.0"

DEFAULT_SKELETON = "body_anim_skel.ask"
DEFAULT_RIG = "body_skel.frig"


def _die(msg):
    sys.stderr.write("error: %s\n" % msg)
    raise SystemExit(1)


def load_names(path):
    """clip_name_map.json -> {hash: name}."""
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    out = {}
    for name, meta in raw.items():
        h = meta.get("hash")
        if h is None:
            continue
        out[int(h)] = name
    return out


def resolve_names(args, mtar):
    """Prefer the shipped map; fall back to hashing anim_infos.json."""
    if args.names:
        return load_names(args.names), "map file"
    if args.anim_infos:
        with open(args.anim_infos, "r", encoding="utf-8") as fh:
            info = json.load(fh)
        names = {}
        for entry in info.get("animations", {}).values():
            fn = entry.get("file_name")
            if fn:
                names[foxhash.strcode32(fn)] = fn
        return names, "anim_infos.json"
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "clip_name_map.json")
    if os.path.exists(here):
        return load_names(here), "map file"
    return {}, "none"


def load_skeleton(args):
    """-> (bone_names, units) or (None, None)."""
    skel = rig = None
    if args.skeleton and os.path.exists(args.skeleton):
        skel = pesmtar.read_ask(open(args.skeleton, "rb").read())
    if args.rig and os.path.exists(args.rig):
        rig = pesmtar.read_frig(open(args.rig, "rb").read())
    return skel, rig


def cmd_list(args):
    data = open(args.mtar, "rb").read()
    m = pesmtar.read_mtar(data)
    names, src = resolve_names(args, m)
    print("mtar      : %s" % os.path.basename(args.mtar))
    print("header    : bones=%d channels=%d (clips use fewer - see README)" % (m["bones"], m["channels"]))
    print("clips     : %d" % m["count"])
    print("name source: %s (%d names)" % (src, len(names)))
    print()
    named = [e for e in m["entries"] if e["hash"] in names]
    print("%-42s %-10s %s" % ("NAME", "HASH", "SIZE"))
    print("-" * 64)
    for e in (named if args.named_only else m["entries"])[: args.limit or len(m["entries"])]:
        print("%-42s %-10d %d" % (names.get(e["hash"], "<unnamed>"), e["hash"], e["size"]))
    if args.named_only:
        print("\n%d of %d clips have a name" % (len(named), m["count"]))


def cmd_names(args):
    data = open(args.mtar, "rb").read()
    m = pesmtar.read_mtar(data)
    names, src = resolve_names(args, m)
    hit = sum(1 for e in m["entries"] if e["hash"] in names)
    print("clips      : %d" % m["count"])
    print("named      : %d (%.1f%%)" % (hit, 100.0 * hit / max(1, m["count"])))
    print("unnamed    : %d" % (m["count"] - hit))
    print("source     : %s" % src)
    if args.out:
        table = {names[e["hash"]]: {"hash": e["hash"], "id": e["id"], "size": e["size"]}
                 for e in m["entries"] if e["hash"] in names}
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(table, fh, indent=2)
        print("written    : %s" % args.out)
    if args.verify:
        print("\nself-check on known clips:")
        for probe in ("run_2_0", "kick_long_4_0_inside_y0_000_punch"):
            want = foxhash.strcode32(probe)
            found = any(e["hash"] == want for e in m["entries"])
            print("  %-40s -> %-10d %s" % (probe, want, "present" if found else "not in this file"))


def _find_clip(m, names, want):
    for e in m["entries"]:
        if names.get(e["hash"]) == want:
            return e
    if want.startswith("0x"):
        h = int(want, 16)
        for e in m["entries"]:
            if e["hash"] == h:
                return e
    if want.isdigit():
        for e in m["entries"]:
            if e["id"] == int(want):
                return e
    return None


def cmd_export(args):
    data = open(args.mtar, "rb").read()
    m = pesmtar.read_mtar(data)
    names, _ = resolve_names(args, m)
    skel, rig = load_skeleton(args)
    if skel is None:
        _die("need the skeleton. pass --skeleton body_anim_skel.ask")
    if rig is None:
        _die("need the rig map. pass --rig body_skel.frig")
    bone_names = [b["name"] for b in skel]
    cmap = pesmtar.channel_map(rig, pesmtar.read_gani(data[m["entries"][0]["addr"]:][:0]) if False else
                               pesmtar.read_gani(data[m["entries"][0]["addr"]:m["entries"][0]["addr"] + m["entries"][0]["size"]])["channels"])

    todo = []
    if args.all:
        todo = [e for e in m["entries"] if e["hash"] in names]
        if args.limit:
            todo = todo[: args.limit]
    else:
        if not args.name:
            _die("pass --name <clip> or --all")
        e = _find_clip(m, names, args.name)
        if e is None:
            _die("clip %r not found in %s" % (args.name, os.path.basename(args.mtar)))
        todo = [e]

    os.makedirs(args.out, exist_ok=True)
    written = 0
    for e in todo:
        g = data[e["addr"]:e["addr"] + e["size"]]
        clip = pesmtar.clip_to_json(g, cmap, bone_names, dense=args.dense)
        name = names.get(e["hash"], "0x%08x" % e["hash"])
        clip["name"] = name
        clip["hash"] = e["hash"]
        clip["id"] = e["id"]
        clip["source"] = os.path.basename(args.mtar)
        path = os.path.join(args.out, name.replace("/", "_") + ".json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(clip, fh, indent=1 if args.pretty else None)
        written += 1
        if not args.all:
            print("clip      : %s" % name)
            print("hash      : %d" % e["hash"])
            print("frames    : %d @ %g fps (%.2fs)" % (clip["frames"], clip["fps"], clip["duration"]))
            print("bones     : %d" % len(clip["tracks"]))
            print("root      : %s" % (", ".join(clip["root"]) if clip["root"] else "none"))
            print("written   : %s" % path)
    if args.all:
        print("exported  : %d clips -> %s" % (written, args.out))


def cmd_selftest(args):
    ok = True
    print("StrCode32 vectors:")
    for name, want in (("run_2_0", 1914981404),
                       ("kick_long_4_0_inside_y0_000_punch", 1649381241)):
        got = foxhash.strcode32(name)
        flag = "ok" if got == want else "MISMATCH"
        ok &= got == want
        print("  %-40s %-10d %s" % (name, got, flag))
    if args.mtar and os.path.exists(args.mtar):
        data = open(args.mtar, "rb").read()
        m = pesmtar.read_mtar(data)
        names, src = resolve_names(args, m)
        hit = sum(1 for e in m["entries"] if e["hash"] in names)
        print("\n%s: %d clips, %d named (%.1f%%) via %s"
              % (os.path.basename(args.mtar), m["count"], hit,
                 100.0 * hit / max(1, m["count"]), src))
    print("\n%s" % ("all checks passed" if ok else "FAILURES above"))
    return 0 if ok else 1


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="pes-gani",
        description="Read PES / Fox Engine MTAR + gani animation files.",
        epilog="Getting the .mtar files themselves is a separate step - see README.md")
    p.add_argument("--version", action="version", version="pes-gani " + __version__)
    sub = p.add_subparsers(dest="cmd")

    def common(sp):
        sp.add_argument("mtar", help="path to a body_anime_fileN.mtar")
        sp.add_argument("--names", help="clip_name_map.json (default: the one shipped here)")
        sp.add_argument("--anim_infos", help="anim_infos.json, used to build names instead")

    sp = sub.add_parser("list", help="list clips in an mtar")
    common(sp)
    sp.add_argument("--named-only", action="store_true")
    sp.add_argument("--limit", type=int, default=0)
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("names", help="attach names and report coverage")
    common(sp)
    sp.add_argument("--out", help="write {name: {hash,id,size}} json")
    sp.add_argument("--verify", action="store_true")
    sp.set_defaults(func=cmd_names)

    sp = sub.add_parser("export", help="decode clips to JSON")
    common(sp)
    sp.add_argument("--name", help="clip name, 0xHASH, or numeric id")
    sp.add_argument("--all", action="store_true", help="every named clip in the file")
    sp.add_argument("--out", "-o", default="out", help="output directory (default: out)")
    sp.add_argument("--skeleton", default=DEFAULT_SKELETON, help="body_anim_skel.ask")
    sp.add_argument("--rig", default=DEFAULT_RIG, help="body_skel.frig")
    sp.add_argument("--dense", action="store_true", help="emit a key on every frame")
    sp.add_argument("--pretty", action="store_true")
    sp.add_argument("--limit", type=int, default=0)
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("selftest", help="verify the hasher and optionally a file")
    sp.add_argument("mtar", nargs="?", help="optional mtar to check name coverage")
    sp.add_argument("--names")
    sp.add_argument("--anim_infos")
    sp.set_defaults(func=cmd_selftest)

    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        p.print_help()
        return 1
    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
