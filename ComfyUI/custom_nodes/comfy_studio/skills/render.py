"""渲染入口：把漫剧生产用的那 12 张真工作流变成可提交的 skill，并把产物落到项目目录。

**为什么运行期转换、不预生成 skill 定义**：这 12 张图住在
``<ComfyUI>/user/default/workflows/AIGC中国风漫剧/``，用户随时会在前端改它们；而提交给
``/prompt`` 的必须是 API 格式。这里每次运行时现转（``graph_to_api`` + ``/object_info``），
改完图立刻生效，也不用维护一份会过期的生成物。

注入点全部是量出来的（2026-09-28 对着本机在跑的引擎，把 12 张图逐张转成 API 格式读数）：

* 图类 01/02/03：``#5.text`` 正向、``#6.text`` 负向（01 那张是布局约束）、``#7.width`` /
  ``#7.height``、``#8.seed`` / ``#8.steps`` / ``#8.cfg``、``#10.filename_prefix``；
* 视频 04/05/06：``#5.global_prompt``、``#5.seed`` / ``#5.width`` / ``#5.height`` /
  ``#5.frame_rate``、``#7.filename_prefix``；
* 音乐 07：``#4.caption``（风格）/ ``#4.lyrics``、``#6.seconds``、``#7.seed``、
  ``#9.filename_prefix``；
* 后处理 08/09：``#1.file``（输入视频名）、08 的 ``#8`` / 09 的 ``#7`` ``filename_prefix``、
  09 另有 ``#5.width`` / ``#5.height``。

**参考图（04/05/06 的首尾帧 / 参考素材）是最容易搞错的一条**，这里记下试错过程与实测结论：
这三张图上**一个 LoadImage 都没有**、``timeline_data.global.refs`` 是空的、导演节点上也没有任何
IMAGE 连线（进 ``#5`` 的只有 model/clip/vae），而 ``bd_grp_*`` 只是**分组标题字符串**。
一开始以为直接往导演节点接 ``reference_image_N`` 就行 —— **错**：真 ``/object_info`` 里导演节点
根本不列这些键。正解是**外部组接线**（节点 README「外部多组接线」一节 + 它自带的示例图
``example_workflows/minimax_h3_director_external_groups_i2v.json`` / ``..._r2v.json`` 读实）：

* fl2v（04/05）：``LoadImage`` → ``MiniMaxH3DirectorGroupImageToVideo``（``first_frame`` /
  ``last_frame``，无帧=t2v、仅首=i2v、首+尾=fl2v）→ ``MiniMaxH3DirectorGroupsCombine``
  （口名 ``groups.group_0``）→ 导演台 ``i2v_groups``；
* r2v（06）：``LoadImage`` → ``MiniMaxH3DirectorGroupReferenceToVideo``（Autogrow 子口
  ``ref_images.ref_image_0`` …，对应提示词里的 ``<Picture N>``）→ 同一个 Combine →
  导演台 ``r2v_groups``。上限 9 张，出处 ``lib/ref_images.py`` 的 ``MAX_REFERENCE_IMAGES = 9``。

两个组节点的 ``prompt`` 与 ``duration_sec`` 都是**必填**，所以外部组这条路上提示词要落在**组**上
（作者示例图里导演台的 ``global_prompt`` 就是空的，提示词写在组里）；``duration_sec`` 没给时按图上
``total_frames / frame_rate`` 推，并把这个折算写进 :attr:`RenderPlan.notes`，不闷着改。
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Sequence

from .graph import graph_to_api
from .outputs import save_media_async, save_media_batch
from .params import param_entry
from .runner import DEFAULT_TIMEOUT, StatusCallback
from .types import NO_DEFAULT, Skill, SkillParam, SkillParamType, SkillRunResult

__all__ = [
    "COMBINE_AUTOGROW",
    "COMBINE_CLASS",
    "COMBINE_SLOT",
    "DIRECTOR_PORT",
    "GROUP_CLASS",
    "INPUT_IMAGE_SUBDIR",
    "MAX_REFERENCE_IMAGES",
    "REF_INPUT_PREFIX",
    "REF_NODE_PREFIX",
    "RENDER_TARGETS",
    "WORKFLOWS_ENV",
    "RenderError",
    "RenderPlan",
    "RenderTarget",
    "build_render_skill",
    "find_target",
    "plan_render",
    "prepare_render",
    "render",
    "render_into",
    "render_listing",
    "stage_input_file",
    "target_to_json",
    "workflows_dir",
]

#: 覆盖工作流目录（换机器/换项目时不必改代码）。
WORKFLOWS_ENV = "COMFY_STUDIO_WORKFLOWS_DIR"

#: 12 张生产图相对 ComfyUI 根的落点。
WORKFLOW_SUBDIR = ("user", "default", "workflows", "AIGC中国风漫剧")

#: 外部组接线的节点类名与口名。出处：节点自带的两张可跑示例图
#: （``example_workflows/minimax_h3_director_external_groups_i2v.json`` / ``..._r2v.json``）。
GROUP_CLASS = {
    "i2v": "MiniMaxH3DirectorGroupImageToVideo",
    "r2v": "MiniMaxH3DirectorGroupReferenceToVideo",
}
COMBINE_CLASS = "MiniMaxH3DirectorGroupsCombine"
#: Combine 的定义里只有一个 Autogrow 口 ``groups``（真 /object_info 就这么写）；
#: ``groups.group_0`` 是**提交期展开的实例子键**，作者示例图的 inputs 里就是这个名字。
COMBINE_AUTOGROW = "groups"
COMBINE_SLOT = f"{COMBINE_AUTOGROW}.group_0"
DIRECTOR_PORT = {"i2v": "i2v_groups", "r2v": "r2v_groups"}

#: fl2v 的槽名（顺序即 图片1=首帧、图片2=尾帧）。
FRAME_SLOTS = ("first_frame", "last_frame")

#: r2v 的 Autogrow 子口名前缀，与节点 ``lib/ref_images.py`` 的 ``REF_IMAGE_KEY_PREFIX`` 同源。
REF_INPUT_PREFIX = "ref_images.ref_image_"

#: 上限：fl2v 只认首尾两帧；r2v 9 张（出处 ``lib/ref_images.py`` 的 ``MAX_REFERENCE_IMAGES = 9``）。
MAX_FRAME_IMAGES = 2
MAX_REFERENCE_IMAGES = 9

#: 本模块补出来的节点 id 前缀（用非数字前缀，绝不与图内节点 id 撞车）。
REF_NODE_PREFIX = "cs-ref-"
GROUP_NODE_ID = "cs-grp-0"
COMBINE_NODE_ID = "cs-combine"

#: 参考图复制进 ``input/`` 后放的子目录（别把用户 input 目录铺满散图）。
INPUT_IMAGE_SUBDIR = "comfy_studio/render"


class RenderError(RuntimeError):
    """渲染目标/工作流/参考图不成立。报错要能直接指导去改哪。"""


# --------------------------------------------------------------------------- 目标表


def _p(
    name: str,
    type: SkillParamType,
    node: str,
    field: str,
    *,
    required: bool = False,
    default: Any = NO_DEFAULT,
    description: str | None = None,
) -> SkillParam:
    return SkillParam(
        name=name, type=type, node=node, field=field, required=required, default=default, description=description
    )


def _image_params(*, second: str, second_hint: str) -> tuple[SkillParam, ...]:
    """01/02/03 共用同一套注入点（节点 id 与字段名逐张核过，完全一致）。

    ``#6`` 那张图在这三个目标里语义不同：01 是"三视图布局约束"，02/03 才是真负向提示词，
    所以参数名不统一叫 negative —— 名字撒谎比缺参数更坏。
    """
    return (
        _p("prompt", "string", "5", "text", required=True, description="正向提示词：角色/场景/镜头的画面描述"),
        _p(second, "string", "6", "text", description=second_hint),
        _p("width", "integer", "7", "width", description="不传就用图上原值"),
        _p("height", "integer", "7", "height"),
        _p("seed", "integer", "8", "seed", default=-1, description="给 -1 表示每次随机（见 params.SEED_RANDOM）"),
        _p("steps", "integer", "8", "steps"),
        _p("cfg", "number", "8", "cfg"),
        _p("filename_prefix", "string", "10", "filename_prefix", description="引擎 output/ 下的相对前缀"),
    )


def _director_params() -> tuple[SkillParam, ...]:
    """04/05/06：MiniMaxH3Director 的注入点（键名取自 /object_info 转换后的真图）。"""
    return (
        _p("prompt", "string", "5", "global_prompt", required=True, description="全局提示词：画面过程与一致性要求"),
        _p("seed", "integer", "5", "seed", default=-1, description="给 -1 表示每次随机"),
        _p("width", "integer", "5", "width"),
        _p("height", "integer", "5", "height"),
        _p("frame_rate", "number", "5", "frame_rate"),
        _p("filename_prefix", "string", "7", "filename_prefix", description="引擎 output/ 下的相对前缀"),
    )


def _music_params() -> tuple[SkillParam, ...]:
    """07：MiniMaxMusic3TextEncode 只认 caption（风格）+ lyrics（歌词）。"""
    return (
        _p("caption", "string", "4", "caption", required=True, description="曲风/编制描述（Style Prompt）"),
        _p("lyrics", "string", "4", "lyrics", required=True, description="歌词正文，带 [Verse]/[Chorus] 结构标记"),
        _p("seconds", "integer", "6", "seconds", description="时长（秒），不传就用图上原值"),
        _p("seed", "integer", "7", "seed", default=-1, description="给 -1 表示每次随机"),
        _p("filename_prefix", "string", "9", "filename_prefix", description="引擎 output/ 下的相对前缀"),
    )


def _post_video_params(*, prefix_node: str, sizes: bool) -> tuple[SkillParam, ...]:
    """08/09：输入是 ``LoadVideo.file``（引擎 input/ 下的文件名，得先把片子放进 input/）。"""
    params = [
        _p("file", "string", "1", "file", required=True, description="输入视频名（相对引擎 input/，用 stage_input_file 放进去）"),
    ]
    if sizes:
        params += [_p("width", "integer", "5", "width"), _p("height", "integer", "5", "height")]
    params.append(_p("filename_prefix", "string", prefix_node, "filename_prefix", description="引擎 output/ 下的相对前缀"))
    return tuple(params)


@dataclass(frozen=True)
class RenderTarget:
    """一个可渲染的用途：一张真工作流 + 一列注入点。

    ``group_kind`` 非空表示这张图能用参考图（04/05/06）：``"i2v"`` 收首/尾帧（最多 2 张），
    ``"r2v"`` 收参考素材（最多 9 张）。图按顺序进外部组节点，再经 Combine 进导演台的
    ``i2v_groups`` / ``r2v_groups``（不是直接接导演节点，见模块头注释）。``ref_node`` 是导演节点 id。
    """

    id: str
    title: str
    description: str
    file: str
    params: tuple[SkillParam, ...]
    tags: tuple[str, ...] = ()
    ref_node: str | None = None
    group_kind: str | None = None

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "file": self.file,
            "tags": list(self.tags),
            # 参数形状与 skill 那边共用一份（见 params.param_entry）：前端只认一套键名。
            "params": [param_entry(param) for param in self.params],
        }
        if self.ref_node is not None:
            data["reference_images"] = True
        return data


def render_listing(directory: Path) -> dict[str, Any]:
    """渲染目标清单的**唯一装配处**：``comfy_list_renders`` 与 ``GET /comfy-studio/renders``
    都从这里取（面板/宿主只认一套字段）。

    ``file_exists`` 照实报：缺的那几张图不让调用方以为"列出来的都能跑"；目录整个不在就把
    ``note`` 说清楚（可以用 :data:`WORKFLOWS_ENV` 指过去），而不是回一个空清单。
    """
    return {
        "workflows_dir": str(directory),
        "note": None if directory.is_dir() else f"这个目录不存在；可以用 {WORKFLOWS_ENV} 指定它",
        "targets": [
            {**target.to_json(), "file_exists": (directory / target.file).is_file()}
            for target in RENDER_TARGETS
        ],
    }


RENDER_TARGETS: tuple[RenderTarget, ...] = (
    RenderTarget(
        id="character-sheet",
        title="角色定妆板（Qwen-Image 2512 · 质量档 30 步）",
        description="出角色三视图定妆板。图上自带风格 LoRA 与国漫 3D CG 配方，改提示词即可。",
        file="01_角色定妆板_Qwen2512.json",
        params=_image_params(second="layout", second_hint="#6 是「三视图布局约束」，不是负向提示词"),
        tags=("image", "character"),
    ),
    RenderTarget(
        id="character-sheet-lightning",
        title="角色定妆板（Qwen-Image 2512 Lightning · 8 步快档）",
        description="同上但走 Lightning 蒸馏配方（8 步 / cfg 1.0），用来快速试提示词。",
        file="01_角色定妆板_Qwen2512_Lightning.json",
        params=_image_params(second="layout", second_hint="#6 是「三视图布局约束」，不是负向提示词"),
        tags=("image", "character", "fast"),
    ),
    RenderTarget(
        id="character-sheet-zimage",
        title="角色定妆板（Z-Image 档）",
        description="同一张定妆板配方的 Z-Image 版本（换底模档位用）。",
        file="01_角色定妆板_ZImage.json",
        params=_image_params(second="layout", second_hint="#6 是「三视图布局约束」，不是负向提示词"),
        tags=("image", "character"),
    ),
    RenderTarget(
        id="scene-card",
        title="场景设定卡（Qwen-Image 2512）",
        description="出场景设定卡。1920×1080，图上 #6 是真负向提示词。",
        file="02_场景设定卡_Qwen2512.json",
        params=_image_params(second="negative", second_hint="负向提示词"),
        tags=("image", "scene"),
    ),
    RenderTarget(
        id="scene-card-zimage",
        title="场景设定卡（Z-Image 档）",
        description="场景设定卡的 Z-Image 版本。",
        file="02_场景设定卡_ZImage.json",
        params=_image_params(second="negative", second_hint="负向提示词"),
        tags=("image", "scene"),
    ),
    RenderTarget(
        id="storyboard-frame",
        title="分镜首帧（Qwen-Image 2512）",
        description="出分镜首帧图。负向里有防人物增殖/串戏的一整套词，别轻易覆盖。",
        file="03_分镜首帧_Qwen2512.json",
        params=_image_params(second="negative", second_hint="负向提示词"),
        tags=("image", "storyboard"),
    ),
    RenderTarget(
        id="video-draft",
        title="视频 768p 试片（fl2v 首尾帧）",
        description="首尾帧生视频的试片档。用 images 传首帧、尾帧（=提示词里的图片1、图片2）。",
        file="04_视频_768p试片_fl2v.json",
        params=_director_params(),
        tags=("video", "draft"),
        ref_node="5",
        group_kind="i2v",
    ),
    RenderTarget(
        id="video-final",
        title="视频 1080p 正片（fl2v 首尾帧）",
        description="首尾帧生视频的正片档。用 images 传首帧、尾帧。",
        file="05_视频_1080p正片_fl2v.json",
        params=_director_params(),
        tags=("video", "final"),
        ref_node="5",
        group_kind="i2v",
    ),
    RenderTarget(
        id="video-multishot",
        title="多镜连贯（r2v 参考主体）",
        description="参考主体生视频，多镜之间保持同一人物。用 images 传参考图（图片1…）。",
        file="06_视频_r2v_多镜连贯.json",
        params=_director_params(),
        tags=("video", "multishot"),
        ref_node="5",
        group_kind="r2v",
    ),
    RenderTarget(
        id="music",
        title="主题曲（MiniMax Music3）",
        description="出主题曲：caption 是曲风/编制，lyrics 是带结构标记的歌词。产物是 flac。",
        file="07_音乐_MiniMax Music3.json",
        params=_music_params(),
        tags=("audio", "music"),
    ),
    RenderTarget(
        id="video-interpolate",
        title="视频补帧（RIFE → 48fps）",
        description="帧率翻倍。输入片子要先经 stage_input_file 放进引擎 input/。",
        file="08_视频_补帧_RIFE.json",
        params=_post_video_params(prefix_node="8", sizes=False),
        tags=("video", "post"),
    ),
    RenderTarget(
        id="video-upscale",
        title="视频放大（GAN ×4 → 1080p 母版）",
        description="出成片母版。输入片子要先经 stage_input_file 放进引擎 input/。",
        file="09_视频_放大_GANx4.json",
        params=_post_video_params(prefix_node="7", sizes=True),
        tags=("video", "post"),
    ),
)


def find_target(target_id: str) -> RenderTarget:
    for target in RENDER_TARGETS:
        if target.id == target_id:
            return target
    known = ", ".join(target.id for target in RENDER_TARGETS)
    raise RenderError(f"没有渲染目标 {target_id!r}；可用：{known}")


def target_to_json(target: RenderTarget) -> dict[str, Any]:
    return target.to_json()


# --------------------------------------------------------------------------- 目录与输入文件


def workflows_dir() -> Path:
    """这 12 张图所在的目录。不写死机器路径：优先环境变量，其次引擎的 ``base_path``。"""
    override = os.environ.get(WORKFLOWS_ENV)
    if override:
        return Path(override)
    return _comfy_base().joinpath(*WORKFLOW_SUBDIR)


def _comfy_base() -> Path:
    try:
        import folder_paths  # 只在引擎进程/引擎工作树里可导入
    except ImportError:
        # 进程外（离线跑测试之类）：从本文件往上找 —— skills → comfy_studio → custom_nodes → ComfyUI
        return Path(__file__).resolve().parents[3]
    return Path(folder_paths.base_path)


def target_path(target: RenderTarget) -> Path:
    path = workflows_dir() / target.file
    if not path.is_file():
        raise RenderError(f"渲染目标 {target.id} 的工作流不在：{path}（可用 {WORKFLOWS_ENV} 指定工作流目录）")
    return path


def stage_input_file(source: str | Path, *, input_dir: str | Path | None = None) -> str:
    """把一份图/视频放进引擎的 ``input/`` 目录，返回它在那里的相对名。

    ``LoadImage.image`` 与 ``LoadVideo.file`` 要的都是**相对 input 目录**的名字
    （引擎按 input 目录注解路径解析），所以外部文件必须先搬进去。
    ``input_dir`` 不给就走引擎的 ``folder_paths.get_input_directory()``。
    """
    source_path = Path(source)
    if not source_path.is_file():
        raise RenderError(f"要放进 input/ 的文件不存在：{source_path}")
    if input_dir is None:
        try:
            import folder_paths
        except ImportError as err:  # pragma: no cover - 只在引擎进程里成立
            raise RenderError(
                "放输入文件需要 ComfyUI 的 folder_paths（本函数在引擎进程外必须显式给 input_dir）"
            ) from err
        input_dir = folder_paths.get_input_directory()
    relative = Path(INPUT_IMAGE_SUBDIR) / source_path.name
    destination = Path(input_dir) / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or destination.read_bytes() != source_path.read_bytes():
        destination.write_bytes(source_path.read_bytes())
    return relative.as_posix()


# --------------------------------------------------------------------------- 组装与运行


def _input_keys(object_info: dict[str, Any], class_type: str) -> frozenset[str]:
    """按节点定义列出输入键（``required`` 与 ``optional`` 两段都算）。节点不存在直接报错。"""
    node = object_info.get(class_type)
    if not isinstance(node, dict):
        raise RenderError(f"/object_info 里没有节点 {class_type}：装的是哪个版本？拿不到它的输入定义")
    sections = node.get("input") or {}
    names: set[str] = set()
    for section in ("required", "optional"):
        names.update((sections.get(section) or {}).keys())
    return frozenset(names)


def _group_slots(kind: str, object_info: dict[str, Any]) -> tuple[str, ...]:
    """参考图槽名序列（按 index 排好），并核对该组节点真的存在、真的收图。

    fl2v 是 ``first_frame`` / ``last_frame`` 两个固定口；r2v 是 Autogrow，口名形如
    ``ref_images.ref_image_0``（与示例图一致）。
    """
    class_type = GROUP_CLASS[kind]
    keys = _input_keys(object_info, class_type)
    if kind == "i2v":
        missing = [slot for slot in FRAME_SLOTS if slot not in keys]
        if missing:
            raise RenderError(f"{class_type} 缺槽位 {missing}：版本对不上，接不了首尾帧")
        return FRAME_SLOTS
    if "ref_images" not in keys:
        raise RenderError(f"{class_type} 没有 ref_images 口：版本对不上，接不了参考素材")
    return tuple(f"{REF_INPUT_PREFIX}{index}" for index in range(MAX_REFERENCE_IMAGES))


@dataclass(frozen=True)
class RenderPlan:
    """一次渲染的组装结果：可运行的 skill + 组装期的可见让步（``graph.notes`` 与本模块的折算说明）。"""

    target: RenderTarget
    skill: Skill
    notes: tuple[str, ...] = ()


def _wire_reference_group(
    target: RenderTarget,
    workflow: dict[str, Any],
    object_info: dict[str, Any],
    image_names: Sequence[str],
    duration_sec: float | None,
    notes: list[str],
) -> None:
    """把参考图接成外部组（LoadImage → 组 → Combine → 导演台的口）。

    这条路上的提示词落在**组**上，所以 ``prompt`` 参数要从导演台改指到组节点（作者示例图里
    导演台的 ``global_prompt`` 也是空的）；不改指的话提示词会被丢在导演台上，实际不生效。
    """
    kind = target.group_kind
    assert kind is not None  # 调用方已判过
    if target.ref_node is None:
        raise RenderError(f"渲染目标 {target.id} 既标了参考图能力、又没给导演节点 id，目标表写坏了")
    limit = MAX_FRAME_IMAGES if kind == "i2v" else MAX_REFERENCE_IMAGES
    if len(image_names) > limit:
        raise RenderError(f"{target.id}（{kind}）最多收 {limit} 张图，这次给了 {len(image_names)} 张")
    director = workflow.get(target.ref_node)
    if director is None:
        raise RenderError(f"渲染目标 {target.id} 的导演节点 #{target.ref_node} 不在转换结果里（图被改过？）")

    port = DIRECTOR_PORT[kind]
    if port not in _input_keys(object_info, str(director["class_type"])):
        raise RenderError(f"{director['class_type']} 没有 {port} 口：版本对不上，外部组接不进去")
    if COMBINE_AUTOGROW not in _input_keys(object_info, COMBINE_CLASS):
        raise RenderError(f"{COMBINE_CLASS} 没有 {COMBINE_AUTOGROW} 口：版本对不上")

    group_inputs: dict[str, Any] = {}
    for index, name in enumerate(image_names):
        node_id = f"{REF_NODE_PREFIX}{index}"
        workflow[node_id] = {"class_type": "LoadImage", "inputs": {"image": name, "upload": "image"}}
        slot = _group_slots(kind, object_info)[index]
        group_inputs[slot] = [node_id, 0]

    if duration_sec is None:
        # 组节点的 duration_sec 是必填；图上只给了 total_frames，按 frame_rate 折算并记账。
        frames = director["inputs"].get("total_frames")
        rate = director["inputs"].get("frame_rate")
        if isinstance(frames, (int, float)) and isinstance(rate, (int, float)) and rate:
            duration_sec = round(float(frames) / float(rate), 2)
            notes.append(
                f"{target.id}：外部组的 duration_sec 没给，按图上 total_frames={frames} / frame_rate={rate} "
                f"折成 {duration_sec}s"
            )
        else:
            raise RenderError(
                f"{target.id}：外部组必须给 duration_sec（节点定义里它是必填），"
                "而图上既没有 total_frames/frame_rate 也没传 duration_sec，无从折算"
            )

    group_prompt_field = "prompt"
    group_inputs[group_prompt_field] = ""  # 由 prompt 参数在运行期填（见下面 params 改指）
    group_inputs["duration_sec"] = duration_sec
    workflow[GROUP_NODE_ID] = {"class_type": GROUP_CLASS[kind], "inputs": group_inputs}
    workflow[COMBINE_NODE_ID] = {"class_type": COMBINE_CLASS, "inputs": {COMBINE_SLOT: [GROUP_NODE_ID, 0]}}
    director["inputs"][port] = [COMBINE_NODE_ID, 0]
    notes.append(
        f"{target.id}：接上外部组（{GROUP_CLASS[kind]} → {COMBINE_CLASS} → 导演台 {port}），"
        f"提示词改落在组的 prompt 上；这条路的接线形状取自节点自带示例图，未在本机实跑过"
    )


def build_render_skill(
    target: RenderTarget,
    object_info: dict[str, Any],
    *,
    image_names: Sequence[str] = (),
    duration_sec: float | None = None,
) -> RenderPlan:
    """把目标的工作流转成 API 格式、接上参考图，组装成可直接跑的 skill。

    ``image_names`` 是**已经放进 input/ 的相对名**（见 :func:`stage_input_file`），按顺序对应
    提示词里的"图片1、图片2…"：fl2v 是首帧、尾帧；r2v 是参考素材。给了图就会接外部组，
    ``params`` 里的 ``prompt`` 随之改指到组节点上。
    """
    if duration_sec is not None and (
        isinstance(duration_sec, bool) or not isinstance(duration_sec, (int, float)) or duration_sec <= 0
    ):
        # 规则住在这里（组装期唯一说了算的地方），各入口照抄它的口径而不是各写一份。
        raise RenderError(f"duration_sec 要给正数（秒），收到 {duration_sec!r}")
    document = json.loads(target_path(target).read_text(encoding="utf-8"))
    result = graph_to_api(document, object_info, source=target.file)
    workflow = copy.deepcopy(result.graph)
    notes = list(result.notes)
    params = target.params

    if image_names:
        if target.group_kind is None:
            raise RenderError(f"渲染目标 {target.id}（{target.file}）不接受参考图，却给了 {len(image_names)} 张")
        _wire_reference_group(target, workflow, object_info, image_names, duration_sec, notes)
        params = tuple(
            param if param.name != "prompt" else replace(param, node=GROUP_NODE_ID, field="prompt")
            for param in target.params
        )

    skill = Skill(
        id=target.id,
        title=target.title,
        description=target.description,
        workflow=workflow,
        params=params,
        tags=target.tags,
        source=f"render:{target.file}",
    )
    return RenderPlan(target=target, skill=skill, notes=tuple(notes))


def plan_render(
    target_id: str,
    object_info: dict[str, Any],
    *,
    image_names: Sequence[str] = (),
    duration_sec: float | None = None,
) -> RenderPlan:
    return build_render_skill(
        find_target(target_id), object_info, image_names=image_names, duration_sec=duration_sec
    )


async def prepare_render(
    engine: Any,
    target_id: str,
    *,
    images: Iterable[str | Path] = (),
    duration_sec: float | None = None,
) -> RenderPlan:
    """组装一个渲染目标（取节点定义 → 放参考图 → 转 API），**不提交**。

    单独拆出来是给"要把 :attr:`RenderPlan.notes` 原样讲给调用方听"的入口用的（引擎侧 MCP 工具
    与面板路由）：那些入口得如实报出组装期的让步（时长折算、接了外部组），不能把它咽掉。

    ``images`` 是**文件路径**，按顺序对应"图片1、图片2…"（fl2v 首帧/尾帧、r2v 参考素材）；
    只对 04/05/06 有用，给了图就会接外部组，``duration_sec`` 也就跟着要（不给会按图上帧数折算）。
    """
    target = find_target(target_id)
    object_info = await engine.object_info()
    names = tuple(stage_input_file(path) for path in images)
    return build_render_skill(target, object_info, image_names=names, duration_sec=duration_sec)


async def render(
    engine: Any,
    target_id: str,
    params: dict[str, Any] | None = None,
    *,
    images: Iterable[str | Path] = (),
    duration_sec: float | None = None,
    on_status: StatusCallback | None = None,
    timeout: float | None = DEFAULT_TIMEOUT,
) -> SkillRunResult:
    """跑一个渲染目标：组装（见 :func:`prepare_render`）→ 注入参数 → 提交 → 等结束。"""
    plan = await prepare_render(engine, target_id, images=images, duration_sec=duration_sec)
    return await engine.run_skill(plan.skill, params, on_status=on_status, timeout=timeout)


async def render_into(
    engine: Any,
    target_id: str,
    params: dict[str, Any] | None,
    output_dir: str | Path,
    *,
    images: Iterable[str | Path] = (),
    duration_sec: float | None = None,
    names: Sequence[str] | None = None,
    on_status: StatusCallback | None = None,
    timeout: float | None = DEFAULT_TIMEOUT,
) -> tuple[Path, ...]:
    """跟 :func:`render` 一样，跑完**把产物落进 ``output_dir``**（项目目录那一步）。

    给了 ``names`` 就按顺序改名（如 ``ID-001.png``）；个数对不上直接报错，不许张冠李戴。
    """
    result = await render(
        engine, target_id, params, images=images, duration_sec=duration_sec, on_status=on_status, timeout=timeout
    )
    if names is None:
        return await save_media_batch(result.media, output_dir, base_url=engine.base_url)
    wanted = tuple(names)
    if len(wanted) != len(result.media):
        raise RenderError(f"产物 {len(result.media)} 个，改名表给了 {len(wanted)} 个，对不上")
    saved = [
        await save_media_async(media, output_dir, name=name, base_url=engine.base_url)
        for media, name in zip(result.media, wanted)
    ]
    return tuple(saved)
