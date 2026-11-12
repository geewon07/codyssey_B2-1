"""Cross-cutting log/timing concern separated from business logic."""
from __future__ import annotations

import logging
from functools import wraps
from time import perf_counter
from typing import Callable, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")
logger = logging.getLogger("budget_app")


def logged_and_timed(func: Callable[P, R]) -> Callable[P, R]:
    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        start = perf_counter()
        logger.info("시작: %s", func.__name__)
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            logger.info("실패: %s (%s)", func.__name__, exc)
            raise
        finally:
            logger.info("완료: %s (%.4f초)", func.__name__, perf_counter() - start)
    return wrapper
