"""Make the shortcut icons from the designer's icon SVG.

    python scripts/make_icons.py path/to/magnacodaIcon.svg

Writes to magnacoda/data/icons/: magnacoda.svg and magnacoda.png (Linux), magnacoda.ico (Windows) and
magnacoda.icns (macOS). Needs the dev extras (Pillow) and Playwright's Chromium.
"""

import base64
import io
import re
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "magnacoda" / "data" / "icons"
WINDOWS_SIZES = [16, 20, 24, 32, 40, 48, 64, 256]
MAC_SIZES = [16, 32, 64, 128, 256, 512, 1024]
# Apple's icon grid: the shape is 824 of 1024 pixels wide, centered.
MAC_SHAPE = 824 / 1024


def read_svg(path: Path) -> str:
    """The SVG as UTF-8 text with a square viewBox around the artwork (CorelDRAW exports UTF-16)."""
    data = path.read_bytes()
    text = data.decode("utf-16") if data[:2] in (b"\xff\xfe", b"\xfe\xff") else data.decode("utf-8")
    text = text.replace("\r\n", "\n").replace('encoding="UTF-16"', 'encoding="UTF-8"')
    box = re.search(r'viewBox="([^"]+)"', text)
    if box is None:
        sys.exit(f"{path}: no viewBox")
    x, y, w, h = (float(v) for v in box.group(1).split())
    side = max(w, h)
    square = f"{x - (side - w) / 2:g} {y - (side - h) / 2:g} {side:g} {side:g}"
    text = re.sub(r'viewBox="[^"]+"', f'viewBox="{square}"', text, count=1)
    return re.sub(r'width="[^"]+" height="[^"]+"', 'width="512" height="512"', text, count=1)


def render(page, svg: str, size: int, shape: float = 1.0) -> Image.Image:
    """The icon drawn at size pixels, transparent around it, the artwork shape × size wide."""
    art = round(size * shape)
    uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
    page.set_viewport_size({"width": size, "height": size})
    page.set_content(
        f'<body style="margin:0;display:grid;place-items:center;width:{size}px;height:{size}px">'
        f'<img src="{uri}" width="{art}" height="{art}"></body>'
    )
    page.wait_for_function("document.images[0].complete")
    return Image.open(io.BytesIO(page.screenshot(omit_background=True))).convert("RGBA")


def main(source: str) -> None:
    svg = read_svg(Path(source).expanduser())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "magnacoda.svg").write_text(svg, encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        windows = [render(page, svg, size) for size in WINDOWS_SIZES]
        mac = [render(page, svg, size, MAC_SHAPE) for size in MAC_SIZES]
        browser.close()
    windows[-1].save(OUT / "magnacoda.png")
    windows[-1].save(OUT / "magnacoda.ico", sizes=[(s, s) for s in WINDOWS_SIZES], append_images=windows[:-1])
    mac[-1].save(OUT / "magnacoda.icns", append_images=mac[:-1])
    for name in sorted(OUT.iterdir()):
        print(f"{name.relative_to(OUT.parent.parent.parent)}  {name.stat().st_size:,} bytes")


if __name__ == "__main__":
    main(sys.argv[1])
