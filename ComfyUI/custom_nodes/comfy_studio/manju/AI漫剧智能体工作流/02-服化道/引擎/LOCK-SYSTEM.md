# LOCK SYSTEM — 锁定系统与修改引擎

> 对应规格 §14 LOCK SYSTEM + §15 MODIFICATION ENGINE + §33 自然语言控制 + §42~§47 各类指令默认语义
> **这是连续生产的核心机制。**

---

## 一、可锁定资产清单（§14）

```text
LOCK_WORLD          世界观
LOCK_CHARACTER      角色身份
LOCK_FACE           脸型五官
LOCK_HAIR           发型发色
LOCK_BODY           体型比例
LOCK_COSTUME        服装
LOCK_PROP           道具
LOCK_ENVIRONMENT    环境
LOCK_COLOR          色彩
LOCK_LIGHTING       光影
LOCK_CAMERA         镜头语言
LOCK_EXPRESSION     表情
LOCK_POSE           动作
```

---

## 二、自然语言 → 锁定映射表（§15 §33）

| 用户说 | 自动解释 |
|---|---|
| 人物不变，只换衣服 | `CHARACTER=LOCK, FACE=LOCK, HAIR=LOCK, BODY=LOCK, COSTUME=MODIFY` |
| 衣服和人物都不变，换成夜景 | `CHARACTER=LOCK, COSTUME=LOCK, ENVIRONMENT=MODIFY, LIGHTING=MODIFY` |
| 全部保持，只改变表情 | `ALL=LOCK, EXPRESSION=MODIFY` |
| 只换发型 | `ALL=LOCK, HAIR=MODIFY` |
| 只换背景 | `ALL=LOCK, ENVIRONMENT=MODIFY` |
| 只改灯光 | `ALL=LOCK, LIGHTING=MODIFY` |
| 只改镜头 | `ALL=LOCK, CAMERA=MODIFY` |
| 全部保持不变（§43） | `WORLD/CHARACTER/FACE/HAIR/BODY/COSTUME/PROP/COLOR/LIGHTING 全 LOCK`，仅用户新指定的变量可变 |
| 重新生成（§44） | **保持资产身份不变，只重新采样画面** |
| 换风格（§45） | `CHARACTER DNA=LOCK, COSTUME DNA=LOCK, PROP DNA=LOCK, WORLD DNA=LOCK, STYLE=MODIFY` |
| 换场景（§46） | `CHARACTER=LOCK, COSTUME=LOCK, PROP=LOCK, ENVIRONMENT=MODIFY, LIGHTING=MODIFY IF NEEDED` |
| 做成漫画/动漫（§47） | 仅改 `rendering style / line quality / shading / visual treatment`，**不得自动改变角色设计** |
| 写实（§48） | 提高写实参数，**保持原始 Character DNA** |
| 高级感/电影感（§49） | 必须具体化光影参数，不得只加 `cinematic, masterpiece` |
| 恢复上一版 | 读 CHANGELOG 上一条，回退 `changed` 项，保持 `unchanged` 项 |
| 恢复原版 | 回退到 v1 |
| 取消这次修改 | 删除最后一条 CHANGELOG 记录并回退 |

---

## 三、修改执行四步（强制）

```text
STEP 1  解析指令 → 生成 LOCK / MODIFY 映射
STEP 2  冲突检测 → 若修改项与 locked_assets 冲突，列出「将发生变化的锁定项」并提示用户
STEP 3  受控生成 → 锁定项写入 prompt 的 Consistency Constraints；修改项写入对应序列位
STEP 4  记录变更 → 追加 CHANGELOG（changed / unchanged / reason），必要时递增版本
```

> ⚠️ **STEP 2 不可省略**。用户要求若会破坏已锁定资产，必须先识别并提示，再执行（规格 §42）。

---

## 四、资产继承规则（§16）

新图默认继承：
```text
WORLD
CHARACTER DNA
COSTUME DNA
PROP DNA
COLOR BIBLE
LIGHTING BIBLE
STYLE BIBLE
```
除非用户明确要求覆盖。

---

## 四·补｜终身固定特征 vs 剧情适配变量（来源：`源skill库/服/character-lifecycle-designer.md`）

> 规格 §29 只说"新建状态卡"，本节明确**边界**——哪些 100% 不可动、哪些可随剧情变化。

### A. 终身固定核心识别特征库（100% 不可改动）

| 项 | 说明 |
|---|---|
| 核心骨相 | 头颅与面部骨架结构 |
| 五官轮廓 | 眼型/鼻型/唇形/耳型轮廓 |
| 瞳色 | 不可变 |
| 标志性永久识别点 | 胎记 / 疤痕 / 齿型 / 痣 |
| 终身不变的微表情习惯 | 如习惯性抿唇、挑眉 |

**修改本组 = 重新设计角色**，必须递增主版本号并通知全项目。

### B. 剧情适配变量项（各状态卡之间可不同）

| 类别 | 可变项 |
|---|---|
| 外貌变化 | 皮肤状态 / 皱纹老化痕迹 / 发色变化 / 胡须毛发变化 / 伤病痕迹 |
| 体态变化 | 身形变化 / 体态气质 |
| 发型妆容 | 发型 / 妆容 |
| 服装配饰 | 全套穿搭 / 核心配饰 |

### C. 状态派生的唯一正确顺序

```
① 先生成【基准状态】（剧本开篇初始状态）套图
        ↓ 用户确认
② 再按关键节点顺序，逐个生成阶段套图
        ↓ 每张单独确认
③ 所有套图的「光影风格 / 渲染质感 / 画幅比例」完全统一
```

> ⚠️ **严禁各阶段同时生成**——必然导致"换脸式"偏差。

### D. 出现偏差时的处理

以**已确认的基准图**为准重新生成，**不得擅自调整人设**。若确实需要改固定特征，按 §42 先列出"将发生变化的锁定项"并提示用户。

---

## 四·补2｜破坏性操作二次确认机制（来源：`源skill库/管线/canvas-organizer.md`）

**所有破坏性操作必须走两步确认：**

```
① 先提交"预览"（不执行）→ 展示将要发生的变化
② 用户确认后 → 才真正执行
```

**适用操作清单（强制）：**

| 操作 | 预览内容 | 备注 |
|---|---|---|
| 覆盖资产卡 / 重新生成已锁定资产 | 将变化的字段与锁定项 | 必须列 `LOCK_*` 影响 |
| 删除 / 归档资产 | 资产 ID + 版本 + 被谁引用 | 建议**软删除**（可恢复） |
| CHANGELOG 回滚 | 将回退的版本与变更项 | |
| 修改 VISUAL_BIBLE / 风格锚点 | 全片影响范围 | 影响最大，需二次确认 |
| 批量更新（如整批重绘光影） | 涉及资产数量与差异 | 批次开始前整体确认，执行时不必逐个确认 |

**软删除与恢复：**
- 删除 = 标记而非物理移除
- 保留"已删除列表"，可随时恢复
- 恢复操作**无需二次确认**（属建设性操作）

---

## 五、状态派生规则（§29 §30 §31）

**角色成长**（受伤/换发型/换服装/成长/衰老/堕落/晋升/易容）→ **新建状态卡，不覆盖原卡**：
```text
Character_001_State_A
Character_001_State_B
Character_001_State_C
```

**服装连续性**：同一套服装必须保持轮廓/主色/材质/扣件/配饰/纹样/长度/层次。
战斗/雨水/泥污/撕裂/血迹/灰尘 → 派生状态卡：
```text
Costume_Normal / Costume_Wet / Costume_Dirty / Costume_Damaged
```

**道具连续性**：重要道具建立 ID（`PROP_001`），记录尺寸/材料/颜色/纹理/损伤/功能/持握方式/状态。
> 同一道具在不同镜头**不得随机改变**。

**场景连续性**：同一场景建立 ID（`ENV_001`），锁定建筑/门窗/家具/地面/光源/主空间关系。
允许变化：天气 · 时间 · 人物 · 灯光状态 · 道具摆放。
> **不得无理由重构空间。**

---

## 六、锁定登记示例

```yaml
locked_assets:
  - LOCK_WORLD
  - "LOCK_CHARACTER:CHR_001"
  - "LOCK_FACE:CHR_001"
  - "LOCK_HAIR:CHR_001"
  - LOCK_COLOR
  - LOCK_LIGHTING

forbidden_changes:
  - "不得改变 CHR_001 的脸型与瞳色"
  - "不得重构 ENV_001 的建筑结构"
  - "全片禁止出现任何文字"
```
