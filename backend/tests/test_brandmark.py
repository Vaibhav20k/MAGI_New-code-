"""Where the real logo goes on a picture, and which colour it takes."""
import importlib.util
import sys
import types
from pathlib import Path

for name in ("app", "app.config", "app.media"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["app"].__path__ = []
sys.modules["app.config"].get_settings = lambda: types.SimpleNamespace(inputs_dir=Path(__file__).parents[2] / "inputs")
sys.modules["app.media"].media_dir = lambda: Path(".")
spec = importlib.util.spec_from_file_location("app.brandmark", Path(__file__).parents[1] / "app" / "brandmark.py")
bm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bm)

LOGO = (1267, 655)                                   # the size of inputs/logo-black.png


def test_a_centred_slot_keeps_the_logo_shape_and_centre():
    left, top, right, bottom = bm.slot_box((1080, 1920), {"x": .5, "y": .8, "width": .34, "anchor": "center"}, LOGO)
    assert right - left == round(1080 * .34)
    assert abs((bottom - top) - (right - left) * LOGO[1] / LOGO[0]) <= 1
    assert abs((left + right) / 2 - 540) <= 1 and abs((top + bottom) / 2 - 1536) <= 1


def test_a_top_left_slot_starts_at_its_corner_and_stays_inside():
    assert bm.slot_box((1000, 1500), {"x": .06, "y": .045, "width": .24, "anchor": "top-left"}, LOGO)[:2] == (60, 68)
    left, top, right, bottom = bm.slot_box((400, 300), {"x": .99, "y": .99, "width": .5, "anchor": "top-left"}, LOGO)
    assert right <= 400 and bottom <= 300


def test_white_on_dark_ground_black_on_light():
    assert bm.colour_for(.1) == "white" and bm.colour_for(.9) == "black"


def test_the_white_logo_is_the_black_one_recoloured(tmp_path):
    black, white = bm.logo("black"), bm.logo("white")
    assert white.size == black.size
    assert list(white.getchannel("A").getdata()) == list(black.getchannel("A").getdata())
    from PIL import Image
    ground = tmp_path / "dark.png"
    Image.new("RGB", (900, 1600), (10, 10, 12)).save(ground)
    out = bm.stamp(ground, tmp_path / "out.png", {"x": .5, "y": .8, "width": .3, "anchor": "center"})
    with Image.open(out) as im:
        assert max(im.convert("L").getdata()) == 255          # white logo laid on the dark picture
