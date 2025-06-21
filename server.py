from typing import Any
from openai import OpenAI
import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.prompts import base
import json
from openai.types.chat.chat_completion import Choice

# 初始化FastMCP服务器，weather是服务器名，非必填
mcp = FastMCP("weather")

# 常量
API_HOST = "https://api.moonshot.cn/v1"
KEY = "sk-HD5HP6jk4maKBkPfrzbli5xT4to44wKWzi5UzpXye9ZL8xLu"

client = OpenAI(
    api_key = KEY,
    base_url = API_HOST,
)

# 发送聊天请求
async def make_request(messages, ctx: Context) -> Choice:
    completion = client.chat.completions.create(
        model="moonshot-v1-8k",
        messages=messages,
        temperature=0.3,
        tools=[
            {
                "type": "builtin_function",  # <-- 使用 builtin_function 声明 $web_search 函数，请在每次请求都完整地带上 tools 声明
                "function": {
                    "name": "$web_search",
                },
            }
        ]
    )
    await ctx.debug(str(completion.choices[0]))
    return completion.choices[0]

# 工具类型的mcp server
@mcp.tool() #装饰器声明一个工具
async def web_search(ctx: Context, msg: str) -> str: # web_search 工具名称
    # 工具的描述说明，包含功能描述和参数说明
    """
    联网搜索

    Args:
        msg: 要搜索的内容
    """
    await ctx.info("搜索内容：%s" % msg) # 打印日志，调试的时候可以看到
    messages = [
        {"role": "system", "content": "你是 Kimi。"},
    ]
 
    messages.append({
        "role": "user",
        "content": "%s" % msg
    })
    finish_reason = None
    choice = None
    # 下面kimi文档里面web search的示例
    while finish_reason is None or finish_reason == "tool_calls":
        choice = await make_request(messages, ctx)
        finish_reason = choice.finish_reason
        if finish_reason == "tool_calls":  # <-- 判断当前返回内容是否包含 tool_calls
            messages.append(choice.message)  # <-- 我们将 Kimi 大模型返回给我们的 assistant 消息也添加到上下文中，以便于下次请求时 Kimi 大模型能理解我们的诉求
            for tool_call in choice.message.tool_calls:  # <-- tool_calls 可能是多个，因此我们使用循环逐个执行
                tool_call_name = tool_call.function.name
                tool_call_arguments = json.loads(tool_call.function.arguments)  # <-- arguments 是序列化后的 JSON Object，我们需要使用 json.loads 反序列化一下
                if tool_call_name == "$web_search":
                    tool_result = tool_call_arguments
                else:
                    tool_result = f"Error: unable to find tool by name '{tool_call_name}'"
 
                # 使用函数执行结果构造一个 role=tool 的 message，以此来向模型展示工具调用的结果；
                # 注意，我们需要在 message 中提供 tool_call_id 和 name 字段，以便 Kimi 大模型
                # 能正确匹配到对应的 tool_call。
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call_name,
                    "content": json.dumps(tool_result),  # <-- 我们约定使用字符串格式向 Kimi 大模型提交工具调用结果，因此在这里使用 json.dumps 将执行结果序列化成字符串
                })
 
    if choice is None:
        return "无数据"
    await ctx.debug(str(choice.message))
    return choice.message.content # 返回调用结果给客户端

# 示例mcp tool 2，为了简化直接返回了一个固定的字符串
@mcp.tool()
async def fix_response() -> str:
    """
    提供新闻头条
    """
    return """小米玄戒研发成功，而且还马上就要量产了，很多人疑惑，14nm以下的芯片都不能被台积电代工，为什么小米可以?

这个是事实，不信掰着指头来盘一盘国内但凡有芯片研发实力的厂家，都被老美制裁一遍，

海思、神威、龙芯、飞腾等等，现在这些厂家都不在台积电代工。

这次小米宣告玄戒3nm研发成功，接下来就要量产应用，也就是说小米芯片可以代工，

至于能代工的原因，要么老美觉得没制裁的必要，要么觉得，等小米折腾一阵子再看看，实在不行再出手。
"""

# resource
# 第一个参数值资源链接URI
@mcp.resource("config://app", name="app config", description="provide app config content")
async def get_config() -> str:
    """"static config data"""
    return "config data"

# 动态的resource
@mcp.resource("users://{user_id}/profile", name="User Profile")
async def get_user_profile(user_id: str) -> str:
    """Dynamic user data"""
    return f"Profile data for user {user_id}"

# 提示词
@mcp.prompt(name="Code Review")
async def review_code(code: str) -> str:
    return f"Please review this code:\n\n{code}"


@mcp.prompt(name="Debug Assistant")
async def debug_error(error: str) -> list[base.Message]:
    return [
        base.UserMessage("I'm seeing this error:"),
        base.UserMessage(error),
        base.AssistantMessage("I'll help debug that. What have you tried so far?"),
    ]

# 运行 uv run server.py 确认是否正常
if __name__ == "__main__":
    # 运行mcp服务器
    mcp.run(transport='stdio')