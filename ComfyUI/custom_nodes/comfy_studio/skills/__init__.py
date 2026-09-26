"""skills：把 ComfyUI API 格式工作流 + 参数表包装成可直接调用的 skill。

对外只有四件事：加载（loader）、校验与合并参数（params）、注入参数（runner.build_prompt）、
执行（runner.run_skill）。skill 数据文件放在本包的 ``workflows/`` 下。
"""

from __future__ import annotations

from pathlib import Path

from .loader import load_skill_file, load_skills, validate_skill
from .params import SEED_RANDOM, merge_params
from .runner import (
    SkillExecutionError,
    build_prompt,
    collect_images,
    run_skill,
    submit_prompt,
    wait_for_prompt,
)
from .types import (
    NO_DEFAULT,
    PARAM_TYPES,
    PromptWorkflow,
    Skill,
    SkillOutputImage,
    SkillParam,
    SkillParamType,
    SkillRunResult,
)

#: 随包自带的 skill 目录。
WORKFLOWS_DIR = Path(__file__).resolve().parent / "workflows"

__all__ = [
    "NO_DEFAULT",
    "PARAM_TYPES",
    "SEED_RANDOM",
    "WORKFLOWS_DIR",
    "PromptWorkflow",
    "Skill",
    "SkillExecutionError",
    "SkillOutputImage",
    "SkillParam",
    "SkillParamType",
    "SkillRunResult",
    "build_prompt",
    "collect_images",
    "load_skill_file",
    "load_skills",
    "merge_params",
    "run_skill",
    "submit_prompt",
    "validate_skill",
    "wait_for_prompt",
]
