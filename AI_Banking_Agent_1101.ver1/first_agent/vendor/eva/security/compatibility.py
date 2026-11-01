"""Bridge the 1029 scanner interface to the preserved banking application."""
from first_agent.security import Scanner


class CompatibleScanner(Scanner):
    def scan_input(self, text, *, ignore_code_blocks=False):
        # The older scanner does not have a code-block exemption. Keep its
        # complete scan, including code blocks, rather than silently weaken it.
        return super().scan_input(text)

    def scan_untrusted_content(self, source, content):
        return self.scan_input(content, ignore_code_blocks=False)
