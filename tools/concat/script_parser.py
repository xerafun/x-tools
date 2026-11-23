"""
分镜头脚本解析器 (Script Parser)

支持格式:
  1. .docx (无需第三方库，基于标准库 zipfile + XML 解析表格与段落)
  2. .txt (支持空行分段，或分镜序号标记如 '分镜1', 'Shot 1', '旁白:')
  3. .json (结构化数组: [{"id": 1, "narration": "..."}, ...])
"""
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


def split_sentences_for_subtitles(text: str, max_len: int = 30) -> list[str]:
    """
    将长段解说词按标点符号切分为适合字幕展示与配音的断句 (10~30 字/句)
    """
    text = text.strip()
    if not text:
        return []

    # 按句号、分号、问号、感叹号主切分
    raw_parts = re.split(r"([；。！？\n]+)", text)
    sentences = []
    current = ""

    for part in raw_parts:
        if not part:
            continue
        if re.match(r"^[；。！？\n]+$", part):
            current += part
            if current.strip():
                sentences.append(current.strip())
            current = ""
        else:
            current += part

    if current.strip():
        sentences.append(current.strip())

    # 对仍然过长 (> max_len) 的长句，按逗号进一步切分
    refined_sentences = []
    for s in sentences:
        if len(s) > max_len and "，" in s:
            sub_parts = re.split(r"(，)", s)
            sub_curr = ""
            for sp in sub_parts:
                if sp == "，":
                    sub_curr += sp
                    if len(sub_curr) >= 12:
                        refined_sentences.append(sub_curr)
                        sub_curr = ""
                else:
                    sub_curr += sp
            if sub_curr.strip():
                refined_sentences.append(sub_curr.strip())
        else:
            refined_sentences.append(s)

    return [s for s in refined_sentences if s.strip()]


def _parse_docx_script(docx_path: Path) -> list[dict]:
    """使用标准库 zipfile 解析 docx 文档中的分镜表格与台词"""
    shots = []
    with zipfile.ZipFile(docx_path) as z:
        if "word/document.xml" not in z.namelist():
            raise ValueError(f"无效的 docx 文件: {docx_path}")
        xml_content = z.read("word/document.xml")

    tree = ET.fromstring(xml_content)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

    # 1. 尝试从表格行中提取
    rows = []
    for tr in tree.iter(f"{{{ns['w']}}}tr"):
        cells = []
        for tc in tr.iter(f"{{{ns['w']}}}tc"):
            texts = [t.text for t in tc.iter(f"{{{ns['w']}}}t") if t.text]
            cells.append("".join(texts).strip())
        if cells:
            rows.append(cells)

    current_shot_id = 1
    for r in rows:
        if len(r) >= 2:
            col0 = r[0]
            col1 = r[1]
            if "旁白" in col0 or "台词" in col0 or "解说" in col0:
                narration = col1.strip()
                if narration and narration != "无":
                    shots.append({
                        "id": current_shot_id,
                        "narration": narration,
                        "sentences": split_sentences_for_subtitles(narration),
                    })
                    current_shot_id += 1

    # 2. 如果表格未命中，从正文段落解析
    if not shots:
        paragraphs = []
        for p in tree.iter(f"{{{ns['w']}}}p"):
            texts = [t.text for t in p.iter(f"{{{ns['w']}}}t") if t.text]
            p_text = "".join(texts).strip()
            if p_text:
                paragraphs.append(p_text)
        return _parse_text_blocks(paragraphs)

    return shots


def _parse_text_blocks(blocks: list[str]) -> list[dict]:
    """从文本段落列表中解析分镜头"""
    shots = []
    shot_id = 1
    i = 0
    while i < len(blocks):
        b = blocks[i].strip()
        lines = [line.strip() for line in b.splitlines() if line.strip()]
        if not lines:
            i += 1
            continue

        first_line = lines[0]
        match = re.match(r"^(?:分镜|镜头|Shot|Scene)\s*(\d+)?[：:｜|\s]*(.*)", first_line, re.IGNORECASE)

        if match:
            # 如果第一行匹配了分镜标题，后面的行就是台词
            if len(lines) > 1:
                narration = " ".join(lines[1:])
            elif i + 1 < len(blocks) and not re.match(
                r"^(?:分镜|镜头|Shot|Scene)", blocks[i + 1].strip(), re.IGNORECASE
            ):
                narration = blocks[i + 1].strip()
                i += 1
            else:
                narration = match.group(2).strip()

            if narration:
                shots.append({
                    "id": shot_id,
                    "narration": narration,
                    "sentences": split_sentences_for_subtitles(narration),
                })
                shot_id += 1
        elif len(b) >= 8:  # 普通段落直接视作分镜台词
            shots.append({
                "id": shot_id,
                "narration": b,
                "sentences": split_sentences_for_subtitles(b),
            })
            shot_id += 1
        i += 1
    return shots


def _parse_txt_file(txt_path: Path) -> list[dict]:
    """解析纯文本文件"""
    content = txt_path.read_text(encoding="utf-8", errors="replace")
    # 先按双换行切分段落
    raw_blocks = [b.strip() for b in re.split(r"\n\s*\n+", content) if b.strip()]
    if not raw_blocks:
        raw_blocks = [line.strip() for line in content.splitlines() if line.strip()]
    return _parse_text_blocks(raw_blocks)


def _parse_json_file(json_path: Path) -> list[dict]:
    """解析 JSON 文件"""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "shots" in data:
        data = data["shots"]

    shots = []
    for idx, item in enumerate(data, 1):
        narration = item.get("narration") or item.get("text") or item.get("content") or ""
        shots.append({
            "id": item.get("id", idx),
            "narration": narration,
            "sentences": item.get("sentences") or split_sentences_for_subtitles(narration),
        })
    return shots


def parse_storyboard_script(script_path: str | Path) -> list[dict]:
    """
    通用分镜头脚本解析入口

    Args:
        script_path: 脚本文件路径 (.docx, .txt, .json)

    Returns:
        list[dict]: [{"id": 1, "narration": "...", "sentences": ["...", "..."]}, ...]
    """
    script_path = Path(script_path)
    if not script_path.is_file():
        raise FileNotFoundError(f"脚本文件不存在: {script_path}")

    suffix = script_path.suffix.lower()
    if suffix == ".docx":
        return _parse_docx_script(script_path)
    elif suffix == ".json":
        return _parse_json_file(script_path)
    elif suffix in (".txt", ".md"):
        return _parse_txt_file(script_path)
    else:
        # 尝试按文本文件读取
        return _parse_txt_file(script_path)
