"""预期内的失败。每种都带一个退出码，agent 按退出码行动（见 SKILL.md）。"""

from __future__ import annotations


class NdError(Exception):
    """有确定退出码的失败；消息原样展示给 agent。"""

    exit_code = 1


class UsageError(NdError):
    """参数不对、来源 id 不存在、profile 损坏、步骤顺序不对。"""

    exit_code = 1


class ValidationFailed(NdError):
    """agent 写的文件没通过校验；agent 改好后再运行 `check`。"""

    exit_code = 3


class AllSourcesFailed(NdError):
    """选中的来源全部失败；通常是没网或被沙箱拦截。"""

    exit_code = 4


INTERNAL_ERROR_EXIT = 5
