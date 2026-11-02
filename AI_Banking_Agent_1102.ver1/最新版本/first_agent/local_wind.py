"""Read the fixed, versioned Wind export once; never accept browser file paths."""
from functools import lru_cache
from pathlib import Path
import base64, hashlib, json
from .market_data import import_workbook, MarketError

DATA_DIR = Path(__file__).resolve().parents[1] / 'data' / 'wind'

@lru_cache(maxsize=1)
def load_local_wind():
    try:
        manifest = json.loads((DATA_DIR / 'wind_manifest_20261027.json').read_text(encoding='utf-8'))
        name = 'wind_banking_products_20261027.xlsx'
        if manifest['workbook']['filename'] != name:
            raise ValueError('manifest 文件名不匹配')
        raw = (DATA_DIR / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest['workbook']['sha256']:
            raise ValueError('数据文件与 manifest 的 SHA256 不匹配')
        data = import_workbook(base64.b64encode(raw).decode('ascii'), name)
        data['metadata'].update(load_mode='bundled_snapshot', analysis_date=manifest['analysis_date'],
            min_scoring_points=253, macro_publication_dates_verified=False, bank_unit_nav_unverified=True)
        data['metadata']['warnings'].extend([
            'Wind 为本地历史快照，不是实时行情；权限或计费状况未经核验。',
            '银行理财单位净值的分红再投资口径未确认；历史不足及不可用条款不填补。',
            'ETF 最小申赎份额不是个人买入的现金起购额，未确认门槛的产品不进入排名。',
            '宏观数据非 point-in-time 且发布日期未经独立核验，展示但不触发 PMI 风险门槛。',
            'SHIBOR 隔夜为银行间利率参考，不是无风险国债收益率。'
        ])
        return data, None
    except (OSError, ValueError, KeyError, TypeError, MarketError) as e:
        return None, '本地 Wind 数据未能通过读取或校验：'+str(e)
