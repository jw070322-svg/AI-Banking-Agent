"""Run actual public requests and save per-index selection evidence as JSON."""
from pathlib import Path
import json
from datetime import datetime
from first_agent.local_wind import load_local_wind
from first_agent.market_data import market_context
from .provider import CN, IndexProvider


def main():
    dataset, error = load_local_wind()
    cards = market_context(dataset, datetime.now(CN).date().isoformat())['indices']
    rows = IndexProvider().resolve(cards)
    path = Path(__file__).resolve().parents[1] / 'reports/指数来源实际联调_1030.json'
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    for row in rows:
        data = row['final_data'] or {}
        print(row['index_code'], row['result_source'], data.get('close'), data.get('as_of'),
              [(s['source'], s['status'], s.get('observation')) for s in row['steps']])
    if error:
        print('Local source:', error)
    print('Saved:', path)


if __name__ == '__main__':
    main()
