"""Resolve an ffmpeg binary without requiring a system install.

Order: a system ffmpeg on PATH, else the binary bundled by the pip package
imageio-ffmpeg (installed via requirements.txt). Raises a clear message if
neither is available.
"""
import shutil


def ffmpeg_exe():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise RuntimeError(
            "Decoder not available. Run setup again (it installs imageio-ffmpeg), "
            "or install ffmpeg on this machine."
        )
