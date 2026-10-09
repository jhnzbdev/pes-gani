"""Dependency-free PES/Fox MTAR + GANI reader (ported from mtar_reader_py37_mrdev.py, no FBX SDK).

Layout (little endian), verified on the PES2021 pack in ../01_animation_data:
  MTAR   : u32 sig, u32 count, u16 bones, u16 channels, 20 pad, then count x (u32 hash, i32 id, u32 addr, u32 size)
  GANI   : u32 sig, u32 nodeOff(0x20), u32 size ... "MOTION" ... motion header at gani+0x90:
           u32 trackGroups, u32 channels, u32 timebase/flags, u32 frameCount, u32 unk, then trackGroups x u32 offsets
           (relative to the motion header). Each track group: u32 hash, u8 channelCount, 3 pad, then channelCount x
           (u32 dataOffset relative to this entry, i16 channelIndex, u8 flags, i8 bitSize).
  channel data, bit size 12/20 (rotation): per key  3 x bitSize-bit fractions, 3 sign bits, 8-bit frame step
           (the final key has no step); bit size 16 (translation): 3 half floats + i8 step (final key has no step).
"""
import math
import struct


class Bits:
    def __init__(self, b):
        self.b = b
        self.n = 0
        self.len = len(b) * 8

    def uint(self, k):
        v = 0
        for i in range(k):
            by = self.b[self.n >> 3]
            v |= ((by >> (self.n & 7)) & 1) << i
            self.n += 1
        return v


def half(h):
    return struct.unpack('<e', struct.pack('<H', h))[0]


def read_mtar(data):
    sig, count, nbones, nchan = struct.unpack('<IIHH', data[:12])
    ents = []
    for i in range(count):
        h, idx, addr, size = struct.unpack('<IiII', data[0x20 + 16 * i:0x30 + 16 * i])
        ents.append({'hash': h, 'id': idx, 'addr': addr, 'size': size})
    return {'sig': sig, 'count': count, 'bones': nbones, 'channels': nchan, 'entries': ents}


def read_gani(g):
    """-> {frames, timebase, unk, channels:[{index, track, flags, bits, off, size}]}"""
    sig, node_off, size = struct.unpack('<III', g[:12])
    m = node_off + 0x70
    groups, nch, timebase, frames, unk = struct.unpack('<5I', g[m:m + 20])
    offs = struct.unpack('<%dI' % groups, g[m + 20:m + 20 + 4 * groups])
    chans = []
    for o in offs:
        p = m + o
        th = struct.unpack('<I', g[p:p + 4])[0]
        n = g[p + 4]
        for c in range(n):
            q = p + 8 + 8 * c
            a, ix, tf, bs = struct.unpack('<IhBb', g[q:q + 8])
            chans.append({'index': ix, 'track': th, 'flags': tf, 'bits': bs, 'off': q + a})
    order = sorted(range(len(chans)), key=lambda i: chans[i]['off'])
    for k, i in enumerate(order):
        end = chans[order[k + 1]]['off'] if k + 1 < len(order) else len(g)
        chans[i]['size'] = end - chans[i]['off']
    return {'frames': frames, 'timebase': timebase, 'unk': unk, 'groups': groups, 'channels': chans}


def decode_rot_raw(data, bits, frames):
    """-> [(frame, fractions[3], signs[3])]; the last key has no step byte, frame == frameCount for animated tracks"""
    B = Bits(data)
    keys = []
    f = 0
    full = 3 * bits + 3
    while B.n + full <= B.len:
        v = [B.uint(bits) / float(1 << bits) for _ in range(3)]
        s = [B.uint(1) for _ in range(3)]
        keys.append((f, v, s))
        if B.n + 8 > B.len:
            break
        st = B.uint(8)
        if st == 0:
            break
        f += st
    return keys


def decode_pos_raw(data, frames):
    keys = []
    p = 0
    f = 0
    while p + 6 <= len(data):
        v = [half(struct.unpack('<H', data[p + 2 * i:p + 2 * i + 2])[0]) for i in range(3)]
        keys.append((f, v))
        p += 6
        if p >= len(data):
            break
        st = struct.unpack('b', data[p:p + 1])[0]
        p += 1
        if st <= 0:
            break
        f += st
    return keys


def read_ask(data):
    """.ask skeleton -> [{name, parent, pos(xyz), rot(xyzw)}] in file order"""
    ver, count = struct.unpack('<ii', data[:8])
    bones = []
    p = 8
    for i in range(count):
        name_off, parent = struct.unpack('<ii', data[p + 4:p + 12])
        px, py, pz, _pw = struct.unpack('<4f', data[p + 12:p + 28])
        rx, ry, rz, rw = struct.unpack('<4f', data[p + 28:p + 44])
        s = p + 4 + name_off
        name = data[s:data.index(b'\0', s)].decode('ascii', 'replace')
        bones.append({'name': name, 'parent': parent, 'pos': [px, py, pz], 'rot': [rx, ry, rz, rw]})
        p += 44
    return bones


# ---------------------------------------------------------------------------
# frig (rig description) -> channel map, quaternions, JSON clip
# ---------------------------------------------------------------------------
HALF_ANGLE_SCALE = math.pi / 2.0   # verified on PES2021: fraction * pi/2 is the half angle (PES2017 reader used 1.0)
POS_SCALE = 0.01                   # translation channels are centimetres
FPS = 30.0


def read_frig(data):
    """body_skel.frig -> units [{kind, nch, nbones, parentBone, parentUnit, bones, ch0}].
    Each unit owns the next `nch` channels of the gani (running counter)."""
    h = struct.unpack('<8I', data[:32])
    n_units, n_chan = h[3], h[4]
    offs = struct.unpack('<%dI' % n_units, data[0x20:0x20 + 4 * n_units])
    ends = list(offs[1:]) + [h[7]]
    units = []
    ch0 = 0
    for o, e in zip(offs, ends):
        u = struct.unpack('<%dH' % ((e - o) // 2), data[o:e])
        kind, _, nch, nb, pb, pu = u[:6]
        start = 8 if e - o == 32 else 24     # 64-byte units (IK limbs) carry 16 bytes of axis data first
        units.append({'kind': kind, 'nch': nch, 'nbones': nb,
                      'parentBone': None if pb == 0xFFFF else pb, 'parentUnit': None if pu == 0xFFFF else pu,
                      'bones': list(u[start:start + nb]) if e - o == 32 else list(u[start + 0:start + nb]), 'ch0': ch0})
        ch0 += nch
    if ch0 != n_chan:
        raise ValueError('frig channel count mismatch %d != %d' % (ch0, n_chan))
    return units


def channel_map(units, channels):
    """-> {channelIndex: (kind 'rot'|'pos', bone index, -1 = ROOT, None = unused limb-root translation)}.
    A unit's rotation channels go to its bones in order; the translation channels left over are the hip / ROOT motion
    or the IK limb-root translations (NaN in every clip, unused)."""
    kinds = {c['index']: ('pos' if c['bits'] == 16 else 'rot') for c in channels}
    out = {}
    for u in units:
        chs = range(u['ch0'], u['ch0'] + u['nch'])
        rots = [c for c in chs if kinds.get(c) == 'rot']
        poss = [c for c in chs if kinds.get(c) == 'pos']
        if u['nbones'] == 0:                       # ROOT
            for c in rots: out[c] = ('rot', -1)
            for c in poss: out[c] = ('pos', -1)
            continue
        for c, b in zip(rots, u['bones']): out[c] = ('rot', b)
        for c in poss: out[c] = ('pos', u['bones'][0] if u['nch'] == 2 else None)
    return out


def quat(frac, signs):
    """12/20-bit key -> [x,y,z,w]. frac[0] = angle, frac[1], frac[2] = two L1-normalised axis parts (third = 1-a-b),
    sign bits flip x,y,z."""
    a, b = frac[1], frac[2]
    c = 1.0 - a - b
    n = math.sqrt(a * a + b * b + c * c)
    h = frac[0] * HALF_ANGLE_SCALE
    s = math.sin(h) / n if n > 1e-9 else 0.0
    x, y, z = a * s, b * s, c * s
    return [-x if signs[0] else x, -y if signs[1] else y, -z if signs[2] else z, math.cos(h)]


def clip_to_json(g, cmap, names, fps=FPS, dense=False, warn=None):
    G = read_gani(g)
    frames = G['frames']
    tracks = {}
    root = {}
    for c in G['channels']:
        km = cmap.get(c['index'])
        if km is None or km[1] is None:
            continue
        kind, bone = km
        data = g[c['off']:c['off'] + c['size']]
        if kind == 'pos':
            keys = decode_pos_raw(data, frames)
            vals = [[f] + [round(x * POS_SCALE, 5) for x in v] for f, v in keys]
        else:
            keys = decode_rot_raw(data, c['bits'], frames)
            vals, prev = [], None
            for f, v, s in keys:
                q = quat(v, s)
                if prev is not None and sum(p * x for p, x in zip(prev, q)) < 0:
                    q = [-x for x in q]
                prev = q
                vals.append([f] + [round(x, 6) for x in q])
        if len(keys) > 1 and keys[-1][0] != frames and warn is not None:
            warn.append('channel %d ends at %d of %d' % (c['index'], keys[-1][0], frames))
        (root if bone == -1 else tracks.setdefault(names[bone], {}))[kind] = vals
    if dense:
        for t in list(tracks.values()) + [root]:
            for k in list(t):
                t[k] = _dense(t[k], k == 'rot', frames)
    return {'frames': frames, 'fps': fps, 'duration': round(frames / fps, 4), 'root': root, 'tracks': tracks}


def _dense(keys, is_rot, frames):
    if len(keys) < 2:
        return [[0] + keys[0][1:]] if keys else []
    out, i = [], 0
    for f in range(frames + 1):
        while i < len(keys) - 2 and keys[i + 1][0] < f:
            i += 1
        a, b = keys[i], keys[i + 1]
        t = min(1.0, max(0.0, (f - a[0]) / float(max(1, b[0] - a[0]))))
        v = [x + (y - x) * t for x, y in zip(a[1:], b[1:])]
        if is_rot:
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            v = [x / n for x in v]
        out.append([f] + [round(x, 6) for x in v])
    return out
