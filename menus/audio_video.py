"""BGM 与拼接菜单"""
from pathlib import Path

from InquirerPy import inquirer
from InquirerPy.base.control import Choice

from menus._prompts import confirm_action


def _prompt_bgm_options() -> tuple[str, float, bool]:
    from tools.concat.ffmpeg_concat import get_available_music

    available_music = get_available_music()

    music_choices = []
    if available_music:
        for m in available_music:
            music_choices.append(Choice(str(m), f"🎵 {m.stem}"))
    music_choices.append(Choice("custom", "📂 指定音乐文件路径"))

    music_choice = inquirer.select(
        message="选择背景音乐:",
        choices=music_choices,
    ).execute()

    if music_choice == "custom":
        music_path = inquirer.filepath(
            message="音乐文件路径:",
            validate=lambda x: Path(x).is_file(),
        ).execute()
    else:
        music_path = music_choice

    music_volume = float(inquirer.text(message="音乐音量 (0.0~1.0):", default="0.3").execute())
    keep_audio = inquirer.confirm(message="是否保留原视频声音 (混合)?", default=False).execute()
    return music_path, music_volume, keep_audio


def menu_add_bgm(videos: list[Path]):
    """添加背景音乐菜单"""
    from tools.bgm.ffmpeg_bgm import add_bgm_to_video

    if not videos:
        print("❌ 未找到视频文件")
        return

    if len(videos) > 1:
        video_choice = inquirer.select(
            message="选择要添加背景音乐的视频:",
            choices=[Choice(str(v), v.name) for v in videos],
        ).execute()
        video_path = Path(video_choice)
    else:
        video_path = videos[0]

    music_path, music_volume, keep_audio = _prompt_bgm_options()

    # 音频淡入淡出
    audio_fade_choice = inquirer.select(
        message="是否进行音频淡入淡出?",
        choices=[
            Choice("0", "🔊 不处理"),
            Choice("1.0", "🔉 1 秒"),
            Choice("2.0", "🔉 2 秒 (推荐)"),
            Choice("3.0", "🔉 3 秒"),
            Choice("custom", "✏️  自定义"),
        ],
        default="2.0",
    ).execute()

    audio_fade_in = 0.0
    audio_fade_out = 0.0
    if audio_fade_choice == "custom":
        audio_fade_in = float(inquirer.text(message="音频首部淡入 (秒):").execute())
        audio_fade_out = float(inquirer.text(message="音频尾部淡出 (秒):").execute())
    else:
        audio_fade_in = audio_fade_out = float(audio_fade_choice)

    if confirm_action("确认添加背景音乐?"):
        add_bgm_to_video(
            video_path=video_path,
            music_path=music_path,
            music_volume=music_volume,
            keep_original_audio=keep_audio,
            audio_fade_in=audio_fade_in,
            audio_fade_out=audio_fade_out,
        )


def _handle_storyboard_concat(videos: list[Path]):
    """处理分镜智能合成流程 (拼接 + AI配音 + 逐句同步字幕)"""
    import os
    import socket

    from tools.concat.script_parser import parse_storyboard_script
    from tools.concat.storyboard_concat import compose_storyboard_video
    from tools.subtitle.tts_dubbing import TTS_VOICES

    print(f"\n已选择 {len(videos)} 个分镜视频:")
    for i, v in enumerate(videos, 1):
        print(f"  分镜 {i}: {v.name}")
    print()

    # 1. 脚本台词输入
    script_mode = inquirer.select(
        message="分镜台词脚本来源:",
        choices=[
            Choice("file", "📂 选择脚本文件 (.docx / .txt / .json / .md)"),
            Choice("manual", "✍️  在终端逐镜录入台词"),
        ],
        default="file",
    ).execute()

    shots_data = []
    if script_mode == "file":
        script_path_str = inquirer.filepath(
            message="脚本文件路径:",
            validate=lambda x: Path(x).is_file(),
        ).execute()
        try:
            shots_data = parse_storyboard_script(script_path_str)
            print(f"✅ 成功解析 {len(shots_data)} 个分镜台词")
        except Exception as e:
            print(f"❌ 脚本解析失败: {e}")
            return
    else:
        print("\n请依次输入各分镜头的解说台词 (回车确认):")
        for i, v in enumerate(videos, 1):
            narration = inquirer.text(message=f"分镜 {i} ({v.name}) 台词:").execute().strip()
            if not narration:
                narration = "无"
            shots_data.append({"id": i, "narration": narration})

    # 2. 选择配音角色
    voice_choices = [
        Choice(info["voice"], info["name"]) for info in TTS_VOICES.values()
    ]
    selected_voice = inquirer.select(
        message="选择配音角色:",
        choices=voice_choices,
        default="zh-CN-YunyangNeural",
    ).execute()

    # 3. 代理配置 (自动检测 7890 端口)
    detected_proxy = os.environ.get("https_proxy") or os.environ.get("http_proxy")
    if not detected_proxy:
        # 探测本地 7890 端口是否开放
        try:
            with socket.create_connection(("127.0.0.1", 7890), timeout=0.5):
                detected_proxy = "http://127.0.0.1:7890"
        except OSError:
            detected_proxy = None

    proxy_choice = inquirer.select(
        message="Edge-TTS 网络代理:",
        choices=[
            Choice("http://127.0.0.1:7890", "🌐 使用本地代理 (http://127.0.0.1:7890, 推荐)"),
            Choice("none", "🚫 直连 (不使用代理)"),
            Choice("custom", "✏️  自定义代理地址"),
        ],
        default="http://127.0.0.1:7890" if detected_proxy else "none",
    ).execute()

    proxy_url = None
    if proxy_choice == "custom":
        proxy_url = inquirer.text(message="代理地址 (例如 http://127.0.0.1:7890):").execute().strip()
    elif proxy_choice != "none":
        proxy_url = proxy_choice

    # 4. 背景音乐选项 (默认纯净模式)
    bgm_enabled = inquirer.confirm(message="是否添加背景音乐 (BGM)?", default=False).execute()
    music_path = None
    music_volume = 0.12
    if bgm_enabled:
        music_path, music_volume, _ = _prompt_bgm_options()

    # 5. 水印去除选项 (针对特定分镜)
    delogo_map = {}
    need_delogo = inquirer.confirm(
        message="是否需要对特定分镜头进行局部去水印 (如片尾 AI 水印)?",
        default=False
    ).execute()

    if need_delogo:
        shot_choices = [Choice(i, f"分镜 {i}: {v.name}") for i, v in enumerate(videos, 1)]
        delogo_shot_idx = inquirer.select(
            message="选择包含水印的分镜:",
            choices=shot_choices,
            default=len(videos),
        ).execute()
        delogo_pos = inquirer.select(
            message="水印位置预设:",
            choices=[
                Choice((1080, 665, 185, 45), "右下角标准角标 (185x45，如豆包AI水印)"),
                Choice("custom", "自定义坐标与宽高 (x, y, w, h)"),
            ],
            default=(1080, 665, 185, 45),
        ).execute()

        if delogo_pos == "custom":
            coords_str = inquirer.text(message="输入坐标 x,y,w,h (例如 1080,665,185,45):").execute()
            parts = [int(p.strip()) for p in coords_str.split(",")]
            delogo_map[delogo_shot_idx] = (parts[0], parts[1], parts[2], parts[3])
        else:
            delogo_map[delogo_shot_idx] = delogo_pos

    if confirm_action(f"确认开始对 {len(videos)} 个分镜头进行智能合成?"):
        print("\n⏳ 正在执行分镜头智能合成流水线，请稍候...")
        result = compose_storyboard_video(
            video_paths=videos,
            script_source=shots_data,
            voice=selected_voice,
            proxy=proxy_url,
            enable_bgm=bgm_enabled,
            music_path=music_path,
            music_volume=music_volume,
            delogo_map=delogo_map,
        )
        print("\n🎉 分镜智能合成完成!")
        print(f"   输出路径: {result['output']}")
        print(f"   成片时长: {result['duration']:.1f} 秒 | 文件大小: {result['size_mb']} MB\n")


def menu_concat(videos: list[Path]):
    """拼接视频菜单"""
    from tools.concat.ffmpeg_concat import TRANSITION_PRESETS, concat_videos

    if len(videos) < 2:
        print("❌ 拼接需要至少 2 个视频")
        return

    # 模式选择: 普通拼接 vs 分镜智能合成
    mode = inquirer.select(
        message="选择拼接模式:",
        choices=[
            Choice("storyboard", "🎙️ 分镜智能合成 (拼接 + AI配音 + 逐句同步字幕 · 推荐)"),
            Choice("normal", "⏩ 普通物理拼接 (仅画面拼接 / 转场 / BGM)"),
        ],
        default="storyboard",
    ).execute()

    if mode == "storyboard":
        _handle_storyboard_concat(videos)
        return

    print(f"\n将按以下顺序拼接 {len(videos)} 个视频:")
    
    for i, v in enumerate(videos, 1):
        print(f"  {i}. {v.name}")
    print()

    # 过渡效果
    transition_choices = [
        Choice(key, preset["name"]) for key, preset in TRANSITION_PRESETS.items()
    ]
    transition = inquirer.select(
        message="过渡效果:",
        choices=transition_choices,
        default="none",
    ).execute()

    transition_duration = 1.0
    if transition != "none":
        transition_duration = float(inquirer.text(message="过渡时长 (秒):", default="1").execute())

    # 音频过渡 (避免接缝爆音) 或静音
    mute_audio = False
    audio_fade_choice = inquirer.select(
        message="如何处理音频?",
        choices=[
            Choice("2.0", "🔉 默认 (保留原声，平滑过渡 2 秒，推荐)"),
            Choice("0", "🔊 保持原声不变 (直接拼接)"),
            Choice("1.0", "🔉 平滑过渡 1 秒"),
            Choice("3.0", "🔉 平滑过渡 3 秒"),
            Choice("custom", "✏️  自定义过渡"),
            Choice("mute", "🔇 消除原声 (静音输出)"),
        ],
        default="2.0",
    ).execute()
    
    audio_fade_in = 0.0
    audio_fade_out = 0.0
    if audio_fade_choice == "mute":
        mute_audio = True
    elif audio_fade_choice == "custom":
        audio_fade_in = float(inquirer.text(message="音频首部淡入 (秒):").execute())
        audio_fade_out = float(inquirer.text(message="音频尾部淡出 (秒):").execute())
    else:
        audio_fade_in = audio_fade_out = float(audio_fade_choice)

    if inquirer.confirm(message=f"确认拼接 {len(videos)} 个视频?", default=True).execute():
        concat_videos(
            video_paths=videos,
            transition=transition,
            transition_duration=transition_duration,
            audio_fade_in=audio_fade_in,
            audio_fade_out=audio_fade_out,
            mute_audio=mute_audio,
        )
