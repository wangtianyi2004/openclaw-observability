import os
import datetime
from langfuse import get_client

os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-3aae0d1930a35c1905a807b2c3375ee1"
os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-f748544a0fa23ed65ae8467fc6fc2372"
os.environ["LANGFUSE_HOST"] = "http://localhost:3100"

langfuse = get_client()

minute = datetime.datetime.now().minute
if minute % 2 != 0:
    prompt = langfuse.get_prompt("feishu/BorderCollie", label="prod-a")
    variant = "prod-a"
else:
    prompt = langfuse.get_prompt("feishu/Samoyed", label="prod-b")
    variant = "prod-b"

compiled = prompt.compile(team_name="AB实验团队")

with open("/root/.openclaw/workspace-feishu-bot-3/SOUL.md", "w") as f:
    f.write(compiled)

print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 分钟: {minute} | variant: {variant}")




