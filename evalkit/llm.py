"""LLM 调用（OpenAI 兼容接口），只用标准库。

约定：
  * key 只从环境变量读，绝不写进代码或配置文件；
  * 每次调用都记录耗时与 token 用量，便于后续聚合 TTFT/整包耗时。
"""
import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = os.environ.get("EVAL_BASE_URL", "https://api.deepseek.com/v1")
DEFAULT_MODEL = os.environ.get("EVAL_MODEL", "deepseek-chat")
KEY_ENV = os.environ.get("EVAL_KEY_ENV", "DEEPSEEK_API_KEY")


class LLMResult:
    __slots__ = ("text", "elapsed", "usage", "raw")

    def __init__(self, text, elapsed, usage, raw):
        self.text, self.elapsed, self.usage, self.raw = text, elapsed, usage, raw

    def __repr__(self):
        return f"LLMResult(elapsed={self.elapsed:.2f}s, tokens={self.usage.get('total_tokens')})"


def api_key():
    key = os.environ.get(KEY_ENV) or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit(f"缺少 API key：请设置环境变量 {KEY_ENV}")
    return key


def llm(messages, model=None, tools=None, temperature=0.0, max_tokens=2048,
        base_url=None, timeout=180, retries=2):
    """返回 LLMResult；reasoning_content 不计入 text。"""
    model = model or DEFAULT_MODEL
    base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
    payload = {"model": model, "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    if tools:
        payload["tools"] = tools
    last = None
    for attempt in range(retries + 1):
        t0 = time.time()
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key()}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            msg = data["choices"][0]["message"]
            return LLMResult(msg.get("content") or "", time.time() - t0, data.get("usage", {}), msg)
        except Exception as e:      # 网络抖动：退避重试
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"LLM 调用失败（{model}）：{last}")
