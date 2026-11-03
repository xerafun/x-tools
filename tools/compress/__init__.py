"""
音视频与图片压缩模块
"""
from tools.compress.batch import batch_compress
from tools.compress.ffmpeg_compress import compress_video
from tools.compress.image_compress import batch_compress_images, compress_image

__all__ = [
    "compress_video",
    "batch_compress",
    "compress_image",
    "batch_compress_images",
]
