from openai import OpenAI

client = OpenAI(
    api_key="sk-434ecda2f9c34355843ecb0e5e159a69",
    base_url="https://api.deepseek.com"
)

response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[
        {"role": "user", "content": "Hello, who are you?"}
    ]
)

print(response.choices[0].message.content)
