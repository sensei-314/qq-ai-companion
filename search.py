"""
search.py —— 联网搜索（2026-11-08 主人要求：她可以自己搜）

仿 hideepseek.py：
  1. DeepSeek 官方搜索（失败自动换下一个）
  2. Tavily（回退）

用法：她在回复里写 <search>关键词</search>，main 会执行搜索、
把结果喂回模型，再让她基于结果回答。
"""

import requests

from config import API_KEY

DEEPSEEK_SEARCH_URL = "https://api.deepseek.com/v1/tools/search"
TAVILY_URL = "https://api.tavily.com/search"
TAVILY_API_KEY = "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"


def _fmt(query, results):
    if not results:
        return f"（搜索「{query}」没有结果）"
    lines = [f"以下是关于「{query}」的搜索结果："]
    for i, item in enumerate(results, 1):
        title = item.get("title", "")
        snippet = (item.get("content") or item.get("snippet") or "")[:500]
        link = item.get("url", "")
        lines.append(f"{i}. {title}\n   {snippet}\n   来源：{link}")
    return "\n".join(lines)


def search_deepseek(query, count=5):
    try:
        r = requests.post(
            DEEPSEEK_SEARCH_URL,
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={"query": query, "count": count},
            timeout=15,
        )
        if r.status_code == 200:
            return _fmt(query, (r.json() or {}).get("results") or [])
    except Exception as e:
        print(f"[search] deepseek fail: {e}")
    return None


def search_tavily(query, count=5):
    try:
        r = requests.post(
            TAVILY_URL,
            json={"api_key": TAVILY_API_KEY, "query": query, "search_depth": "advanced", "max_results": count},
            timeout=20,
        )
        if r.status_code == 200:
            return _fmt(query, (r.json() or {}).get("results") or [])
    except Exception as e:
        print(f"[search] tavily fail: {e}")
    return None


def search_web(query, count=5):
    """双引擎：官方优先，Tavily 回退。"""
    q = str(query or "").strip()
    if not q:
        return "（没给搜索关键词）"
    return search_deepseek(q, count) or search_tavily(q, count) or f"（搜索「{q}」失败了）"
