# pes-gani

Read PES (Fox Engine) animation files. This tool opens `.mtar` containers, pulls the
`gani` clips out of them, and decodes each clip into plain JSON: bone rotations, root
motion and frame timings, with the real clip names attached.

No dependencies. Standard library only.

```
4105 of 4389 clips named, 93.5% coverage
```

## Compatibility

Developed and verified against **PES 2021** (`dt13_all.cpk`, 4389 clips, 4105 named,
zero decode failures).

The `.mtar` and `gani` formats are shared across PES 2019, 2020 and 2021. This
decoder's format knowledge comes from mrdev's PES 2019 reader, so those versions
should work too, but they have not been tested here. If you try one of them, a
report would be welcome.

## What it does

| Command | What it does |
|---|---|
| `pes-gani list` | lists the clips inside an `.mtar` |
| `pes-gani names` | attaches real names using the Fox `StrCode32` hash and reports coverage |
| `pes-gani export` | decodes clips to JSON, either one clip or the whole file |
| `pes-gani selftest` | checks the hasher against known vectors |

## What it does not do

**It does not unpack `.cpk`.** That is CRI's archive format, not Konami's. See
[Getting the files](#getting-the-files) below.

**It does not retarget.** The output is PES's own 20 bone rig. Mapping that onto a
GTA, Blender or other game skeleton is a separate job and is up to you.

**It does not read models.** `.fmdl` is out of scope.

## Install

```
git clone <this repo>
cd pes-gani
python pes_gani/__main__.py selftest
```

Python 3.8 or newer. Nothing to `pip install`.

## Getting the files

The animations live in `dt13_all.cpk` in PES 2021 and eFootball. The CPK is a CRI
archive. Unpacking it is not this tool's job, and the unpackers people use carry no
open source licence, so this repo links to them instead of bundling them:

1. Get `pes-cpk-unpack.py` from
   [the4chancup/pes-file-tools](https://github.com/the4chancup/pes-file-tools)
2. Run `python pes-cpk-unpack.py -d out/ dt13_all.cpk`

Inside the extracted tree you want these paths:

```
common/anime/FoxAnim/Body/body_anime_file0.mtar .. body_anime_file9.mtar
common/anime/FoxAnim/Body/CharacterAssets/body_anim_skel.ask
common/anime/FoxAnim/Body/CharacterAssets/body_skel.frig
common/anime/Mbinfo/json/anim_infos.json        (optional)
```

## Usage

```bash
B=extracted/dt13/common/anime/FoxAnim/Body
C=$B/CharacterAssets

# what is in this file?
python pes_gani/__main__.py list $B/body_anime_file0.mtar --named-only --limit 20

# how many clips have names?
python pes_gani/__main__.py names $B/body_anime_file6.mtar --verify

# decode one clip
python pes_gani/__main__.py export $B/body_anime_file6.mtar \
    --name run_2_0 --skeleton $C/body_anim_skel.ask --rig $C/body_skel.frig -o out

# decode everything in a file
python pes_gani/__main__.py export $B/body_anime_file0.mtar --all \
    --skeleton $C/body_anim_skel.ask --rig $C/body_skel.frig -o out
```

Decoding the whole library, all ten files and 4105 clips, takes about 2 minutes and
produces roughly 196 MB of JSON.

### Options

| Flag | Effect |
|---|---|
| `--dense` | emits a key on every frame, interpolated, instead of PES's sparse keys |
| `--pretty` | indented JSON |
| `--limit N` | stops after N clips |
| `--names FILE` | uses a different name map |
| `--anim_infos FILE` | builds names from `anim_infos.json` instead of the shipped map |

## Output format

```json
{
  "name": "run_2_0",
  "hash": 1914981404,
  "id": 26199,
  "frames": 27,
  "fps": 30.0,
  "duration": 0.9,
  "root": { "rot": [...], "pos": [...] },
  "tracks": {
    "sk_thigh_l": { "rot": [[frame, x, y, z, w], ...] },
    "sk_belly":   { "rot": [...] }
  }
}
```

Quaternions are `[x, y, z, w]` and sign continuous along the track.

The `root` block holds the clip's own translation. If your engine moves the character
itself, strip this out, or the player will travel twice.

Keys are sparse. PES stores one roughly every 3 to 4 frames. Use `--dense` if your
engine needs a key on every frame.

## Two traps worth knowing

**The `.mtar` header lies about bone counts.** It reports `bones=21 channels=29`, but
every clip actually uses 20 bones and 27 channels. Trust the clips, not the header.

**Arms are driven by IK chains, not direct channels.** `sk_shoulder_*` and
`sk_upperarm_*` have no channel of their own. They only exist inside the type 8
arm-chain units described by `body_skel.frig`. A decoder that maps channels to bones
one to one leaves them at rest, which looks like a T-pose. `pesmtar.channel_map()`
handles this.

## How the naming works

Each clip in an `.mtar` is stored under `StrCode32(clip_name)`, Fox Engine's name
hash (CityHash64 v1.0.3 with Konami's seeds). The `.mtar` stores only the number. The
names live in `anim_infos.json`. Hashing every name in that file and matching the
results against the `.mtar` entry list recovers 4105 of the 4389 names.

`clip_name_map.json` is that result, in the form `{name: {hash, id, mtar, frames,
info}}`, so you do not have to re-derive it.

`pes_gani/foxhash.py` is the hasher, and it carries self test vectors.

## Layout

```
pes_gani/
  __main__.py   CLI
  pesmtar.py    MTAR, gani, .ask and .frig readers, plus the decoder
  foxhash.py    Fox StrCode32 (CityHash64) name hasher
clip_name_map.json   4105 clip names
```

## Credits

MTAR and gani format research builds on `mtar_reader_py37_mrdev.py` by mrdev, a
PES 2019 reader, and on the format discussion at
[ResHax](https://reshax.com/topic/19234-pes-2021-ganimtar-animation-format-channel-mapping-ik-chains-and-ue5-reconstruction/).

`StrCode32` belongs to Fox Engine. The same hash is used by MGSV tooling such as
GzsTool.

The `.frig` arm-chain mapping follows the explanation in that ResHax thread.

## Licence

MIT for the code in this repo. `clip_name_map.json` is reverse engineered metadata,
meaning names, hashes and frame counts, and it contains no animation data.

This repository ships no game assets. It contains tools that read files the user
supplies, plus metadata derived from those files. Pro Evolution Soccer and eFootball
are trademarks of Konami Digital Entertainment. This project is not affiliated with or
endorsed by Konami.
