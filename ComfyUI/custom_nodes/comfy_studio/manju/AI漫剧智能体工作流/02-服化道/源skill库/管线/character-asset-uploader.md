---
name: character-asset-uploader
display_name: 角色资产上传器（资产监工）
description: 帮助用户将生成的角色图片上传至素材库（资产库）并进行分类管理
---

> ⚠️ 命名不一致提示：源文件名为 `character-asset-supervisor`（资产监工），内部 `name` 字段为 `character-asset-uploader`（资产上传器）。实际功能为**资产规范化入库**。

# 角色资产上传器

## Skill Goal

引导用户将生成的角色资产（如定妆照、三视图、表情包等）规范化保存到项目素材库中，确保项目素材井然有序，方便后续分镜和视频生成调用。

## Workflow

1. **识别资产**：检测当前对话中生成或上传的角色图片
2. **确认分类**：询问用户该资产属于哪个角色，以及资产类型（定妆照/三视图/参考图/其他）
3. **执行保存**：调用 `asset_folder(action="save")`，将图片保存到 `/角色/[角色名]/[类型]` 目录下
4. **状态反馈**：展示保存成功的路径，并引导用户下一步操作（如：继续生成场景图或开始写分镜）

## Instructions

- 必须先 `asset_folder(action="ls", path="/角色")` 检查目录结构，若角色文件夹不存在则先 `mkdir` 创建
- 保存时，文件名应包含角色名和资产类型，例如 `[角色名]_[类型]_[序号].png`
- 若用户未指定角色名，需主动询问，**不可随意命名**

## Implementation Example

**Step 1: 检查并创建目录**
```python
# 检查是否存在该角色文件夹
asset_folder(action="ls", path="/角色")
# 若不存在，创建
asset_folder(action="mkdir", path="/角色", name="[角色名]")
# 创建子目录
asset_folder(action="mkdir", path="/角色/[角色名]", name="定妆照")
```

**Step 2: 保存资产**
```python
asset_folder(
    action="save",
    path="/角色/[角色名]/定妆照",
    name="[角色名]_定妆照_01.png",
    url="[图片URL]"
)
```

## Version

- **Version**: 1.0.0
- **Author**: updream 资产管理组
- **Last Updated**: 2024-12

---

## 与本项目 V2.0 规格的映射

**这是「资产质检 Gate」的入库环节工具。**

| 本文机制 | V2.0 规格对应 |
|---|---|
| `/角色/[角色名]/[类型]` 目录结构 | §40 的 `02_CHARACTERS/CHARACTER_001/`（含 `turnaround.png`、`expressions/`、`poses/`） |
| 文件名 `[角色名]_[类型]_[序号].png` | 命名规范（见 `项目骨架/README.md`：`CHR_001_State_B_v2_turnaround.png`） |
| 入库前检查目录 | 对应 §39 ASSET_CARD 建档 |
| 引导下一步 | 对应 §41 总循环的 ASSET UPDATE → USER OUTPUT |

### 本项目命名规范（以本地为准）

```
<类型前缀>_<3位序号>[_<状态>][_v<版本>]_<资产类型>.<扩展名>

例：
CHR_001_v1_turnaround.png          角色三视图
CST_001_Wet_v1.png                 服装（淋湿状态）
PRP_001_Intact_v1.png              道具（完好状态）
ENV_001_multi-angle_v1.png         场景（多角度）
EXP_CHR001_愤怒_v1.png              表情
```

### 入库质检项（§23 Postflight + §06 标准）

- [ ] 分辨率符合 8K 级视觉细节要求
- [ ] 透明通道（如需）/ 纯白背景（角色/服装/道具类）
- [ ] 三视图比例一致
- [ ] 色值与 ASSET_CARD 记录一致
- [ ] 风格英文锚点已追加
- [ ] 文件名符合命名规范
- [ ] 已在 ASSET_CARD.yaml 建档并分配 ID
- [ ] 已在对应 INDEX 中登记
