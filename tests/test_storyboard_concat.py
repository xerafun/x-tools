"""
分镜头智能拼接与字幕配音单元测试
"""
import json
from pathlib import Path

import pytest

from tools.concat.script_parser import (
    parse_storyboard_script,
    split_sentences_for_subtitles,
)
from tools.concat.storyboard_concat import (
    _format_ass_timestamp,
    get_default_chinese_font,
)


def test_split_sentences_basic():
    """测试基本标点断句"""
    text = (
        "商品实物交收，现场货物查验、移库点交，成本高、效率低；"
        "标准化可流转电子仓单，以仓单背书转让替代实物交付。"
        "两种交付法律地位一样，成本效率差异巨大。"
    )
    sentences = split_sentences_for_subtitles(text, max_len=30)
    assert len(sentences) >= 3
    assert "商品实物交收" in sentences[0]
    assert "标准化可流转电子仓单" in sentences[1]
    assert "两种交付法律地位一样" in sentences[2]


def test_split_sentences_empty():
    """测试空文本处理"""
    assert split_sentences_for_subtitles("") == []
    assert split_sentences_for_subtitles("   \n\t  ") == []


def test_format_ass_timestamp():
    """测试 ASS 时间戳格式化"""
    assert _format_ass_timestamp(0.0) == "0:00:00.00"
    assert _format_ass_timestamp(1.5) == "0:00:01.50"
    assert _format_ass_timestamp(65.25) == "0:01:05.25"
    assert _format_ass_timestamp(3661.12) == "1:01:01.12"
    assert _format_ass_timestamp(-5.0) == "0:00:00.00"


def test_get_default_chinese_font():
    """测试字体自动探测"""
    font = get_default_chinese_font()
    assert isinstance(font, str)
    assert len(font) > 0


def test_parse_storyboard_txt(tmp_path: Path):
    """测试解析纯文本脚本"""
    txt_content = """
分镜1: 实物交收
商品实物交收，现场货物查验，成本高效率低。

分镜2: 电子仓单
标准化可流转电子仓单，以背书转让替代交付。

分镜3: 交付结算
钱货两讫，完成同步闭环。
"""
    txt_file = tmp_path / "script.txt"
    txt_file.write_text(txt_content, encoding="utf-8")

    shots = parse_storyboard_script(txt_file)
    assert len(shots) == 3
    assert shots[0]["id"] == 1
    assert "商品实物交收" in shots[0]["narration"]
    assert shots[1]["id"] == 2
    assert "标准化可流转电子仓单" in shots[1]["narration"]
    assert shots[2]["id"] == 3
    assert "钱货两讫" in shots[2]["narration"]


def test_parse_storyboard_json(tmp_path: Path):
    """测试解析 JSON 脚本"""
    json_data = [
        {"id": 1, "narration": "第一镜头解说内容"},
        {"id": 2, "narration": "第二镜头解说内容"},
    ]
    json_file = tmp_path / "script.json"
    json_file.write_text(json.dumps(json_data, ensure_ascii=False), encoding="utf-8")

    shots = parse_storyboard_script(json_file)
    assert len(shots) == 2
    assert shots[0]["narration"] == "第一镜头解说内容"
    assert len(shots[0]["sentences"]) == 1
    assert shots[1]["narration"] == "第二镜头解说内容"


def test_parse_storyboard_nonexistent():
    """测试不存在的文件报错"""
    with pytest.raises(FileNotFoundError):
        parse_storyboard_script(Path("/nonexistent/path/to/script.docx"))
