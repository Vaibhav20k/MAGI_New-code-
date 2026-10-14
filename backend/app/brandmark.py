"""The real MAGPPIE logo, placed on finished pictures (and, later, video frames) after they are made.

Image and video models cannot be trusted to draw a logo: they misspell it and change its shape. So no model is
ever asked for it. A place is kept clear for it, and the logo file itself is laid there, white on dark ground and
black on light ground.
"""

import logging
from functools import lru_cache
from pathlib import Path

from .config import get_settings
from .media import media_dir

log = logging.getLogger("mai.brandmark")


@lru_cache
def logo(colour: str):
    """The logo as an RGBA picture in 'black' or 'white'. White is the black logo recoloured, so the shape is exact."""
    from PIL import Image
    black = Image.open(get_settings().inputs_dir / "logo-black.png").convert("RGBA")
    if colour == "black":
        return black
    alpha = black.getchannel("A")
    white = Image.new("RGBA", black.size, (255, 255, 255, 255))
    white.putalpha(alpha)
    return white


def slot_box(size: tuple[int, int], slot: dict, logo_size: tuple[int, int]) -> tuple[int, int, int, int]:
    """Where the logo goes, in pixels. slot: x, y (fractions of the picture), width (fraction of the picture's width),
    anchor 'center' (x, y is the logo's centre) or 'top-left' (x, y is its top-left corner)."""
    w, h = size
    lw = max(1, round(w * float(slot.get("width", .3))))
    lh = max(1, round(lw * logo_size[1] / logo_size[0]))
    x, y = float(slot.get("x", .5)) * w, float(slot.get("y", .9)) * h
    if slot.get("anchor", "center") == "center":
        x, y = x - lw / 2, y - lh / 2
    left, top = int(round(min(max(0, x), w - lw))), int(round(min(max(0, y), h - lh)))
    return left, top, left + lw, top + lh


def colour_for(brightness: float) -> str:
    """Average brightness under the logo (0 dark, 1 light) decides its colour."""
    return "black" if brightness >= .55 else "white"


def stamp(src: Path, dest: Path, slot: dict, colour: str = "auto") -> Path:
    """Lay the logo on a picture; writes dest and returns it."""
    from PIL import Image, ImageStat
    with Image.open(src) as im:
        im = im.convert("RGBA")
        mark = logo("black")
        box = slot_box(im.size, slot, mark.size)
        if colour == "auto":
            under = im.crop(box).convert("L")
            colour = colour_for(ImageStat.Stat(under).mean[0] / 255)
        mark = logo(colour).resize((box[2] - box[0], box[3] - box[1]), Image.LANCZOS)
        im.alpha_composite(mark, (box[0], box[1]))
        out = im.convert("RGB") if dest.suffix.lower() in (".jpg", ".jpeg") else im
        out.save(dest)
    return dest


def stamp_media(url: str, slot: dict) -> str:
    """Stamp a picture saved under /media and return the /media address of the stamped copy (the original stays)."""
    src = media_dir() / url.removeprefix("/media/")
    dest = src.with_name(src.stem + "_logo.png")
    stamp(src, dest, slot)
    return "/media/" + dest.relative_to(media_dir()).as_posix()
