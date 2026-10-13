"""Агент на Claude, который критикует документы."""

from .agent import CriticConfig, CritiqueError, Document, DocumentCritic
from .schema import Critique, Issue, Score

__all__ = [
    "CriticConfig",
    "Critique",
    "CritiqueError",
    "Document",
    "DocumentCritic",
    "Issue",
    "Score",
]
