import asyncio
import ollama


async def test():
    client = ollama.AsyncClient(host="http://127.0.0.1:11434")
    response = await client.chat(
        model="qwen3.5:9b",
        messages=[{"role": "user", "content": "你好"}],
        stream=False,
    )
    print(response.message.content)


asyncio.run(test())
