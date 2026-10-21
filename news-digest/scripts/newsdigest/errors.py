"""Expected failures. Each carries the exit code the agent acts on (see SKILL.md)."""

from __future__ import annotations


class NdError(Exception):
    """A failure with a defined exit code; its message is shown to the agent as-is."""

    exit_code = 1


class UsageError(NdError):
    """Bad flags, unknown source ids, a broken profile, a step run out of order."""

    exit_code = 1


class ValidationFailed(NdError):
    """An agent-written file is invalid; the agent fixes it and runs `check`."""

    exit_code = 3


class AllSourcesFailed(NdError):
    """Every selected source failed; usually no network or a sandbox."""

    exit_code = 4


INTERNAL_ERROR_EXIT = 5
