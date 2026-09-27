# 06_EXPRESSIONS

> 本目录为项目骨架占位说明，可直接删除本文件后开始工作。

## 用途

表情资产

目录结构：
EXP_CHR001/
  - anger.png / joy.png / sadness.png / fear.png / surprise.png
  - disgust.png / neutral.png ...（共 16 式，见 ../../引擎/EXPRESSION-POSE-LIBRARY.md）

命名：EXP_CHR001_愤怒
铁律：只改眉/眼/嘴/肌肉，不改脸型/年龄/发型/发色。

---

## 相关文档

- 项目结构总览：`../../项目骨架/README.md`
- 规格主控：`../../00-主控智能体.md`
- 检查规则：`../../引擎/CONSISTENCY-CHECKLIST.md`


---

## ⚠️ ID 登记要求

本目录资产属 **EXP_** 段，**必须先在 `../00_PROJECT/ID-REGISTRY.md` 登记**：

| 项 | 值 |
|---|---|
| 命名格式 | EXP_<CHR号>_<表情名>（如 EXP_CHR001_愤怒）｜派生 ID，不占号位 |
| 谁分配 | 02 服化道 |
| 状态要求 | 出图前须 ≥ `DRAFT`；下游引用须为 `LOCKED`（由 02 跑一致性 Gate 后升级） |

- **不得自造未登记 ID**；发现缺失 → 回报对应模块补登记
- 号位**永不复用**（废弃 ID 保留空位，防旧稿引用错位）
- 命名规范权威：`00-总控路由.md` §四
