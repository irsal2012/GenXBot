"""Test configuration overrides for deterministic backend test behavior."""

from __future__ import annotations

import os


# Keep tests isolated from local developer `.env` overrides.
os.environ["ADMIN_API_TOKEN"] = ""
os.environ["TELEGRAM_OPEN_BY_DEFAULT"] = "false"
os.environ["CHANNEL_OUTBOUND_ENABLED"] = "false"
