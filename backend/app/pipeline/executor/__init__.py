"""MR executor: safe HTTP client, JSONPath selectors, relation evaluation and runner."""

from app.pipeline.executor.http import FetchResult, SUTClient, UnsafeRequestError, build_url
from app.pipeline.executor.relations import RelationCheck, RelationEvaluationError, evaluate
from app.pipeline.executor.runner import execute_instance, execute_many, execute_mr
from app.pipeline.executor.selectors import SelectorError, select

__all__ = [
    "FetchResult",
    "RelationCheck",
    "RelationEvaluationError",
    "SUTClient",
    "SelectorError",
    "UnsafeRequestError",
    "build_url",
    "evaluate",
    "execute_instance",
    "execute_many",
    "execute_mr",
    "select",
]
