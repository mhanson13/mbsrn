from __future__ import annotations

import asyncio
import logging

import app.main as main_module


def _restore_logger_filters(target_logger: logging.Logger, original_filters: list[logging.Filter]) -> None:
    target_logger.filters[:] = original_filters


def _capture_lifecycle_events(target: list[str]):
    def _capture(message, *args, **kwargs):  # noqa: ANN001
        rendered = str(message)
        if args:
            try:
                rendered = rendered % args
            except Exception:  # noqa: BLE001
                rendered = str(message)
        target.append(rendered)

    return _capture


def test_uvicorn_lifespan_cancelled_filter_suppresses_expected_shutdown_noise(
    monkeypatch,
) -> None:
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    uvicorn_logger = logging.getLogger("uvicorn")
    original_filters = list(uvicorn_error_logger.filters)
    original_uvicorn_filters = list(uvicorn_logger.filters)
    lifecycle_events: list[str] = []

    try:
        uvicorn_error_logger.filters.clear()
        uvicorn_logger.filters.clear()
        monkeypatch.setattr(main_module.logger, "info", _capture_lifecycle_events(lifecycle_events))
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
        assert (
            "Expected ASGI lifespan cancellation observed during shutdown; suppressing uvicorn error traceback noise."
            in lifecycle_events
        )
    finally:
        _restore_logger_filters(uvicorn_error_logger, original_filters)
        _restore_logger_filters(uvicorn_logger, original_uvicorn_filters)


def test_uvicorn_lifespan_cancelled_filter_suppresses_production_like_traceback_record(
    monkeypatch,
) -> None:
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    uvicorn_logger = logging.getLogger("uvicorn")
    original_filters = list(uvicorn_error_logger.filters)
    original_uvicorn_filters = list(uvicorn_logger.filters)
    lifecycle_events: list[str] = []

    try:
        uvicorn_error_logger.filters.clear()
        uvicorn_logger.filters.clear()
        monkeypatch.setattr(main_module.logger, "info", _capture_lifecycle_events(lifecycle_events))
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
        assert (
            "Expected ASGI lifespan cancellation observed during shutdown; suppressing uvicorn error traceback noise."
            in lifecycle_events
        )
    finally:
        _restore_logger_filters(uvicorn_error_logger, original_filters)
        _restore_logger_filters(uvicorn_logger, original_uvicorn_filters)


def test_uvicorn_lifespan_cancelled_filter_suppresses_traceback_text_without_exc_info(
    monkeypatch,
) -> None:
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    uvicorn_logger = logging.getLogger("uvicorn")
    original_filters = list(uvicorn_error_logger.filters)
    original_uvicorn_filters = list(uvicorn_logger.filters)
    lifecycle_events: list[str] = []

    try:
        uvicorn_error_logger.filters.clear()
        uvicorn_logger.filters.clear()
        monkeypatch.setattr(main_module.logger, "info", _capture_lifecycle_events(lifecycle_events))
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
            msg=(
                "ERROR: Traceback (most recent call last):\n"
                '  File "/usr/local/lib/python3.11/site-packages/starlette/routing.py", line 701, in lifespan\n'
                '  File "/usr/local/lib/python3.11/site-packages/uvicorn/lifespan/on.py", line 137, in receive\n'
                "asyncio.exceptions.CancelledError"
            ),
            args=(),
            exc_info=None,
        )

        assert installed_filter.filter(cancelled_record) is False
        assert (
            "Expected ASGI lifespan cancellation observed during shutdown; suppressing uvicorn error traceback noise."
            in lifecycle_events
        )
    finally:
        _restore_logger_filters(uvicorn_error_logger, original_filters)
        _restore_logger_filters(uvicorn_logger, original_uvicorn_filters)


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


def test_uvicorn_lifespan_cancelled_filter_keeps_non_lifespan_cancelled_traceback_text() -> None:
    test_filter = main_module._UvicornLifespanCancelledErrorFilter()
    cancelled_record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Traceback (most recent call last): asyncio.exceptions.CancelledError in background task",
        args=(),
        exc_info=None,
    )
    assert test_filter.filter(cancelled_record) is True


def test_install_uvicorn_lifespan_cancelled_filter_is_idempotent() -> None:
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    uvicorn_logger = logging.getLogger("uvicorn")
    original_filters = list(uvicorn_error_logger.filters)
    original_uvicorn_filters = list(uvicorn_logger.filters)
    original_info = main_module.logger.info
    lifecycle_events: list[str] = []
    try:
        uvicorn_error_logger.filters.clear()
        uvicorn_logger.filters.clear()
        main_module.logger.info = _capture_lifecycle_events(lifecycle_events)
        main_module._install_uvicorn_lifespan_cancelled_error_filter()
        main_module._install_uvicorn_lifespan_cancelled_error_filter()
        installed_error_logger = [
            active_filter
            for active_filter in uvicorn_error_logger.filters
            if isinstance(active_filter, main_module._UvicornLifespanCancelledErrorFilter)
        ]
        installed_uvicorn_logger = [
            active_filter
            for active_filter in uvicorn_logger.filters
            if isinstance(active_filter, main_module._UvicornLifespanCancelledErrorFilter)
        ]
        assert len(installed_error_logger) == 1
        assert len(installed_uvicorn_logger) == 1
        assert (
            lifecycle_events.count("api_lifespan_cancelled_error_filter_installed target_loggers=uvicorn.error,uvicorn")
            == 1
        )
    finally:
        main_module.logger.info = original_info
        _restore_logger_filters(uvicorn_error_logger, original_filters)
        _restore_logger_filters(uvicorn_logger, original_uvicorn_filters)
