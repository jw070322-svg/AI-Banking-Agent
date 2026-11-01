"""合规扫描：提示注入识别、PII 检测与脱敏。

合规职责：
- 用户输入中的“绕过限额/审批/风控”等指令必须被识别，涉及资金变动时直接阻断；
- 日志、错误信息和回复文本不得包含完整卡号、手机号、身份证号、OTP、密钥；
- Action Log 写入前统一脱敏，避免“日志本身成为泄露渠道”。

注意：这里只做确定性的正则与规则检查，不把用户文本送去 LLM 判断。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ----------------------------------------------------------------------
# 规则
# ----------------------------------------------------------------------

_INJECTION_CN_RE = re.compile(
    r"(?:忽略|无视|绕过|跳过|不要遵守|不用遵守|别管|不用管|解除|关闭)"
    r"[^。；;\n]{0,16}"
    r"(?:限额|审批|确认|风控|规则|策略|安全|权限|校验|登录|验证)"
)
_INJECTION_EN_RE = re.compile(
    r"(?:ignore|disregard|bypass|override|circumvent)\s+"
    r"(?:all\s+)?(?:the\s+)?(?:previous|prior|above|system)?\s*"
    r"(?:instructions?|rules?|limits?|approvals?|polic(?:y|ies)|"
    r"risk\s*checks?|security|authentication)",
    re.IGNORECASE,
)
_JAILBREAK_RE = re.compile(
    r"(?:system\s*prompt|developer\s*mode|jailbreak|越狱模式|系统提示词)",
    re.IGNORECASE,
)

_ID_CARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){15,18}\d(?!\d)")
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_OTP_RE = re.compile(
    r"((?:验证码|动态码|短信码|otp|OTP)\D{0,8})(\d{4,8})"
)

_SENSITIVE_KEYS = {
    "otp",
    "password",
    "passcode",
    "pin",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "private_key",
    "api_key",
    "card_number",
    "account_number",
    "id_number",
    "approval_token",
    "auth_assertion",
    "auth_assertion_token",
}


@dataclass
class ComplianceFinding:
    code: str
    severity: str  # low / medium / high
    detail: str
    matched: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "detail": self.detail,
            "matched": self.matched,
        }


@dataclass
class ComplianceReport:
    findings: list[ComplianceFinding] = field(default_factory=list)

    @property
    def injection_suspected(self) -> bool:
        return any(
            finding.code
            in {
                "PROMPT_INJECTION_SUSPECTED",
                "JAILBREAK_PATTERN_SUSPECTED",
            }
            for finding in self.findings
        )

    @property
    def pii_found(self) -> bool:
        return any(finding.code == "PII_IN_TEXT" for finding in self.findings)

    @property
    def passed(self) -> bool:
        return not self.injection_suspected

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "injection_suspected": self.injection_suspected,
            "pii_found": self.pii_found,
            "findings": [finding.to_dict() for finding in self.findings],
        }


class ComplianceScanner:
    # ------------------------------------------------------------------
    # 扫描
    # ------------------------------------------------------------------

    def scan_input(self, text: str) -> ComplianceReport:
        findings: list[ComplianceFinding] = []
        text = text or ""

        for match in _INJECTION_CN_RE.finditer(text):
            findings.append(
                ComplianceFinding(
                    "PROMPT_INJECTION_SUSPECTED",
                    "high",
                    "用户输入包含试图绕过限额/审批/风控的指令。",
                    match.group(0),
                )
            )
        for match in _INJECTION_EN_RE.finditer(text):
            findings.append(
                ComplianceFinding(
                    "PROMPT_INJECTION_SUSPECTED",
                    "high",
                    "User input appears to override risk or approval rules.",
                    match.group(0),
                )
            )
        for match in _JAILBREAK_RE.finditer(text):
            findings.append(
                ComplianceFinding(
                    "JAILBREAK_PATTERN_SUSPECTED",
                    "high",
                    "用户输入包含系统提示词/越狱相关模式。",
                    match.group(0),
                )
            )

        pii_hits = self._pii_matches(text)
        if pii_hits:
            findings.append(
                ComplianceFinding(
                    "PII_IN_TEXT",
                    "medium",
                    "输入包含疑似敏感个人信息，写入日志前会被脱敏。",
                    ", ".join(sorted(pii_hits)),
                )
            )

        return ComplianceReport(findings=findings)

    def scan_log_payload(self, payload: Any) -> ComplianceReport:
        """检查即将写日志的结构是否仍含敏感键或 PII。"""
        findings: list[ComplianceFinding] = []
        sensitive_keys: set[str] = set()

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if (
                        str(key).lower() in _SENSITIVE_KEYS
                        and item != "[REDACTED]"
                    ):
                        sensitive_keys.add(str(key))
                    walk(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)
            elif isinstance(value, str):
                if self._pii_matches(value):
                    findings.append(
                        ComplianceFinding(
                            "PII_IN_LOG",
                            "high",
                            "待写入日志的字段包含疑似 PII。",
                            value[:40],
                        )
                    )

        walk(payload)
        if sensitive_keys:
            findings.append(
                ComplianceFinding(
                    "SENSITIVE_KEY_IN_LOG",
                    "high",
                    "待写入日志包含敏感字段：" + ", ".join(sorted(sensitive_keys)),
                )
            )
        return ComplianceReport(findings=findings)

    # ------------------------------------------------------------------
    # 脱敏
    # ------------------------------------------------------------------

    def redact_text(self, text: Any) -> str:
        if text is None:
            return ""
        value = str(text)

        value = _OTP_RE.sub(r"\1[REDACTED_OTP]", value)
        value = _EMAIL_RE.sub("***@***", value)
        value = _ID_CARD_RE.sub("******", value)

        def mask_card(match: re.Match[str]) -> str:
            digits = re.sub(r"\D", "", match.group(0))
            if len(digits) < 12:
                return match.group(0)
            return "**** **** **** " + digits[-4:]

        value = _CARD_RE.sub(mask_card, value)
        value = _PHONE_RE.sub(
            lambda match: match.group(0)[:3] + "****" + match.group(0)[-4:],
            value,
        )
        return value

    def redact_obj(self, value: Any) -> Any:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                if str(key).lower() in _SENSITIVE_KEYS:
                    result[str(key)] = "[REDACTED]"
                else:
                    result[str(key)] = self.redact_obj(item)
            return result
        if isinstance(value, (list, tuple)):
            return [self.redact_obj(item) for item in value]
        if isinstance(value, str):
            return self.redact_text(value)
        return value

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    @staticmethod
    def _pii_matches(text: str) -> set[str]:
        hits: set[str] = set()
        if _ID_CARD_RE.search(text):
            hits.add("id_card")
        if _CARD_RE.search(text):
            hits.add("card_or_account_number")
        if _PHONE_RE.search(text):
            hits.add("phone")
        if _EMAIL_RE.search(text):
            hits.add("email")
        if _OTP_RE.search(text):
            hits.add("otp")
        return hits
