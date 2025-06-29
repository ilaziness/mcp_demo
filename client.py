import asyncio
import sys,json,time
from typing import Optional
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from openai import OpenAI

# 常量
API_HOST = "https://api.moonshot.cn/v1"
KEY = "sk-HD5HP6jk4maKBkPfrzbli5xT4to44wKWzi5UzpXye9ZL8xLu"

# MCP客户端类
class MCPClient:
    def __init__(self):
        # 初始化会话和客户端对象
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        # 连接大模型接口的客户端对象
        self.openai = OpenAI(
            api_key = KEY,
            base_url = API_HOST,
        )
    
    # 连接MCP服务器，这里支持python和node
    # 获取到可用MCP服务器的基本信息，比如名称，功能描述等
    async def connect_to_server(self, server_script_path: str):
        """连接到 MCP 服务器

        Args:
            server_script_path: 服务器脚本的路径 (.py 或 .js)
        """
        is_python = server_script_path.endswith('.py')
        is_js = server_script_path.endswith('.js')
        if not (is_python or is_js):
            raise ValueError("服务器脚本必须是 .py 或 .js 文件")

        command = "python" if is_python else "node"
        # 运行MCP服务器的参数
        server_params = StdioServerParameters(
            command=command,
            args=[server_script_path],
            env=None
        )

        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))

        await self.session.initialize()

        # 列出可用的工具
        response = await self.session.list_tools()
        tools = response.tools
        print("\n已连接到服务器，工具包括：", [tool.name for tool in tools])

    # 提交大模型对话查询
    # 这里的作用是把用户的输入提交给大模型，大模型如果返回需要调用某个MCP服务器，那么调用MCP服务器，获得MCP返回的结果后再和用户输入一起提交给大模型，然后把最终结果返回客户用户展示
    async def process_query(self, query: str) -> str:
        """使用 Claude 和可用的工具处理查询"""
        messages = [
            {
                "role": "user",
                "content": query
            }
        ]

        response = await self.session.list_tools()
        # 可调用的工具信息加到api里面，具体内容参考实际接口的文档
        # 可用工具传递给LLM的方法除了使用API接口里面的tools参数以外，也可以通过role=system的消息传递给LLM，这样传递需要在消息里面约定返回格式
        available_tools = [{
            "type": 'function',
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.inputSchema
            }
        } for tool in response.tools]

        print(json.dumps(available_tools, ensure_ascii=False))
        print(f"messages: {messages}")

        # 初始大模型API 调用
        response = self.openai.chat.completions.create(
            model="moonshot-v1-8k",
            max_tokens=1000,
            messages=messages,
            tools=available_tools
        )

        print("reponse: %s" % str(response))
        choice = response.choices[0]

        # 调用工具,这部分内容根据具体api文档来实现，这里是安装kimi的规则来的
        # 核心内容就是大模型返回需要调用MCP工具回去必要信息，根据返回参数使用call_tool调用工具得到结果，再一起发送给大模型得到最终结果
        # 这里需要判断LLM的回答是否结束，如果需要多轮调用MCP工具需要不断循环直到LLM返回了最终回答的标识后才结束
        # 这里演示没有做循环处理
        if choice.finish_reason == "tool_calls":
            # 把返回的role='assistant'消息也添加到上下文中,LLM的返回响应也需要作为assistant再次提交, 不加会报tool_call_id  is not found错误
            messages.append(choice.message)
            for tool_call in choice.message.tool_calls: # <-- tool_calls 可能是多个，因此我们使用循环逐个执行
                tool_call_name = tool_call.function.name
                tool_call_arguments = json.loads(tool_call.function.arguments) # <-- arguments 是序列化后的 JSON Object，我们需要使用 json.loads 反序列化一下
                # 执行工具调用
                time.sleep(20) # 暂停一下防止速率限制
                result = await self.session.call_tool(tool_call_name, tool_call_arguments)
                print(f"[调用工具 {tool_call_name}，参数 {tool_call_arguments}],结果 [{result}]")
    
                # 使用函数执行结果构造一个 role=tool 的 message，以此来向模型展示工具调用的结果；
                # 注意，我们需要在 message 中提供 tool_call_id 和 name 字段，以便 Kimi 大模型
                # 能正确匹配到对应的 tool_call。
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call_name,
                    "content": result.content[0].text,
                })
                print(f"tool call messges: {messages}")
            # 获取下一个响应
            time.sleep(20) # 暂停一下防止速率限制
            response = self.openai.chat.completions.create(
                model="moonshot-v1-8k",
                max_tokens=1000,
                messages=messages,
                tools=available_tools
            )
            choice = response.choices[0]
            print(f"{choice}")
        # 最后返回结果
        return choice.message.content
    
    # 提供和用户的交互的功能，输入问题，展示结果
    async def chat_loop(self):
        """运行交互式聊天循环"""
        print("\nMCP 客户端已启动！")
        print("输入你的查询或输入 'quit' 退出。")

        while True:
            try:
                query = input("\n查询: ").strip()

                if query.lower() == 'quit':
                    break

                response = await self.process_query(query)
                print("\n--------------对话结果" + response)

            except Exception as e:
                print(f"\n错误: {str(e)}")

    async def cleanup(self):
        """清理资源"""
        await self.exit_stack.aclose()

# 主入口
async def main():
    if len(sys.argv) < 2:
        print("使用方法: python client.py <path_to_server_script>")
        sys.exit(1)

    client = MCPClient()
    try:
        await client.connect_to_server(sys.argv[1])
        await client.chat_loop()
    finally:
        await client.cleanup()

if __name__ == "__main__":
    asyncio.run(main())