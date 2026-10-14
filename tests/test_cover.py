from PIL import Image

from apofika.cover import apply_red_corner


def test_red_corner_pixels():
    img = Image.new("RGB", (200, 200), color=(10, 20, 30))
    out = apply_red_corner(img, fraction=0.25)
    assert out.getpixel((2, 2)) == (196, 18, 48)
    assert out.getpixel((180, 180)) == (10, 20, 30)
