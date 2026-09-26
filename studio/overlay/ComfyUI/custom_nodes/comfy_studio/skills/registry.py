"""skill 的内存视图：读（列/跑）走它，写（存）之后当场 :meth:`SkillRegistry.reload`。

以前 skill 是"进程启动时读一次"的死元组，于是"把对话里打磨好的工作流存成专属 skill"
这条路走不通：存进去也得等重启才认。改成读写都过这一层之后，``save`` 落盘立刻 reload，
紧接着的 ``comfy_run_skill`` 就能跑刚存下的那份。

一处诚实的限制：``skill__<id>`` 那类"每个 skill 一把工具"的工具表是**构建时**的快照
（宿主与 MCP 客户端的工具表也一样，都在启动时拉一次），所以新存的 skill 要立刻可用得走
``comfy_run_skill``；``skill__<id>`` 要等下一次重建工具表。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .loader import validate_skill
from .store import check_skill_id, load_all_skills, load_user_skills, write_skill
from .types import Skill


class SkillRegistry:
    """一份 skill 目录（内置目录 + 用户目录）的内存视图。"""

    def __init__(
        self,
        builtin_dir: str | Path | None = None,
        user_dir: str | Path | None = None,
    ) -> None:
        #: 随包自带的 skill 目录（必须有东西，随包发布）。
        self.builtin_dir = Path(builtin_dir) if builtin_dir is not None else None
        #: 用户自己的 skill 目录（可以还不存在）；``None`` = 这份视图不落盘。
        self.user_dir = Path(user_dir) if user_dir is not None else None
        self._skills: dict[str, Skill] = {}
        self._builtin_ids: frozenset[str] = frozenset()

    # ---- 构造 -----------------------------------------------------------

    @classmethod
    def in_memory(cls, skills: Iterable[Skill]) -> SkillRegistry:
        """只有内存里这些 skill 的视图（测试与临时场景用）；不落盘，``save`` 会报错。"""
        registry = cls()
        registry._install(skills)
        return registry

    # ---- 读 -------------------------------------------------------------

    def reload(self) -> None:
        """按两个目录重新读一遍。id 撞车 / 文件不合法都直接抛错，不做静默跳过。"""
        builtin = ()
        if self.builtin_dir is not None:
            from .loader import load_skills

            builtin = load_skills(self.builtin_dir)
        user = load_user_skills(self.user_dir) if self.user_dir is not None else ()
        # 与 load_all_skills 同一套查重规则，这里手工拼是为了记住"哪些是内置的"。
        self._install((*builtin, *user))
        self._builtin_ids = frozenset(s.id for s in builtin)

    def _install(self, skills: Iterable[Skill]) -> None:
        loaded: dict[str, Skill] = {}
        for skill in skills:
            other = loaded.get(skill.id)
            if other is not None:
                raise ValueError(
                    f"skill id 冲突: {skill.id} 同时来自 {other.source} 与 {skill.source}；请改掉其中一个"
                )
            loaded[skill.id] = skill
        self._skills = loaded

    def all(self) -> tuple[Skill, ...]:
        """全部 skill：内置在前、用户在后的稳定顺序。"""
        return tuple(self._skills.values())

    def get(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def paths(self) -> dict[str, str | None]:
        """两个目录的字符串形式（报错信息与状态接口用）。"""
        return {
            "builtin": str(self.builtin_dir) if self.builtin_dir is not None else None,
            "user": str(self.user_dir) if self.user_dir is not None else None,
        }

    # ---- 写 -------------------------------------------------------------

    def save(self, document: dict, *, overwrite: bool = False) -> Skill:
        """校验一份 skill 文档并落到用户目录；返回加载回来的那份（带真实来源路径）。

        * 文档本身由 :func:`~comfy_studio.skills.loader.validate_skill` 严格校验
          （节点/字段对不对得上都在这里挡掉），不合规就抛 ValueError；
        * id 会被当成文件名，所以额外要求它是个安全的 slug；
        * 内置 skill 同名一律拒绝——那份随包发布，覆盖它既不可能也不该发生；
        * 已经存过同名 skill：不覆盖，除非显式 ``overwrite=True``。
        """
        if self.user_dir is None:
            raise ValueError("这份 skill 视图没有用户目录（不落盘），存不了 skill")
        skill: Skill = validate_skill(document, "<待保存的 skill>")
        check_skill_id(skill.id)
        if skill.id in self._builtin_ids:
            raise ValueError(f"skill id {skill.id} 已被随包自带的 skill 占用；请换一个 id")

        target = self.user_dir / f"{skill.id}.json"
        if target.exists() and not overwrite:
            raise ValueError(
                f"用户目录里已经有 skill {skill.id}（{target}）；确认要覆盖就带上 overwrite=true"
            )

        written = write_skill(skill, self.user_dir)
        self.reload()
        saved = self.get(skill.id)
        if saved is None:
            # 写盘成功却读不回来：说明两边对不上，宁可当场报错也别回一个假的成功。
            raise ValueError(f"skill {skill.id} 写入 {written} 之后没能加载回来")
        return saved


__all__ = ["SkillRegistry"]
