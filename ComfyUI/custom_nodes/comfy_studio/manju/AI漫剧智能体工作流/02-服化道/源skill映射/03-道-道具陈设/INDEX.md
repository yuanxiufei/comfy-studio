# 03 道 · 道具陈设 — 源 skill 映射清单

> ⚠️ **本节为初版清单，状态已过时。** 实际抓取进度以 ../INDEX.md（总表）与 ../../源skill库/（已抓归档）为准——多项已抓取完成。


> 职责：手持道具、关键物件、象征物、武器、材质表现
> 抓取模板：`https://raw.githubusercontent.com/021gink/short-drama-ai-skills/main/<URL编码路径>`

---

## A. 道具资产生成（核心）

| 文件 | 路径 | 用途 | 优先级 |
|---|---|---|---|
| `Asset Producer（人物场景道具资产生成器）.md` | `角色/` | 人物+场景+道具一体化资产（8.8KB） | ⭐⭐⭐ |
| `script-to-art-assets.md` | `场景/` | 剧本→美术资产（自动提取道具清单） | ⭐⭐⭐ |
| `asset-expander.md` | `角色/` | 资产扩展器（衍生变体） | ⭐⭐ |
| `character-asset-supervisor.md` | `工具/` | 资产监工（质检） | ⭐⭐⭐ |
| `character-asset-uploader.md` | `工具/` | 资产入库 | ⭐⭐ |

---

## B. 材质与细节表现

| 文件 | 路径 | 用途 | 优先级 |
|---|---|---|---|
| `product-texture-fusion.md` | `场景/` | 产品材质融合 | ⭐⭐⭐ |
| `texture-super-res.md` | `风格/` | 材质超分（纹理增强） | ⭐⭐ |
| `material-auto-fill-i2.md` | `分镜/` | 素材自动填充 | ⭐⭐ |
| `ai-video-micro-detail-director.md` | `分镜/` | 微细节导演（22KB，道具细节） | ⭐⭐ |

---

## C. 特殊题材道具

| 文件 | 路径 | 用途 | 优先级 |
|---|---|---|---|
| `sci-fi-hard-surface-mv.md` | `场景/` | 科幻硬表面（机械/武器） | ⭐⭐ |
| `cg-mech-action-designer.md` | `分镜/` | CG 机甲动作设计 | ⭐ |
| `combat-skill-designer（战斗）.md` | `文档/` | 战斗技能设计（含武器设定） | ⭐⭐ |
| `combat-move-creator.md` | `文档/` | 招式创作 | ⭐ |
| `anime-combat-moves.md` | `分镜/` | 动漫战斗招式（9.9KB） | ⭐⭐ |

---

## D. 场景陈设（与 04 景 联动）

| 文件 | 路径 | 用途 |
|---|---|---|
| `bootstrap-locations.md` | `场景/` | 场景地点引导（13KB，含陈设清单） |
| `scene-layout-designer.md` | `分镜/` | 场景布局设计（4.4KB） |
| `canvas-organizer.md` | `工具/` | 画布组织（13KB，资产排布） |

---

## 工作流定位

```
剧本道具表（第 1 步资产盘点产出）
        ↓
【3.1】道具资产生成  ← Asset Producer / script-to-art-assets
        ↓
【3.2】材质与细节    ← product-texture-fusion / texture-super-res
        ↓
【3.3】道具落位到场景 ← 交接给 04 景
        ↓
【3.4】入库质检      ← character-asset-supervisor
```

## 建议抓取顺序

1. `Asset Producer（人物场景道具资产生成器）.md`
2. `script-to-art-assets.md`
3. `product-texture-fusion.md`
4. `character-asset-supervisor.md`
5. `bootstrap-locations.md`（陈设部分）

