# NEGATIVE PROMPT LIBRARY — 负面提示词库

> 对应规格 §22｜NEGATIVE PROMPT ENGINE + §24｜ERROR RECOVERY

---

## 一、通用负面提示词（所有资产默认追加）

```text
bad anatomy,
malformed anatomy,
deformed body,
extra fingers,
missing fingers,
fused fingers,
extra limbs,
duplicated body parts,
distorted face,
asymmetrical eyes,
inconsistent hairstyle,
inconsistent costume,
wrong accessories,
incorrect proportions,
floating objects,
broken perspective,
low detail,
blurry,
noisy,
muddy colors,
harsh shadows,
plastic skin,
unnatural highlights,
text,
letters,
logo,
watermark,
caption,
signature,
random symbols
```

---

## 二、三视图专用（§22 三视图）

```text
inconsistent character design,
different face between views,
different hairstyle,
different costume,
different age,
different skin tone,
different eye color,
inconsistent accessories,
inconsistent body proportions,
cropped head,
cropped feet,
overlapping views,
merged limbs,
duplicate character,
extra character
```

---

## 三、按模块追加

### 角色 / 三视图（Character）
```
不同视图之间比例不一致, 多出角色, 人物重叠, 头部被裁切, 脚部被裁切
mismatched proportions between views, extra characters, overlapping figures, cropped head, cropped feet
```

### 服装（Costume）
```
结构混乱, 穿戴顺序错误, 材质不明, 层次融合, 配饰缺失, 图案错位
confused garment structure, wrong wearing order, ambiguous material, merged layers, missing accessories, misaligned patterns
```

### 道具（Prop）
```
角度不一致, 比例失真, 结构错误, 材质混淆, 多出部件
inconsistent angles, distorted scale, wrong structure, confused materials, extra parts
```

### 表情（Expression）
```
改变脸型, 改变年龄, 改变种族, 面部塌陷, 眼睛变形
changed face shape, changed age, changed ethnicity, collapsed facial structure, deformed eyes
```

### 动作（Pose）
```
肢体断裂, 关节反向, 多余手臂, 重心失衡, 悬浮
broken limbs, reversed joints, extra arms, unbalanced center of gravity, floating
```

### 场景（Environment）
```
纯白背景, 空间逻辑矛盾, 建筑结构突变, 光源矛盾, 尺度错误
pure white background, contradictory spatial logic, abrupt architecture change, contradictory light sources, wrong scale
```

---

## 四、ERROR RECOVERY 修复映射表（§24）

| 编号 | 失败现象 | 处理方案 | 追加负面词 |
|---|---|---|---|
| **FAILURE-001** | 脸不一致 | 强化 Face DNA → 锁定五官 → 锁定年龄 → 锁定发型 → 减少无关形容词 | （见"表情"组） |
| **FAILURE-002** | 三视图不一致 | 明确 Front/Side/Back → 重复 Character DNA → 锁定服装 → 锁定比例 → 禁止视图重叠 | （见"三视图"组） |
| **FAILURE-003** | 服装错误 | 拆分服装层级 → 明确材料 → 明确结构 → 明确穿戴顺序 | （见"服装"组） |
| **FAILURE-004** | 背景污染 | 强制 `pure white background, seamless white studio background, no environment, no props` | `environment, background objects, props, scenery` |
| **FAILURE-005** | 产生文字 | 强制 `no text, no letters, no logo, no watermark, no caption` | `text, letters, logo, watermark, caption, signature, random symbols` |

---

## 五、使用纪律

1. **默认全量追加**：通用负面词 + 对应模块负面词，两层叠加
2. **fail 后只增不换**：出现失败现象时，在原有负面词基础上**追加**修复映射表中的词，不要整体替换
3. **不得虚构参数**：SD/FLUX 的 negative 字段写纯文本词表；MJ 用 `--no` 参数；GPT Image 用自然语言禁止项描述

### 各平台负面词写法

| 平台 | 写法 |
|---|---|
| Midjourney / Niji | `--no text, watermark, logo, extra fingers` |
| Stable Diffusion / FLUX | `Negative Prompt:` 字段，逗号分隔词表 |
| GPT Image / 通用 | 自然语言 Brief 中的「禁止变化项」段落 |
| Seedance / 可灵 | 中文自然语言中的「禁止出现」段落 |
