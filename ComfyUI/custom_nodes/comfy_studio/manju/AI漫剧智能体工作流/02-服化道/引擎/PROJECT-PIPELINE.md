# PROJECT PIPELINE — 生产流水线与行为总循环操作手册

> 对应规格 §25 FULL PROJECT PIPELINE + §26 剧本解析器 + §41 完整行为总循环
> **本文把规格里的流程图变成每一步可执行、有输入输出契约、有检查点的操作手册。**

---

## 一、完整漫剧生产流水线（§25）

```
小说 / 剧本
    ↓ ① 文本解析
文本解析
    ↓ ② 人物抽取
人物抽取
    ↓ ③ 人物关系
人物关系
    ↓ ④ 世界观
世界观
    ↓ ⑤ 视觉圣经 ← ★闸门1：世界观锁定
视觉圣经
    ↓ ⑥ Character DNA
Character DNA
    ↓ ⑦ Character Turnaround ← ★闸门2：角色一致性
Character Turnaround
    ↓ ⑧ Expression Sheet
Expression Sheet
    ↓ ⑨ Pose Sheet
Pose Sheet
    ↓ ⑩ Costume Library
Costume Library
    ↓ ⑪ Prop Library
Prop Library
    ↓ ⑫ Environment Library
Environment Library
    ↓ ⑬ Storyboard
Storyboard
    ↓ ⑭ Shot Prompt
Shot Prompt
    ↓ ⑮ Image Generation ← RULE-001 图像优先
Image Generation
    ↓ ⑯ Consistency Check ← ★闸门3：一致性
Consistency Check
    ↓ ⑰ Revision
Revision
    ↓ ⑱ Final Asset
Final Asset
```

---

## 二、每一步的输入/输出契约

| 步 | 阶段 | 输入 | 产出物 | 落盘位置 | 闸门 |
|---|---|---|---|---|---|
| ① | 文本解析 | 小说/剧本原文 | 结构化场景表 | `00_PROJECT/` | — |
| ② | 人物抽取 | 场景表 | CHARACTER INDEX | `00_PROJECT/INDEX_CHARACTER.md` | — |
| ③ | 人物关系 | CHARACTER INDEX | 关系表 + 身高关系图 | 同上 | — |
| ④ | 世界观 | 场景表 + 人物 | 世界观草案（9 项） | `01_WORLD/` | — |
| ⑤ | 视觉圣经 | 世界观草案 | `VISUAL_BIBLE`（六大项） | `00_PROJECT/VISUAL_BIBLE.md` | **★世界观锁定** |
| ⑥ | Character DNA | 人物小传 | FACE/HAIR/BODY/COSTUME/SIGNATURE DNA | `02_CHARACTERS/CHR_00X/ASSET_CARD.yaml` | — |
| ⑦ | 三视图 | Character DNA | 三视图图 + prompt | 同上 `turnaround.png` | **★角色一致性** |
| ⑧ | 表情表 | 三视图 | 16 表情 | `06_EXPRESSIONS/EXP_00X/` | — |
| ⑨ | 动作表 | 三视图 | 动作集 | `07_POSES/POS_00X/` | — |
| ⑩ | 服装库 | COSTUME INDEX | 服装独立资产（三视图构图） | `03_COSTUMES/CST_00X/` | — |
| ⑪ | 道具库 | PROP INDEX | 道具独立资产 | `04_PROPS/PRP_00X/` | — |
| ⑫ | 场景库 | ENVIRONMENT INDEX | 场景多角度 | `05_ENVIRONMENTS/ENV_00X/` | — |
| ⑬ | 分镜 | SHOT INDEX | 分镜表 | `08_STORYBOARDS/` | — |
| ⑭ | 镜头提示词 | 分镜表 | 每镜 17 项 prompt | `09_SHOTS/SHT_xxx/` | — |
| ⑮ | 出图 | prompt | 图像 | 同上 | RULE-001 |
| ⑯ | 一致性检查 | 全部资产 | 检查报告 | `10_CONSISTENCY/REPORT_*.md` | **★一致性** |
| ⑰ | 修订 | 检查报告 | 修正后资产 + CHANGELOG | 各处 | — |
| ⑱ | 最终资产 | 修订后资产 | 定稿资产库 | — | — |

---

## 三、行为总循环（§41）逐环节说明

智能体每次收到任务，**严格按此顺序**：

| # | 环节 | 动作 | 失败处理 |
|---|---|---|---|
| 1 | INPUT | 接收用户输入 | — |
| 2 | INTENT ROUTER | 判定 A~J 十个意图之一 | 多意图时按优先级问一句确认 |
| 3 | PROJECT STATE | 读取/建立项目状态 | 无状态则先建 |
| 4 | WORLD CONTEXT | 载入世界观 | 无世界观则先走 §04（或在对话中快速确立） |
| 5 | ASSET CONTEXT | 载入相关资产卡与索引 | 无则新建 |
| 6 | LOCK CHECK | 解析 LOCK/MODIFY 映射 | 与 locked_assets 冲突 → **先提示再执行** |
| 7 | REFERENCE CHECK | 三层继承（身份/风格/构图） | 参考图不得覆盖用户新要求 |
| 8 | PROMPT ENGINE | 按 17 项序列构建 prompt | — |
| 9 | QUALITY PREFLIGHT | 10 项预检 | 未过 → 补齐后重来 |
| 10 | IMAGE GENERATION | **先生成图像** | 无图像能力 → 降级为可执行 prompt 模式 |
| 11 | POSTFLIGHT | 10 项后检 | 未过 → 走 §24 修复 |
| 12 | CONSISTENCY CHECK | 18 项一致性 | 冲突 → 出报告并修复 |
| 13 | ASSET UPDATE | 更新资产卡/索引/CHANGELOG | — |
| 14 | USER OUTPUT | 输出结果（图像 → prompt → 说明） | — |

---

## 三·补｜两个补充环节（来源：源 skill 库）

### 补充环节 A｜场景资产库前置（`源skill库/景/scene-multi-angle-generator.md`）

**位置**：步⑫「Environment Library」内部，必须先于分镜生成。

```
接场景描述
    ↓
① 建立 N/S/E/W 绝对坐标系（禁用"左/右"）
    ↓
② 构建场景圣经（光源/建筑/家具/陈设 —— 材质词全程唯一）
    ↓
③ 向用户确认缺失细节（≤3 个问题）
    ↓
④ 生成 S01 基准图（纯文字 prompt）→ 保存 URL
    ↓
⑤ S02–S06 全部以 S01 为 reference_image 生成
    ↓
⑥ 一致性自审五问（坐标/家具/物品/光线/S01 引用）
    ↓
⑦ 输出资产索引表（景别标签 + 方向标签 + URL）
```

**对用户只输出一行**：`✅ 场景「XXX」资产库已建立，包含 N 个角度参考图`

> ⚠️ 各角度**独立从文字生成 = 必然漂移**，必须图片锚定。

**分镜阶段查表使用：**
```
分镜描述 + 景别 → 查资产索引表 → 取对应参考图 URL → 作为 reference_image 输入生图
```

适用于**所有场景**，是 `04-景` 模块标准产线。

### 补充环节 B｜工程重试层（`源skill库/管线/video-generation-supervisor.md`）

**位置**：步⑮「Image Generation」与其后的失败处理。

**重试顺序（重要）：**

```
生成 → 失败
    ↓
① 原参数重试（不改任何参数）—— 最多 2 次
    ↓ 仍失败
② 走 §24 FAILURE 修复表（改提示词后再试）
    ↓ 仍失败
③ 上报用户，记录到失败登记表
```

> **区分**：① 是**工程层**（可能是服务抖动/排队失败），② 是**内容层**（提示词本身有问题）。先做 ① 可避免因服务问题误改提示词。

**参数建议：**
- `max_retries`: 3-5（避免无限循环占用额度）
- 失败重试**完全保留原参数**，不做任何修改
- 批量生成时统一 max_retries

---

## 四、三个闸门（Gate）

| 闸门 | 位置 | 通过标准 | 未过的后果 |
|---|---|---|---|
| **① 世界观锁定** | 步⑤后 | VISUAL_BIBLE 六大项齐全 + 登记 `LOCK_WORLD` | 全片世界观漂移 |
| **② 角色一致性** | 步⑦后 | 三视图比例统一、Signature DNA ≥3 项、色值标注 | 后续所有出图脸崩 |
| **③ 一致性检查** | 步⑯ | 18 项无 P0/P1 冲突 | 资产不可用，需重做 |

> ⚠️ 任一闸门未过，**不得进入下一步**。用户说"跳过"时应提示风险并请求二次确认。

---

## 五、输出节奏纪律

**默认输出顺序（RULE-001）：**
```
① 图像
② 中文 Prompt
③ English Prompt
④ Negative Prompt
⑤ Asset Lock
```

**禁止：** 先输出大段解释或理论，再生成图像。

**单次输出控制：**
- 一次只处理一个意图（除非用户明确要求批量）
- 剧本级任务分批：先出索引 → 确认 → 再出资产
- 不得一次性生成整部剧的全部资产

---

## 六、非图像环境降级模式

当运行环境不具备图像生成能力（§RULE-001）：

1. **不得假装已生成图像**
2. 转为「可执行生图 Prompt 模式」
3. 输出顺序调整为：
```
① 中文 Prompt（完整 17 项）
② English Prompt
③ Negative Prompt
④ Asset Lock
⑤ 建议模型与参数（按 §21 适配层）
```

---

## 七、任务启动自检（每次生产前）

- [ ] 意图路由已判定
- [ ] 项目状态已读取/建立
- [ ] 世界观已存在（否则先建）
- [ ] 相关资产卡已载入
- [ ] LOCK/MODIFY 映射已解析
- [ ] 冲突项已提示给用户
- [ ] Preflight 10 项通过
- [ ] 输出顺序符合 RULE-001
