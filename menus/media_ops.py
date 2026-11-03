"""裁切、滤镜、压缩菜单 (轻量模块合集)"""
from pathlib import Path

from InquirerPy import inquirer
from InquirerPy.base.control import Choice

from menus._prompts import confirm_action, maybe_show_file_list


def menu_crop(media: list[Path]):
    """裁切比例菜单"""
    from tools.crop.batch import batch_crop

    ratio = inquirer.select(
        message="选择目标比例:",
        choices=[
            Choice("1:1", "⬜ 1:1 正方形"),
            Choice("3:4", "📱 3:4 竖屏经典"),
            Choice("4:3", "🖥️  4:3 横屏经典"),
            Choice("9:16", "📲 9:16 竖屏全面"),
            Choice("16:9", "🎬 16:9 横屏宽幅"),
        ],
        default="3:4",
    ).execute()

    if confirm_action(f"确认将 {len(media)} 个文件裁切为 {ratio}?"):
        batch_crop(files=media, ratio=ratio)


def menu_filter(media: list[Path]):
    """滤镜效果菜单"""
    from tools.filter.batch import batch_filter
    from tools.filter.ffmpeg_filter import FILTER_PRESETS, preview_filter

    # 直接在后台打开预览窗口
    close_preview_fn = preview_filter(media[0])

    # 构建选项列表: 展示滤镜名称 + 描述 + 对应序号 (方便对照)
    filter_choices = []
    for idx, (key, info) in enumerate(FILTER_PRESETS.items()):
        # idx 对应生成的预览图上的数字: 0-> 2 (1 是原图)
        filter_choices.append(Choice(key, f"[{idx + 2}] {info['name']}  {info['desc']}"))

    try:
        preset = inquirer.select(
            message="选择滤镜 (可参考弹出的预览窗口):",
            choices=filter_choices,
            default="saturate",
        ).execute()
    except KeyboardInterrupt:
        # 用户取消, 关闭预览窗口后向上传播异常
        if close_preview_fn is not None:
            close_preview_fn()
        raise

    # 用户选择完毕, 关闭预览窗口
    if close_preview_fn is not None:
        close_preview_fn()

    maybe_show_file_list(media)

    preset_name = FILTER_PRESETS[preset]["name"]
    if confirm_action(f"确认为 {len(media)} 个文件应用 {preset_name} 滤镜?"):
        batch_filter(files=media, preset=preset)


def _menu_compress_video(videos: list[Path]):
    """视频压缩子流程"""
    from tools.compress.batch import batch_compress

    codec = inquirer.select(
        message="视频编码器:",
        choices=[
            Choice("libx264", "🔧 H.264 (兼容各类主流媒体平台, 稳定推荐)"),
            Choice("libx265", "🚀 H.265 (HEVC, 极致体积, 部分旧设备或环境可能不兼容)"),
        ],
        default="libx264",
    ).execute()

    strength = inquirer.select(
        message="压缩强度:",
        choices=[
            Choice(24, "🌟 标准平衡 (视觉几乎无损, 适合上传抖音/视频号等)"),
            Choice(28, "🗜️  体积极限 (画质极轻微降低, 体积最小化)"),
            Choice(18, "💎 极致高保真 (接近原画大小, 适合高清存档)"),
        ],
        default=24,
    ).execute()

    maybe_show_file_list(videos)
    if confirm_action(f"确认压缩 {len(videos)} 个视频?"):
        batch_compress(files=videos, codec=codec, crf=strength)


def _menu_compress_image(images: list[Path]):
    """图片压缩子流程 (TinyPNG 级)"""
    from tools.compress.image_compress import batch_compress_images

    mode = inquirer.select(
        message="选择图片压缩策略:",
        choices=[
            Choice("tinypng", "🌟 智能有损瘦身 (TinyPNG 模式, 推荐, 视觉无损, 减重 60%~80%)"),
            Choice("lossless", "💎 极致完全无损 (仅剔除元数据与重优化, 减重 10%~25%)"),
            Choice("webp", "🚀 转换为 WebP 格式 (新一代现代格式, 体积极致最小)"),
        ],
        default="tinypng",
    ).execute()

    quality = 82
    if mode in ("tinypng", "webp"):
        quality = int(
            inquirer.select(
                message="压缩质量预设:",
                choices=[
                    Choice(82, "🌟 标准平衡 (Quality 82, 推荐, 兼顾高画质与小体积)"),
                    Choice(70, "🗜️  轻量省流 (Quality 70, 适合极速网络加载)"),
                    Choice(90, "💎 高清保真 (Quality 90, 极微损)"),
                ],
                default=82,
            ).execute()
        )

    maybe_show_file_list(images)
    convert_to_webp = mode == "webp"
    actual_mode = "tinypng" if mode == "webp" else mode

    if confirm_action(f"确认压缩 {len(images)} 张图片?"):
        batch_compress_images(
            files=images,
            mode=actual_mode,
            quality=quality,
            convert_to_webp=convert_to_webp,
        )


def menu_compress(files: list[Path] | None = None):
    """无损/视觉无损压缩菜单 (支持视频与图片)"""
    from menus._prompts import get_input_images, get_input_videos

    if files is not None and len(files) > 0:
        # 自动根据文件类型分流
        from config import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
        has_images = any(f.suffix.lower() in IMAGE_EXTENSIONS for f in files)
        has_videos = any(f.suffix.lower() in VIDEO_EXTENSIONS for f in files)

        if has_images and not has_videos:
            _menu_compress_image(files)
            return
        elif has_videos and not has_images:
            _menu_compress_video(files)
            return

    # 引导选择压缩分类
    compress_type = inquirer.select(
        message="选择压缩类型:",
        choices=[
            Choice("image", "🖼️ 图片智能瘦身 (TinyPNG 级别: PNG 256色量化 / JPG 渐进式 / WebP)"),
            Choice("video", "🎬 视频压缩 (H.264 / H.265 CRF 预设)"),
            Choice("back", "⬅️  返回上一级"),
        ],
        default="image",
    ).execute()

    if compress_type == "back":
        return

    if compress_type == "image":
        images = get_input_images()
        if not images:
            return
        _menu_compress_image(images)
    else:
        videos = get_input_videos()
        if not videos:
            return
        _menu_compress_video(videos)

