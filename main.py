from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import json

@register("hextech", "Payne", "海克斯乱斗信息差", "0.0.1")
class MyPlugin(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        pass

    @filter.command("海斗")
    async def haidou(self, event: AstrMessageEvent, hero_name: str):
        """查询英雄"""
        # 尝试标准化英雄名
        normalized = await self._normalize_hero_name(hero_name)
        
        name = hero_name
        en_name = ""
        
        if normalized and normalized.get("name"):
            name = normalized["name"]
            en_name = normalized.get("en_name", "")
            logger.info(f"英雄名标准化: {hero_name} -> {name} ({en_name})")
        else:
            logger.warning(f"无法标准化英雄名: {hero_name}")
            
        result_msg = f"英雄: {name}"
        if en_name:
            result_msg += f" ({en_name})"
            
        yield event.plain_result(result_msg)

    async def _normalize_hero_name(self, query: str) -> dict:
        """调用LLM标准化英雄名"""
        provider = None
        
        # 1. 尝试从配置获取 provider_id
        provider_id = self.config.get("provider_id")
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
            
        prompt = f"""
用户输入: {query}
请识别这是英雄联盟(League of Legends)中的哪个英雄。用户输入的可能是别名、外号或不标准的名称。
请返回一个JSON对象，包含以下字段：
- "name": 英雄的标准中文名称
- "en_name": 英雄的标准英文名称

如果无法识别或不是英雄联盟的英雄，请返回 null。
只返回JSON格式，不要包含其他文本。
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
