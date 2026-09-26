"""MCP 工具集。

工具名字与语义对齐最初的 TS 实现（``packages/comfy-mcp/src/tools.ts``）：
7 把通用工具，外加「每个 skill 各暴露一把 ``skill__<id>``」，
让 agent 不必先查一遍参数表再拼哈希，直接按 schema 填参即可。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..engine import EngineClient, EngineError, MODEL_PROBES
from ..skills import Skill

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


def build_tools(engine: EngineClient, skills: tuple[Skill, ...]) -> list[Tool]:
    """按引擎句柄 + 已加载的 skill 组装工具列表。"""

    skill_ids = [s.id for s in skills]

    async def list_models(args: dict[str, Any]) -> Any:
        folder = args.get("folder", "checkpoints")
        if not isinstance(folder, str):
            raise ValueError("folder 必须是字符串")
        return text_result(await engine.list_models(folder))

    async def list_skills(_args: dict[str, Any]) -> Any:
        return text_result(
            [
                {
                    "id": s.id,
                    "title": s.title,
                    "description": s.description,
                    "tags": list(s.tags),
                    "params": [
                        {
                            "name": p.name,
                            "type": p.type,
                            "required": p.required,
                            "default": p.default if p.has_default else None,
                            "description": p.hint(),
                        }
                        for p in s.params
                    ],
                }
                for s in skills
            ]
        )

    async def run_skill(args: dict[str, Any]) -> Any:
        skill_id = _require_str(args, "skill_id")
        skill = next((s for s in skills if s.id == skill_id), None)
        if skill is None:
            raise ValueError(f"没有 skill {skill_id}；可用: {', '.join(skill_ids) or '（无）'}")
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

    for skill in skills:
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


__all__ = ["Tool", "ToolHandler", "build_tools", "error_result", "schema_for", "text_result"]
