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
    async def haidou(self, event: AstrMessageEvent, hero_name: str = ""):
        """查询英雄"""
        if not hero_name:
            yield event.plain_result("请输入英雄名，例如：/海斗 提莫")
            return

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
   "en_name": "Hero's official English name" 
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
