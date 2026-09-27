# 项目骨架 · AI_DRAMA_PROJECT

> 对应规格 §40｜最终项目结构
> 用法：复制整个 `AI_DRAMA_PROJECT/` 文件夹为新剧项目目录，重命名为你的项目名，然后按各目录职责填充资产。

---

## 一、目录职责

```
AI_DRAMA_PROJECT/
│
├── 00_PROJECT/                 项目管理
│   ├── PROJECT_STATE            ← 复制 `模板/PROJECT_STATE.yaml`
│   ├── VISUAL_BIBLE             ← 复制 `模板/VISUAL_BIBLE.md`
│   ├── CHANGELOG                ← 复制 `模板/CHANGELOG.yaml`
│   ├── ID-REGISTRY              ← ⭐ 复制 `01-剧本文本/模板/ID-REGISTRY.md`（**由 05 建纲时创建**）
│   └── OPEN-ISSUES              ← ⭐ 复制 `01-剧本文本/模板/OPEN-ISSUES.md`（同上）
│
├── 01_WORLD/                   世界观
│   ├── ERA                     时代
│   ├── ARCHITECTURE            建筑
│   ├── MATERIAL                材料
│   ├── COLOR                   色彩
│   └── LIGHTING                灯光
│
├── 02_CHARACTERS/              角色（每个角色一个子目录）
│   └── CHARACTER_001/
│       ├── ASSET_CARD          ← 复制 `模板/ASSET_CARD.yaml`
│       ├── turnaround.png      三视图
│       ├── expressions/        表情集
│       └── poses/              动作集
│
├── 03_COSTUMES/                服装（独立资产，不依附角色）
│   └── COSTUME_001/…
│
├── 04_PROPS/                   道具（独立资产）
│   └── PROP_001/…
│
├── 05_ENVIRONMENTS/            场景
│   └── ENV_001/…
│
├── 06_EXPRESSIONS/             表情总库
│
├── 07_POSES/                   动作总库
│
├── 08_STORYBOARDS/             分镜
│
├── 09_SHOTS/                   镜头
│
└── 10_CONSISTENCY/             一致性检查记录
    └── REPORT_<日期>.md         ← 按 `引擎/CONSISTENCY-CHECKLIST.md` 格式
```

---

## 二、命名规范

> 权威来源：`00-总控路由.md` §四。⚠️ 分镜是 `SHT_` 不是 `SHOT_`；场景是 `ENV_` 不是 `SCN_`。

### 独立占号段

| 类型 | 前缀 | 示例 | 谁分配 |
|---|---|---|---|
| 角色 | `CHR_` | `CHR_001`、`CHR_001_State_A` | 05 |
| 服装 | `CST_` | `CST_001_Normal`、`CST_001_Wet` | 05 提逻辑 / 02 定稿 |
| 道具 | `PRP_` | `PRP_001`、`PRP_001_Damaged` | 05 |
| 场景 | `ENV_` | `ENV_001` | 05 |
| 动作 | `POS_` | `POS_001_拔剑` | 02 |
| 分镜 | `SHT_` | `SHT_S01_001` | 01 |
| 音频 | `AUD_` | `AUD_BGM_001`、`AUD_VO_001` | 04 |

### 派生（不占号位）

| 类型 | 前缀 | 示例 | 由谁生成 |
|---|---|---|---|
| 表情 | `EXP_` | `EXP_CHR001_愤怒` | 02 |
| 镜头视频 | `VID_` | `VID_SHT_S01_006` | 03 |
| 版本 | `_v` | `CHR_001_v2` | 02 |

**组合示例：** `CHR_001_State_B_v2_turnaround.png`

### 状态机（`ASSET_CARD.yaml` 的 `id_status`）

```
RESERVED  →  DRAFT  →  LOCKED  →  （DEPRECATED）
05 留号     资产已建    已过 Gate     废弃
不可出图    不可投产    可全链路引用   号位永久保留不复用
```

> **升 `LOCKED` 只能由 02 执行**（只有本模块跑一致性 Gate）。号位**永不复用**。

---

## 三、初始化步骤

1. 复制 `AI_DRAMA_PROJECT/` 到项目位置并重命名
2. **先建两份共享文档**（`ID-REGISTRY` + `OPEN-ISSUES`）——这两份**由 01 剧本文本在建纲阶段创建**，若你从 02 阶段介入，先向用户索要或补建
3. 把 `模板/` 下模板复制进 `00_PROJECT/` 并改名（PROJECT_STATE / VISUAL_BIBLE / CHANGELOG / ASSET_CARD / INDEX-TEMPLATES）
4. 填写 `VISUAL_BIBLE` → 过世界观锁定
5. 填写 `PROJECT_STATE` → 登记 `LOCK_WORLD`
6. **核对 ID 注册表**：确认待生产资产 ID 均已登记（未登记 → 回报 05 补登）
7. 开始按 `00-主控智能体.md` 的流程生产资产

> ⚠️ **跳过第 2 步的后果**：后续集新角色出现时号段冲突；版权问题拖到发布前才发现。
