"""FA Foundry "Aura" logo: a teal orb with a tilting rainbow halo and two eyes.

Rendered frame by frame (numpy + scipy) so the halo can be several blurred 3D hoops with motion
blur. The eye and hop timing in motion_30fps.json was measured from the reference clip the
product owner chose in October 2026; the artwork itself is drawn here. Needs numpy, scipy and
Pillow, which the app itself does not.

  python3 tools/logo/aura.py assets              # regenerate every app asset below
  python3 tools/logo/aura.py frames OUT_DIR [--size 512] [--fps 30]   # transparent RGBA frames
  python3 tools/logo/aura.py still OUT.png [--size 1024] [--t 0.3] [--tile]
"""
import argparse, json, math, os
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter

T = 7.0  # loop length, seconds

# Screen-angle colour map (degrees, counter-clockwise from the right, y up): warm on top, cool below.
STOPS = [(0, (255, 62, 96)), (40, (255, 74, 44)), (85, (255, 142, 42)), (128, (255, 186, 64)),
         (162, (150, 214, 130)), (198, (44, 212, 200)), (240, (32, 152, 255)), (285, (44, 104, 255)),
         (322, (136, 84, 255)), (360, (255, 62, 96))]
_sa = np.array([s[0] for s in STOPS], float)
_sc = np.array([s[1] for s in STOPS], float) / 255.0


def cmap(deg):
    deg = np.mod(deg, 360.0)
    return np.stack([np.interp(deg, _sa, _sc[:, k]) for k in range(3)], -1)


def smooth(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def keyed(keys, t):
    """Piecewise smoothstep interpolation over [(time, value-tuple), ...] spanning 0..T."""
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t0 <= t <= t1:
            u = smooth((t - t0) / max(t1 - t0, 1e-6))
            return tuple(a + (b - a) * u for a, b in zip(v0, v1))
    return keys[-1][1]


# How restless the halo is: calm, then hoops swing across the face, then settle.
ACTIVE = [(0, (.35,)), (2.6, (.35,)), (3.1, (1,)), (4.9, (1,)), (5.6, (.35,)), (7.0, (.35,))]


_TRACK = None


def track(t):
    """Linear interpolation of the measured per-frame motion; eye lists are matched by index."""
    global _TRACK
    if _TRACK is None:
        _TRACK = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'motion_30fps.json')))
    fr, fps = _TRACK['frames'], _TRACK['fps']
    x = (t % T) * fps
    i0 = int(math.floor(x)) % len(fr); i1 = (i0 + 1) % len(fr); u = x - math.floor(x)
    a, b = fr[i0], fr[i1]
    if len(a['eyes']) != len(b['eyes']):
        b, u = a, 0.0
    lerp = lambda p, q: p + (q - p) * u
    return dict(lift=lerp(a['lift'], b['lift']), sx=lerp(a['sx'], b['sx']), sy=lerp(a['sy'], b['sy']),
                eyes=[[lerp(p, q) for p, q in zip(ea, eb)] for ea, eb in zip(a['eyes'], b['eyes'])])


def hoops(t):
    """Each hoop: radius, tilt about x and y (deg), centre offset, core/haze blur, gain, phase."""
    a = keyed(ACTIVE, t)[0]
    w = 2 * math.pi * t / T
    return [
        dict(r=1.0, ax=7 + 9 * a * math.sin(w), ay=10 * math.sin(w + 1.1) + 14 * a * math.sin(2 * w), off=(.02 * math.sin(w), -.015),
             core=.052, haze=.095, gain=1.6, ph=w, crisp=.021),
        dict(r=1.09, ax=-14 - 55 * a * math.sin(2 * w + .6), ay=18 * math.cos(w) + 40 * a * math.cos(2 * w), off=(-.035, .025 * math.cos(w)),
             core=.045, haze=.1, gain=.5 + .55 * a, ph=-w + 2),
        dict(r=.99, ax=10 + 45 * a * math.cos(2 * w + 2), ay=-12 - 45 * a * math.sin(2 * w + 1), off=(.03, .03),
             core=.05, haze=.11, gain=.35 + .55 * a, ph=w * 1.5 + 4),
        dict(r=1.16, ax=62 + 10 * math.sin(w), ay=-24 + 40 * math.sin(w * 2 + .5), off=(0, .04),
             core=.04, haze=.09, gain=.9 * max(0, a - .2), ph=w * 2),
    ]


def render(t, n=512, tile=False):
    S = n / 512.0
    cx = cy = n / 2.0
    R = 150 * S
    yy, xx = np.mgrid[0:n, 0:n].astype(float)
    X, Y = (xx + .5 - cx) / R, (cy - yy - .5) / R           # sphere units, y up
    D = np.hypot(X, Y)
    ang = np.degrees(np.arctan2(Y, X))
    a = keyed(ACTIVE, t)[0]
    shift = 10 * math.sin(2 * math.pi * t / T)               # colours drift a little, light stays on top

    # ---- halo: splat hoop points (with motion blur), blur into a soft band ----
    glow = np.zeros((n, n, 3))
    phi = np.linspace(0, 2 * math.pi, int(1400 * S), endpoint=False)
    for k in range(4):
        acc = np.zeros((n, n, 3))
        for sub in range(4):
            ts = (t + sub * 0.012) % T
            h = hoops(ts)[k]
            if h['gain'] <= 0.01:
                continue
            ax, ay = math.radians(h['ax']), math.radians(h['ay'])
            p = np.stack([np.cos(phi), np.sin(phi), np.zeros_like(phi)]) * h['r']
            p = np.array([[1, 0, 0], [0, math.cos(ax), -math.sin(ax)], [0, math.sin(ax), math.cos(ax)]]) @ p
            p = np.array([[math.cos(ay), 0, math.sin(ay)], [0, 1, 0], [-math.sin(ay), 0, math.cos(ay)]]) @ p
            px, py, pz = p[0] + h['off'][0], p[1] + h['off'][1], p[2]
            behind = (pz < 0) & (np.hypot(px, py) < .97)
            bright = (.38 + .62 * (.5 + .5 * np.cos(phi - h['ph'])) ** 1.3) * 1.2 * np.where(behind, 0.0, 1.0) * (1 + .25 * np.clip(pz, -1, 1))
            col = cmap(np.degrees(np.arctan2(py, px)) + shift) * bright[:, None]
            ix, iy = cx + px * R, cy - py * R
            i0, j0 = np.floor(ix).astype(int), np.floor(iy).astype(int)
            fx, fy = ix - i0, iy - j0
            for di, dj, wgt in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
                ii, jj = i0 + di, j0 + dj
                ok = (ii >= 0) & (ii < n) & (jj >= 0) & (jj < n)
                np.add.at(acc, (jj[ok], ii[ok]), col[ok] * (wgt[ok] * h['gain'] / 4)[:, None])
        if not acc.any():
            continue
        h = hoops(t)[k]
        per_px = len(phi) / (2 * math.pi * h['r'] * R)        # splat density along the ring
        for sig, wgt in ((h['core'], .9), (h['haze'], .2)) + (((h['crisp'], .55),) if 'crisp' in h else ()):
            s = sig * R
            glow += wgt * math.sqrt(2 * math.pi) * s / per_px * np.stack([gaussian_filter(acc[..., c], s) for c in range(3)], -1)
    # a wide aura under everything
    aura = gaussian_filter(np.clip(D - .9, 0, None) * 0 + np.exp(-((D - 1.05) / .22) ** 2), 6 * S)
    glow += .05 * aura[..., None] * cmap(ang + shift)

    # ---- sphere ----
    edge = 1.0 / R
    M = np.clip((1 - D) / edge + .5, 0, 1)
    rr = np.hypot(X * .95, Y + .28)
    base = (np.array([10, 98, 82]) * np.exp(-(rr / .75) ** 2)[..., None] + np.array([5, 40, 44]) * (1 - np.exp(-(rr / .75) ** 2))[..., None]) / 255
    base *= (1 - .35 * smooth((Y - .2) / .8))[..., None]       # darker crown
    # silk ribbons drifting inside
    w = 2 * math.pi * t / T
    th = .45 + .25 * math.sin(w)
    u = X * math.cos(th) + Y * math.sin(th)
    v = -X * math.sin(th) + Y * math.cos(th)
    f1 = np.sin(3.2 * v + 1.5 * np.sin(2.3 * u + w) + w * 2)
    f2 = np.sin(2.4 * u - 1.2 * np.sin(2.9 * v - w * 2) - w + 1.3)
    rib = np.exp(-(f1 ** 2) * 9) * (.07 + .16 * a) + np.exp(-(f2 ** 2) * 14) * (.05 + .12 * a)
    base += rib[..., None] * np.array([70, 220, 190]) / 255 * smooth(1 - D)[..., None]
    base -= (np.exp(-(np.sin(2.1 * v + 2 * w + 1) ** 2) * 6) * (.05 + .1 * a) * smooth(1 - D))[..., None]
    # rim light picks up the halo colour, strongest at the bottom like a lens
    rim = smooth((D - .72) / .28) ** 1.6
    base += rim[..., None] * cmap(ang + shift) * (.32 + .3 * smooth((-Y) / .8))[..., None]
    base += (.06 * np.exp(-((X + .1) ** 2 + (Y - .62) ** 2) / .05))[..., None]     # faint top sheen

    # eyes: per-eye position, size and tilt follow the measured reference timing (motion_30fps.json)
    eyes = np.zeros((n, n))
    mx_ = my_ = 0.0
    tr = track(t)
    for ecx, ecy, ew, eh, sl in tr['eyes']:
        hw, hh = ew / 2, eh / 2
        c, s_ = math.cos(math.radians(sl)), math.sin(math.radians(sl))
        qx, qy = (X - ecx) * c + (Y - ecy) * s_, -(X - ecx) * s_ + (Y - ecy) * c
        rad = min(hw, hh)
        dd = np.hypot(np.maximum(np.abs(qx) - (hw - rad), 0), np.maximum(np.abs(qy) - (hh - rad), 0)) - rad
        eyes = np.maximum(eyes, np.clip(.5 - dd / edge, 0, 1))
        mx_ += ecx / 2; my_ += ecy / 2
    open_ = min(1.0, max((e[3] for e in tr['eyes']), default=0) / .29)
    green = np.exp(-((X - mx_) ** 2 + (Y - my_) ** 2) / .09) * (.12 + .16 * open_)
    base += green[..., None] * np.array([40, 210, 100]) / 255
    eye_glow = gaussian_filter(eyes, 5 * S)
    base += eye_glow[..., None] * np.array([150, 255, 225]) / 255 * .7

    # ---- composite on black, then recover alpha so it sits on any background ----
    front = glow * (.6 + .4 * smooth((D - .8) / .2))[..., None]   # halo laid over the sphere edge too
    C = base * M[..., None] + front
    mx = np.maximum(C.max(-1, keepdims=True), 1e-6)
    C = C / mx * (1 - np.exp(-mx * 1.25))                      # hue-preserving tone map keeps the halo saturated
    C = C * (1 - eyes[..., None]) + eyes[..., None] * np.array([246, 255, 252]) / 255
    A = np.clip(np.maximum(M, C.max(-1)), 0, 1)
    rgb = np.where(A[..., None] > 1e-4, C / np.maximum(A, 1e-4)[..., None], 0)
    img = np.dstack([np.clip(rgb, 0, 1), A])
    lift, bx, by = tr['lift'], tr['sx'], tr['sy']
    if (lift, bx, by) != (0, 1, 1):
        img = squash(img, n, cx, cy, R, lift, bx, by)
    if tile:
        img = over(img, tile_bg(n))
    return Image.fromarray((img * 255 + .5).astype(np.uint8), 'RGBA')


def squash(img, n, cx, cy, R, lift, bx, by):
    """Scale the whole orb about its centre and raise it; resample premultiplied so edges stay clean."""
    from scipy.ndimage import affine_transform
    pre = np.dstack([img[..., :3] * img[..., 3:], img[..., 3:]])
    ty = -lift * R                                            # rows grow downwards
    m = np.array([1 / by, 1 / bx])
    off = np.array([cy - (cy + ty) / by, cx - cx / bx])
    out = np.dstack([affine_transform(pre[..., c], m, offset=off, order=1, mode='constant') for c in range(4)])
    a = np.clip(out[..., 3:], 0, 1)
    return np.dstack([np.where(a > 1e-4, out[..., :3] / np.maximum(a, 1e-4), 0), a])


def tile_bg(n):
    """Rounded tile in near-black midnight blue, full bleed like the current icon."""
    yy, xx = np.mgrid[0:n, 0:n].astype(float)
    rc = .225 * n                                             # same corner as the current icon
    qx = np.maximum(np.abs(xx + .5 - n / 2) - (n / 2 - rc), 0)
    qy = np.maximum(np.abs(yy + .5 - n / 2) - (n / 2 - rc), 0)
    m = np.clip(rc - np.hypot(qx, qy) + .5, 0, 1)
    g = np.exp(-(((xx / n) - .5) ** 2 + ((yy / n) - .45) ** 2) / .18)
    col = (np.array([7, 10, 18]) * (1 - g)[..., None] + np.array([16, 24, 40]) * g[..., None]) / 255
    return np.dstack([col, m])


def over(fg, bg):
    a = fg[..., 3:] + bg[..., 3:] * (1 - fg[..., 3:])
    c = (fg[..., :3] * fg[..., 3:] + bg[..., :3] * bg[..., 3:] * (1 - fg[..., 3:])) / np.maximum(a, 1e-6)
    return np.dstack([c, a])


def write_assets():
    """App icon (icns + png), the header's animated WebP and its reduced-motion still."""
    app = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'app')
    icon = render(0.3, 1024, tile=True)
    icon.save(os.path.join(app, 'resources', 'icon.png'))
    icon.save(os.path.join(app, 'resources', 'icon.icns'),
              append_images=[icon.resize((s, s), Image.LANCZOS) for s in (16, 32, 64, 128, 256, 512)])
    render(0.3, 192).save(os.path.join(app, 'src', 'assets', 'logo.png'), optimize=True)
    # 96px at 20 fps keeps the header's renderer cost low (see components.css)
    frames = [render(i / 20, 96) for i in range(int(T * 20))]
    frames[0].save(os.path.join(app, 'src', 'assets', 'logo-animated.webp'), save_all=True,
                   append_images=frames[1:], duration=50, loop=0, quality=80, method=6)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['frames', 'still', 'assets'])
    ap.add_argument('out', nargs='?')
    ap.add_argument('--size', type=int, default=512)
    ap.add_argument('--fps', type=float, default=30)
    ap.add_argument('--t', type=float, default=0.3)
    ap.add_argument('--tile', action='store_true')
    ap.add_argument('--start', type=int, default=0)
    ap.add_argument('--step', type=int, default=1)
    o = ap.parse_args()
    if o.mode == 'assets':
        write_assets()
    elif o.mode == 'still':
        render(o.t, o.size, o.tile).save(o.out)
    else:
        os.makedirs(o.out, exist_ok=True)
        nf = int(round(T * o.fps))
        for i in range(o.start, nf, o.step):
            render(i / o.fps, o.size, o.tile).save(os.path.join(o.out, f'f{i:04d}.png'))
