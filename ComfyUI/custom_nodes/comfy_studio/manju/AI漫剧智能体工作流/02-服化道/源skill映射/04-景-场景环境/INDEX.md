# 04 景 · 场景环境 — 源 skill 映射清单

> ⚠️ **本节为初版清单，状态已过时。** 实际抓取进度以 ../INDEX.md（总表）与 ../../源skill库/（已抓归档）为准——多项已抓取完成。


> 源目录：`场景/`（10 文件）
> 职责：空间结构、建筑、陈设、多角度还原、全景、天气
> 抓取模板：`https://raw.githubusercontent.com/021gink/short-drama-ai-skills/main/%E5%9C%BA%E6%99%AF/<文件名>`

---

## A. 场景多角度还原（核心）

| 文件 | 用途 | 优先级 |
|---|---|---|
| `Scene Multi-Angle Generator（场景多角度参考图生成器）.md` | 场景多角度参考图（9.7KB） | ⭐⭐⭐ |
| `scene-multi-angle-generator.md` | 同上英文版（4.4KB） | ⭐⭐⭐ |
| `场景多视角生成器.md` | 场景多视角（中文版） | ⭐⭐⭐ |
| `GPT-Image2双视角空间还原生成器.md` | 双视角空间还原 | ⭐⭐⭐ |
| `gpt-image2-dual-view-i2.md` | 双视角 v2 | ⭐⭐ |

---

## B. 场景构建与环境

| 文件 | 用途 | 优先级 |
|---|---|---|
| `bootstrap-locations.md` | 场景地点引导（13KB，最全） | ⭐⭐⭐ |
| `script-to-art-assets.md` | 剧本→场景资产 | ⭐⭐⭐ |
| `vr-panorama-generator.md` | VR 全景生成 | ⭐⭐ |
| `scene-to-panorama.md`（在 `分镜/`） | 场景转全景 | ⭐⭐ |
| `anime-bg-unifier.md`（在 `角色/`） | 动漫背景统一（8.4KB） | ⭐⭐⭐ |

---

## C. 特殊场景

| 文件 | 路径 | 用途 | 优先级 |
|---|---|---|---|
| `sci-fi-hard-surface-mv.md` | `场景/` | 科幻硬表面场景 | ⭐⭐ |
| `animation-studio-suite.md` / `animation studio suite.md` | `场景/` | 动画工作室套件 | ⭐⭐ |
| `product-texture-fusion.md` | `场景/` | 材质融合（陈设质感） | ⭐⭐ |
| `weather-control.md` | `风格/` | 天气控制（雨雪雾） | ⭐⭐ |
| `anchor-scene-generator-i3.md` | `分镜/` | 锚定场景生成（10KB） | ⭐⭐ |

---

## D. 场景布局与分镜衔接

| 文件 | 路径 | 用途 |
|---|---|---|
| `scene-layout-designer.md` | `分镜/` | 场景布局设计 |
| `grid-storyboard.md` | 已归档 | 宫格分镜（含场景交代） |
| `25宫格动态漫分镜.md` | 已归档 | 25宫格（含场景过渡） |

---

## 工作流定位

```
【第 1 步】场景表（资产盘点）
        ↓
【4.1】场景主体生成   ← bootstrap-locations
        ↓
【4.2】多角度还原     ← Scene Multi-Angle Generator（保证空间自洽）
        ↓
【4.3】道具落位       ← 承接 03 道（product-texture-fusion 材质）
        ↓
【4.4】天气/氛围      ← weather-control
        ↓
【4.5】背景统一       ← anime-bg-unifier
        ↓
→ 过【风格锁定 Gate】交接 05 风格光影
```

## 建议抓取顺序

1. `bootstrap-locations.md`（场景基础，最全）
2. `Scene Multi-Angle Generator（场景多角度参考图生成器）.md`（多角度，核心）
3. `anime-bg-unifier.md`（背景统一）
4. `script-to-art-assets.md`（自动化提取）
5. `weather-control.md`（氛围）
6. `vr-panorama-generator.md`（全景，按需）

