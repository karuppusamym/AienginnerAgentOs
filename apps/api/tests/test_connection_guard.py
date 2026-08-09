"""Standalone unit tests for the per-connector concurrency guard.

No database or FastAPI app needed here -- this exercises the semaphore
logic in app/connection_guard.py directly, the same module
connector_runtime.execute_connector_query() relies on to cap simultaneous
physical connections against one source system.
"""
from __future__ import annotations

import os
import threading
import time
import unittest
from unittest.mock import patch

from app.connection_guard import ConnectionLimitExceeded, limit_connector_concurrency, max_concurrent_connections


class ConnectionGuardTests(unittest.TestCase):
    def test_default_limit_is_a_positive_integer(self) -> None:
        self.assertGreaterEqual(max_concurrent_connections(), 1)

    def test_env_override_is_respected(self) -> None:
        with patch.dict(os.environ, {"CONNECTOR_MAX_CONCURRENT_CONNECTIONS": "3"}):
            self.assertEqual(max_concurrent_connections(), 3)

    def test_invalid_env_value_falls_back_to_default(self) -> None:
        with patch.dict(os.environ, {"CONNECTOR_MAX_CONCURRENT_CONNECTIONS": "not-a-number"}):
            self.assertEqual(max_concurrent_connections(), 8)

    def test_slots_are_released_after_use(self) -> None:
        connector_id = "guard-test-sequential"
        with patch.dict(os.environ, {"CONNECTOR_MAX_CONCURRENT_CONNECTIONS": "1"}):
            for _ in range(5):
                with limit_connector_concurrency(connector_id, wait_seconds=1.0):
                    pass  # each call must succeed once the previous one released its slot

    def test_exceeding_the_limit_raises_instead_of_blocking_forever(self) -> None:
        connector_id = "guard-test-limit"
        with patch.dict(os.environ, {"CONNECTOR_MAX_CONCURRENT_CONNECTIONS": "2"}):
            release_event = threading.Event()
            both_entered = threading.Event()
            entered_count = 0
            count_lock = threading.Lock()

            def hold_a_slot() -> None:
                nonlocal entered_count
                with limit_connector_concurrency(connector_id, wait_seconds=2.0):
                    with count_lock:
                        entered_count += 1
                        if entered_count == 2:
                            both_entered.set()
                    release_event.wait(timeout=5)

            holders = [threading.Thread(target=hold_a_slot) for _ in range(2)]
            for holder in holders:
                holder.start()
            both_entered.wait(timeout=5)  # both holders now occupy the 2 available slots

            started = time.perf_counter()
            with self.assertRaises(ConnectionLimitExceeded):
                with limit_connector_concurrency(connector_id, wait_seconds=0.3):
                    pass
            elapsed = time.perf_counter() - started
            self.assertGreaterEqual(elapsed, 0.25)  # actually waited, not an instant reject
            self.assertLess(elapsed, 2.0)  # but didn't block forever

            release_event.set()
            for holder in holders:
                holder.join(timeout=5)

    def test_different_connectors_have_independent_budgets(self) -> None:
        with patch.dict(os.environ, {"CONNECTOR_MAX_CONCURRENT_CONNECTIONS": "1"}):
            hold_event = threading.Event()
            entered_event = threading.Event()

            def hold_connector_a() -> None:
                with limit_connector_concurrency("guard-test-a", wait_seconds=2.0):
                    entered_event.set()
                    hold_event.wait(timeout=5)

            holder = threading.Thread(target=hold_connector_a)
            holder.start()
            entered_event.wait(timeout=5)
            try:
                # Connector B's budget is untouched by connector A being saturated.
                with limit_connector_concurrency("guard-test-b", wait_seconds=1.0):
                    pass
            finally:
                hold_event.set()
                holder.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
