"""PDFApps – Utility to generate icon_512.png and multi-resolution icon.ico from pdfapps.svg."""
import os
import struct
import sys
import tempfile
from pathlib import Path


def _build_ico_binary(png_data_by_size: list[tuple[int, bytes]]) -> bytes:
    """Pack multiple PNG byte streams into standard Windows .ico binary format."""
    num_images = len(png_data_by_size)
    header = struct.pack("<HHH", 0, 1, num_images)
    entries = []
    offset = 6 + (16 * num_images)
    data_blobs = []

    for size, data in png_data_by_size:
        w = 0 if size >= 256 else size
        h = 0 if size >= 256 else size
        entry = struct.pack(
            "<BBBBHHII",
            w, h, 0, 0, 1, 32, len(data), offset
        )
        entries.append(entry)
        data_blobs.append(data)
        offset += len(data)

    return header + b"".join(entries) + b"".join(data_blobs)


def render_svg_to_file(svg_path: Path, out_path: Path, size: int) -> None:
    """Render an SVG file at the specified pixel size to a PNG file using Qt."""
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    app = QGuiApplication.instance()
    if app is None:
        app = QGuiApplication(sys.argv[:1])

    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise ValueError(f"Could not load valid SVG from: {svg_path}")

    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter)
    painter.end()

    img.save(str(out_path))


def generate_all_icons(root_dir: Path | None = None) -> tuple[Path, Path]:
    """Generate icon_512.png and multi-resolution icon.ico from pdfapps.svg."""
    if root_dir is None:
        root_dir = Path(__file__).resolve().parent

    svg_file = root_dir / "pdfapps.svg"
    png_512_file = root_dir / "icon_512.png"
    ico_file = root_dir / "icon.ico"

    if not svg_file.is_file():
        raise FileNotFoundError(f"SVG source not found at {svg_file}")

    print(f"[Icon Generator] Rendering 512x512 master from {svg_file.name}...")
    render_svg_to_file(svg_file, png_512_file, 512)
    print(f"[Icon Generator] Saved {png_512_file.name}")

    ico_sizes = [256, 128, 64, 48, 32, 24, 16]

    # First attempt: use Pillow for multi-resolution ICO packaging
    try:
        from PIL import Image
        master = Image.open(str(png_512_file))
        master.save(
            str(ico_file),
            format="ICO",
            sizes=[(sz, sz) for sz in ico_sizes],
        )
        print(f"[Icon Generator] Saved {ico_file.name} (via Pillow with {len(ico_sizes)} layers)")
        return png_512_file, ico_file
    except Exception as exc:
        print(f"[Icon Generator] Pillow ICO save unavailable ({exc}), using native binary builder...")

    # Fallback: render each size and assemble binary ICO
    png_layers: list[tuple[int, bytes]] = []
    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        for sz in ico_sizes:
            tmp_png = tmp_dir / f"layer_{sz}.png"
            render_svg_to_file(svg_file, tmp_png, sz)
            png_layers.append((sz, tmp_png.read_bytes()))

    ico_bytes = _build_ico_binary(png_layers)
    ico_file.write_bytes(ico_bytes)
    print(f"[Icon Generator] Saved {ico_file.name} (via native ICO binary builder with {len(ico_sizes)} layers)")

    return png_512_file, ico_file


if __name__ == "__main__":
    generate_all_icons()