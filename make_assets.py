"""Make the pictures the game uses, from raw_art/ (Pillow).

Run this on your own computer:  python make_assets.py

It only READS raw_art/ (those pictures must never change) and writes assets/.
Every picture becomes 3 times bigger with NEAREST scaling, so the pixels stay
sharp -- no blurring. Two bright crystal gems are coloured from
raw_art/gem.png: blue for 1 XP and pink for 2 XP.
"""

import json
import os

from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(BASE_DIR, "raw_art")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
CONFIG_PATH = os.path.join(BASE_DIR, "data", "game.json")

#: (dark edge, bright shine) for each gem colour.
GEM_COLOURS = {
    "gem_blue.png": ((14, 44, 140), (170, 245, 255)),
    "gem_pink.png": ((122, 22, 96), (255, 176, 232)),
}


def load_scale():
    """How many times bigger the pictures become (from data/game.json)."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
        return int(json.load(handle)["assets"]["scale"])


def tint(gem, dark, bright):
    """Colour a grey crystal: keep its dark and light parts, change the hue."""
    source = gem.convert("RGBA")
    width, height = source.size
    result = Image.new("RGBA", (width, height))
    src_pixels = source.load()
    out_pixels = result.load()
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = src_pixels[x, y]
            if alpha == 0:
                continue
            light = (0.299 * red + 0.587 * green + 0.114 * blue) / 255.0
            out_pixels[x, y] = (
                int(dark[0] + (bright[0] - dark[0]) * light),
                int(dark[1] + (bright[1] - dark[1]) * light),
                int(dark[2] + (bright[2] - dark[2]) * light),
                alpha,
            )
    return result


def enlarge(image, scale):
    """Make the picture bigger without blurring: NEAREST copies pixels."""
    return image.resize((image.width * scale, image.height * scale), Image.NEAREST)


def main():
    scale = load_scale()
    os.makedirs(ASSETS_DIR, exist_ok=True)

    # Start clean, so a picture that was renamed does not stay behind.
    for old in os.listdir(ASSETS_DIR):
        if old.lower().endswith(".png"):
            os.remove(os.path.join(ASSETS_DIR, old))

    names = sorted(n for n in os.listdir(RAW_DIR) if n.lower().endswith(".png"))
    for name in names:
        source = Image.open(os.path.join(RAW_DIR, name))
        big = enlarge(source, scale)
        big.save(os.path.join(ASSETS_DIR, name))
        print("%-12s %2dx%d -> %2dx%d  (x%d)" % (
            name, source.width, source.height, big.width, big.height, scale))

    gem = Image.open(os.path.join(RAW_DIR, "gem.png"))
    for out_name, (dark, bright) in GEM_COLOURS.items():
        coloured = enlarge(tint(gem, dark, bright), scale)
        coloured.save(os.path.join(ASSETS_DIR, out_name))
        print("%-12s %2dx%d -> %2dx%d  (x%d, coloured)" % (
            out_name, gem.width, gem.height,
            coloured.width, coloured.height, scale))

    print("done: %d pictures in %s" % (len(os.listdir(ASSETS_DIR)), ASSETS_DIR))


if __name__ == "__main__":
    main()
