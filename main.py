from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import json
import os
import aiohttp
from bs4 import BeautifulSoup

@register("hextech", "Payne", "海克斯乱斗信息差", "0.0.1")
class MyPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        self.hero_data = []
        self._load_hero_data()

    def _load_hero_data(self):
        """加载英雄数据"""
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
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        pass

    def _find_hero_local(self, query: str) -> dict:
        """本地查找英雄（支持中文名、英文名、称号、ID模糊匹配）"""
        if not self.hero_data:
            return None
            
        query = query.lower().strip()
        
        # 1. 精确匹配
        for hero in self.hero_data:
            if (hero.get("name", {}).get("zh", "") == query or 
                hero.get("name", {}).get("en", "").lower() == query or 
                hero.get("title", {}).get("zh", "") == query or 
                hero.get("title", {}).get("en", "").lower() == query or
                hero.get("id", "").lower() == query):
                return hero
                
        # 2. 模糊匹配
        for hero in self.hero_data:
            if (query in hero.get("name", {}).get("zh", "") or 
                query in hero.get("name", {}).get("en", "").lower() or 
                query in hero.get("title", {}).get("zh", "") or 
                query in hero.get("title", {}).get("en", "").lower()):
                return hero
                
        return None

    async def _fetch_hextech_info(self, hero_id: str) -> str:
        """爬取海克斯联动数据"""
        url = f"https://apexlol.info/zh/champions/{hero_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"获取海克斯数据失败: HTTP {response.status}")
                        return f"获取海克斯数据失败: HTTP {response.status}"
                    html = await response.text()
            
            soup = BeautifulSoup(html, 'html.parser')
            
            # 查找 "海克斯联动分析" 标题
            header = soup.find(string=lambda t: "海克斯联动分析" in t if t else False)
            if not header:
                return "未找到海克斯联动数据。"
            
            # 查找 interaction-card
            cards = soup.select(".interaction-card")
            if not cards:
                return "该英雄暂无海克斯联动数据。"
            
            result = ["\n⚡ **海克斯联动分析**"]
            for card in cards:
                # 阶级: .hex-tier
                tier_elem = card.select_one(".hex-tier")
                tier = tier_elem.get_text(strip=True) if tier_elem else ""
                
                # 名称: .hex-name
                name_elem = card.select_one(".hex-name")
                name = name_elem.get_text(strip=True) if name_elem else ""
                
                # 评分: .rating-badge
                rating_elem = card.select_one(".rating-badge")
                rating = rating_elem.get_text(strip=True) if rating_elem else ""
                
                # 描述: .note
                note_elem = card.select_one(".note")
                note = note_elem.get_text(strip=True) if note_elem else ""
                
                result.append(f"- 【{rating}】 {name} ({tier}): {note}")
                
            return "\n".join(result)

        except Exception as e:
            logger.error(f"爬取海克斯数据失败: {e}")
            return f"爬取数据出错: {e}"

    @filter.command("海斗")
    async def haidou(self, event: AstrMessageEvent, hero_name: str = ""):
        """查询英雄"""
        if not hero_name:
            yield event.plain_result("请输入英雄名，例如：/海斗 提莫")
            return

        # 1. 优先本地查找
        hero = self._find_hero_local(hero_name)
        
        # 2. 如果本地没找到，且开启了LLM搜索，则尝试LLM标准化
        if not hero and self.config.get("enable_llm_search", True):
            logger.info(f"本地未找到英雄 {hero_name}，尝试调用LLM...")
            normalized = await self._normalize_hero_name(hero_name)
            if normalized and normalized.get("name"):
                # LLM返回标准名后，再次在本地查找以获取完整数据
                # 尝试用 name 找
                hero = self._find_hero_local(normalized["name"])
                
                # 如果没找到，尝试用 en_name 找
                if not hero and normalized.get("en_name"):
                    hero = self._find_hero_local(normalized["en_name"])

                # 如果还没找到，尝试用 alias 列表找
                if not hero and normalized.get("alias"):
                    for alias in normalized["alias"]:
                        hero = self._find_hero_local(alias)
                        if hero:
                            break

                if not hero:
                     # 如果LLM返回了名字但本地还是没找到（可能是LLM幻觉或数据不一致），兜底使用LLM返回的简单信息
                     logger.warning(f"LLM返回了 {normalized['name']} 但本地数据未匹配")
                     hero = {
                         "name": {"zh": normalized["name"], "en": normalized.get("en_name", "")},
                         "title": {"zh": "未知", "en": "Unknown"},
                         "id": "Unknown"
                     }

        if hero:
            zh_name = hero.get("name", {}).get("zh", "未知")
            en_name = hero.get("name", {}).get("en", "")
            title = hero.get("title", {}).get("zh", "")
            hero_id = hero.get("id", "Unknown")
            
            yield event.plain_result(f"🔍 正在查询【{zh_name} {title}】的相关信息...")
            
            result_msg = f"英雄: {zh_name} {title}"
            if en_name:
                result_msg += f" ({en_name})"
            result_msg += f"\nID: {hero_id}"

            # 爬取海克斯数据
            if hero_id and hero_id != "Unknown":
                try:
                    hex_info = await self._fetch_hextech_info(hero_id)
                    result_msg += f"\n{hex_info}"
                except Exception as e:
                    logger.error(f"获取海克斯数据异常: {e}")
            
            yield event.plain_result(result_msg)
        else:
            yield event.plain_result(f"未找到英雄: {hero_name}")

    async def _normalize_hero_name(self, query: str) -> dict:
        """调用LLM标准化英雄名"""
        provider = None
        
        # 1. 尝试从配置获取 provider_id
        provider_id = self.config.get("llm_provider_id") # 注意这里用了 llm_provider_id
        if provider_id:
            provider = self.context.get_provider_by_id(provider_id)
            
        # 2. 如果未配置，尝试获取第一个可用的 provider
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
 
 # Knowledge Base & Rules 
 1. **官方名称优先**：如“亚索”对应“疾风剑豪 亚索”。 
 2. **黑话/梗识别**： 
    - 数字梗（如：4396 -> 李青, 2800 -> 艾尼维亚）。 
    - 技能/形象外号（如：大腰子 -> 慎, 快乐风男 -> 亚索, 轮子妈 -> 希维尔）。 
    - 职业选手关联（如：UZI -> 薇恩, 飞科 -> 瑞兹/阿兹尔）。 
 3. **容错性**：用户输入可能存在拼写错误（如：卢仙 -> 卢锡安, 维恩 -> 薇恩）。 
 4. **唯一性**：只返回一个最匹配的英雄。如果无法确认或不属于英雄联盟英雄，返回 null。 
 
 # Output Format (JSON Only) 
 {{ 
   "name": "英雄的标准中文全称", 
   "en_name": "Hero's official English name",
   "alias": ["可能的其他中文称呼1", "称呼2"]
 }} 
 
 # Constraint 
 - 禁止输出任何解释性文字。 
 - 禁止包含 Markdown 代码块标识符（除非明确要求）。 
 - 确保 JSON 键值对双引号规范。 
 
 # User Input: 
 {query} 
"""
        try:
            response = await provider.text_chat(prompt=prompt, contexts=[])
            if response and response.completion_text:
                text = response.completion_text
                # 清理可能的 Markdown 代码块
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0]
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0]
                
                return json.loads(text.strip())
        except Exception as e:
            logger.error(f"LLM标准化英雄名失败: {e}")
            
        return None

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
