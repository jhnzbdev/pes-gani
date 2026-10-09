"""Fox engine StrCode32 (CityHash64 v1.0.3 with seeds, GzsTool style). mtar entry hash == strcode32(anim_infos file_name)."""
import struct
M = 0xFFFFFFFFFFFFFFFF
k0, k1, k2, k3 = 0xc3a5c85c97cb3127, 0xb492b66fbe98f273, 0x9ae16a3b2f90404f, 0xc949d7c7509e6557
def f64(s, i): return struct.unpack_from('<Q', s, i)[0]
def f32(s, i): return struct.unpack_from('<I', s, i)[0]
def rot(v, n): return v if n == 0 else ((v >> n) | (v << (64 - n))) & M
def rot1(v, n): return ((v >> n) | (v << (64 - n))) & M
def smix(v): return v ^ (v >> 47)
def h16(u, v):
    km = 0x9ddfea08eb382d69
    a = ((u ^ v) * km) & M; a ^= a >> 47
    b = ((v ^ a) * km) & M; b ^= b >> 47
    return (b * km) & M
def l0_16(s, n):
    if n > 8:
        a = f64(s, 0); b = f64(s, n - 8)
        return h16(a, rot1((b + n) & M, n)) ^ b
    if n >= 4:
        a = f32(s, 0); return h16((n + (a << 3)) & M, f32(s, n - 4))
    if n > 0:
        a, b, c = s[0], s[n >> 1], s[n - 1]
        y = (a + (b << 8)) & 0xFFFFFFFF; z = (n + (c << 2)) & 0xFFFFFFFF
        return (smix(((y * k2) ^ (z * k3)) & M) * k2) & M
    return k2
def l17_32(s, n):
    a = (f64(s, 0) * k1) & M; b = f64(s, 8); c = (f64(s, n - 8) * k2) & M; d = (f64(s, n - 16) * k0) & M
    return h16((rot((a - b) & M, 43) + rot(c, 30) + d) & M, (a + rot(b ^ k3, 20) - c + n) & M)
def l33_64(s, n):
    z = f64(s, 24); a = (f64(s, 0) + ((n + f64(s, n - 16)) * k0)) & M
    b = rot((a + z) & M, 52); c = rot(a, 37); a = (a + f64(s, 8)) & M; c = (c + rot(a, 7)) & M; a = (a + f64(s, 16)) & M
    vf = (a + z) & M; vs = (b + rot(a, 31) + c) & M
    a = (f64(s, 16) + f64(s, n - 32)) & M; z = f64(s, n - 8); b = rot((a + z) & M, 52); c = rot(a, 37)
    a = (a + f64(s, n - 24)) & M; c = (c + rot(a, 7)) & M; a = (a + f64(s, n - 16)) & M
    wf = (a + z) & M; ws = (b + rot(a, 31) + c) & M
    r = smix(((vf + ws) * k2 + (wf + vs) * k0) & M)
    return (smix((r * k0 + vs) & M) * k2) & M
def weak(s, i, a, b):
    w, x, y, z = f64(s, i), f64(s, i + 8), f64(s, i + 16), f64(s, i + 24)
    a = (a + w) & M; b = rot((b + a + z) & M, 21); c = a; a = (a + x + y) & M; b = (b + rot(a, 44)) & M
    return (a + z) & M, (b + c) & M
def city64(s):
    n = len(s)
    if n <= 16: return l0_16(s, n)
    if n <= 32: return l17_32(s, n)
    if n <= 64: return l33_64(s, n)
    x = f64(s, n - 40); y = (f64(s, n - 16) + f64(s, n - 56)) & M
    z = h16((f64(s, n - 48) + n) & M, f64(s, n - 24))
    v = weak(s, n - 64, n, z); w = weak(s, n - 32, (y + k1) & M, x)
    x = (x * k1 + f64(s, 0)) & M
    ln = (n - 1) & ~63; i = 0
    while True:
        x = (rot((x + y + v[0] + f64(s, i + 8)) & M, 37) * k1) & M
        y = (rot((y + v[1] + f64(s, i + 48)) & M, 42) * k1) & M
        x ^= w[1]; y = (y + v[0] + f64(s, i + 40)) & M
        z = (rot((z + w[0]) & M, 33) * k1) & M
        v = weak(s, i, (v[1] * k1) & M, (x + w[0]) & M)
        w = weak(s, i + 32, (z + w[1]) & M, (y + f64(s, i + 16)) & M)
        z, x = x, z; i += 64; ln -= 64
        if ln == 0: break
    return h16((h16(v[0], w[0]) + smix(y) * k1 + z) & M, (h16(v[1], w[1]) + x) & M)
def city64_seeds(s, a, b): return h16((city64(s) - a) & M, b)
def strcode64(text, nul=True):
    b = text.encode()
    seed1 = ((b[0] << 16) + len(b)) if b else 0
    return city64_seeds(b + (b'\0' if nul else b''), k2, seed1) & 0xFFFFFFFFFFFF
def strcode32(text, nul=True): return strcode64(text, nul) & 0xFFFFFFFF
if __name__ == '__main__':
    # verified against body_anime_file6/5.mtar entries
    assert strcode32("run_2_0") == 1914981404
    assert strcode32("kick_long_4_0_inside_y0_000_punch") == 1649381241
    print("ok")
