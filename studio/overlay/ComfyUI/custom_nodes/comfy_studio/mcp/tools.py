"""MCP 工具集。

工具名字与语义对齐最初的 TS 实现（``packages/comfy-mcp/src/tools.ts``）：
8 把通用工具，外加「每个 skill 各暴露一把 ``skill__<id>``」，
让 agent 不必先查一遍参数表再拼哈希，直接按 schema 填参即可。

第 8 把是 ``comfy_save_skill``（"方法复用"那条路的入口）：把对话里打磨好的工作流当场
沉淀成用户自己的 skill。skill 的读写都过 :class:`~comfy_studio.skills.registry.SkillRegistry`，
所以存完立刻就能被 ``comfy_run_skill`` 跑起来；``skill__<id>`` 那类静态工具要等下次
重建工具表（工具表是启动时拉的快照）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..engine import EngineClient, EngineError, MODEL_PROBES
from ..skills import PARAM_TYPES, Skill, SkillRegistry

ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "inputSchema": self.input_schema}


def text_result(obj: Any) -> dict[str, Any]:
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    return {"content": [{"type": "text", "text": text}]}


def error_result(err: BaseException) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": f"{type(err).__name__}: {err}"}], "isError": True}


def schema_for(skill: Skill) -> dict[str, Any]:
    """把一个 skill 的参数表翻译成 JSON Schema。"""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in skill.params:
        entry: dict[str, Any] = {"type": param.type, "description": param.hint()}
        if param.has_default:
            entry["default"] = param.default
        properties[param.name] = entry
        if param.required:
            required.append(param.name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _require_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or value == "":
        raise ValueError(f"缺少参数 {key}（应为非空字符串）")
    return value


def skill_entry(skill: Skill) -> dict[str, Any]:
    """skill 在工具返回值里的统一形状（``comfy_list_skills`` 与 ``comfy_save_skill`` 共用）。"""
    return {
        "id": skill.id,
        "title": skill.title,
        "description": skill.description,
        "tags": list(skill.tags),
        "file": skill.source,
        "params": [
            {
                "name": p.name,
                "type": p.type,
                "required": p.required,
                "default": p.default if p.has_default else None,
                "description": p.hint(),
            }
            for p in skill.params
        ],
    }


#: ``comfy_save_skill`` 认识的字段（除 overwrite 外，原样就是 skill 文件的字段）。
SAVE_SKILL_FIELDS = ("id", "title", "description", "tags", "workflow", "params")


def build_tools(engine: EngineClient, registry: SkillRegistry) -> list[Tool]:
    """按引擎句柄 + skill 目录视图组装工具列表。

    ``skill__<id>`` 是**此刻**快照里每个 skill 一把；``comfy_list_skills`` /
    ``comfy_run_skill`` / ``comfy_save_skill`` 则都走 ``registry``，看的是实时结果。
    """

    async def list_models(args: dict[str, Any]) -> Any:
        folder = args.get("folder", "checkpoints")
        if not isinstance(folder, str):
            raise ValueError("folder 必须是字符串")
        return text_result(await engine.list_models(folder))

    async def list_skills(_args: dict[str, Any]) -> Any:
        return text_result([skill_entry(s) for s in registry.all()])

    async def run_skill(args: dict[str, Any]) -> Any:
        skill_id = _require_str(args, "skill_id")
        skill = registry.get(skill_id)
        if skill is None:
            available = ", ".join(s.id for s in registry.all()) or "（无）"
            raise ValueError(f"没有 skill {skill_id}；可用: {available}")
        params = args.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError("params 必须是对象")
        result = await engine.run_skill(skill, params)
        return text_result(result.to_json(engine.base_url))

    async def submit_workflow(args: dict[str, Any]) -> Any:
        workflow = args.get("workflow")
        if not isinstance(workflow, dict) or not workflow:
            raise ValueError("缺少 workflow 参数（API 格式工作流对象）")
        prompt_id = await engine.submit(workflow)
        return text_result({"prompt_id": prompt_id})

    async def save_skill(args: dict[str, Any]) -> Any:
        overwrite = args.get("overwrite", False)
        if not isinstance(overwrite, bool):
            raise ValueError("overwrite 必须是布尔值")
        unknown = sorted(set(args) - set(SAVE_SKILL_FIELDS) - {"overwrite"})
        if unknown:
            # 不装作没看见：多出来的字段不会进文件，但说明调用方对字段名有误解，早点说。
            raise ValueError(
                f"不认识的字段: {', '.join(unknown)}；只认 {', '.join(SAVE_SKILL_FIELDS)}（外加 overwrite）"
            )
        document = {key: args[key] for key in SAVE_SKILL_FIELDS if key in args}
        skill = registry.save(document, overwrite=overwrite)
        return text_result(
            {
                **skill_entry(skill),
                "note": "已存为用户 skill；现在就能用 comfy_run_skill 调用（skill__<id> 要等下次重建工具表）",
            }
        )

    async def get_history(args: dict[str, Any]) -> Any:
        prompt_id = _require_str(args, "prompt_id")
        entry = await engine.history(prompt_id)
        if entry is None:
            raise EngineError(f"history 里没有 prompt {prompt_id}")
        return text_result(entry)

    async def get_queue(_args: dict[str, Any]) -> Any:
        return text_result(await engine.queue())

    async def interrupt(_args: dict[str, Any]) -> Any:
        await engine.interrupt()
        return text_result("interrupted")

    tools = [
        Tool(
            name="comfy_list_models",
            description=(
                "列出本机 ComfyUI 可用的模型文件。"
                f"folder 可选值: {', '.join(MODEL_PROBES)}；默认 checkpoints"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "enum": list(MODEL_PROBES),
                        "description": "模型类别，默认 checkpoints",
                    }
                },
            },
            handler=list_models,
        ),
        Tool(
            name="comfy_list_skills",
            description="列出可用的 skill（参数化工作流模板）及各自的参数定义",
            input_schema={"type": "object", "properties": {}},
            handler=list_skills,
        ),
        Tool(
            name="comfy_run_skill",
            description="运行一个 skill 并等待完成，返回生成的文件。参数定义先看 comfy_list_skills",
            input_schema={
                "type": "object",
                "properties": {
                    "skill_id": {"type": "string", "description": "skill 的 id"},
                    "params": {"type": "object", "description": "skill 参数"},
                },
                "required": ["skill_id"],
            },
            handler=run_skill,
        ),
        Tool(
            name="comfy_save_skill",
            description=(
                "把一个 API 格式工作流沉淀成可复用的 skill（存成用户自己的 skill，以后可反复调用）。"
                "workflow 是 {nodeId: {class_type, inputs}}，params 声明哪些节点的哪个输入暴露给调用方。"
                "来源可以是刚跑通的提交（comfy_get_history 拿回 prompt）或已跑过的工作流；"
                "id/title/description 拿不准就先问用户。同名 skill 默认不覆盖，确认要覆盖才带 overwrite=true"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "skill 的唯一 id，会成为文件名（小写字母/数字/-/_）",
                    },
                    "title": {"type": "string", "description": "给人看的一行标题"},
                    "description": {"type": "string", "description": "这个 skill 干什么、什么时候用"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "可选的标签"},
                    "workflow": {"type": "object", "description": "API 格式工作流 JSON"},
                    "params": {
                        "type": "array",
                        "description": "暴露给调用方的参数表；每一项指向 workflow 里某个节点的某个输入",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "type": {"type": "string", "enum": sorted(PARAM_TYPES)},
                                "node": {"type": "string", "description": "workflow 里的节点 id"},
                                "field": {"type": "string", "description": "该节点的 inputs 键名"},
                                "required": {"type": "boolean"},
                                "default": {"description": "不传时用的值；省略表示没有默认值"},
                                "description": {"type": "string"},
                            },
                            "required": ["name", "type", "node", "field"],
                        },
                    },
                    "overwrite": {"type": "boolean", "description": "同 id 已存在时是否覆盖，默认 false"},
                },
                "required": ["id", "title", "description", "workflow", "params"],
            },
            handler=save_skill,
        ),
        Tool(
            name="comfy_submit_workflow",
            description="直接提交一个 ComfyUI API 格式工作流（{nodeId: {class_type, inputs}}），只排队不等待，返回 prompt_id",
            input_schema={
                "type": "object",
                "properties": {"workflow": {"type": "object", "description": "API 格式工作流 JSON"}},
                "required": ["workflow"],
            },
            handler=submit_workflow,
        ),
        Tool(
            name="comfy_get_history",
            description="查询一次执行的 history 记录（含输出文件）",
            input_schema={
                "type": "object",
                "properties": {"prompt_id": {"type": "string"}},
                "required": ["prompt_id"],
            },
            handler=get_history,
        ),
        Tool(
            name="comfy_get_queue",
            description="查询执行队列（running / pending）",
            input_schema={"type": "object", "properties": {}},
            handler=get_queue,
        ),
        Tool(
            name="comfy_interrupt",
            description="中断当前正在执行的任务",
            input_schema={"type": "object", "properties": {}},
            handler=interrupt,
        ),
    ]

    for skill in registry.all():
        tools.append(
            Tool(
                name=f"skill__{skill.id}",
                description=f"{skill.title} —— {skill.description}",
                input_schema=schema_for(skill),
                handler=_make_skill_handler(engine, skill),
            )
        )
    return tools


def _make_skill_handler(engine: EngineClient, skill: Skill) -> ToolHandler:
    async def handler(args: dict[str, Any]) -> Any:
        result = await engine.run_skill(skill, args)
        return text_result(result.to_json(engine.base_url))

    return handler


__all__ = [
    "SAVE_SKILL_FIELDS",
    "Tool",
    "ToolHandler",
    "build_tools",
    "error_result",
    "schema_for",
    "skill_entry",
    "text_result",
]
