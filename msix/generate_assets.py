"""Generate the MSIX visual assets (Store logo, tiles, splash screen)
from the project's icon_512.png and pdfapps.svg.

Microsoft Store / sideload requires PNGs at specific resolutions.
This script produces them all from the master SVG / 512×512 master so
the package only carries ONE source-of-truth icon.

Usage (from project root):
    py msix/generate_assets.py

Output: msix/Assets/*.png at the resolutions listed below.
"""
import os
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("error: Pillow required (`pip install pillow`).")
    sys.exit(1)


# (filename, width, height, use_svg_renderer)
TARGETS = [
    ("Square44x44Logo.png",   44,  44,  False),
    ("Square71x71Logo.png",   71,  71,  False),
    ("Square150x150Logo.png", 150, 150, False),
    ("Square310x310Logo.png", 310, 310, False),
    ("Wide310x150Logo.png",   310, 150, False),
    ("StoreLogo.png",         50,  50,  False),
    ("SplashScreen.png",      620, 300, False),
]

TARGETSIZE_VARIANTS = [16, 24, 32, 48, 96, 256]


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    project_root = Path(here).parent
    src = project_root / "icon_512.png"
    svg_src = project_root / "pdfapps.svg"

    # If icon_512.png is absent or older than pdfapps.svg, regenerate it
    if svg_src.is_file():
        need_rebuild = not src.is_file()
        if not need_rebuild:
            try:
                need_rebuild = svg_src.stat().st_mtime > src.stat().st_mtime
            except Exception:
                pass
        if need_rebuild:
            try:
                if str(project_root) not in sys.path:
                    sys.path.insert(0, str(project_root))
                from generate_icons import generate_all_icons
                generate_all_icons(project_root)
            except Exception as exc:
                print(f"Warning: could not run generate_all_icons: {exc}")

    if not src.is_file():
        print(f"error: {src} not found")
        sys.exit(2)

    assets_dir = os.path.join(here, "Assets")
    os.makedirs(assets_dir, exist_ok=True)

    master = Image.open(str(src)).convert("RGBA")

    for name, w, h, _ in TARGETS:
        out = os.path.join(assets_dir, name)
        if w == h:
            img = master.resize((w, h), Image.LANCZOS)
        else:
            canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            inner = min(w, h)
            scaled = master.resize((inner, inner), Image.LANCZOS)
            canvas.paste(scaled, ((w - inner) // 2, (h - inner) // 2), scaled)
            img = canvas
        img.save(out, "PNG", optimize=True)
        print(f"wrote {os.path.relpath(out, str(project_root))} ({w}x{h})")

    for size in TARGETSIZE_VARIANTS:
        name = f"Square44x44Logo.targetsize-{size}.png"
        out = os.path.join(assets_dir, name)
        img = master.resize((size, size), Image.LANCZOS)
        img.save(out, "PNG", optimize=True)
        print(f"wrote {os.path.relpath(out, str(project_root))} ({size}x{size})")

    total = len(TARGETS) + len(TARGETSIZE_VARIANTS)
    print(f"\n[OK] {total} MSIX assets generated in {assets_dir}")


if __name__ == "__main__":
    main()