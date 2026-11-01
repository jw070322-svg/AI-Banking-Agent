"""Integration patches over eva scanner and toolkit's explicit scope gate."""
import re
from .vendor.eva.risk.compliance import ComplianceScanner

class Scanner(ComplianceScanner):
    def redact_text(self, value):
        # Preserve exact cryptographic identifiers; never exempt free-text fields.
        text=str(value) if value is not None else ''
        text=re.sub(r'(?i)((?:密码|password|api[_ -]?key|secret|token)\s*[:：=是为]?\s*)[^\s,，;；。]+',r'\1[REDACTED]',text)
        return super().redact_text(text)

    def redact_obj(self, value):
        if isinstance(value,dict):
            return {str(k): (v if str(k) in {'preview_hash','request_hash','sha256','index_sha256','document_sha256'}
                                   and isinstance(v,str) and re.fullmatch(r'(?:sha256:)?[a-f0-9]{64}',v)
                            else '[REDACTED]' if str(k).lower() in {'password','pin','otp','code','token','assertion_id','secret','api_key'}
                            else self.redact_obj(v)) for k,v in value.items()}
        if isinstance(value,(list,tuple)):return [self.redact_obj(x) for x in value]
        if isinstance(value,(str,int)) and not isinstance(value,bool):
            if isinstance(value,int) and not re.fullmatch(r'1[3-9]\d{9}|\d{16,18}',str(value)):return value
            return self.redact_text(value)
        return value
