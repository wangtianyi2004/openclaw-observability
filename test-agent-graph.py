"""
用 Langfuse Python SDK 构造一个完整的 Agent Graphs 测试 trace
"""
import os
os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-f748544a0fa23ed65ae8467fc6fc2372"
os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-3aae0d1930a35c1905a807b2c3375ee1"
os.environ["LANGFUSE_HOST"] = "http://langfuse-web:3000"

from langfuse import get_client
from datetime import datetime, timezone, timedelta

langfuse = get_client()

# 构造一个模拟 OpenClaw 的 trace
with langfuse.start_as_current_observation(
    as_type="span",
    name="openclaw.message.processed",
    input={"text": "请帮我查询 CPU 和内存使用情况", "sender": "测试用户"},
) as root:
    root.update_trace(
        name="openclaw.message.processed",
        input={"text": "请帮我查询 CPU 和内存使用情况", "sender": "测试用户"},
        output={"text": "系统资源报告已生成"},
    )

    # 父 agent 推理
    with langfuse.start_as_current_observation(
        as_type="agent",
        name="feishu-bot-1 agent",
        input=[{"role": "user", "content": "请帮我查询 CPU 和内存使用情况"}],
    ):
        # exec 工具调用
        with langfuse.start_as_current_observation(
            as_type="tool",
            name="exec: top -bn1 | grep Cpu(s)",
            input={"command": "top -bn1 | grep 'Cpu(s)'"},
            output={"result": "%Cpu(s):  2.1 us,  0.5 sy"},
        ):
            pass

        # sessions_spawn 调用子 agent
        with langfuse.start_as_current_observation(
            as_type="agent",
            name="sessions_spawn → subagent",
            input={"task": "请执行 free -h 查询内存使用情况"},
        ) as spawn_span:
            # 子 agent 推理
            with langfuse.start_as_current_observation(
                as_type="agent",
                name="subagent: memory-check",
                input=[{"role": "user", "content": "请执行 free -h 查询内存使用情况"}],
            ):
                # 子 agent 的工具调用
                with langfuse.start_as_current_observation(
                    as_type="tool",
                    name="exec: free -h",
                    input={"command": "free -h"},
                    output={"result": "Mem: 7.4Gi total, 4.6Gi used"},
                ):
                    pass

            spawn_span.update(output={"result": "内存查询完成"})

        # sessions_yield
        with langfuse.start_as_current_observation(
            as_type="tool",
            name="sessions_yield",
            input={},
            output={"result": "子 agent 结果已返回"},
        ):
            pass

langfuse.flush()
print("✅ trace 写入完成，trace_id:", langfuse.get_current_trace_id() or "请查看 Langfuse UI")
