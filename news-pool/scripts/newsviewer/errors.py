"""预期内的失败：命令退出码（各自的含义见 SKILL.md）和 API 错误状态码。"""

from __future__ import annotations


class NvError(Exception):
    """有明确退出码的命令失败；消息原样展示给 agent。"""

    exit_code = 1


class UsageError(NvError):
    """参数不对、没有新闻池、<pool>/viewer/config.json 写坏了。"""

    exit_code = 1


class StartFailed(NvError):
    """后台服务没能启动起来；原因见 server.log。"""

    exit_code = 5


INTERNAL_ERROR_EXIT = 5


class ApiError(Exception):
    """API 拒绝的请求；它变成 {"error": message}，HTTP 状态码为这里的 status。"""

    status = 400


class Forbidden(ApiError):
    status = 403


class NotFound(ApiError):
    status = 404


class MethodNotAllowed(ApiError):
    status = 405


class Conflict(ApiError):
    status = 409
