"""
分镜头智能拼接与配音字幕合成引擎 (Storyboard Video Assembler)

核心特性:
  1. 智能音画自适应对齐: 当台词长于视频画面时，自动尾帧定格 (tpad)，画面平稳过渡；
  2. 毫秒级逐句对齐字幕: 自动按断句生成 ASS 字幕，配音读到哪句、字幕动态切换到哪句；
  3. 商业科技级字幕样式: 纯白大字 + 深蓝微透底栏 + 核心词强调，多端浅色/深色背景清晰可见；
  4. 局部智能去水印: 支持对特定镜头 (如片尾镜头) 消除 AI 生成水印；
  5. 纯净优先: 默认纯净人声无背景乐干扰，亦支持一键开启轻柔 BGM 混流。
"""
import os
import platform
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from config import FFMPEG_BIN, FFPROBE_BIN, OUTPUT_CONCAT
from tools.common import generate_output_name, get_video_info, logger
from tools.concat.script_parser import parse_storyboard_script


def get_default_chinese_font() -> str:
    """根据操作系统自动探测推荐的中文字体名称"""
    system = platform.system()
    if system == "Darwin":
        # macOS 优先使用冬青黑体或苹方
        for font in ["Hiragino Sans GB", "PingFang SC", "STHeiti"]:
            return font
    elif system == "Windows":
        return "Microsoft YaHei"
    else:
        return "Noto Sans CJK SC"
    return "Arial"


def _format_ass_timestamp(seconds: float) -> str:
    """将秒数转为 ASS 时间戳格式 H:MM:SS.cs"""
    if seconds < 0:
        seconds = 0
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hrs}:{mins:02d}:{secs:05.2f}"


def _get_media_duration(file_path: Path | str) -> float:
    """获取音视频文件精确时长 (秒)"""
    cmd = [
        FFPROBE_BIN, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    try:
        out = subprocess.check_output(cmd).decode().strip()
        return float(out)
    except Exception:
        info = get_video_info(str(file_path))
        return float(info.get("duration", 0.0))


def _synthesize_sentence(text: str, voice: str, proxy: str | None, out_wav: Path) -> float:
    """合成单句语音并输出标准 44100Hz 双声道 WAV"""
    env = os.environ.copy()
    if proxy:
        env["https_proxy"] = proxy
        env["http_proxy"] = proxy
        env["all_proxy"] = proxy.replace("http://", "socks5://")

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_mp3:
        tmp_mp3_path = Path(tmp_mp3.name)

    try:
        cmd_tts = [
            "edge-tts",
            "--voice", voice,
            "--text", text,
            "--write-media", str(tmp_mp3_path)
        ]
        if proxy:
            cmd_tts.extend(["--proxy", proxy])

        res = subprocess.run(cmd_tts, env=env, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Edge-TTS 错误: {res.stderr}")

        # 转为 44100Hz 双声道 WAV
        cmd_cv = [
            FFMPEG_BIN, "-y",
            "-i", str(tmp_mp3_path),
            "-ar", "44100", "-ac", "2",
            str(out_wav)
        ]
        subprocess.run(cmd_cv, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return _get_media_duration(out_wav)
    finally:
        if tmp_mp3_path.is_file():
            tmp_mp3_path.unlink()


def compose_storyboard_video(
    video_paths: list[str | Path],
    script_source: list[dict] | str | Path,
    output_path: str | Path | None = None,
    voice: str = "zh-CN-YunyangNeural",
    proxy: str | None = "http://127.0.0.1:7890",
    enable_bgm: bool = False,
    music_path: str | Path | None = None,
    music_volume: float = 0.12,
    delogo_map: dict[int, tuple[int, int, int, int]] | None = None,
    font_name: str | None = None,
    progress_callback: Callable | None = None,
) -> dict:
    """
    分镜头智能拼接与逐句配音字幕合成主入口

    Args:
        video_paths: 分镜头视频文件路径列表 (按播放顺序)
        script_source: 脚本文件路径 (.docx, .txt, .json) 或已解析好的分镜列表
        output_path: 输出视频文件路径 (None 则自动生成)
        voice: 配音音色 (默认 zh-CN-YunyangNeural 云扬商业男声)
        proxy: 网络代理地址 (如 http://127.0.0.1:7890，None 则不走代理)
        enable_bgm: 是否添加背景音乐 (默认 False 纯净人声模式)
        music_path: 背景音乐文件路径
        music_volume: 背景音乐音量 (默认 0.12)
        delogo_map: 水印去除字典, 键为分镜序号 (1-indexed), 值为 (x, y, w, h)
        font_name: 字幕字体名称 (None 则自动探测系统最佳中文字体)
        progress_callback: 进度回调函数 progress_callback(step_name, percent)

    Returns:
        dict: {"output": str, "duration": float, "size_mb": float, "shot_count": int}
    """
    video_paths = [Path(p).resolve() for p in video_paths]
    for vp in video_paths:
        if not vp.is_file():
            raise FileNotFoundError(f"分镜视频不存在: {vp}")

    # 1. 解析脚本台词
    if isinstance(script_source, (str, Path)):
        shots_data = parse_storyboard_script(script_source)
    else:
        shots_data = script_source

    if not shots_data:
        raise ValueError("分镜台词数据为空，无法生成配音与字幕")

    # 确保视频数量与分镜头匹配 (若视频多于脚本，截断视频；若脚本多于视频，按视频数量对齐)
    num_shots = min(len(video_paths), len(shots_data))
    video_paths = video_paths[:num_shots]
    shots_data = shots_data[:num_shots]

    font = font_name or get_default_chinese_font()
    delogo_map = delogo_map or {}

    # 确定输出路径
    OUTPUT_CONCAT.mkdir(parents=True, exist_ok=True)
    if output_path is None:
        out_name = generate_output_name("storyboard", ".mp4", tag=f"{num_shots}shots")
        output_path = OUTPUT_CONCAT / out_name
    output_path = Path(output_path).resolve()

    work_dir = Path(tempfile.mkdtemp(prefix="x_tools_storyboard_"))
    logger.info(f"开始分镜头智能合流: 共 {num_shots} 个分镜，临时工作区: {work_dir}")

    try:
        processed_clips = []

        for idx in range(num_shots):
            shot_num = idx + 1
            v_path = video_paths[idx]
            s_data = shots_data[idx]
            sentences = s_data.get("sentences") or [s_data.get("narration", "")]

            if progress_callback:
                progress_callback(f"处理分镜 {shot_num}/{num_shots}", idx / num_shots * 0.8)
            logger.info(f"正在处理分镜 {shot_num}/{num_shots}: {v_path.name}")

            shot_dir = work_dir / f"shot_{shot_num}"
            shot_dir.mkdir(parents=True, exist_ok=True)

            # 2. 逐句合成音频并记录毫秒级时间戳
            current_time = 0.25  # 留 0.25 秒画面先起再出声
            sentence_audios = []
            dialogue_events = []
            pause_dur = 0.25

            # 起始轻微静音
            init_silence = shot_dir / "init_silence.wav"
            subprocess.run([
                FFMPEG_BIN, "-y", "-f", "lavfi", "-t", "0.25",
                "-i", "anullsrc=r=44100:cl=stereo", str(init_silence)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            sentence_audios.append(init_silence)

            for s_idx, raw_sentence in enumerate(sentences):
                raw_sentence = raw_sentence.strip()
                if not raw_sentence:
                    continue
                s_wav = shot_dir / f"sent_{s_idx}.wav"
                dur = _synthesize_sentence(raw_sentence, voice, proxy, s_wav)
                sentence_audios.append(s_wav)

                start_t = current_time
                end_t = current_time + dur
                dialogue_events.append((start_t, end_t, raw_sentence))
                current_time = end_t + pause_dur

                # 句间自然停顿
                pause_wav = shot_dir / f"pause_{s_idx}.wav"
                subprocess.run([
                    FFMPEG_BIN, "-y", "-f", "lavfi", "-t", f"{pause_dur:.3f}",
                    "-i", "anullsrc=r=44100:cl=stereo", str(pause_wav)
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                sentence_audios.append(pause_wav)

            total_speech_dur = max(0.5, current_time - pause_dur)

            # 拼接单镜完整音频
            concat_list_file = shot_dir / "audio_concat.txt"
            with open(concat_list_file, "w", encoding="utf-8") as f:
                for a_file in sentence_audios[:-1]:
                    f.write(f"file '{a_file.as_posix()}'\n")

            full_shot_audio = shot_dir / "full_audio.wav"
            subprocess.run([
                FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0",
                "-i", str(concat_list_file), "-c", "copy", str(full_shot_audio)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # 3. 画面自适应时长计算 (给配音完预留 0.5s 停顿呼吸)
            video_dur = _get_media_duration(v_path)
            target_dur = max(video_dur, total_speech_dur + 0.5)

            # 4. 生成 ASS 逐句同步字幕
            ass_path = shot_dir / "subtitles.ass"
            ass_header = (
                "[Script Info]\n"
                "ScriptType: v4.00+\n"
                "PlayResX: 1280\n"
                "PlayResY: 720\n"
                "ScaledBorderAndShadow: yes\n\n"
                "[V4+ Styles]\n"
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
                "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                "Alignment, MarginL, MarginR, MarginV, Encoding\n"
                f"Style: Default,{font},24,&H00FFFFFF,&H000000FF,&H00000000,"
                "&H60723616,1,0,0,0,100,100,1,0,3,8,0,2,20,20,28,1\n\n"
                "[Events]\n"
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            )
            with open(ass_path, "w", encoding="utf-8") as f:
                f.write(ass_header)
                for st, et, txt in dialogue_events:
                    st_str = _format_ass_timestamp(st)
                    et_str = _format_ass_timestamp(et)
                    f.write(f"Dialogue: 0,{st_str},{et_str},Default,,0,0,0,,{txt}\n")

            # 5. 构建分镜头 FFmpeg 处理滤镜 (tpad 尾帧定格 + delogo + subtitles)
            vfilters = []
            if target_dur > video_dur:
                pad_len = target_dur - video_dur
                vfilters.append(f"tpad=stop_mode=clone:stop_duration={pad_len:.3f}")

            # 检查是否有该镜头的 delogo 去水印配置
            if shot_num in delogo_map:
                dx, dy, dw, dh = delogo_map[shot_num]
                vfilters.append(f"delogo=x={dx}:y={dy}:w={dw}:h={dh}")

            # 转义字幕文件路径中的冒号与特殊字符
            escaped_ass = str(ass_path).replace("\\", "/").replace(":", "\\:")
            vfilters.append(f"subtitles={escaped_ass}:fontsdir=/System/Library/Fonts")
            vfilters.append("format=yuv420p")
            vf_str = ",".join(vfilters)

            af_str = f"apad=whole_dur={target_dur:.3f},aformat=sample_rates=44100:channel_layouts=stereo"

            shot_out_mp4 = shot_dir / f"processed_shot_{shot_num}.mp4"
            cmd_shot = [
                FFMPEG_BIN, "-y",
                "-i", str(v_path),
                "-i", str(full_shot_audio),
                "-filter_complex", f"[0:v]{vf_str}[v];[1:a]{af_str}[a]",
                "-map", "[v]",
                "-map", "[a]",
                "-c:v", "libx264", "-r", "24", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                "-t", f"{target_dur:.3f}",
                str(shot_out_mp4)
            ]
            subprocess.run(cmd_shot, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processed_clips.append(shot_out_mp4)

        # 6. 使用 filter_complex 逐帧无缝拼接所有分镜
        if progress_callback:
            progress_callback("正在拼接合流全片", 0.85)

        filter_inputs = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(len(processed_clips)))
        filter_str = f"{filter_inputs}concat=n={len(processed_clips)}:v=1:a=1[vcat][acat]"

        concatenated_video = work_dir / "concatenated.mp4"
        cmd_concat = [FFMPEG_BIN, "-y"]
        for clip in processed_clips:
            cmd_concat.extend(["-i", str(clip)])
        cmd_concat.extend([
            "-filter_complex", filter_str,
            "-map", "[vcat]",
            "-map", "[acat]",
            "-c:v", "libx264", "-r", "24", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            str(concatenated_video)
        ])
        subprocess.run(cmd_concat, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        total_dur = _get_media_duration(concatenated_video)

        # 7. 背景音乐混流处理 (可选)
        if enable_bgm and music_path and Path(music_path).is_file():
            if progress_callback:
                progress_callback("正在混流背景音乐", 0.95)
            music_path = Path(music_path).resolve()
            bgm_filter = (
                f"[1:a]volume={music_volume},"
                f"afade=t=in:st=0:d=1,"
                f"afade=t=out:st={max(0, total_dur - 2.5):.2f}:d=2.5,"
                f"aformat=sample_rates=44100:channel_layouts=stereo[bgm];"
                f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            )
            cmd_mix = [
                FFMPEG_BIN, "-y",
                "-i", str(concatenated_video),
                "-i", str(music_path),
                "-filter_complex", bgm_filter,
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                "-t", f"{total_dur:.3f}",
                str(output_path)
            ]
            subprocess.run(cmd_mix, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            # 纯净模式: 直接输出
            shutil.copy(concatenated_video, output_path)

        if not output_path.is_file():
            raise RuntimeError(f"成片文件输出失败: {output_path}")

        final_dur = _get_media_duration(output_path)
        final_size_mb = output_path.stat().st_size / (1024 * 1024)

        logger.info(f"✅ 分镜头智能合流完成: {output_path.name} ({final_dur:.1f}s, {final_size_mb:.2f} MB)")
        return {
            "output": str(output_path),
            "duration": round(final_dur, 2),
            "size_mb": round(final_size_mb, 2),
            "shot_count": num_shots,
        }

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
