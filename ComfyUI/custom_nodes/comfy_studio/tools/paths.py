"""引擎侧运维脚本共用的路径探测 —— 只此一份，各脚本不许再写死机器盘符。

写死盘符的害处不是「跑不起来」，而是**换台机器就静默指到别处**：脚本照样 exit 0，
只是改的/查的不是同一份文件。所以这里一律现算。

本文件住在 ``<ComfyUI>/custom_nodes/comfy_studio/tools/`` 下，和用它的那批脚本一起
跟着仓库走。**ComfyUI 根不靠「数层级」算** —— 这批脚本早先住 ``<ComfyUI>/.cache/``
（往上两级），搬进 ``tools/`` 就是四级；数层级属于「搬一次目录就静默指错」的脆写法。
改为往上找**标志物** ``user/default/workflows``，与 ``src/video_provider.py::find_comfy_root()``
同一口径（那个是 `COMFYUI_ROOT` 环境变量优先、再从文件往上找，这里照同一顺序）。

三样事实源：
1. ComfyUI 根：`COMFYUI_ROOT` 环境变量 → 从本文件往上找含 ``user/default/workflows`` 的目录。
2. 工作流目录：``<ComfyUI>/user/default/workflows/AIGC中国风漫剧``，固定相对路径。
3. 模型池：读 ``<ComfyUI>/extra_model_paths.yaml`` 里 ``shared_models.base_path``。
   这正是 ComfyUI 启动时自己读的同一份配置（``main.py::apply_custom_paths`` ->
   ``utils/extra_config.py``），不是第二套探测；该文件被 ComfyUI/.gitignore 忽略，
   属于本机配置，所以换台机器它自带正确值。文件不存在才退回 ``<ComfyUI>/models``。

用法（脚本会自己 ``import paths``，因为 Python 把脚本所在目录放在 sys.path[0]）::

    python custom_nodes/comfy_studio/tools/switch-h3-weights.py upgraded
"""
import os
import pathlib

WORKFLOW_SUBDIR = pathlib.Path("user") / "default" / "workflows" / "AIGC中国风漫剧"


def _find_comfy_root():
    """往上找含 ``user/default/workflows`` 的目录。找不到就显式报错，不猜。"""
    env = os.environ.get("COMFYUI_ROOT")
    if env:
        p = pathlib.Path(env).expanduser().resolve()
        if not (p / WORKFLOW_SUBDIR).is_dir():
            raise SystemExit(
                "COMFYUI_ROOT={} 下没有 {}，不是 ComfyUI 根".format(p, WORKFLOW_SUBDIR)
            )
        return p
    start = pathlib.Path(__file__).resolve().parent
    for cand in (start, *start.parents):
        if (cand / WORKFLOW_SUBDIR).is_dir():
            return cand
    raise SystemExit(
        "从 {} 往上找不到含 {} 的目录；请设 COMFYUI_ROOT 指向 ComfyUI 根".format(
            start, WORKFLOW_SUBDIR
        )
    )


COMFY_ROOT = _find_comfy_root()

# 工作流改动前快照的落点。放 .cache 底下而不是工作流目录：ComfyUI 会把工作流目录里
# 所有 *.json 都列进工作流列表，.bak/.pre-*.json 会污染那个列表。
# （.cache/ 被 .gitignore 忽略，快照本来也不该入库。）
BACKUP_DIR = COMFY_ROOT / ".cache" / "h3-workflow-backup"


def comfy_root():
    return COMFY_ROOT


def workflows():
    return COMFY_ROOT / WORKFLOW_SUBDIR


def backup():
    return BACKUP_DIR


def model_roots():
    """ComfyUI 实际会搜的模型根。自己的 models/ 在前，共享池在后。

    两处都要查：extra_model_paths.yaml 只是**追加**搜索路径（main.py::apply_custom_paths），
    并不会取消 <ComfyUI>/models。只查共享池，会把放在本地 models/ 下的权重误报成缺文件。
    """
    roots = []
    for root in (COMFY_ROOT / "models", pool()):
        if root not in roots:
            roots.append(root)
    return roots


def pool():
    """共享模型池的根（其下是 diffusion_models/ text_encoders/ loras/ ... 各子目录）。"""
    config = COMFY_ROOT / "extra_model_paths.yaml"
    if config.is_file():
        import yaml  # ComfyUI 的运行时依赖，venv 里必然有

        data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
        section = data.get("shared_models")
        if not isinstance(section, dict) or not section.get("base_path"):
            raise SystemExit(
                "{} 里没有 shared_models.base_path，无法定位模型池".format(config)
            )
        return pathlib.Path(section["base_path"])
    return COMFY_ROOT / "models"
