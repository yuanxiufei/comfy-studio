# 03_COSTUMES

> 本目录为项目骨架占位说明，可直接删除本文件后开始工作。

## 用途

服装资产（独立资产，不依附角色）

目录结构：
COSTUME_001/
  - ASSET_CARD.yaml
  - front.png / side.png / back.png / fabric.png

命名：CST_001 / CST_001_Wet / CST_001_Dirty / CST_001_Damaged
状态派生规则见 §30。

---

## 相关文档

- 项目结构总览：`../../项目骨架/README.md`
- 规格主控：`../../00-主控智能体.md`
- 检查规则：`../../引擎/CONSISTENCY-CHECKLIST.md`


---

## ⚠️ ID 登记要求

本目录资产属 **CST_** 段，**必须先在 `../00_PROJECT/ID-REGISTRY.md` 登记**：

| 项 | 值 |
|---|---|
| 命名格式 | CST_<3位>（可选状态后缀，如 CST_001_Wet） |
| 谁分配 | 05 提逻辑 / 02 定稿 |
| 状态要求 | 出图前须 ≥ `DRAFT`；下游引用须为 `LOCKED`（由 02 跑一致性 Gate 后升级） |

- **不得自造未登记 ID**；发现缺失 → 回报对应模块补登记
- 号位**永不复用**（废弃 ID 保留空位，防旧稿引用错位）
- 命名规范权威：`00-总控路由.md` §四
