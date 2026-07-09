from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

import base64
import binascii
from io import BytesIO
from pathlib import Path
import html
import json
import os
import re
import tempfile
import time
import uuid

import aiohttp
from bs4 import BeautifulSoup
from PIL import Image as PILImage

from .utils import fetch_hextech_data_from_url


@register("hextech", "Payne", "海克斯乱斗信息差", "0.0.1")
class MyPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        self.hero_data = []
        self._load_hero_data()
        self.hextech_data = None
        self.last_fetch_time = 0

    def _load_hero_data(self):
        try:
            curr_dir = os.path.dirname(os.path.abspath(__file__))
            json_path = os.path.join(curr_dir, "herolist.json")
            if os.path.exists(json_path):
                with open(json_path, "r", encoding="utf-8") as f:
                    self.hero_data = json.load(f)
                logger.info(f"成功加载 {len(self.hero_data)} 个英雄数据")
            else:
                logger.warning(f"未找到英雄数据文件: {json_path}")
        except Exception as e:
            logger.error(f"加载英雄数据失败: {e}")

    async def initialize(self):
        pass

    def _find_hero_local(self, query: str) -> dict:
        if not self.hero_data:
            return None

        query = query.lower().strip()
        fuzzy_match = None

        for hero in self.hero_data:
            zh_name = hero.get("name", {}).get("zh", "").lower()
            en_name = hero.get("name", {}).get("en", "").lower()
            title_zh = hero.get("title", {}).get("zh", "").lower()
            title_en = hero.get("title", {}).get("en", "").lower()
            hero_id = hero.get("id", "").lower()

            if (
                zh_name == query
                or en_name == query
                or title_zh == query
                or title_en == query
                or hero_id == query
            ):
                return hero

            if not fuzzy_match and (
                query in zh_name
                or query in en_name
                or query in title_zh
                or query in title_en
            ):
                fuzzy_match = hero

        return fuzzy_match

    async def _get_hextech_data(self):
        current_time = time.time()
        if self.hextech_data and (current_time - self.last_fetch_time < 3600):
            return self.hextech_data

        try:
            data = await fetch_hextech_data_from_url()
            if data:
                self.hextech_data = data
                self.last_fetch_time = current_time
                logger.info(f"成功更新 {len(data)} 条海克斯数据")
                return data
            logger.warning("获取海克斯数据失败，尝试使用旧数据")
            return self.hextech_data
        except Exception as e:
            logger.error(f"获取海克斯数据异常: {e}")
            return self.hextech_data

    @filter.command("海克斯")
    async def search_hextech(self, event: AstrMessageEvent, query: str = ""):
        async for result in self._handle_search_hextech(event, query=query):
            yield result

    @filter.command("海斗")
    async def haidou(self, event: AstrMessageEvent, hero_name: str = ""):
        async for result in self._handle_haidou(event, hero_name=hero_name):
            yield result

    @staticmethod
    def _detect_intent(raw_text: str):
        if not raw_text or not raw_text.startswith("/"):
            return None, ""
        m = re.match(r"^/(海克斯)\s*(.*)", raw_text)
        if m:
            return "hextech", m.group(2).strip()
        m = re.match(r"^/(海斗)\s*(.*)", raw_text)
        if m:
            return "haidou", m.group(2).strip()
        return None, ""

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def listen_plain_messages(self, event: AstrMessageEvent):
        raw_text = (event.message_str or "").strip()
        intent, arg = self._detect_intent(raw_text)
        if not intent:
            return

        logger.info(f"hextech passive listener matched intent: {intent}")
        if intent == "hextech":
            async for result in self._handle_search_hextech(event, query=arg):
                yield result
        elif intent == "haidou":
            async for result in self._handle_haidou(event, hero_name=arg):
                yield result

    async def _handle_search_hextech(self, event: AstrMessageEvent, query: str = ""):
        if not query:
            yield event.plain_result("请输入要查询的海克斯名称，例如：/海克斯 利刃华尔兹")
            return

        yield event.plain_result(f"🔍 正在查询海克斯【{query}】...")

        hextechs = await self._get_hextech_data()
        if not hextechs:
            yield event.plain_result("无法获取海克斯数据，请稍后再试。")
            return

        query = query.lower().strip()
        matched = []

        for h in hextechs:
            zh_name = h.get("name", {}).get("zh", "")
            en_name = h.get("name", {}).get("en", "")
            if query in zh_name or query in en_name.lower():
                matched.append(h)

        if not matched:
            yield event.plain_result(f"未找到海克斯: {query}")
            return

        if len(matched) > 5:
            yield event.plain_result(
                f"找到 {len(matched)} 个相关海克斯，请提供更精确的名称。显示前 5 个结果："
            )
            matched = matched[:5]

        result_msg = []
        for h in matched:
            zh_name = h.get("name", {}).get("zh", "未知")
            en_name = h.get("name", {}).get("en", "")
            tier = h.get("tier", "Unknown")
            desc_zh = h.get("description", {}).get("zh", "")
            desc_clean = BeautifulSoup(desc_zh, "html.parser").get_text()

            tier_map = {"Prismatic": "棱彩阶", "Gold": "黄金阶", "Silver": "白银阶"}
            tier_zh = tier_map.get(tier, tier)

            emoji = "🔸"
            if tier == "Prismatic":
                emoji = "💎"
            elif tier == "Gold":
                emoji = "🌟"
            elif tier == "Silver":
                emoji = "⚪"

            msg = f"{emoji} **{zh_name}** ({tier_zh})\n"
            if en_name:
                msg += f"   EN: {en_name}\n"
            msg += f"   📝 {desc_clean}"

            mechanism = h.get("mechanism")
            if mechanism:
                mech_zh = mechanism.get("zh", "")
                if mech_zh:
                    mech_clean = BeautifulSoup(mech_zh, "html.parser").get_text()
                    msg += f"\n\n   ⚠️ **特殊机制**:\n   {mech_clean}"

            result_msg.append(msg)

        yield event.plain_result("\n\n".join(result_msg))

    async def _fetch_hero_page_html(self, hero_id: str) -> str | None:
        url = f"https://apexlol.info/zh/champions/{hero_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        }
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"获取英雄页面失败: HTTP {response.status}, url={url}")
                        return None
                    return await response.text()
        except Exception as e:
            logger.error(f"获取英雄页面异常: {e}")
            return None

    @staticmethod
    def _clean_text(raw: str) -> str:
        if not raw:
            return ""
        text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _make_abs_url(url: str) -> str:
        if not url:
            return ""
        if url.startswith("http://") or url.startswith("https://"):
            return url
        if url.startswith("//"):
            return f"https:{url}"
        if url.startswith("/"):
            return f"https://apexlol.info{url}"
        return f"https://apexlol.info/{url.lstrip('/')}"

    def _parse_hero_profile(self, soup: BeautifulSoup) -> str:
        selectors = [
            ".champion-intro",
            ".hero-intro",
            ".champion-description",
            ".hero-description",
            ".champion-overview p",
            ".hero-overview p",
            ".prose p",
        ]
        for selector in selectors:
            node = soup.select_one(selector)
            if not node:
                continue
            text = self._clean_text(str(node))
            if len(text) >= 20:
                return text

        for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
            heading_text = self._clean_text(heading.get_text())
            if not heading_text:
                continue
            if "介绍" in heading_text or "简介" in heading_text or "背景" in heading_text:
                parent = heading.parent
                if not parent:
                    continue
                paragraph = parent.find("p")
                if paragraph:
                    text = self._clean_text(str(paragraph))
                    if len(text) >= 20:
                        return text

        paragraphs = soup.find_all("p")
        best = ""
        for p in paragraphs:
            text = self._clean_text(str(p))
            if len(text) > len(best):
                best = text
        return best[:400] if best else "暂无英雄介绍。"

    def _parse_hero_skills(self, soup: BeautifulSoup) -> list[dict]:
        slot_keywords = {
            "PASSIVE": ["被动", "passive", "p:", "p ", " p"],
            "Q": [" q", "q:", "q ", "技能q", "q技能"],
            "W": [" w", "w:", "w ", "技能w", "w技能"],
            "E": [" e", "e:", "e ", "技能e", "e技能"],
            "R": [" r", "r:", "r ", "技能r", "r技能", "ultimate", "大招"],
        }

        candidate_nodes = []
        selectors = [
            ".skill-card",
            ".ability-card",
            ".champion-skill",
            ".skills .card",
            ".abilities .card",
            "[class*='skill']",
            "[class*='ability']",
        ]
        for selector in selectors:
            candidate_nodes.extend(soup.select(selector))

        if not candidate_nodes:
            candidate_nodes = soup.find_all(["article", "li", "div"])

        parsed = []
        seen = set()

        for node in candidate_nodes:
            img = node.find("img")
            if not img:
                continue

            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
            icon_url = self._make_abs_url(src)
            if not icon_url:
                continue

            key_node = node.select_one(".skill-key, .ability-key, .key, .badge, .slot")
            name_node = node.select_one(
                ".skill-name, .ability-name, .name, h3, h4, strong, .title"
            )
            desc_node = node.select_one(
                ".skill-desc, .ability-desc, .description, .note, p"
            )

            key_text = self._clean_text(key_node.get_text() if key_node else "")
            name = self._clean_text(name_node.get_text() if name_node else img.get("alt", ""))
            desc = self._clean_text(desc_node.get_text() if desc_node else "")
            full_text = f" {key_text} {name} {desc} ".lower()

            slot = ""
            if "被动" in full_text or "passive" in full_text:
                slot = "PASSIVE"
            else:
                for candidate_slot, words in slot_keywords.items():
                    if candidate_slot == "PASSIVE":
                        continue
                    if any(word in full_text for word in words):
                        slot = candidate_slot
                        break

            dedupe_key = f"{slot}|{name}|{icon_url}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            parsed.append(
                {
                    "slot": slot,
                    "name": name or "未知技能",
                    "desc": desc or "暂无描述",
                    "icon": icon_url,
                }
            )

        slots = {"PASSIVE": None, "Q": None, "W": None, "E": None, "R": None}
        unknown = []

        for item in parsed:
            slot = item.get("slot", "")
            if slot in slots and slots[slot] is None:
                slots[slot] = item
            else:
                unknown.append(item)

        fill_order = ["PASSIVE", "Q", "W", "E", "R"]
        unknown_idx = 0
        for slot in fill_order:
            if slots[slot] is None and unknown_idx < len(unknown):
                item = unknown[unknown_idx]
                item["slot"] = slot
                slots[slot] = item
                unknown_idx += 1

        result = []
        for slot in fill_order:
            item = slots.get(slot)
            if not item:
                continue
            item["slot_label"] = "被动" if slot == "PASSIVE" else slot
            result.append(item)

        logger.info(f"技能解析结果: total_candidates={len(parsed)}, resolved={len(result)}")
        return result

    def _parse_hextech_interactions(self, soup: BeautifulSoup, limit: int = 10) -> list[dict]:
        cards = soup.select(".interaction-card")
        result = []
        for card in cards:
            if len(card.select(".hex-name")) > 1:
                continue

            tier_elem = card.select_one(".hex-tier")
            name_elem = card.select_one(".hex-name")
            rating_elem = card.select_one(".rating-badge")
            note_elem = card.select_one(".note")
            icon_elem = card.select_one(
                ".hex-icon img, .hex-icon-image, .hex-img img, .hex-image img, img"
            )

            name = self._clean_text(name_elem.get_text() if name_elem else "")
            if not name:
                continue

            rating = self._clean_text(rating_elem.get_text() if rating_elem else "")
            tier = self._clean_text(tier_elem.get_text() if tier_elem else "")
            note = self._clean_text(note_elem.get_text() if note_elem else "")
            icon_raw = ""
            if icon_elem:
                icon_raw = (
                    icon_elem.get("src")
                    or icon_elem.get("data-src")
                    or icon_elem.get("data-lazy-src")
                    or ""
                )
            icon = self._make_abs_url(icon_raw)

            result.append(
                {
                    "name": name,
                    "rating": rating or "-",
                    "tier": tier or "未知",
                    "note": note or "暂无说明",
                    "icon": icon,
                }
            )
            if len(result) >= limit:
                break

        logger.info(f"海克斯联动解析结果: cards={len(cards)}, kept={len(result)}")
        return result


    @staticmethod
    def _resolve_output_dir() -> Path | None:
        for candidate in (Path("/AstrBot/data/temp"), Path("/AstrBot/data/cache")):
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate
            except Exception:
                continue
        return None

    def _write_temp_image(self, image_bytes: bytes, suffix: str = ".png") -> str | None:
        if not image_bytes:
            return None
        shared_dir = self._resolve_output_dir()
        if shared_dir is not None:
            temp_path = shared_dir / f"hextech_report_{uuid.uuid4().hex}{suffix}"
            temp_path.write_bytes(image_bytes)
            return os.fspath(temp_path)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(image_bytes)
            return temp_file.name

    @staticmethod
    def _preview_invalid_bytes(image_bytes: bytes, limit: int = 160) -> str:
        preview = image_bytes[:limit]
        try:
            text = preview.decode("utf-8", errors="ignore").strip()
        except Exception:
            text = ""
        if text:
            return text.replace("\n", " ")
        return preview.hex()

    def _normalize_image_bytes(self, image_bytes: bytes, source: str = "bytes") -> bytes | None:
        if not image_bytes:
            return None
        try:
            with PILImage.open(BytesIO(image_bytes)) as image:
                image.load()
                if image.mode not in ("RGB", "RGBA", "L"):
                    image = image.convert("RGBA")
                elif image.mode == "L":
                    image = image.convert("RGBA")
                output = BytesIO()
                image.save(output, format="PNG", optimize=True)
                normalized_bytes = output.getvalue()
                logger.info(
                    "hextech report image normalized from %s: format=%s size=%sx%s bytes=%s",
                    source,
                    image.format,
                    image.size[0],
                    image.size[1],
                    len(normalized_bytes),
                )
                return normalized_bytes
        except Exception as exc:
            logger.warning(
                "hextech report image is invalid from %s: %s; preview=%s",
                source,
                exc,
                self._preview_invalid_bytes(image_bytes),
            )
            return None

    def _normalize_image_path(self, file_path: str) -> str | None:
        if not file_path or not os.path.exists(file_path):
            return None
        try:
            with open(file_path, "rb") as file:
                image_bytes = file.read()
        except Exception as exc:
            logger.warning(f"读取图片文件失败: {file_path}, error={exc}")
            return None
        normalized_bytes = self._normalize_image_bytes(image_bytes, source=file_path)
        if not normalized_bytes:
            return None
        return self._write_temp_image(normalized_bytes, ".png")

    def _materialize_render_result(self, image_data, render_type: str) -> str | None:
        if isinstance(image_data, bytes):
            normalized_bytes = self._normalize_image_bytes(
                image_data, source=f"render:{render_type}:bytes"
            )
            if normalized_bytes:
                return self._write_temp_image(normalized_bytes, ".png")
            return None

        if isinstance(image_data, str):
            if image_data.startswith("base64://"):
                try:
                    raw_bytes = base64.b64decode(image_data.removeprefix("base64://"))
                except (ValueError, binascii.Error) as exc:
                    logger.warning(f"解析 base64 图片失败: render_type={render_type}, error={exc}")
                    return None
                normalized_bytes = self._normalize_image_bytes(
                    raw_bytes,
                    source=f"render:{render_type}:base64",
                )
                if normalized_bytes:
                    return self._write_temp_image(normalized_bytes, ".png")
                return None
            if image_data.startswith("file:///"):
                file_path = "/" + image_data.removeprefix("file:///").lstrip("/")
                return self._normalize_image_path(file_path)
            if os.path.exists(image_data):
                return self._normalize_image_path(image_data)
            logger.warning(
                f"图片渲染返回了无法识别的字符串结果: render_type={render_type}, value={image_data[:200]}"
            )
            return None

        logger.warning(
            f"图片渲染返回了不支持的结果类型: render_type={render_type}, type={type(image_data)}"
        )
        return None

    @staticmethod
    def _rating_class(rating: str) -> str:
        text = (rating or "").upper()
        if "S" in text:
            return "rate-s"
        if "A" in text:
            return "rate-a"
        if "B" in text:
            return "rate-b"
        if "D" in text:
            return "rate-d"
        return "rate-default"

    def _render_hero_report_html(self, payload: dict) -> str:
        hero_name_zh = html.escape(payload.get("hero_name_zh", "未知英雄"))
        hero_name_en = html.escape(payload.get("hero_name_en", ""))
        hero_title = html.escape(payload.get("hero_title", ""))
        intro = html.escape(payload.get("intro", "暂无英雄介绍。"))

        skills_html = []
        for skill in payload.get("skills", []):
            slot = html.escape(skill.get("slot_label", "?"))
            name = html.escape(skill.get("name", "未知技能"))
            desc = html.escape(skill.get("desc", "暂无描述"))
            icon = html.escape(skill.get("icon", ""))
            skills_html.append(
                f"""
                <div class=\"skill-card\">
                  <div class=\"skill-head\">
                    <img src=\"{icon}\" alt=\"{name}\" loading=\"eager\" referrerpolicy=\"no-referrer\" />
                    <div class=\"skill-meta\">
                      <span class=\"slot\">{slot}</span>
                      <span class=\"name\">{name}</span>
                    </div>
                  </div>
                  <div class=\"skill-desc\">{desc}</div>
                </div>
                """
            )

        interactions_html = []
        for item in payload.get("interactions", []):
            rating = html.escape(item.get("rating", "-"))
            tier = html.escape(item.get("tier", "未知"))
            name = html.escape(item.get("name", "未知海克斯"))
            note = html.escape(item.get("note", "暂无说明"))
            icon = html.escape(item.get("icon", ""))
            rating_class = self._rating_class(rating)
            icon_html = (
                f'<img class="hex-icon" src="{icon}" alt="{name}" loading="eager" referrerpolicy="no-referrer" />'
                if icon
                else '<div class="hex-icon placeholder">?</div>'
            )
            interactions_html.append(
                f"""
                <div class=\"hex-card\">
                  <div class=\"hex-top\">
                    {icon_html}
                    <span class=\"rating {rating_class}\">{rating}</span>
                    <span class=\"hex-name\">{name}</span>
                    <span class=\"tier\">{tier}</span>
                  </div>
                  <div class=\"hex-note\">{note}</div>
                </div>
                """
            )

        return f"""
<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
<meta charset=\"UTF-8\" />
<title>Hextech Hero Report</title>
<style>
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  padding: 24px;
  background: #121822;
  font-family: Arial, \"Microsoft YaHei\", sans-serif;
  color: #e8edf5;
}}
.card {{
  width: 1120px;
  margin: 0 auto;
  background: #1a2230;
  border: 1px solid #2d3a4f;
  box-shadow: 0 12px 36px rgba(0,0,0,.35);
}}
.section {{
  padding: 18px 24px;
  border-bottom: 1px solid #2b3648;
}}
.section:last-child {{ border-bottom: none; }}
.title h1 {{ margin: 0; font-size: 30px; color: #f3f6fb; }}
.subtitle {{ margin-top: 8px; font-size: 14px; color: #9eb0cc; }}
.block-title {{
  margin: 0 0 14px 0;
  font-size: 18px;
  color: #dce8ff;
  border-left: 4px solid #5aa8ff;
  padding-left: 10px;
}}
.intro {{
  font-size: 15px;
  line-height: 1.75;
  color: #d9e2f0;
  white-space: pre-wrap;
}}
.skills {{
  display: grid;
  grid-template-columns: repeat(2, minmax(0,1fr));
  gap: 12px;
}}
.skill-card {{
  background: #1f2a3b;
  border: 1px solid #32445e;
  border-radius: 10px;
  padding: 12px;
}}
.skill-head {{
  display: flex;
  align-items: center;
  gap: 12px;
}}
.skill-head img {{
  width: 56px;
  height: 56px;
  object-fit: cover;
  border-radius: 8px;
  border: 1px solid #436084;
  background: #0e1622;
}}
.skill-meta {{ display: flex; flex-direction: column; gap: 4px; }}
.slot {{
  display: inline-block;
  width: fit-content;
  padding: 1px 8px;
  border-radius: 999px;
  background: #2f4360;
  color: #b8d7ff;
  font-size: 12px;
  border: 1px solid #4d6b93;
}}
.name {{ font-size: 16px; font-weight: 700; color: #f0f6ff; }}
.skill-desc {{ margin-top: 8px; font-size: 14px; color: #cfdcf0; line-height: 1.6; }}
.hex-grid {{ display: grid; grid-template-columns: 1fr; gap: 10px; }}
.hex-card {{
  background: #1f2a3b;
  border: 1px solid #32445e;
  border-radius: 10px;
  padding: 10px 12px;
}}
.hex-top {{ display: flex; align-items: center; gap: 10px; }}
.hex-icon {{
  width: 34px;
  height: 34px;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid #48658d;
  background: #0f1928;
  flex-shrink: 0;
}}
.hex-icon.placeholder {{
  display: flex;
  align-items: center;
  justify-content: center;
  color: #9cb2d5;
  font-size: 14px;
  font-weight: 700;
}}
.rating {{
  display: inline-block;
  min-width: 62px;
  text-align: center;
  font-weight: 700;
  border-radius: 6px;
  padding: 3px 8px;
  font-size: 13px;
  border: 1px solid transparent;
}}
.rate-s {{ background: #3a2a12; color: #ffc55e; border-color: #8c6428; }}
.rate-a {{ background: #1a3524; color: #7cf09d; border-color: #2f7d4a; }}
.rate-b {{ background: #23364f; color: #8dc4ff; border-color: #3f6593; }}
.rate-d {{ background: #462020; color: #ff8f8f; border-color: #8a3a3a; }}
.rate-default {{ background: #2f3c53; color: #d0def5; border-color: #546889; }}
.hex-name {{ font-size: 15px; font-weight: 700; color: #eaf2ff; }}
.tier {{ font-size: 12px; color: #9fb4d6; }}
.hex-note {{ margin-top: 7px; font-size: 14px; line-height: 1.6; color: #cfdbf1; }}
</style>
</head>
<body>
  <div class=\"card\">
    <div class=\"section title\">
      <h1>{hero_name_zh}</h1>
      <div class=\"subtitle\">{hero_title} {hero_name_en}</div>
    </div>

    <div class=\"section\">
      <h2 class=\"block-title\">英雄介绍</h2>
      <div class=\"intro\">{intro}</div>
    </div>

    <div class=\"section\">
      <h2 class=\"block-title\">技能组（被动 + Q/W/E/R）</h2>
      <div class=\"skills\">
        {''.join(skills_html)}
      </div>
    </div>

    <div class=\"section\">
      <h2 class=\"block-title\">海克斯联动分析（Top 10）</h2>
      <div class=\"hex-grid\">
        {''.join(interactions_html)}
      </div>
    </div>
  </div>
</body>
</html>
"""

    async def _generate_hero_report_image(self, payload: dict) -> str | None:
        html_content = self._render_hero_report_html(payload)
        render_options_list = [
            {
                "full_page": True,
                "type": "png",
                "quality": 95,
                "scale": "device",
                "device_scale_factor_level": "normal",
            },
            {
                "full_page": True,
                "type": "jpeg",
                "quality": 85,
                "scale": "device",
                "device_scale_factor_level": "normal",
            },
        ]

        for render_options in render_options_list:
            render_type = str(render_options.get("type") or "unknown")
            try:
                image_data = await self.html_render(html_content, {}, False, render_options)
            except Exception as exc:
                logger.warning(f"英雄报告图片渲染失败: render_type={render_type}, error={exc}")
                continue

            image_path = self._materialize_render_result(image_data, render_type)
            if image_path:
                logger.info(f"英雄报告图片生成成功: render_type={render_type}, path={image_path}")
                return image_path

        logger.warning("英雄报告图片生成失败：html_render 未返回有效图片")
        return None

    async def _send_report_image(self, event: AstrMessageEvent, image_path: str) -> bool:
        try:
            logger.info(f"准备发送英雄报告图片文件: {image_path}")
            if os.path.exists(image_path):
                logger.info(f"英雄报告图片文件大小: {os.path.getsize(image_path)} bytes")
            await self.context.send_message(
                event.unified_msg_origin,
                MessageChain([Image.fromFileSystem(image_path)]),
            )
            return True
        except Exception as e:
            logger.warning(f"发送英雄报告图片失败: {e}")
            return False

    async def _handle_haidou(self, event: AstrMessageEvent, hero_name: str = ""):
        if not hero_name:
            yield event.plain_result("请输入英雄名，例如：/海斗 提莫")
            return

        hero = self._find_hero_local(hero_name)

        if not hero and self.config.get("enable_llm_search", True):
            logger.info(f"本地未找到英雄 {hero_name}，尝试调用LLM...")
            normalized = await self._normalize_hero_name(hero_name)
            if normalized and normalized.get("name"):
                hero = self._find_hero_local(normalized["name"])
                if not hero and normalized.get("en_name"):
                    hero = self._find_hero_local(normalized["en_name"])
                if not hero and normalized.get("alias"):
                    for alias in normalized["alias"]:
                        hero = self._find_hero_local(alias)
                        if hero:
                            break

        if not hero:
            yield event.plain_result(f"未找到英雄: {hero_name}")
            return

        zh_name = hero.get("name", {}).get("zh", "未知")
        en_name = hero.get("name", {}).get("en", "")
        title = hero.get("title", {}).get("zh", "")
        hero_id = hero.get("id", "Unknown")

        if not hero_id or hero_id == "Unknown":
            yield event.plain_result(f"英雄 {zh_name} 缺少有效ID，暂时无法抓取详情")
            return

        html_content = await self._fetch_hero_page_html(hero_id)
        if not html_content:
            yield event.plain_result("获取英雄页面失败，请稍后再试")
            return

        soup = BeautifulSoup(html_content, "html.parser")
        intro = self._parse_hero_profile(soup)
        skills = self._parse_hero_skills(soup)
        interactions = self._parse_hextech_interactions(soup, limit=10)

        if len(skills) < 5:
            logger.warning(
                f"技能解析不足: hero_id={hero_id}, hero={zh_name}, resolved={len(skills)}"
            )
            yield event.plain_result(
                f"{zh_name} 技能数据解析不完整（{len(skills)}/5），请稍后重试或反馈管理员。"
            )
            return

        if not interactions:
            yield event.plain_result(f"{zh_name} 暂无海克斯联动分析数据。")
            return

        payload = {
            "hero_name_zh": zh_name,
            "hero_name_en": en_name,
            "hero_title": title,
            "intro": intro,
            "skills": skills,
            "interactions": interactions,
        }

        image_path = await self._generate_hero_report_image(payload)
        if not image_path:
            yield event.plain_result("英雄报告图片生成失败，请联系管理员检查渲染服务。")
            return

        if not await self._send_report_image(event, image_path):
            yield event.plain_result("英雄报告图片发送失败，请联系管理员检查发图链路。")

    async def _normalize_hero_name(self, query: str) -> dict:
        provider = None
        provider_id = self.config.get("llm_provider_id")
        if provider_id:
            provider = self.context.get_provider_by_id(provider_id)

        if not provider and hasattr(self.context, "get_all_providers"):
            providers = self.context.get_all_providers()
            if providers:
                provider = providers[0]

        if not provider:
            logger.warning("未找到可用的LLM Provider，跳过英雄名标准化")
            return None

        prompt = f"""# Role
你是一个精通《英雄联盟》(League of Legends) 全球版本数据、职业比赛梗及玩家社区黑话的专业识别助手。

# Task
根据用户输入的【别名、外号、数字代码或不标准名称】，识别其对应的英雄，并以严格的 JSON 格式返回。

# Output Format (JSON Only)
{{
  \"name\": \"英雄的标准中文全称\",
  \"en_name\": \"Hero's official English name\",
  \"alias\": [\"可能的其他中文称呼1\", \"称呼2\"]
}}

# Constraint
- 禁止输出任何解释性文字。
- 禁止包含 Markdown 代码块标识符。
- 确保 JSON 键值对双引号规范。

# User Input:
{query}
"""
        try:
            response = await provider.text_chat(prompt=prompt, contexts=[])
            if response and response.completion_text:
                text = response.completion_text
                try:
                    if "```json" in text:
                        text = text.split("```json")[1].split("```")[0]
                    elif "```" in text:
                        parts = text.split("```")
                        if len(parts) >= 3:
                            text = parts[1]
                        else:
                            text = text.replace("```", "")
                    return json.loads(text.strip())
                except (IndexError, json.JSONDecodeError):
                    logger.warning(f"LLM返回格式解析失败，尝试直接解析: {text}")
                    try:
                        return json.loads(text.strip())
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"LLM标准化英雄名失败: {e}")
        return None

    async def terminate(self):
        pass
