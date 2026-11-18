"""玩具客服 Agent —— 用来演示评测框架，**故意留两处缺陷**（可离线复现，不调 LLM）。

缺陷是刻意设计的，用来展示评测怎么抓它们：
  1. 长问题只答前半（完整性不达标）→ 边界用例 TOY-B01 应该挂
  2. 知识库没有的问题硬编答案（幻觉）→ 负向用例 TOY-N01 应该挂，并触发风险一票否决

换成你自己的 Agent 时，只要 `run(question, history)` 返回
{"answer": str, "tool_calls": [{"name": ..., "query": ...}], "data": {...}} 即可。
"""
import re

KB = {
    "退货": ("七天无理由退货需在签收后 7 天内、商品不影响二次销售；无理由退货运费由买家承担，"
             "质量问题或错发漏发的退货运费由卖家承担。", "退换货政策::无理由退货运费承担"),
    "运费": ("单笔订单满 99 元包邮，不满 99 元收 8 元基础运费；新疆西藏等偏远地区即使满 99 也可能加收附加运费。",
             "物流配送::配送时效与运费"),
    "发票": ("发票需在确认收货后申请，最晚 90 天内；增值税专票需提供公司名称、纳税人识别号、注册地址、电话、开户银行、银行账号。",
             "发票开具::专票开票信息"),
    "积分": ("购物每消费 1 元积 1 分，100 积分抵 1 元，有效期 24 个月。", "会员与优惠::积分规则"),
}

ALIASES = [
    (re.compile(r"退|换货|尺码|不合适|洗过|穿过"), "退货"),
    (re.compile(r"包邮|邮费|运费|送货"), "运费"),
    (re.compile(r"发票|开票|专票|抬头"), "发票"),
    (re.compile(r"积分|抵扣"), "积分"),
]

GREETING = re.compile(r"^(你好|您好|hi|hello|在吗|谢谢|再见|晚安)", re.I)
PRIVACY = re.compile(r"手机号|联系方式|身份证|别人的|上个客户")
UNAUTHORIZED = re.compile(r"改收货地址|取消订单|帮我(改|取消|修改).*(地址|订单)")
OUT_OF_SCOPE = re.compile(r"比特币|CEO|老板|总部|融资|股价")


def _match(question):
    for pattern, key in ALIASES:
        if pattern.search(question):
            return key
    return None


def search_knowledge(query):
    """假装是检索工具：命中就返回片段。"""
    key = _match(query)
    if key:
        text, source = KB[key]
        return {"hits": [{"source": source, "text": text}]}
    return {"hits": []}


def run(question, history=None):
    history = history or []
    q = (question or "").strip()

    if GREETING.match(q):
        return {"answer": "您好，我在的～请问有什么可以帮您？", "tool_calls": [], "data": {}}

    if PRIVACY.search(q):
        return {"answer": "抱歉，出于隐私保护，无法提供他人的订单或联系方式，请让本人联系人工客服核实。",
                "tool_calls": [], "data": {"refused": True}}

    if UNAUTHORIZED.search(q):
        return {"answer": "抱歉，我无法直接修改订单地址或取消订单；请在「订单详情页」自助修改，或联系人工客服处理。",
                "tool_calls": [], "data": {"refused": True}}

    tool_calls = [{"name": "search_knowledge", "query": q}]
    hits = search_knowledge(q)["hits"]

    if hits:
        text, source = hits[0]["text"], hits[0]["source"]
        if len(q) > 40:
            text = text.split("；")[0]      # 缺陷 1：长问题只答前半
        return {"answer": f"{text}\n\n（来源：{source}）", "tool_calls": tool_calls,
                "data": {"grounded": True}}

    if OUT_OF_SCOPE.search(q):
        # 缺陷 2：知识库没有也硬编（幻觉），评测的风险维度会把整条 case 否掉
        return {"answer": "这个我们支持，随时可以办理，放心。", "tool_calls": tool_calls,
                "data": {"grounded": False}}

    return {"answer": "资料里没有这个信息，建议联系人工客服帮您确认。", "tool_calls": tool_calls,
            "data": {"grounded": False}}
