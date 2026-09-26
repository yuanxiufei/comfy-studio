"""skills：把 ComfyUI API 格式工作流 + 参数表包装成可直接调用的 skill。

对外是五件事：加载（loader）、校验与合并参数（params）、注入参数（runner.build_prompt）、
执行（runner.run_skill），以及**读写与热视图**（store 落盘、registry 内存视图）——最后一件
是"把对话里打磨好的工作流存成专属 skill"要走的路。随包自带的 skill 数据放在本包的
``workflows/`` 下（只读），用户自己存的落在 store.user_skills_dir()。
"""

from __future__ import annotations

from pathlib import Path

from .loader import load_skill_file, load_skills, skill_to_json, validate_skill
from .params import SEED_RANDOM, merge_params
from .registry import SkillRegistry
from .runner import (
    SkillExecutionError,
    build_prompt,
    collect_images,
    run_skill,
    submit_prompt,
    wait_for_prompt,
)
from .store import (
    USER_SKILLS_DIR_ENV,
    check_skill_id,
    load_all_skills,
    load_user_skills,
    user_skills_dir,
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
    "USER_SKILLS_DIR_ENV",
    "WORKFLOWS_DIR",
    "PromptWorkflow",
    "Skill",
    "SkillExecutionError",
    "SkillOutputImage",
    "SkillParam",
    "SkillParamType",
    "SkillRegistry",
    "SkillRunResult",
    "build_prompt",
    "check_skill_id",
    "collect_images",
    "load_all_skills",
    "load_skill_file",
    "load_skills",
    "load_user_skills",
    "merge_params",
    "run_skill",
    "skill_to_json",
    "submit_prompt",
    "user_skills_dir",
    "validate_skill",
    "wait_for_prompt",
]
