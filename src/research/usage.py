"""Per-run usage accounting propagated through LangGraph's worker context."""
from contextvars import ContextVar
from dataclasses import dataclass, field
import threading


@dataclass
class Usage:
    calls: int = 0
    failures: int = 0
    unknown: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hits: int = 0
    token_reports: int = 0
    lock: object = field(default_factory=threading.Lock)

    def add(self, **values):
        with self.lock:
            for key, value in values.items():
                setattr(self, key, getattr(self, key) + value)

    def snapshot(self):
        with self.lock:
            result = {k: getattr(self, k) for k in ('calls', 'failures', 'unknown', 'input_tokens', 'output_tokens', 'cache_hits')}
            result['token_usage_complete'] = self.calls == self.token_reports
            result['cost_status'] = 'unknown' if self.calls else 'not_applicable'
            return result


CURRENT_USAGE = ContextVar('analysis_usage', default=None)

FAILED_CALLS = ContextVar('failed_model_calls', default=0)
