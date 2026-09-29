"""MCP 工具集。

工具名字与语义对齐最初的 TS 实现（``packages/comfy-mcp/src/tools.ts``）：
14 把通用工具，外加「每个 skill 各暴露一把 ``skill__<id>``」，
让 agent 不必先查一遍参数表再拼哈希，直接按 schema 填参即可。

第 8 把是 ``comfy_save_skill``（"方法复用"那条路的入口）：把对话里打磨好的工作流当场
沉淀成用户自己的 skill。skill 的读写都过 :class:`~comfy_studio.skills.registry.SkillRegistry`，
所以存完立刻就能被 ``comfy_run_skill`` 跑起来；``skill__<id>`` 那类静态工具要等下次
重建工具表（工具表是启动时拉的快照）。

第 9 把是 ``comfy_list_model_folders``：模型类别是**引擎那边**决定的（``folder_paths``
的键，第三方节点还能自己注册），写死在工具描述里必然落后，所以单独开一把工具让模型
先问类别、再拿类别去 ``comfy_list_models`` 取文件。

紧挨着 ``comfy_render`` 的三把是**工作流库**（``comfy_list_workflows`` / ``comfy_read_workflow`` /
``comfy_write_workflow``）：对着工作流目录里那些**存成文件的 UI 图**做增删改查。开着它们是因为
``comfy_list_renders`` 那 12 条只是"已登记过注入点"的图，而用户手里还有他自己存的、改到一半的、
另存过的 —— 那些图以前只有"拖进编辑器手改"一条路。读写都过 :mod:`comfy_studio.skills.workflows`，
所以越界、盲写、写出转不动的图这三件事在那一层就被挡住了（不在这一层各判一次）。
顺带把 ``comfy_render`` 也放开成"可以按 ``file`` 跑目录里任意一张"：看得到却跑不了，等于没看到。

再往后是联网那三把（``web__search`` / ``web__fetch`` / ``web__crawl``）：本地模型的知识停在
训练那天，而"这个插件现在怎么装""这个报错什么意思"本机查不到。它们在
:mod:`comfy_studio.web` 里定义，**只有给了 ``WebFetcher`` 才挂上**（见 :func:`build_tools`
的 ``fetcher`` 参数）—— 那东西握着一条 aiohttp 连接，谁用谁负责关，不能让这里凭空造一个
没人管的。引擎面板里的对话与引擎侧 MCP 走的是同一批工具（见
:mod:`comfy_studio.agent.loop` 开头那句），所以两边都传同一个句柄。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..engine import EngineClient, EngineError
from ..skills import PARAM_TYPES, Skill, SkillRegistry, param_entry, save_media_batch
from ..skills.render import prepare_render, prepare_render_target, render_listing, workflows_dir
from ..skills.workflows import as_target, list_workflows, read_workflow, write_workflow
from ..web import (
    SEARCH_BACKEND_BING,
    SEARCH_BACKEND_SEARXNG,
    WEB_TOOLS,
    WebConfig,
    WebError,
    WebFetcher,
    call_web_tool,
    check_search_urls,
    qualified_name,
)

#: 关掉引擎侧联网的环境变量（与宿主侧的 ``--no-web`` 同一个意思）。
#: 存在这一条是因为联网会**往外面发请求**：不想让它出门的机器得有个开关，而不是让人去改代码。
NO_WEB_ENV = "COMFY_NO_WEB"

#: 换搜索后端的环境变量（与宿主侧的 ``--searxng-url`` 同一个意思）：填了自建 SearXNG 就用它，
#: 不填走必应 RSS。名字与宿主侧那份（``COMFY_STUDIO_SEARXNG_URL``）刻意不同：两边是**两份独立
#: 的安装**，同一个变量名会让人以为设一个就两边都换了，而实际上引擎起在 ComfyUI 的进程里、
#: 宿主起在桌面壳里，环境根本不是同一份。
SEARXNG_ENV = "COMFY_SEARXNG_URL"

#: 换搜索**入口**的环境变量（与宿主侧的 ``--web-search-url`` 同一个意思）：只想换一个搜索入口
#: （镜像 / 地区域名 / 自建 RSS 代理）而仍然按必应的 RSS 形状读回来时用它。名字与宿主侧那份
#: （``COMFY_STUDIO_WEB_SEARCH_URL``）同样刻意不同，理由同上一条。
SEARCH_URL_ENV = "COMFY_WEB_SEARCH_URL"

#: 环境变量里哪些值算"关"。**只认这几个真值**：写 ``COMFY_NO_WEB=0`` 不算关，
#: 免得"我明明写了变量怎么还联网"变成一场猜谜（默认就是开着的）。
_FALSEY = frozenset({"1", "true", "yes", "on"})

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


def _string_list(args: dict[str, Any], key: str) -> tuple[str, ...]:
    """取一个"字符串数组"参数。给了别的形状就报错 —— 只给一条字符串是最常见的手滑，
    静默当成一项会让"少接了一张图"变成一场没人发现的猜谜。"""
    value = args.get(key) or ()
    if isinstance(value, str):
        raise ValueError(f"{key} 必须是数组（哪怕只有一项也要写成 [\"…\"]）")
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{key} 必须是字符串数组")
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{key} 里每一项都要是非空字符串")
    return tuple(value)


def _optional_number(args: dict[str, Any], key: str) -> float | None:
    """取一个可选的正数参数；不给就是 ``None``（由下游按图上的帧数折算）。"""
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} 必须是数字")
    if value <= 0:
        raise ValueError(f"{key} 必须大于 0，给的是 {value}")
    return float(value)


def _require_str(args: dict[str, Any], key: str) -> str:
    """取一个必填的非空字符串参数。"""
    value = args.get(key)
    if not isinstance(value, str) or value == "":
        raise ValueError(f"缺少参数 {key}（应为非空字符串）")
    return value


def skill_entry(skill: Skill) -> dict[str, Any]:
    """skill 在工具返回值里的统一形状（``comfy_list_skills`` 与 ``comfy_save_skill`` 共用）。

    参数形状取自 :func:`~comfy_studio.skills.params.param_entry` —— 渲染目标那边也用同一份，
    免得前端要对两套键名。
    """
    return {
        "id": skill.id,
        "title": skill.title,
        "description": skill.description,
        "tags": list(skill.tags),
        "file": skill.source,
        "params": [param_entry(p) for p in skill.params],
    }


#: ``comfy_save_skill`` 认识的字段（除 overwrite 外，原样就是 skill 文件的字段）。
SAVE_SKILL_FIELDS = ("id", "title", "description", "tags", "workflow", "params")


def web_enabled(environ: dict[str, str] | None = None) -> bool:
    """联网开关（默认开）。见 :data:`NO_WEB_ENV`。"""
    source = os.environ if environ is None else environ
    return source.get(NO_WEB_ENV, "").strip().lower() not in _FALSEY


def web_config(environ: dict[str, str] | None = None) -> WebConfig:
    """按环境变量拼联网配置：``SEARXNG_ENV`` 给了就换后端，``SEARCH_URL_ENV`` 给了就换入口，
    两个都不给就是必应 RSS 的默认值。

    **不给变量时一律走默认**（必应 RSS）：那条路不用部署任何东西，所以引擎侧"什么都没配"
    也必须可用。给了地址才换成自建实例 —— 那是用户自己架的东西，连不上是他自己的机器/网络
    问题，报错里会带上实例地址与排查方向（见 :meth:`comfy_studio.web.WebFetcher.search`）。

    ``SEARCH_URL_ENV`` 只换入口、不换后端：那种入口仍按必应的 RSS 形状解析
    （``BING_SEARCH_FORMAT``）—— 换的是"去哪儿问"，不是"怎么读回来"。逗号分隔可以给多个
    （前面那个连不上就试后面的），与 ``SEARXNG_ENV`` 的多实例同一个口径。

    **两个都给就报错**（:class:`~comfy_studio.web.WebError`），而不是安静地挑一个：被静默丢掉的
    那个变量，在别人机器上就是"设了却不生效"，这比当场报错难查得多。与宿主侧
    :func:`comfy_studio.web.search_config` 同一条口径 —— 两边各读各的环境，但话得是同一套。
    """
    source = os.environ if environ is None else environ
    url = source.get(SEARXNG_ENV, "").strip()
    entry = source.get(SEARCH_URL_ENV, "").strip()
    if url and entry:
        raise WebError(
            f"{SEARXNG_ENV} 与 {SEARCH_URL_ENV} 只能设一个：前者换搜索后端（自建 SearXNG，"
            "结果多源、带直接答案，代价是自己维护那个实例），后者只换一个搜索入口"
            "（镜像 / 地区域名 / 自建 RSS 代理）"
        )
    if url:
        return WebConfig(search_backend=SEARCH_BACKEND_SEARXNG, searxng_url=url)
    if entry:
        return WebConfig(
            search_url=check_search_urls(entry), search_backend=SEARCH_BACKEND_BING
        )
    return WebConfig()


def build_web_tools(fetcher: WebFetcher) -> list[Tool]:
    """把 :data:`comfy_studio.web.WEB_TOOLS` 那几张定义装配成可调用的 :class:`Tool`。

    失败一律回 ``isError`` 文本而不是抛出去：网址写错、落在禁区、对方回 404，模型都能自己
    换个做法再试（这与 MCP 那一层的兜底是同一条口径，见 :mod:`comfy_studio.mcp.server`）。
    """

    def make(name: str) -> ToolHandler:
        async def handler(args: dict[str, Any]) -> Any:
            try:
                payload = await call_web_tool(fetcher, name, args)
            except WebError as err:
                return error_result(err)
            return text_result(payload)

        return handler

    return [
        Tool(
            # 限定名由这里拼（``web__search``）而不是写在 web.py 里：那一层只管"工具是什么"，
            # 不关心自己在哪个命名空间下（见 comfy_studio.web.WebToolSpec）。
            name=qualified_name(spec.name),
            description=spec.description,
            input_schema=spec.input_schema,
            handler=make(spec.name),
        )
        for spec in WEB_TOOLS
    ]


def build_tools(
    engine: EngineClient, registry: SkillRegistry, fetcher: WebFetcher | None = None
) -> list[Tool]:
    """按引擎句柄 + skill 目录视图组装工具列表。

    ``skill__<id>`` 是**此刻**快照里每个 skill 一把；``comfy_list_skills`` /
    ``comfy_run_skill`` / ``comfy_save_skill`` 则都走 ``registry``，看的是实时结果。

    ``fetcher`` 给了才挂联网那三把 —— 它是调用方建的（连接得有人关），这里不凭空造一个
    没人管的句柄；``fetcher=None`` 时工具表与从前一模一样。
    """

    async def list_model_folders(_args: dict[str, Any]) -> Any:
        return text_result(await engine.list_model_folders())

    async def list_models(args: dict[str, Any]) -> Any:
        folder = args.get("folder", "checkpoints")
        if not isinstance(folder, str) or not folder:
            raise ValueError("folder 必须是非空字符串（类别名见 comfy_list_model_folders）")
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

    async def list_renders(_args: dict[str, Any]) -> Any:
        # 装配只有一处（render.render_listing），面板那条 GET 路由取的也是它。
        return text_result(render_listing(workflows_dir()))

    async def render_target(args: dict[str, Any]) -> Any:
        target_id = args.get("target_id")
        file = args.get("file")
        if (target_id is None) == (file is None):
            raise ValueError(
                "target_id 与 file 二选一：登记过的渲染目标用 target_id（见 comfy_list_renders），"
                "工作流目录里任意一张图用 file（见 comfy_list_workflows）"
            )
        params = args.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError("params 必须是对象")
        images = _string_list(args, "images")
        duration_sec = _optional_number(args, "duration_sec")
        output_dir = args.get("output_dir")
        if output_dir is not None and (not isinstance(output_dir, str) or not output_dir.strip()):
            raise ValueError("output_dir 必须是目录路径（不给就只回引擎里那些产物的地址）")

        if target_id is not None:
            if not isinstance(target_id, str) or not target_id:
                raise ValueError("target_id 必须是非空字符串")
            plan = await prepare_render(engine, target_id, images=images, duration_sec=duration_sec)
        else:
            # 目录里没登记过注入点的图：包成"没有参数"的目标来跑（全按图上原值）。
            plan = await prepare_render_target(
                engine, as_target(file, workflows_dir()), images=images, duration_sec=duration_sec
            )
        result = await engine.run_skill(plan.skill, params)
        payload: dict[str, Any] = {**result.to_json(engine.base_url), "target": plan.target.id}
        # 组装期的让步（时长是按帧数折的、接的是外部组）必须带给模型：它可能据此改提示词或改接法。
        if plan.notes:
            payload["notes"] = list(plan.notes)
        if output_dir is not None:
            saved = await save_media_batch(result.media, output_dir, base_url=engine.base_url)
            payload["saved"] = [str(path) for path in saved]
        return text_result(payload)

    async def list_workflow_files(_args: dict[str, Any]) -> Any:
        return text_result(list_workflows(workflows_dir()))

    async def read_workflow_file(args: dict[str, Any]) -> Any:
        file = _require_str(args, "file")
        raw = args.get("raw", False)
        if not isinstance(raw, bool):
            raise ValueError("raw 必须是布尔值")
        unknown = sorted(set(args) - {"file", "raw"})
        if unknown:
            raise ValueError(f"不认识的字段: {', '.join(unknown)}；只认 file / raw")
        payload = read_workflow(
            file, workflows_dir(), object_info=await engine.object_info(), raw=raw
        )
        return text_result(payload)

    async def write_workflow_file(args: dict[str, Any]) -> Any:
        file = _require_str(args, "file")
        unknown = sorted(set(args) - {"file", "base_digest", "workflow", "edits"})
        if unknown:
            raise ValueError(
                f"不认识的字段: {', '.join(unknown)}；只认 file / base_digest / workflow / edits"
            )
        if args.get("base_digest") is None:
            # 库里也拦这一条，但那儿的报错面向调用方；这里先说清楚该做什么。
            raise ValueError(
                "缺 base_digest：先 comfy_read_workflow 读一遍，把它回的 digest 原样带过来（防止盖掉"
                "用户刚在前端保存的版本）；新建一份整图时给空字符串"
            )
        workflow = args.get("workflow")
        edits = args.get("edits")
        if (workflow is None) == (edits is None):
            raise ValueError("workflow（整份图）与 edits（按字段改值）要给且只给一个")
        if workflow is not None and not isinstance(workflow, dict):
            raise ValueError("workflow 必须是对象（UI 图，含 nodes 数组）；API 格式的图走 comfy_submit_workflow")
        if edits is not None and not isinstance(edits, list):
            raise ValueError("edits 必须是数组，每项 {node, field, value}")
        return text_result(
            write_workflow(
                file,
                workflows_dir(),
                base_digest=args["base_digest"],
                workflow=workflow,
                edits=edits,
                object_info=await engine.object_info(),
            )
        )

    tools = [
        Tool(
            name="comfy_list_models",
            description=(
                "列出本机某个类别下已安装的模型文件名（例如 checkpoints 里的底模、loras 里的 LoRA）。"
                "folder 取 comfy_list_model_folders 报出来的类别名，默认 checkpoints；"
                "不确定类别名就先问那把工具，不要自己猜"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": (
                            "模型类别名（例如 checkpoints / loras / vae / text_encoders），默认 checkpoints；"
                            "不确定就先调 comfy_list_model_folders"
                        ),
                    }
                },
            },
            handler=list_models,
        ),
        Tool(
            name="comfy_list_model_folders",
            description=(
                "列出本机 ComfyUI 已注册的**模型类别**。类别由引擎的 folder_paths 决定，"
                "除自带那些（checkpoints / loras / vae / controlnet …）以外，第三方自定义节点"
                "注册的目录也在里面。要查某个类别下究竟有哪些文件，拿这里的名字去调 comfy_list_models"
            ),
            input_schema={"type": "object", "properties": {}},
            handler=list_model_folders,
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
        Tool(
            name="comfy_list_renders",
            description=(
                "列出这台机器上配好的**渲染目标**（角色定妆板 / 场景卡 / 视频试片 / 音乐 / 补帧 …）："
                "每个目标对应一张现成的生产工作流 + 一列可填参数，用 comfy_render 跑它。"
                "先看这里再动手 —— 目标 id 与参数名不要猜；file_exists=false 表示那张图不在。"
                "这里只有**登记过**的目标：工作流目录里其余的图（用户自己存的、另存过的）"
                "用 comfy_list_workflows 看，那些没有参数表，comfy_render 带 file 按图上原值跑"
            ),
            input_schema={"type": "object", "properties": {}},
            handler=list_renders,
        ),
        Tool(
            name="comfy_render",
            description=(
                "跑一个渲染目标并等待完成，返回产物地址（给了 output_dir 就落盘并回文件路径）。"
                "参数定义与目标 id 由 comfy_list_renders 给出；工作流目录里没登记过的图改用 file 跑"
                "（那种图没有参数可填，全按图上原值）。"
                "images 只在视频目标上有用：按顺序对应提示词里的「图片1、图片2…」"
                "（试片/母版是首帧、尾帧；多镜连贯是参考素材），是**这台机器上的文件路径**，"
                "内部会先搬进引擎 input/。这种时候 duration_sec 最好显式给（不给按图上帧数折算）"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "target_id": {
                        "type": "string",
                        "description": "渲染目标 id，见 comfy_list_renders（与 file 二选一）",
                    },
                    "file": {
                        "type": "string",
                        "description": (
                            "工作流文件名，见 comfy_list_workflows（与 target_id 二选一）："
                            "没登记过注入点的图用这条按图上原值跑，params 就没得填"
                        ),
                    },
                    "params": {"type": "object", "description": "该目标的参数（名字见 comfy_list_renders）"},
                    "images": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "参考图/首尾帧的文件路径，按「图片1、图片2…」顺序；只有视频目标收",
                    },
                    "duration_sec": {
                        "type": "number",
                        "description": "每组时长（秒）。接了参考图（外部组）时组的这个字段必填，不给就按图上帧数折算",
                    },
                    "output_dir": {"type": "string", "description": "给就把产物落进这个目录并按顺序回路径"},
                },
            },
            handler=render_target,
        ),
        Tool(
            name="comfy_list_workflows",
            description=(
                "列出工作流目录里的**每一份工作流文件**（不只是 comfy_list_renders 登记过的那 12 条）："
                "用户自己存的、改到一半的、另存过的图都在这儿。used_by 为空的那批是还没登记成渲染目标的"
                "图 —— 它们照样能用 comfy_render 的 file 参数跑（按图上原值）。"
                "要改一张图或新建一张，先 comfy_read_workflow 读、再 comfy_write_workflow 写回"
            ),
            input_schema={"type": "object", "properties": {}},
            handler=list_workflow_files,
        ),
        Tool(
            name="comfy_read_workflow",
            description=(
                "读工作流目录里的一份 UI 图，返回**按字段名摊开的节点清单**：每个节点的 widgets 就是它的"
                "可改字段（steps / seed / text / fps …，动态下拉的子字段是 selection.tau 这种点号名），"
                "wired_in 是走连线的口（改图上那种值没用）。同时回 digest —— 改完写回时原样当 base_digest。"
                "要动结构（加节点、接线）才加 raw=true 拿整份原始图；平时别要，位置数组又大又难改"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "工作流文件名，见 comfy_list_workflows"},
                    "raw": {"type": "boolean", "description": "是否附带整份原始 UI 图，默认 false"},
                },
                "required": ["file"],
            },
            handler=read_workflow_file,
        ),
        Tool(
            name="comfy_write_workflow",
            description=(
                "把工作流写回磁盘，两种改法二选一。edits 按字段改值（每项 {node, field, value}，field 取"
                "comfy_read_workflow 摊出来的 widgets 键名）：写完先试转成 API 格式，转不动就不落盘。"
                "workflow 整份替换（要动结构时用）：会逐条报出新增/删除/改了哪些节点。"
                "base_digest 必填 —— 先读一遍把它回的 digest 带过来，免得盖掉用户刚在前端保存的版本；"
                "新建一份整图时给空字符串。覆盖前的旧版会留在 _backups/ 里，改错了可以退回去"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "工作流文件名，见 comfy_list_workflows"},
                    "base_digest": {
                        "type": "string",
                        "description": "comfy_read_workflow 回的 digest（乐观锁）；新建整图时给空字符串",
                    },
                    "edits": {
                        "type": "array",
                        "description": "按字段改值，每项 {node, field, value}",
                        "items": {
                            "type": "object",
                            "properties": {
                                "node": {"type": "string", "description": "节点 id（清单里那个 id 字符串）"},
                                "field": {"type": "string", "description": "字段名，见该节点的 widgets"},
                                "value": {"description": "新值，类型照节点定义（整数 / 浮点 / 字符串 / 布尔）"},
                            },
                            "required": ["node", "field", "value"],
                        },
                    },
                    "workflow": {"type": "object", "description": "整份 UI 图对象（含 nodes 数组）"},
                },
                "required": ["file", "base_digest"],
            },
            handler=write_workflow_file,
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
    if fetcher is not None:
        tools.extend(build_web_tools(fetcher))
    return tools


def _make_skill_handler(engine: EngineClient, skill: Skill) -> ToolHandler:
    async def handler(args: dict[str, Any]) -> Any:
        result = await engine.run_skill(skill, args)
        return text_result(result.to_json(engine.base_url))

    return handler


__all__ = [
    "NO_WEB_ENV",
    "SAVE_SKILL_FIELDS",
    "SEARXNG_ENV",
    "Tool",
    "ToolHandler",
    "build_tools",
    "build_web_tools",
    "error_result",
    "schema_for",
    "skill_entry",
    "text_result",
    "web_config",
    "web_enabled",
]
