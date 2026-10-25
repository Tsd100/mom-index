"""有限中文表达规则：宁可保留方向未知，也不把否定、转述、亏损当作交易。"""
import re

BUY_ACTIONS = ('买入', '买了', '加仓', '补仓', '建仓', '入手', '已入', '已上车', '抄底', '梭哈', '满仓')
SELL_ACTIONS = ('卖出', '卖了', '割肉', '止损', '清仓', '减仓', '赎回', '离场', '下车')
GREED_WORDS = ('冲', '梭哈', '稳赚', '必涨', '躺赚', '满仓', '抄底', '起飞', '暴涨', '翻倍', '赚了', '盈利')
FEAR_WORDS = ('割肉', '止损', '亏', '跌惨', '暴跌', '崩盘', '完了', '套牢', '深套', '赔了', '大跌')
_REPORTED = re.compile(r'(朋友|同事|博主|大佬|老师|网友|群里|有人|他们|别人|媒体).{0,4}(说|喊|建议|推荐|称)|听说|据说|转发|转述')
_THIRD_PERSON = re.compile(r'^(?:我的|我有个|我)?(?:朋友|同事|博主|大佬|老师|网友|群里|有人|他们|别人|媒体|他|她)')
_QUESTION = re.compile(r'[?？吗么]|是否|要不要|该不该|能不能|可不可以|会不会|还能|咋办')
_NEGATION = re.compile(r'不|没|别|莫|勿|并非|未|拒绝|停止|避免|谨防')


def asserted_clauses(text):
    """引用和第三方转述不归因于作者；转折后可重新表达作者立场。"""
    text = re.sub(r'“[^”]*”|「[^」]*」|『[^』]*』|"[^"\n]*"', '', text)
    text = re.sub(r'但是|不过|然而|但|(?=可我)', '。', text)
    clauses, reported, question_target = [], False, None
    for part in re.split(r'([，,。；;！!\n？?])', text):
        if part in ('。', '；', ';', '！', '!', '\n'):
            reported = False
            question_target = None
            continue
        if part in ('？', '?'):
            if question_target is not None:
                clauses[question_target] += part
            reported = False
            question_target = None
            continue
        question_target = None
        part = part.strip()
        if not part or part in ('，', ','):
            continue
        if _REPORTED.search(part) or _THIRD_PERSON.search(part):
            reported = True
        elif part.startswith(('我', '本人')):
            reported = False
        if not reported:
            clauses.append(part)
            question_target = len(clauses) - 1
    return clauses


def affirmative_hits(clause, words):
    """最长词优先，重叠命中只算一次；同一分句前缀否定时保守排除。"""
    hits, occupied = [], set()
    for word in sorted(set(words), key=lambda value: (-len(value), value)):
        for match in re.finditer(re.escape(word), clause, flags=re.IGNORECASE):
            span = set(range(match.start(), match.end()))
            if span & occupied:
                continue
            occupied.update(span)
            prefix = clause[:match.start()]
            if not _NEGATION.search(prefix):
                hits.append(word)
    return hits


def expression_features(text):
    clauses = asserted_clauses(text)
    buy = sell = greed = fear = 0
    for clause in clauses:
        greed += len(affirmative_hits(clause, GREED_WORDS))
        fear += len(affirmative_hits(clause, FEAR_WORDS))
        if not _QUESTION.search(clause):
            buy += len(affirmative_hits(clause, BUY_ACTIONS))
            sell += len(affirmative_hits(clause, SELL_ACTIONS))
    intent = 'buy' if buy > sell else 'sell' if sell > buy else 'neutral'
    return {'intent': intent, 'intent_strength': min(1.0, abs(buy - sell) / 5),
            'sentiment': round((greed - fear) / (greed + fear), 2) if greed + fear else 0.0}
