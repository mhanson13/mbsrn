from __future__ import annotations

import asyncio
import logging

import app.main as main_module


def _restore_logger_filters(target_logger: logging.Logger, original_filters: list[logging.Filter]) -> None:
    target_logger.filters[:] = original_filters


def test_uvicorn_lifespan_cancelled_filter_suppresses_expected_shutdown_noise(
    monkeypatch,
) -> None:
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    original_filters = list(uvicorn_error_logger.filters)
    lifecycle_events: list[str] = []

    try:
        uvicorn_error_logger.filters.clear()
        monkeypatch.setattr(
            main_module.logger, "info", lambda message, *args, **kwargs: lifecycle_events.append(str(message))
        )
        main_module._install_uvicorn_lifespan_cancelled_error_filter()
        installed_filter = next(
            active_filter
            for active_filter in uvicorn_error_logger.filters
            if isinstance(active_filter, main_module._UvicornLifespanCancelledErrorFilter)
        )

        cancelled_record = logging.LogRecord(
            name="uvicorn.error",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Exception in 'lifespan' protocol",
            args=(),
            exc_info=(asyncio.CancelledError, asyncio.CancelledError(), None),
        )

        assert installed_filter.filter(cancelled_record) is False
        assert "Expected ASGI lifespan cancellation observed during shutdown; suppressing uvicorn error traceback noise." in lifecycle_events
    finally:
        _restore_logger_filters(uvicorn_error_logger, original_filters)


def test_uvicorn_lifespan_cancelled_filter_suppresses_production_like_traceback_record(
    monkeypatch,
) -> None:
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    original_filters = list(uvicorn_error_logger.filters)
    lifecycle_events: list[str] = []

    try:
        uvicorn_error_logger.filters.clear()
        monkeypatch.setattr(
            main_module.logger, "info", lambda message, *args, **kwargs: lifecycle_events.append(str(message))
        )
        main_module._install_uvicorn_lifespan_cancelled_error_filter()
        installed_filter = next(
            active_filter
            for active_filter in uvicorn_error_logger.filters
            if isinstance(active_filter, main_module._UvicornLifespanCancelledErrorFilter)
        )

        cancelled_record = logging.LogRecord(
            name="uvicorn.error",
            level=logging.ERROR,
            pathname="/usr/local/lib/python3.11/site-packages/uvicorn/lifespan/on.py",
            lineno=137,
            msg="ERROR: Traceback (most recent call last):",
            args=(),
            exc_info=(asyncio.CancelledError, asyncio.CancelledError(), None),
        )

        assert installed_filter.filter(cancelled_record) is False
        assert "Expected ASGI lifespan cancellation observed during shutdown; suppressing uvicorn error traceback noise." in lifecycle_events
    finally:
        _restore_logger_filters(uvicorn_error_logger, original_filters)


def test_uvicorn_lifespan_cancelled_filter_keeps_non_lifespan_exceptions() -> None:
    test_filter = main_module._UvicornLifespanCancelledErrorFilter()
    non_lifespan_record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Unhandled ASGI exception",
        args=(),
        exc_info=(RuntimeError, RuntimeError("boom"), None),
    )
    assert test_filter.filter(non_lifespan_record) is True


def test_uvicorn_lifespan_cancelled_filter_keeps_non_lifespan_cancelled_errors() -> None:
    test_filter = main_module._UvicornLifespanCancelledErrorFilter()
    cancelled_record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Background task cancelled during request handling",
        args=(),
        exc_info=(asyncio.CancelledError, asyncio.CancelledError(), None),
    )
    assert test_filter.filter(cancelled_record) is True


def test_install_uvicorn_lifespan_cancelled_filter_is_idempotent() -> None:
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    original_filters = list(uvicorn_error_logger.filters)
    original_info = main_module.logger.info
    lifecycle_events: list[str] = []
    try:
        uvicorn_error_logger.filters.clear()
        main_module.logger.info = lambda message, *args, **kwargs: lifecycle_events.append(str(message))
        main_module._install_uvicorn_lifespan_cancelled_error_filter()
        main_module._install_uvicorn_lifespan_cancelled_error_filter()
        installed = [
            active_filter
            for active_filter in uvicorn_error_logger.filters
            if isinstance(active_filter, main_module._UvicornLifespanCancelledErrorFilter)
        ]
        assert len(installed) == 1
        assert lifecycle_events.count("api_lifespan_cancelled_error_filter_installed target_logger=uvicorn.error") == 1
    finally:
        main_module.logger.info = original_info
        _restore_logger_filters(uvicorn_error_logger, original_filters)
