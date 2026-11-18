"""一个最小可用的中文 RAG 客服 Agent（纯标准库，离线可跑）。

设计上保留两处**真实会出现的缺陷**，让评测有用武之地：
  1. 多轮里不处理省略/指代（"那要多久" 这类追问直接检索不到）→ 多轮用例应该挂
  2. 一个问题里有多个子问题时只回 top-1 片段 → 完整性用例应该挂

检索：BM25（标题/正文同权，中文用 bigram 切词），不做向量、不依赖任何包，
      这样 CI 上没有任何外部依赖，结果也可复现。
"""
import math
import os
import re

KB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kb")
GREETING = re.compile(r"^(你好|您好|hi|hello|在吗|谢谢|感谢|再见|晚安|你是谁|你能做什么)", re.I)
PRIVACY = re.compile(r"手机号|联系方式|身份证|收货地址发|别人的|上个客户|昨天那个客户")
UNAUTHORIZED = re.compile(r"帮我把收货地址改成|改收货地址|取消订单|把订单.*改")
OUT_OF_SCOPE = re.compile(r"CEO|老板|总部|融资|股价|老板电话")
THANKS = re.compile(r"^(谢谢|感谢|好的|解决了)")

STOP_TOP = 0.8          # BM25 低于这个分就认为「资料里没有」


# ------------------------------------------------------------------ 检索
def tokenize(text):
    text = (text or "").lower()
    toks = re.findall(r"[a-z0-9]+", text)
    for run in re.findall(r"[\u4e00-\u9fff]+", text):      # 中文按 bigram
        toks.extend(run[i:i + 2] for i in range(len(run) - 1))
    return toks


def load_chunks(kb_dir=KB_DIR):
    chunks = []
    for fn in sorted(os.listdir(kb_dir)):
        if not fn.endswith(".md"):
            continue
        with open(os.path.join(kb_dir, fn), encoding="utf-8") as f:
            text = f.read()
        doc_title = ""
        for block in re.split(r"^# ", text, flags=re.M):
            if not block.strip():
                continue
            head, _, body = block.partition("\n")
            doc_title = doc_title or head.strip()
            for seg in re.split(r"^## ", body, flags=re.M):
                seg = seg.strip()
                if not seg:
                    continue
                title, _, content = seg.partition("\n")
                chunks.append({"source": f"{fn[:-3]}::{title.strip()}",
                               "title": f"{doc_title} {title.strip()}", "text": content.strip()})
    return chunks


class BM25:
    def __init__(self, chunks, k1=1.5, b=0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.docs = [tokenize(c["title"] + "\n" + c["text"]) for c in chunks]
        self.avg = sum(len(d) for d in self.docs) / max(len(self.docs), 1)
        self.df = {}
        for d in self.docs:
            for t in set(d):
                self.df[t] = self.df.get(t, 0) + 1
        self.n = len(self.docs)

    def idf(self, t):
        df = self.df.get(t, 0)
        return math.log((self.n - df + 0.5) / (df + 0.5) + 1)

    def search(self, query, top_k=3):
        q = tokenize(query)
        scored = []
        for i, d in enumerate(self.docs):
            tf = {}
            for t in d:
                tf[t] = tf.get(t, 0) + 1
            s = 0.0
            for t in q:
                if t not in tf:
                    continue
                f = tf[t]
                s += self.idf(t) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(d) / self.avg))
            if s > 0:
                scored.append((round(s, 3), i))
        scored.sort(reverse=True)
        return [{"score": s, **self.chunks[i]} for s, i in scored[:top_k]]


_RAG = None


def _rag():
    global _RAG
    if _RAG is None:
        _RAG = BM25(load_chunks())
    return _RAG


def search_knowledge(query, top_k=3):
    return {"hits": _rag().search(query, top_k)}


# ------------------------------------------------------------------ Agent
def run(question, history=None):
    history = history or []
    q = (question or "").strip()

    if PRIVACY.search(q):
        return {"answer": "抱歉，出于隐私保护，我无法提供他人的订单或联系方式；请让本人联系人工客服核实身份后处理。",
                "tool_calls": [], "data": {"refused": True}}

    if UNAUTHORIZED.search(q):
        return {"answer": "抱歉，我无法直接修改收货地址或取消订单；发货前可在「订单详情」页自助修改，已发货请联系人工客服拦截。",
                "tool_calls": [], "data": {"refused": True}}

    if THANKS.match(q) or GREETING.match(q):
        return {"answer": "您好，我在的～有什么可以帮您？", "tool_calls": [], "data": {}}

    tool_calls = [{"name": "search_knowledge", "query": q}]
    hits = search_knowledge(q)["hits"]

    if OUT_OF_SCOPE.search(q) or not hits or hits[0]["score"] < STOP_TOP:
        return {"answer": "资料里没有相关说明，建议联系人工客服帮您确认。", "tool_calls": tool_calls,
                "data": {"hits": hits[:3], "grounded": False}}

    top = hits[0]
    answer = f"{top['text'].strip()}\n\n（来源：{top['source']}；相关度 {top['score']}）"
    return {"answer": answer, "tool_calls": tool_calls,
            "data": {"hits": hits[:3], "grounded": True, "source": top["source"]}}


if __name__ == "__main__":
    for q in ["满 99 包邮吗", "我在西藏还包邮吗", "发票最晚多久", "你们 CEO 是谁"]:
        r = run(q)
        print(f"\nQ: {q}\nA: {r['answer'][:120]}")
