"""Development quota guard. Account usage is supplied by a trusted host callback.

Bank customers and LLM arguments cannot supply or override this callback.
No credentials, account ID, or private reasoning are written to the handoff.
"""
import json
import math
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path


class QuotaPaused(RuntimeError):
    pass


class QuotaGuard:
    def __init__(self, provider, output_path, *, user_id='JW', threshold=15, clock=None):
        self.provider, self.output_path = provider, Path(output_path)
        self.user_id, self.threshold = user_id, threshold
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def check(self, operations=(), next_steps=()):
        """Snapshot {observed_at: ISO8601, windows: {name: remaining_percent}}.

        Unknown/stale usage pauses too, but is never represented as zero credit.
        Existing project rule uses <=15, a conservative boundary for <15.
        """
        reason, windows = '', {}
        try:
            snapshot = self.provider()
            observed = datetime.fromisoformat(snapshot['observed_at'])
            now = self.clock()
            if observed.tzinfo is None or not 0 <= (now - observed).total_seconds() <= 300:
                raise ValueError('stale usage')
            windows = snapshot['windows']
            if not isinstance(windows, dict) or not windows:
                raise ValueError('usage unavailable')
            if any(type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 100
                   for value in windows.values()):
                raise ValueError('invalid usage')
            if min(windows.values()) <= self.threshold:
                reason = '任一可信额度窗口剩余小于或等于15%，按项目约定暂停。'
        except Exception:
            windows, reason = {}, '未取得新鲜可信的额度，暂停新的业务与GitHub写操作。'
        if not reason:
            return windows
        payload = {'用户ID': self.user_id, '剩余额度': windows or None,
            '状态': 'paused', '暂停原因': reason,
            '操作记录': list(operations), '后续处理建议': list(next_steps) + [
                '仅保存必要本地交接与审计；不要继续业务修改、测试或GitHub写操作。',
                '用户明确继续后重新读取交接，核验所有可信额度窗口均高于15%。'],
            'timestamp': self.clock().astimezone(timezone(timedelta(hours=8))).isoformat()}
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.output_path.with_suffix(self.output_path.suffix + '.tmp')
        with temporary.open('w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(self.output_path)
        raise QuotaPaused(reason)
