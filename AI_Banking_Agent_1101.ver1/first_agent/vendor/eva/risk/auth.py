"""R4 逐步认证（step-up）接口与 Demo 实现。

生产环境必须把 `DemoStepUpAuthenticator` 替换成真实的 OTP/生物识别断言服务：
- 前端只把一次性断言交给后端，后端不接收原始 OTP；
- 断言必须绑定 user_id + session_id + preview_hash；
- 断言一次一用，过期即失效。

本模块保留同样的接口，使 Demo 中的 R4 也经过强制校验，而不是仅在文档里声明。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from ..models import new_id


@dataclass(frozen=True)
class StepUpAssertion:
    assertion_id: str
    user_id: str
    session_id: str
    preview_hash: str
    issued_at: str
    expires_at: str
    simulated: bool = True


class StepUpAuthenticator:
    """step-up 断言服务接口。"""

    def issue(
        self,
        *,
        user_id: str,
        session_id: str,
        preview_hash: str,
        ttl_seconds: int = 300,
    ) -> StepUpAssertion:
        raise NotImplementedError

    def verify(
        self,
        assertion_id: str,
        *,
        user_id: str,
        session_id: str,
        preview_hash: str,
    ) -> bool:
        raise NotImplementedError

    def consume(self, assertion_id: str) -> bool:
        raise NotImplementedError


class DemoStepUpAuthenticator(StepUpAuthenticator):
    """仅用于演示：进程内一次性断言，日志明确标记 simulated=True。"""

    def __init__(
        self,
        ttl_seconds: int = 300,
        clock: Callable[[], datetime] | None = None,
    ):
        self.ttl_seconds = ttl_seconds
        self.clock = clock or (lambda: datetime.now().astimezone())
        self._assertions: dict[str, StepUpAssertion] = {}
        self._consumed: set[str] = set()
        self._lock = threading.RLock()

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now

    def issue(
        self,
        *,
        user_id: str,
        session_id: str,
        preview_hash: str,
        ttl_seconds: int | None = None,
    ) -> StepUpAssertion:
        now = self._now()
        expires = now + timedelta(
            seconds=ttl_seconds or self.ttl_seconds
        )
        assertion = StepUpAssertion(
            assertion_id=new_id("ASSERT"),
            user_id=user_id,
            session_id=session_id,
            preview_hash=preview_hash,
            issued_at=now.isoformat(timespec="seconds"),
            expires_at=expires.isoformat(timespec="seconds"),
            simulated=True,
        )
        with self._lock:
            self._assertions[assertion.assertion_id] = assertion
        return assertion

    def verify(
        self,
        assertion_id: str,
        *,
        user_id: str,
        session_id: str,
        preview_hash: str,
    ) -> bool:
        with self._lock:
            assertion = self._assertions.get(assertion_id)
            if assertion is None or assertion_id in self._consumed:
                return False
            if (
                assertion.user_id != user_id
                or assertion.session_id != session_id
                or assertion.preview_hash != preview_hash
            ):
                return False
            try:
                expires = datetime.fromisoformat(assertion.expires_at)
            except ValueError:
                return False
            if expires <= self._now():
                return False
            return True

    def consume(self, assertion_id: str) -> bool:
        with self._lock:
            assertion = self._assertions.get(assertion_id)
            if assertion is None or assertion_id in self._consumed:
                return False
            self._consumed.add(assertion_id)
            return True
