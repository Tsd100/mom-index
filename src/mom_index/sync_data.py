"""重新生成并发布过滤后的生产看板；不复制原始历史或帖子。"""
from mom_index.analyzer.index_calculator import get_dashboard_data
from mom_index.analyzer.signal import generate_signals
from mom_index.pipeline import publish_dashboard


def sync():
    dashboard = get_dashboard_data()
    dashboard['signals'] = generate_signals(dashboard)
    publish_dashboard(dashboard)
    print(f"已发布 {dashboard['record_count']} 条已核验历史；旧记录和演示数据保持隔离")


if __name__ == '__main__':
    sync()
