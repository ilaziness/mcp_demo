from mcp.server.fastmcp import FastMCP

mcp = FastMCP("StatefullServer")

@mcp.tool(description="A simple echo tool")
def echo(message: str) -> str:
    return f"Echo: {message}"

@mcp.tool(description="A simple add tool")
def add_two(n: int) -> int:
    return n + 2

# http流MCP服务器
if __name__ == "__main__":
    # 运行mcp服务器
    mcp.run(transport='streamable-http')