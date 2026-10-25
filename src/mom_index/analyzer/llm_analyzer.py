"""
宝妈指数 LLM 分析引擎
多维度精准分类，输出有理有据的判定逻辑
"""
from typing import Dict, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import json
import os
import random
from math import isfinite
from mom_index.analyzer.text_rules import asserted_clauses, affirmative_hits, expression_features

# ============================================================
# 信号定义库
# ============================================================

@dataclass
class Signal:
    """单个判定信号"""
    name: str
    weight: float          # 权重 (-5 到 +5, 正=小白, 负=专业)
    description: str       # 人类可读的描述

# ---- 小白信号 (正向) ----
NEWBIE_SIGNALS = [
    Signal("身份自述", 8, "明确自称小白/新手/刚入门/宝妈"),
    Signal("知识求助", 6, "在问基础问题（怎么买/在哪看/什么意思）"),
    Signal("决策依赖", 7, "请求他人替自己做投资决策（该不该/要不要/能不能）"),
    Signal("情绪恐慌", 5, "表达明显的恐惧/焦虑/后悔情绪"),
    Signal("跟风行为", 6, "提及跟别人买/听说/博主推荐/朋友说"),
    Signal("过度乐观", 4, "非理性乐观（梭哈/稳赚/必涨/躺赚）"),
    Signal("短期思维", 3, "关注明天/后天/今天涨跌，非长期视角"),
    Signal("金额极小", 2, "讨论几百几千块的投资，试水心态"),
    Signal("术语缺失", 4, "全文无任何专业术语（PE/PB/ETF/溢价率等）"),
    Signal("互动异常", 3, "大量emoji/感叹号/问号，情绪化表达"),
]

# ---- 专业信号 (负向) ----
PRO_SIGNALS = [
    Signal("专业术语", -5, "使用PE/PB/ROE/基本面/技术面/估值等专业词汇"),
    Signal("策略思维", -4, "讨论定投/仓位/分散/对冲/止损等策略"),
    Signal("数据引用", -4, "引用具体数据/财报/宏观经济指标"),
    Signal("风险意识", -3, "明确提及风险/仅供参考/不构成建议"),
    Signal("长期视角", -3, "讨论长期趋势/定投计划/年度收益"),
    Signal("冷静表达", -2, "理性分析，客观陈述，无情绪化表达"),
]

# 关键词匹配规则
NEWBIE_KEYWORDS = {
    "身份自述": ["小白", "新手", "新人", "刚入", "第一次", "菜鸟", "萌新", "宝妈", "全职妈妈", "学生党"],
    "知识求助": ["不懂", "请教", "各位大哥", "大佬", "请问", "有没有人", "谁知道", "求助", "怎么买", "在哪看", "什么意思"],
    "决策依赖": ["该不该", "要不要", "能不能", "可以吗", "行不行", "靠谱吗", "还能上车吗", "现在入手", "还会涨吗", "还会跌吗"],
    "情绪恐慌": ["好慌", "救命", "完了", "哭了", "怕了", "吓死", "心态崩", "太惨", "亏死了", "割肉", "后悔", "早知道"],
    "跟风行为": ["跟着买的", "别人推荐", "博主说", "听说", "朋友说", "同事买", "群里说", "都在买"],
    "过度乐观": ["冲", "梭哈", "稳赚", "必涨", "躺赚", "满仓干", "起飞", "暴富"],
    "短期思维": ["明天涨", "今天跌", "后天走势", "今天买"],
}

PRO_KEYWORDS = {
    "专业术语": ["PE", "PB", "ROE", "溢价率", "折价", "估值", "基本面", "技术面", "MACD", "KDJ", "ETF", "联接", "LOF"],
    "策略思维": ["定投", "仓位", "分散", "对冲", "止损", "止盈", "网格", "轮动", "资产配置"],
    "数据引用": ["季报", "年报", "GDP", "CPI", "非农", "美联储", "加息", "降息", "收益率", "年化"],
    "风险意识": ["仅供参考", "不构成建议", "个人观点", "理性投资", "风险自担", "谨慎"],
    "长期视角": ["长期持有", "定投计划", "年度", "养老", "十年"],
    "冷静表达": ["分析", "观点", "看法", "逻辑", "原因在于"],
}

# ============================================================
# 分析引擎
# ============================================================

@dataclass
class AnalysisResult:
    """单条帖子的完整分析结果"""
    post_id: str
    title: str
    platform: str
    sector: str
    source_url: str = ""
    
    # 分数
    newbie_score: float = 0.0       # 小白总分 (0-100)
    newbie_confidence: str = "low"   # 置信度: high/medium/low
    
    # 命中信号
    matched_newbie: List[Tuple[str, str, float]] = field(default_factory=list)  
    matched_pro: List[Tuple[str, str, float]] = field(default_factory=list)
    
    # 判定
    level: str = "未判定"      # 纯小白/偏小白/中间派/偏专业/专业
    reasoning: str = ""        # 人类可读的推理过程
    sentiment_score: float = 0  # -1(恐慌) ~ +1(贪婪)
    intent: str = "neutral"     # buy/sell/neutral — 买入/卖出意图
    intent_strength: float = 0  # 0~1 意图强度
    intent_basis: str = ""  # 表达依据不等于成交或持仓证明
    
    # 用于前端展示
    key_signals: List[str] = field(default_factory=list)


def analyze_post(post: Dict, sector: str) -> AnalysisResult:
    """分析单条帖子，返回详细判定"""
    title = post.get("title", "")
    content = post.get("content", "")
    full_text = f"{title}\n{content}" if content else title
    
    # 0. 垃圾过滤
    SPAM_PATTERNS = [
        "我是冲着金条来的",
        "金条来的，你呢",
        "领金条",
        "签到",
        "打卡",
        "广告",
    ]
    for spam in SPAM_PATTERNS:
        if spam in full_text:
            result = AnalysisResult(
                post_id=post.get("id", ""),
                title=title[:80],
                platform=post.get("platform", "unknown"),
                sector=sector,
                source_url=post.get("url", ""),
                newbie_score=0,
                newbie_confidence="high",
                level="垃圾帖",
                reasoning=f"检测到垃圾/活动帖（命中: 「{spam}」），已过滤，不计入指数。",
            )
            return result
    
    result = AnalysisResult(
        post_id=post.get("id", ""),
        title=title[:80],
        platform=post.get("platform", "unknown"),
        sector=sector,
        source_url=post.get("url", ""),
    )
    
    # 1. 逐信号匹配
    matched_newbie = []
    matched_pro = []
    
    for signal in NEWBIE_SIGNALS:
        keywords = NEWBIE_KEYWORDS.get(signal.name, [])
        matched_kws = sorted({kw for clause in asserted_clauses(full_text)
                              for kw in affirmative_hits(clause, keywords)})
        if matched_kws:
            matched_newbie.append((signal.name, signal.description, signal.weight, matched_kws))
    
    for signal in PRO_SIGNALS:
        keywords = PRO_KEYWORDS.get(signal.name, [])
        matched_kws = [kw for kw in keywords if kw.lower() in full_text.lower()]
        if matched_kws:
            matched_pro.append((signal.name, signal.description, signal.weight, matched_kws))
    
    # 2. 额外特征
    # 标题长度很短 + 情绪化
    extra_score = 0
    extra_reasons = []
    
    if len(title) < 12 and any(kw in title for kw in ["涨", "跌", "买", "卖"]):
        extra_score += 3
        extra_reasons.append("标题极短+情绪化，典型小白特征")
    
    if title.endswith("吗") or title.endswith("呢") or title.endswith("？"):
        extra_score += 2
        extra_reasons.append("以问句结尾，在寻求答案")
    
    # 3. 计算总分
    total_newbie = sum(s[2] for s in matched_newbie) + extra_score
    total_pro = abs(sum(s[2] for s in matched_pro))
    
    raw_score = total_newbie - total_pro * 0.8  # 专业信号打8折
    result.newbie_score = max(0, min(100, raw_score * 4 + 10))
    
    # 4. 置信度
    total_signals = len(matched_newbie) + len(matched_pro)
    if total_signals >= 4:
        result.newbie_confidence = "high"
    elif total_signals >= 2:
        result.newbie_confidence = "medium"
    else:
        result.newbie_confidence = "low"
    
    # 5. 判定等级
    s = result.newbie_score
    if s >= 50:
        result.level = "纯小白"
    elif s >= 35:
        result.level = "偏小白"
    elif s >= 20:
        result.level = "中间派"
    elif s >= 10:
        result.level = "偏专业"
    else:
        result.level = "专业投资者"
    
    # 6. 生成推理文本
    result.reasoning = _generate_reasoning(
        title, matched_newbie, matched_pro, extra_reasons,
        total_newbie, total_pro, result
    )
    
    # 7. 情绪分析
    features = expression_features(full_text)
    result.sentiment_score = features['sentiment']
    
    # 8. 买入/卖出意图判定
    result.intent = features['intent']
    result.intent_strength = features['intent_strength']
    result.intent_basis = ('识别到作者的方向表达，不证明实际交易' if result.intent != 'neutral'
                           else '未确认方向：提问、否定、转述、亏损或买卖表达相抵不推断交易')
    
    # 9. 关键信号摘要（用于前端卡片）
    result.key_signals = []
    for name, desc, weight, kws in matched_newbie[:3]:
        result.key_signals.append(f"「{name}」{desc} (命中: {', '.join(kws[:2])})")
    for name, desc, weight, kws in matched_pro[:2]:
        result.key_signals.append(f"「{name}」{desc} (命中: {', '.join(kws[:2])})")
    
    result.matched_newbie = [(n, d, w) for n, d, w, _ in matched_newbie]
    result.matched_pro = [(n, d, w) for n, d, w, _ in matched_pro]
    
    return result


def _generate_reasoning(
    title: str,
    matched_newbie: List[Tuple],
    matched_pro: List[Tuple],
    extra_reasons: List[str],
    total_newbie: float,
    total_pro: float,
    result: AnalysisResult,
) -> str:
    """生成人类可读的推理文本"""
    parts = []
    
    # 开头
    parts.append(f"帖子「{title[:40]}...」")
    
    if not matched_newbie and not matched_pro:
        parts.append("未命中明确的信号词，内容较短或信息不足。")
        parts.append("根据有限信息判定为中间派。")
        return " ".join(parts)
    
    # 小白信号
    if matched_newbie:
        signal_descs = [f"{name}({weight}分)" for name, desc, weight, kws in matched_newbie]
        parts.append(f"命中{len(matched_newbie)}个小信号: {', '.join(signal_descs)}。")
    
    # 专业信号
    if matched_pro:
        signal_descs = [f"{name}({weight}分)" for name, desc, weight, kws in matched_pro]
        parts.append(f"命中{len(matched_pro)}个专业信号: {', '.join(signal_descs)}。")
    
    # 额外
    if extra_reasons:
        parts.extend(extra_reasons)
    
    # 结论
    parts.append(f"综合得分{result.newbie_score}分，")
    parts.append(f"判定为「{result.level}」")
    parts.append(f"(置信度: {result.newbie_confidence})。")
    
    return " ".join(parts)


def _analyze_sentiment(text: str) -> float:
    """情绪分析: -1(恐慌) ~ +1(贪婪)"""
    return expression_features(text)['sentiment']


# ============================================================
# 批量分析
# ============================================================

def analyze_sector(posts: List[Dict], sector: str) -> List[AnalysisResult]:
    """分析一个板块的所有帖子（可选 LLM 抽查复核，默认关闭）"""
    results = []
    for post in posts:
        result = analyze_post(post, sector)
        if llm_spotcheck_enabled() and random.random() < LLM_SAMPLE_RATE:
            result = llm_rejudge(post, result)
        results.append(result)
    
    # 按小白分数排序
    results.sort(key=lambda r: r.newbie_score, reverse=True)
    return results


def analyze_all(sector_data: Dict[str, List[Dict]]) -> Dict[str, List[AnalysisResult]]:
    """分析所有板块"""
    all_results = {}
    for sector, posts in sector_data.items():
        print(f"  分析 {sector}: {len(posts)} 条帖子...")
        all_results[sector] = analyze_sector(posts, sector)
    if llm_used_count() > 0:
        print(f"  🤖 LLM 抽查复核 {llm_used_count()} 条")
    return all_results


# ============================================================
# 可选 LLM 混合分析（默认关闭，设置 MOM_INDEX_LLM_API_KEY 后启用）
# 方向与情绪由本地表达规则确定；LLM 只按采样率抽查讨论特征分。
# ============================================================
LLM_API_KEY = os.environ.get("MOM_INDEX_LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("MOM_INDEX_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_MODEL = os.environ.get("MOM_INDEX_LLM_MODEL", "gpt-4o-mini")
LLM_SAMPLE_RATE = float(os.environ.get("MOM_INDEX_LLM_SAMPLE_RATE", "0.05"))
_llm_used = 0


def llm_spotcheck_enabled() -> bool:
    return bool(LLM_API_KEY) and LLM_SAMPLE_RATE > 0


def llm_used_count() -> int:
    return _llm_used


def _level_for_score(score: float) -> str:
    if score >= 50:
        return "纯小白"
    if score >= 35:
        return "偏小白"
    if score >= 20:
        return "中间派"
    if score >= 10:
        return "偏专业"
    return "专业投资者"


def llm_rejudge(post: Dict, result: AnalysisResult) -> AnalysisResult:
    """用 LLM 复核一条帖子的小白程度（失败时保留规则引擎结果）"""
    global _llm_used
    try:
        import requests as _req

        prompt = (
            "你是散户情绪分析器。判断这条帖子作者的\"小白程度\""
            "（越不懂投资分越高）。\n"
            f"帖子标题: {post.get('title', '')[:120]}\n"
            "只评估文字中的讨论特征，不判断作者身份或提出交易建议。\n"
            "只输出JSON: {\"newbie_score\": 0-100整数}"
        )
        resp = _req.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 150,
            },
            timeout=20,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = json.loads(content[content.find("{"):content.rfind("}") + 1])
        score = float(data.get("newbie_score", result.newbie_score))
        if not isfinite(score):
            raise ValueError('Invalid model score')
        result.newbie_score = max(0, min(100, score))
        result.level = _level_for_score(result.newbie_score)
        # 模型只抽查特征分；方向和情绪继续使用可回放的本地表达规则。
        # 不直接发布任意模型措辞，避免引入交易指令和与规则依据矛盾的解释。
        result.reasoning = f"[模型抽查] 讨论特征分 {result.newbie_score:g}；方向与情绪沿用本地表达规则。"
        result.newbie_confidence = "medium"
        _llm_used += 1
    except Exception:
        pass  # LLM 失败不影响主流程
    return result
