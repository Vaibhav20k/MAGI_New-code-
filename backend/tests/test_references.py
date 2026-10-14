"""How Drive files enter the reference library: which kind, which finish, which are skipped."""
import importlib.util
import json
import sys
import types
from pathlib import Path

# references.py imports the app's database and model modules; only its pure functions are tested here.
for name in ("app", "app.db", "app.embed", "app.vision", "app.config", "app.media"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["app"].__path__ = []
sys.modules["app.config"].get_settings = lambda: None
sys.modules["app.media"].media_dir = lambda: Path(".")
spec = importlib.util.spec_from_file_location("app.references", Path(__file__).parents[1] / "app" / "references.py")
refs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refs)

CFG = json.loads((Path(__file__).parents[2] / "inputs" / "reference-library.json").read_text(encoding="utf-8"))


def test_finish_swatches_take_their_name_from_the_file():
    got = refs.classify("/Finishes/PG 2/pg 2.tex", "MAGPPIE  EARTH GREY .jpg", CFG)
    assert got == {"kind": "finish", "source": "real", "media_type": "image", "finish": "MAGPPIE EARTH GREY", "finish_from": "file"}


def test_real_kitchens_and_renders_are_told_apart_by_folder():
    assert refs.classify("/more/kitchen/Real pictures", "kitchen10.jpg", CFG)["source"] == "real"
    assert refs.classify("/more/kitchen/renders", "00.jpg", CFG)["source"] == "render"
    main = refs.classify("/visuals main/kitchens", "01.jpg", CFG)
    assert main["kind"] == "kitchen" and main["source"] is None          # left for the picture itself to say


def test_rooms_logo_and_clips():
    assert refs.classify("/more/vanities/Highresolution", "onyx gold_overmount.png", CFG)["kind"] == "vanity"
    assert refs.classify("/visuals main/wardrobes", "07.png", CFG)["kind"] == "wardrobe"
    assert refs.classify("/LOGO", "magppie-black.png", CFG)["kind"] == "logo"
    clip = refs.classify("/more/videos", "breccia.mp4", CFG)
    assert clip["kind"] == "video" and clip["media_type"] == "video"


def test_duplicates_and_unreadable_files_are_skipped():
    assert refs.classify("/more/videos", "breccia.webm", CFG) is None          # the same clip as the .mp4
    assert refs.classify("/more/magppie logos", "magppie-black.png", CFG) is None
    assert refs.classify("/visuals main/kitchens", "notes.pdf", CFG) is None


def test_a_drive_listing_page_is_read_into_files_and_folders():
    page = ('<div class="flip-entry" id="entry-AAA" tabindex="0"><div><a href="https://drive.google.com/drive/folders/AAA" target="_parent">'
            '<div class="flip-entry-title">Finishes</div></a></div></div>'
            '<div class="flip-entry" id="entry-BBB" tabindex="0"><div><a href="https://drive.google.com/file/d/BBB/view" target="_parent">'
            '<div class="flip-entry-title">M ONYX GOLD &amp; more.jpg</div></a></div></div>')
    assert refs.parse_folder(page) == [("AAA", "Finishes", True), ("BBB", "M ONYX GOLD & more.jpg", False)]


def test_catalogue_text_covers_what_people_search_by():
    text = refs.catalogue_text({"kind": "kitchen", "source": "real", "layout": "island", "finish": "MAGPPIE CALM",
                                "colours": ["ivory", "grey"], "description": "Wide shot of an island kitchen.", "tags": ["island", "pendant"]})
    assert "island" in text and "finish MAGPPIE CALM" in text and "real" in text
