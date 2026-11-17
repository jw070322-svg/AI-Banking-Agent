"""Configurable risk matrix. Scores are prototype policy, never banking law."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskResult:
    score: int
    decision: str
    policy_version: str


@dataclass(frozen=True)
class RiskAssessment:
    review_at: int
    block_at: int
    policy_version: str

    def __post_init__(self):
        if (type(self.review_at) is not int or type(self.block_at) is not int
                or not 1 <= self.review_at < self.block_at <= 25
                or not isinstance(self.policy_version, str) or not self.policy_version.strip()):
            raise ValueError("Supply approved integer thresholds (1..25) and a policy version")

    def assess(self, likelihood: int, impact: int) -> RiskResult:
        # The caller must supply validated risk inputs; the LLM cannot invent them.
        if any(type(v) is not int or not 1 <= v <= 5 for v in (likelihood, impact)):
            raise ValueError("Likelihood and impact must be integers from 1 to 5")
        score = likelihood * impact
        decision = "block" if score >= self.block_at else "review" if score >= self.review_at else "pass"
        return RiskResult(score, decision, self.policy_version)
