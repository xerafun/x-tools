"""
图片智能压缩与瘦身 (TinyPNG 级) 单元测试
"""
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from tools.compress.image_compress import (
    _quantize_png_pillow,
    batch_compress_images,
    compress_image,
)


@pytest.fixture
def sample_png(tmp_path: Path) -> Path:
    """生成带丰富透明度和色彩的 RGBA 测试 PNG"""
    img_path = tmp_path / "test_rgba.png"
    im = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    for y in range(200):
        for x in range(200):
            im.putpixel((x, y), (x, y, (x + y) % 256, (x * 2) % 256))
    im.save(img_path, format="PNG")
    return img_path


@pytest.fixture
def sample_jpeg(tmp_path: Path) -> Path:
    """生成真彩色 RGB 测试 JPEG"""
    img_path = tmp_path / "test_rgb.jpg"
    im = Image.new("RGB", (400, 400), (255, 255, 255))
    draw = ImageDraw.Draw(im)
    for i in range(100):
        draw.rectangle([i * 2, i * 2, 400 - i * 2, 400 - i * 2], fill=(i * 2, 100, 255 - i * 2))
    im.save(img_path, format="JPEG", quality=100)
    return img_path


def test_compress_png_tinypng_mode(sample_png: Path, tmp_path: Path):
    """测试 PNG TinyPNG 智能量化模式"""
    out_path = tmp_path / "compressed.png"
    result = compress_image(sample_png, output_path=out_path, mode="tinypng")

    assert out_path.exists()
    assert result["output_size_mb"] <= result["input_size_mb"]
    assert result["saved_percent"] >= 0

    # 验证输出图像格式与尺寸保持一致
    with Image.open(out_path) as out_im:
        assert out_im.size == (200, 200)
        assert out_im.format == "PNG"


def test_compress_png_pillow_fallback(sample_png: Path, tmp_path: Path):
    """测试 Pillow 兜底量化函数"""
    out_path = tmp_path / "fallback.png"
    with Image.open(sample_png) as im:
        _quantize_png_pillow(im, out_path, max_colors=256)

    assert out_path.exists()
    assert out_path.stat().st_size > 0
    with Image.open(out_path) as out_im:
        assert out_im.mode == "P"


def test_compress_jpeg_tinypng_mode(sample_jpeg: Path, tmp_path: Path):
    """测试 JPEG 渐进式色彩抽样压缩"""
    out_path = tmp_path / "compressed.jpg"
    result = compress_image(sample_jpeg, output_path=out_path, mode="tinypng", quality=80)

    assert out_path.exists()
    assert result["saved_percent"] > 0
    assert out_path.stat().st_size < sample_jpeg.stat().st_size

    with Image.open(out_path) as out_im:
        assert out_im.size == (400, 400)
        assert out_im.format == "JPEG"


def test_compress_convert_to_webp(sample_jpeg: Path, tmp_path: Path):
    """测试一键转换为 WebP 现代格式"""
    out_path = tmp_path / "converted.webp"
    result = compress_image(sample_jpeg, output_path=out_path, convert_to_webp=True, quality=80)

    assert out_path.exists()
    assert result["output"].endswith(".webp")
    with Image.open(out_path) as out_im:
        assert out_im.format == "WEBP"


def test_compress_validation_errors(tmp_path: Path):
    """测试异常参数拦截"""
    # 不存在的文件
    with pytest.raises(FileNotFoundError):
        compress_image(tmp_path / "not_found.png")

    # 不支持的格式
    fake_txt = tmp_path / "test.txt"
    fake_txt.write_text("hello")
    with pytest.raises(ValueError, match="不支持的图片格式"):
        compress_image(fake_txt)


def test_batch_compress_images(sample_png: Path, sample_jpeg: Path, tmp_path: Path):
    """测试多文件批量压缩流程"""
    out_dir = tmp_path / "batch_out"
    results = batch_compress_images(
        files=[sample_png, sample_jpeg],
        mode="tinypng",
        quality=80,
        output_dir=out_dir,
    )

    assert len(results) == 2
    for r in results:
        assert r["status"] == "success"
        assert Path(r["output"]).exists()
