"""
Langfuse → OpenClaw SOUL.md 同步服务

从 Langfuse 获取最新的 prompt，写入对应的 SOUL.md 文件。
OpenClaw 每次处理消息前都会重新读取 SOUL.md，因此文件更新后立即生效。
"""

import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests

from langfuse import Langfuse

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("prompt-sync")

# ---------------------------------------------------------------------------
# 优雅退出
# ---------------------------------------------------------------------------
running = True


def _handle_signal(signum, _frame):
    global running
    logger.info("收到信号 %s，准备退出…", signum)
    running = False


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
CONFIG_PATH = os.environ.get("SYNC_CONFIG_PATH", "/app/sync-prompt.cfg")
SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL", "5"))  # 秒

# Langfuse REST API 配置
LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "http://langfuse-web:3000")
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")


def load_config(path: str) -> list[dict]:
    """读取配置文件，返回 prompt ↔ soul 映射列表。"""
    with open(path, "r", encoding="utf-8") as f:
        config = json.load(f)
    logger.info("已加载 %d 条映射配置", len(config))
    return config


# ---------------------------------------------------------------------------
# 同步逻辑
# ---------------------------------------------------------------------------
# 内存缓存：记录上一次写入的内容，避免无变化时重复写磁盘
_cache: dict[str, str] = {}


def fetch_prompt_via_api(prompt_name: str, label: str) -> dict | None:
    """通过 REST API 获取 prompt，返回包含 id 的完整数据。"""
    encoded_name = quote(prompt_name, safe="")
    url = f"{LANGFUSE_HOST}/api/public/v2/prompts/{encoded_name}?label={label}"
    try:
        resp = requests.get(url, auth=(LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY), timeout=10)
        if resp.status_code == 200:
            return resp.json()
        else:
            logger.error("获取 prompt [%s] 失败: status=%d, body=%s", prompt_name, resp.status_code, resp.text)
            return None
    except Exception as e:
        logger.error("获取 prompt [%s] 请求异常: %s", prompt_name, e)
        return None


def sync_one(client: Langfuse, mapping: dict) -> None:
    """同步单个 prompt → SOUL.md。"""
    prompt_name = mapping["prompt_name"]
    label = mapping.get("label", "production")
    soul_path = Path(mapping["soul_path"])

    data = fetch_prompt_via_api(prompt_name, label)
    if data is None:
        return

    # 获取 prompt 内容
    raw = data.get("prompt", "")
    if isinstance(raw, list):
        # ChatPrompt：拼接所有消息内容
        body = "\n\n".join(
            msg.get("content", "") for msg in raw if isinstance(msg, dict)
        )
    else:
        body = str(raw)

    # 获取 prompt 元数据
    prompt_id = data.get("id", "")
    prompt_version = data.get("version", "")

    # 拼接：HTML 注释元数据 + 正文
    meta_comment = (
        f"<!-- prompt_id: {prompt_id} -->\n"
        f"<!-- prompt_name: {prompt_name} -->\n"
        f"<!-- prompt_version: {prompt_version} -->\n"
    )
    content = meta_comment + "\n" + body

    # 跟缓存比较，无变化则跳过
    cache_key = f"{prompt_name}:{label}"
    if _cache.get(cache_key) == content:
        return

    # 跟磁盘文件比较（首次启动时缓存为空，需要读文件）
    if soul_path.exists():
        existing = soul_path.read_text(encoding="utf-8")
        if existing == content:
            _cache[cache_key] = content
            return

    # 写入文件
    soul_path.parent.mkdir(parents=True, exist_ok=True)
    soul_path.write_text(content, encoding="utf-8")
    _cache[cache_key] = content
    logger.info(
        "已同步 [%s:%s v%s] → %s", prompt_name, label, prompt_version, soul_path
    )


def sync_all(client: Langfuse, mappings: list[dict]) -> None:
    """遍历所有映射，逐个同步。"""
    for mapping in mappings:
        try:
            sync_one(client, mapping)
        except Exception as e:
            logger.error("同步异常 [%s]: %s", mapping.get("prompt_name"), e)


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------
def main():
    logger.info("=== Langfuse → SOUL.md 同步服务启动 ===")
    logger.info("同步间隔: %d 秒", SYNC_INTERVAL)

    # 初始化 Langfuse 客户端（从环境变量读取 LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST）
    client = Langfuse()

    # 加载配置
    mappings = load_config(CONFIG_PATH)

    # 首次同步
    sync_all(client, mappings)
    logger.info("首次同步完成")

    # 持续同步
    while running:
        time.sleep(SYNC_INTERVAL)
        if not running:
            break
        sync_all(client, mappings)

    logger.info("=== 同步服务已停止 ===")
    client.shutdown()


if __name__ == "__main__":
    main()


