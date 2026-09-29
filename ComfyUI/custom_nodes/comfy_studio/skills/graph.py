"""UI 图工作流 → ComfyUI API 格式（提交给 ``/prompt`` 的 ``{节点 id: {class_type, inputs}}``）。

为什么不能只靠「无 link 项按序取 widgets_values[i]」：
    那条口径是本仓既有的 ``graph_to_api`` 留下的（原 ``src/image_provider.py``，随引擎树
    删除，判据留在 ``tools/patch-image-recipes.py`` 的注释里）。2026-09-28 拿
    ``ComfyUI/user/default/workflows/AIGC中国风漫剧`` 的 12 张真文件逐节点量过，它在两代
    前端导出的图上都对不齐：

    * 新版前端把「已被转成连线输入的 widget」的值照样留在 ``widgets_values`` 里占位
      （``CreateVideo`` 的 ``fps``：inputs 里它带 link，值 24.0 仍占一位）；
    * ``seed`` 这类字段后面会多一个 ``control_after_generate`` 值（``"fixed"`` /
      ``"randomize"`` / ``"increment"``），它不属于节点定义；
    * ``COMFY_DYNAMICCOMBO_V3``（动态下拉）选中的选项会带出自己的子 widget，值紧跟在
      选中 key 后面。

    所以这里改成**以 ``/object_info`` 的 ``INPUT_TYPES`` 顺序为准**逐个字段对位，多一个
    少一个都显式报错，绝不静默丢值。

事实出处（2026-09-28 逐条核过本机在跑的引擎）：
    * ``/history`` 里引擎真收到过的报文（MiniMaxH3Director，04_视频_768p试片_fl2v）：
      ``seed`` 后面那个 ``"fixed"`` 没有进 API；连线写成 ``["13", 0]``；optional 的
      widget 是**带定义默认值**提交的（``CreateVideo``：``color_space="sRGB"``、
      ``codec="none"``，与 ``/object_info`` 里的 default 逐字相同）。
    * 动态下拉（``COMFY_DYNAMICCOMBO_V3``）在报文里是**点号扁平键**：``"selection"``
      与 ``"selection.tau"`` 平铺在同一层（SaveVideo 则是 ``"format"`` 与
      ``"format.codec"``）。与 ``comfy_api/latest/_io.py`` 里 ``DynamicCombo.
      _expand_schema_for_dynamic`` 用 ``finalize_prefix`` 拼前缀的写法一致；引擎执行前
      会把它收拢成 ``{"selection": "sol-attn", "tau": 1.3}`` 再交给节点，所以
      ``comfy_extras/nodes_sparse_attention.py`` 里读的是 ``selection["selection"]``。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

__all__ = ["GraphConvertError", "GraphResult", "API_WORKFLOW_FORMAT", "graph_to_api", "widget_slots"]

#: 本模块产出的形状（写进 skill 定义时用它做校验用）。
API_WORKFLOW_FORMAT = "comfy_api_workflow"

# 连线口类型：值来自上游节点输出，不占 widgets_values。
# 不在这张表里的字段一律当 widget（INT/FLOAT/STRING/BOOLEAN/COMBO 这些基本类型，以及
# BDGROUP、COMFY_DYNAMICCOMBO_V3 这类"要占一个值"的自定义 widget 类型）。
# 命中不到的情况不会静默：对不上位会报 GraphConvertError 并列出多余的值。
_WIRE_TYPES = frozenset({
    "*", "MODEL", "CLIP", "VAE", "IMAGE", "MASK", "LATENT", "CONDITIONING", "AUDIO",
    "VIDEO", "SIGMAS", "GUIDER", "SAMPLER", "CONTROL_NET", "STYLE_MODEL", "GLIGEN",
    "UPSCALE_MODEL", "INTERP_MODEL", "CLIP_VISION", "CLIP_VISION_OUTPUT",
    "MMX_DIR_GROUP", "MMX_DIR_REFINE",
})

# 动态输入（值按名字散落在 UI 图的 inputs 里，不占 widgets_values）：按前缀判。
_DYNAMIC_INPUT_PREFIX = "COMFY_AUTOGROW"

#: 前端的隐式「生成后操作」选择器：跟在 seed 一类字段后面，值只可能是这三种。
_GENERATE_MODES = frozenset({"fixed", "randomize", "increment"})

# litegraph 的虚拟节点：不参与执行，不进 API 报文。
_VIRTUAL_TYPES = frozenset({"Reroute", "PrimitiveNode", "Note", "MarkdownNote"})


class GraphConvertError(RuntimeError):
    """UI 图转不成 API 格式。报错信息必须带节点 id 与类型，好直接去图上定位。"""


@dataclass
class GraphResult:
    """转换结果。``notes`` 是"看得见的让步"，例如可选 widget 没值走了节点默认。"""

    graph: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def graph_to_api(doc: dict[str, Any], object_info: dict[str, Any], *, source: str = "") -> GraphResult:
    """把一份 UI 图（``workflow`` 格式）转成 API 格式。

    ``object_info`` 是 ``/object_info`` 的返回（``{class_type: {...}}``），**必须传**：
    节点定义的字段顺序是唯一的对位依据，缺了它就只能猜，所以这里不给默认值。
    """
    where = f"{source}：" if source else ""
    nodes = doc.get("nodes")
    if not isinstance(nodes, list):
        raise GraphConvertError(f"{where}不是一份 UI 图：缺少 nodes 数组")
    links = _link_index(doc)
    result = GraphResult()
    for node in nodes:
        node_id, ctype = node.get("id"), node.get("type")
        if ctype in _VIRTUAL_TYPES or node.get("mode") in (2, 4):
            continue
        info = object_info.get(ctype)
        if info is None:
            raise GraphConvertError(
                f"{where}节点 #{node_id} 的类型 {ctype!r} 不在本机引擎的节点表里（节点没装？）")
        if not (info.get("output") or []):
            result.notes.append(f"{where}节点 #{node_id} {ctype} 没有输出，不进 API 报文")
            continue
        result.graph[str(node_id)] = {
            "class_type": ctype,
            "inputs": _node_inputs(node, info, links, result.notes, where),
        }
    if not result.graph:
        raise GraphConvertError(f"{where}转换后没有任何可执行节点（是不是全被 mute / bypass 了？）")
    return result


def widget_slots(node: dict[str, Any], info: dict[str, Any]) -> dict[str, int]:
    """``{字段名: widgets_values 里的下标}``（动态下拉的子字段用点号扁平名，同 API 报文的键）。

    为什么要有这张表：UI 图的 ``widgets_values`` 是**纯位置数组**，图上不带字段名 —— 想按
    "改 steps" 去动它，只能先知道 steps 是第几格。让调用方自己去数，等于把
    :func:`_node_inputs` 里那些坑（``control_after_generate`` 多占一位、动态下拉自带子 widget、
    已被连线占位的 widget 仍留值）在外面重踩一遍，迟早两处口径不一致。

    这里与 :func:`_node_inputs` 共用同一套推进规则（``_skip_one`` / ``_fields_from_option``），
    所以"这张表指的那一格"与"转换时读的那一格"必然是同一格。

    * **已被连线占位的字段不进表**：它的值不在这条链上，改它没用（转换时会跳过该值）。
    * 下标可能等于 ``len(widgets_values)``：图上没给值、定义里却有默认，那种字段要改就得先
      把数组补到这一格（见 ``skills/workflows.py`` 的改值那段）。
    """
    values = node.get("widgets_values")
    if isinstance(values, dict):  # 老格式按名字存：按定义顺序摆成一个数组来看待（同 _node_inputs）
        values = [values.get(name) for _section, name, _spec in _widget_fields(info)]
    if not isinstance(values, list):
        values = []
    wired = {item.get("name") for item in node.get("inputs") or [] if item.get("link") is not None}
    slots: dict[str, int] = {}
    cursor = 0
    for _section, name, spec in _widget_fields(info):
        if name in wired:
            cursor = _skip_one(spec, values, cursor)
            continue
        cursor = _walk_slots(name, spec, values, cursor, slots)
    return slots


# --------------------------------------------------------------------------- 内部


def _link_index(doc: dict[str, Any]) -> dict[Any, tuple[Any, int]]:
    """``{link_id: (origin_node_id, origin_slot)}``。两种存法都认（数组六元组 / 对象）。"""
    index: dict[Any, tuple[Any, int]] = {}
    for row in doc.get("links") or []:
        if isinstance(row, dict):
            index[row["id"]] = (row["origin_id"], row["origin_slot"])
        elif isinstance(row, (list, tuple)) and len(row) >= 3:
            index[row[0]] = (row[1], row[2])
    return index


def _input_sections(info: dict[str, Any]) -> list[tuple[str, str, Any]]:
    """按 required → optional 顺序给出 ``(所在段, 字段名, 定义)``。"""
    sections = info.get("input") or {}
    out: list[tuple[str, str, Any]] = []
    for section in ("required", "optional"):
        for name, spec in (sections.get(section) or {}).items():
            out.append((section, name, spec))
    return out


def _is_wire(spec: Any) -> bool:
    """这条输入定义是不是连线口（不占 widgets_values）。"""
    if not isinstance(spec, (list, tuple)) or not spec:
        return False
    options = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
    if options.get("forceInput"):
        return True
    itype = spec[0]
    if isinstance(itype, list):
        return False  # COMBO：枚举下拉，一律是 widget
    if not isinstance(itype, str):
        return False
    return itype in _WIRE_TYPES or itype.startswith(_DYNAMIC_INPUT_PREFIX)


def _widget_fields(info: dict[str, Any]) -> list[tuple[str, str, Any]]:
    """按 ``INPUT_TYPES`` 的 required + optional 顺序给出「要吃 widgets_values 的字段」。

    每项是 ``(所在段, 字段名, 定义)``：段名用来判"缺值能不能放过"（可选才放过）。
    """
    return [(section, name, spec) for section, name, spec in _input_sections(info) if not _is_wire(spec)]


def _fields_from_option(inputs: Any) -> list[tuple[str, str, Any]]:
    """动态下拉某个选项自带的子字段（形状同 ``input``，只有 required / optional）。"""
    if not isinstance(inputs, dict):
        return []
    out: list[tuple[str, str, Any]] = []
    for section in ("required", "optional"):
        for name, spec in (inputs.get(section) or {}).items():
            if not _is_wire(spec):
                out.append((section, name, spec))
    return out


def _node_inputs(node: dict[str, Any], info: dict[str, Any], links: dict[Any, tuple[Any, int]],
                 notes: list[str], where: str) -> dict[str, Any]:
    tag = f"{where}节点 #{node.get('id')} {node.get('type')}"
    inputs: dict[str, Any] = {}

    # 1) 连线：UI 图里带 link 的项，名字照抄（value.a / value.b 这类动态名就在这儿进来）
    for item in node.get("inputs") or []:
        link_id = item.get("link")
        if link_id is None:
            continue
        row = links.get(link_id)
        if row is None:
            raise GraphConvertError(f"{tag} 的输入 {item.get('name')!r} 指向不存在的连线 #{link_id}")
        inputs[item["name"]] = [str(row[0]), row[1]]

    # 2) widget 值：按节点定义顺序对位
    values = node.get("widgets_values")
    if values is None:
        values = []
    if isinstance(values, dict):  # 老格式可能按名字存
        values = [values.get(name) for _section, name, _spec in _widget_fields(info)]
    if not isinstance(values, list):
        raise GraphConvertError(f"{tag} 的 widgets_values 既不是数组也不是对象：{type(values).__name__}")

    fields = _widget_fields(info)
    cursor = 0
    for section, name, spec in fields:
        if name in inputs:
            # 已被转成连线输入的 widget：值仍占 widgets_values 的位置，但不进报文
            cursor = _skip_one(spec, values, cursor)
            continue
        if cursor >= len(values):
            # 图上没给值：optional 的按定义默认补齐 —— 引擎真收到过的报文就是这么带的
            # （04 图的 CreateVideo：color_space="sRGB"、codec="none"，与定义 default 一致）。
            default = _default_value(spec) if section == "optional" else _NO_DEFAULT
            if default is _NO_DEFAULT:
                if section == "optional":
                    notes.append(f"{tag} 的可选 widget {name!r} 图上没值、定义里也没默认，跳过")
                    continue
                raise GraphConvertError(
                    f"{tag} 的必填 widget {name!r} 没值：widgets_values 只有 {len(values)} 项"
                    f"（按定义到它这里已经是第 {cursor + 1} 项）")
            notes.append(f"{tag} 的可选 widget {name!r} 图上没值，按定义默认 {default!r} 补上")
            inputs[name] = default
            continue
        cursor = _take_into(name, spec, values, cursor, inputs, tag)

    if cursor != len(values):
        raise GraphConvertError(
            f"{tag} 的 widgets_values 有 {len(values)} 项，按节点定义只解释了 {cursor} 项，"
            f"多出来的是 {values[cursor:]!r}（节点定义变了？把 object_info 重新取一份再试）")
    return inputs


_NO_DEFAULT = object()


def _default_value(spec: Any) -> Any:
    """字段图上没给值时的默认（与前端建节点时的行为一致）。没有默认就返回 ``_NO_DEFAULT``。"""
    options = spec[1] if isinstance(spec, (list, tuple)) and len(spec) > 1 and isinstance(spec[1], dict) else {}
    if "default" in options:
        return options["default"]
    itype = spec[0] if isinstance(spec, (list, tuple)) and spec else None
    if isinstance(itype, list):
        return itype[0] if itype else _NO_DEFAULT  # COMBO 的默认是第一项
    return _NO_DEFAULT


def _take_into(name: str, spec: Any, values: list[Any], cursor: int, inputs: dict[str, Any], tag: str) -> int:
    """取一个字段的值写进 ``inputs``，返回新游标。

    动态下拉（``COMFY_DYNAMICCOMBO_V3``）的写法与引擎真收到的报文一致：选中的 key 占
    ``name``，它自带的子 widget 用**点号扁平键**平铺在同级（``selection`` +
    ``selection.tau``）。出处：``/history`` 里 14918bd4 那条真报文（BlockSparseAttention
    是 ``selection`` / ``selection.tau``，SaveVideo 是 ``format`` / ``format.codec``），
    以及 ``comfy_api/latest/_io.py`` 里 ``finalize_prefix`` 拼前缀的写法。
    """
    itype = spec[0] if isinstance(spec, (list, tuple)) and spec else None
    if itype == "COMFY_DYNAMICCOMBO_V3":
        key = values[cursor]
        cursor += 1
        options = (spec[1] or {}).get("options") or []
        chosen = next((opt for opt in options if isinstance(opt, dict) and opt.get("key") == key), None)
        if chosen is None:
            raise GraphConvertError(
                f"{tag} 的动态下拉 {name!r} 选了 {key!r}，但节点定义里没有这个选项"
                f"（可选：{[opt.get('key') for opt in options if isinstance(opt, dict)]}）")
        inputs[name] = key
        for _section, sub_name, sub_spec in _fields_from_option(chosen.get("inputs")):
            if cursor >= len(values):
                raise GraphConvertError(
                    f"{tag} 的动态下拉 {name!r} 选了 {key!r}，但它自带的 {sub_name!r} 没值了")
            cursor = _take_into(f"{name}.{sub_name}", sub_spec, values, cursor, inputs, tag)
        return cursor
    inputs[name] = values[cursor]
    return _skip_one(spec, values, cursor)


def _walk_slots(name: str, spec: Any, values: list[Any], cursor: int, slots: dict[str, int]) -> int:
    """记下 ``name`` 占的那一格再推进游标；动态下拉连它自带的子字段一起记（同 :func:`_take_into`）。"""
    itype = spec[0] if isinstance(spec, (list, tuple)) and spec else None
    slots[name] = cursor
    if itype != "COMFY_DYNAMICCOMBO_V3":
        return _skip_one(spec, values, cursor)
    key = values[cursor] if cursor < len(values) else None
    cursor += 1
    options = (spec[1] or {}).get("options") or []
    chosen = next((opt for opt in options if isinstance(opt, dict) and opt.get("key") == key), None)
    if chosen is not None:
        for _section, sub_name, sub_spec in _fields_from_option(chosen.get("inputs")):
            cursor = _walk_slots(f"{name}.{sub_name}", sub_spec, values, cursor, slots)
    return cursor


def _skip_one(spec: Any, values: list[Any], cursor: int) -> int:
    """吃掉一个值；若该字段带 control_after_generate，再吃掉它后面那个隐式选择。"""
    cursor += 1
    options = spec[1] if isinstance(spec, (list, tuple)) and len(spec) > 1 and isinstance(spec[1], dict) else {}
    if options.get("control_after_generate") and cursor < len(values) and values[cursor] in _GENERATE_MODES:
        cursor += 1
    return cursor


def object_info_from_file(path: str) -> dict[str, Any]:
    """读一份离线存的 ``/object_info`` 快照（测试与排障用；线上直接给 ``/object_info`` 的返回）。"""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise GraphConvertError(f"{path} 不是 object_info 快照：顶层不是对象")
    return data
