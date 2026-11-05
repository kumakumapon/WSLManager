"""アプリのアイコン (assets/wslmanager.ico / assets/wslmanager.png) を作り直すスクリプト。

普段のビルドでは使わない (生成済みのファイルをリポジトリに置いている)。デザインを
変えるときだけ、開発環境で実行する::

    pip install pillow
    python tools/make_icon.py

ICO は Windows の標準的な構成にする: 16〜128 px は非圧縮の 32 bit BMP (DIB)、
256 px だけ PNG 圧縮。Tk 8.6 の ``wm iconbitmap`` は DIB のエントリしか読めないため、
小さいサイズを PNG にしない (Pillow の既定はすべて PNG)。
"""

from __future__ import annotations

import io
import struct
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
CANVAS = 1024
DIB_SIZES = (16, 24, 32, 48, 64, 128)


def render() -> Image.Image:
    """1024 px の原画: 青いグラデーションの角丸の四角に、白い ">" と水色の "_"。"""
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    gradient = Image.new("RGBA", (CANVAS, CANVAS))
    top, bottom = (37, 99, 235), (23, 37, 84)
    draw = ImageDraw.Draw(gradient)
    for y in range(CANVAS):
        t = y / (CANVAS - 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (CANVAS, y)], fill=(*color, 255))
    mask = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40, 40, CANVAS - 40, CANVAS - 40], radius=200, fill=255)
    image.paste(gradient, (0, 0), mask)

    draw = ImageDraw.Draw(image)
    # ウィンドウのタイトルバー風の 3 つの点
    for index, color in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        cx = 170 + index * 80
        draw.ellipse([cx - 24, 126, cx + 24, 174], fill=(*color, 255))
    # プロンプトの ">"
    width = 92
    white = (255, 255, 255, 255)
    draw.line([(250, 360), (470, 560), (250, 760)], fill=white, width=width, joint="curve")
    for x, y in ((250, 360), (250, 760), (470, 560)):
        draw.ellipse([x - width / 2, y - width / 2, x + width / 2, y + width / 2], fill=white)
    # カーソルの "_"
    cyan = (125, 211, 252, 255)
    draw.rounded_rectangle([540, 712, 800, 712 + width], radius=width // 2, fill=cyan)
    return image


def dib_entry(image: Image.Image) -> bytes:
    """ICO の 1 エントリ分の DIB (BITMAPINFOHEADER + BGRA 画素 + AND マスク)。"""
    image = image.convert("RGBA")
    width, height = image.size
    pixels = image.load()
    assert pixels is not None
    # biHeight は画素とマスクを合わせた高さ (2 倍) を書く決まり
    header = struct.pack("<IiiHHIIiiII", 40, width, height * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    color = bytearray()
    for y in range(height - 1, -1, -1):  # 下の行から
        for x in range(width):
            r, g, b, a = pixels[x, y]  # type: ignore[misc]
            color += bytes((b, g, r, a))
    row_bytes = ((width + 31) // 32) * 4
    and_mask = bytearray()
    for y in range(height - 1, -1, -1):
        row = bytearray(row_bytes)
        for x in range(width):
            if pixels[x, y][3] == 0:  # type: ignore[index]
                row[x // 8] |= 0x80 >> (x % 8)
        and_mask += row
    return header + bytes(color) + bytes(and_mask)


def build_ico(original: Image.Image) -> bytes:
    entries = [
        (size, dib_entry(original.resize((size, size), Image.LANCZOS))) for size in DIB_SIZES
    ]
    png = io.BytesIO()
    original.resize((256, 256), Image.LANCZOS).save(png, "PNG")
    entries.append((256, png.getvalue()))

    directory = bytearray(struct.pack("<HHH", 0, 1, len(entries)))
    offset = 6 + 16 * len(entries)
    blobs = bytearray()
    for size, data in entries:
        dimension = 0 if size == 256 else size  # 0 は 256 px を表す
        directory += struct.pack(
            "<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset + len(blobs)
        )
        blobs += data
    return bytes(directory + blobs)


def main() -> None:
    original = render()
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    original.resize((256, 256), Image.LANCZOS).save(assets / "wslmanager.png")
    (assets / "wslmanager.ico").write_bytes(build_ico(original))
    print(f"wrote {assets / 'wslmanager.ico'} and {assets / 'wslmanager.png'}")


if __name__ == "__main__":
    main()
