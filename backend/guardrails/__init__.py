"""
VouchFlow AI Guardrails Package
================================
Provides three guardrail layers for the Investigation Agent:
- permissions.py  : Policy table; blocks and logs unauthorized tool actions
- injection.py    : Detects prompt-injection text inside invoice content
- grounding.py    : Verifies every number/clause/supplier in LLM output is in evidence
"""

