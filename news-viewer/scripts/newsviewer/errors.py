"""Expected failures: command exit codes (SKILL.md documents each) and API error statuses."""

from __future__ import annotations


class NvError(Exception):
    """A command failure with a defined exit code; its message is shown to the agent as-is."""

    exit_code = 1


class UsageError(NvError):
    """Bad flags, no pool, a broken <pool>/viewer/config.json."""

    exit_code = 1


class StartFailed(NvError):
    """The background server did not come up; server.log says why."""

    exit_code = 5


INTERNAL_ERROR_EXIT = 5


class ApiError(Exception):
    """A request the API refuses; it becomes {"error": message} with this HTTP status."""

    status = 400


class Forbidden(ApiError):
    status = 403


class NotFound(ApiError):
    status = 404


class MethodNotAllowed(ApiError):
    status = 405


class Conflict(ApiError):
    status = 409
