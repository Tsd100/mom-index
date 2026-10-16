"""板块标的唯一配置。代码身份按官方来源核查；行业覆盖仍属于研究代理。"""
from copy import deepcopy

MAPPING_VERSION = '2026-10-16-v1'
_ROWS = [
    ('nasdaq', '纳斯达克', '159941', '广发纳斯达克100ETF', 'https://www.gffunds.com.cn/funds/?fundcode=159941', '只代表该境内ETF及其股吧，不代表全体美股投资者'),
    ('gold', '黄金', '518880', '华安黄金ETF', 'https://www.huaan.com.cn/funds/518880/index.shtml', '国内黄金ETF，非国际现货金直接报价'),
    ('telecom', '通信', '515880', '国泰通信ETF', 'https://e.gtfund.com/Etrade/Jijin/etflist', '通信设备行业代理，不能等同于纯光纤或纯CPO'),
    ('semiconductor', '半导体', '512480', '国联安半导体ETF', 'https://www.sse.com.cn/disclosure/fund/etflist/detail.shtml?fundid=512480', '半导体产品与设备行业代理'),
    ('innovative_drug', '创新药', '159992', '银华创新药ETF', 'https://www.szse.cn/disclosure/notice/t20200407_575761.html', '中证创新药产业代理'),
    ('nonferrous_metals', '有色金属', '512400', '南方有色金属ETF', 'https://www.sse.com.cn/assortment/fund/list/etfinfo/basic/index.shtml?FUNDID=512400', '中证申万有色金属行业代理'),
    ('new_energy', '新能源', '516160', '南方新能源ETF', 'https://www.nffund.com/main/files/2026/03/20/980714377670.pdf', '中证新能源行业代理'),
    ('power', '电力', '159611', '广发电力ETF', 'https://www.gffunds.com.cn/funds/?fundcode=159611', '中证全指电力公用事业行业代理'),
    ('chip', '芯片', '159995', '华夏半导体芯片ETF', 'https://en.chinaamc.com/etf-connect/chip-etf/', '国证半导体芯片行业代理，与半导体板块存在重叠'),
    ('robot', '机器人', '562500', '华夏机器人ETF', 'https://www.chinaamc.com/fund_en/562500/index.shtml?source=click', '中证机器人行业代理'),
    ('petrochemical', '石油石化', '159731', '华夏石化产业ETF', 'https://accountquery.chinaamc.com/fund/159731/index.shtml?source=click', '中证石化产业代理；旧159930为能源ETF，覆盖范围不同'),
    ('aerospace', '商业航天', '159206', '永赢卫星ETF', 'https://www.szse.cn/disclosure/notice/fund/t20250311_612257.html', '以商用卫星通信代理商业航天，仅覆盖部分产业；旧512710为军工龙头ETF'),
]
SECTORS = {
    key: {'name': name, 'code': 'of' + code, 'etf': code, 'fund_name': fund,
          'mapping_version': MAPPING_VERSION, 'verified_on': '2026-10-16',
          'source_url': url, 'coverage_note': note}
    for key, name, code, fund, url, note in _ROWS
}


def record_instrument(record, sector):
    """仅从该次运行证明中读取，不能把当前配置套到历史记录上。"""
    cfg = record.get('provenance', {}).get('definition', {}).get('sectors', {}).get(sector)
    if not cfg:
        return None
    cfg = deepcopy(cfg)
    override = record.get('sectors', {}).get(sector, {}).get('instrument')
    if override:
        # 重算可以显式纠正价格映射，但必须仍指向原采集股吧。
        if override.get('code') != cfg.get('code'):
            return None
        cfg.update(override)
    if cfg.get('code') != 'of' + str(cfg.get('etf', '')):
        return None
    return cfg
