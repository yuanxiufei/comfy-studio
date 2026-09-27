# 05 风格光影 — 源 skill 映射清单

> ⚠️ **本节为初版清单，状态已过时。** 实际抓取进度以 ../INDEX.md（总表）与 ../../源skill库/（已抓归档）为准——多项已抓取完成。


> 源目录：`风格/`（21 文件）
> 职责：影调、色彩、LUT、光线一致性、画风锁定（**防画风漂移的关键闸门**）
> 抓取模板：`https://raw.githubusercontent.com/021gink/short-drama-ai-skills/main/%E9%A3%8E%E6%A0%BC/<文件名>`

---

## A. 光影体系（核心）

| 文件 | 用途 | 优先级 |
|---|---|---|
| `cinematic-lighting-master.md` | 电影光影大师（12KB）→ 已归档至 `03-分镜导演/源skill/` | ⭐⭐⭐ |
| `cinematic-lighting-library.md` | 光影库（15KB，最全，31种布光） | ⭐⭐⭐ |
| `分镜光影统一大师.md` | 分镜光影统一（15.5KB，跨镜一致性） | ⭐⭐⭐ |
| `storyboard-lighting-kimi-i3.md` | 分镜布光 v3 | ⭐⭐ |
| `storyboard lighting kimi i3.md` | 分镜布光原始版 | ⭐⭐ |

---

## B. 调色与色彩

| 文件 | 用途 | 优先级 |
|---|---|---|
| `cinematic-colorist.md` | 电影调色师（10KB） | ⭐⭐⭐ |
| `hollywood-lut.md` | 好莱坞 LUT | ⭐⭐⭐ |
| `image-analyzer-prompt-reverse.md` | 图像分析 + 提示词逆向（取色） | ⭐⭐ |

---

## C. 画风锁定（Gate 支撑）

| 文件 | 用途 | 优先级 |
|---|---|---|
| `style-extractor.md` | 风格提取器（4.1KB，核心） | ⭐⭐⭐ |
| `绘风指南.md` | 绘风指南 | ⭐⭐⭐ |
| `熊猫的画风守护者.md` | 画风守护者（防漂移） | ⭐⭐⭐ |
| `ai-art-director.md` | AI 艺术总监（5.5KB） | ⭐⭐ |

---

## D. 风格专题

| 文件 | 用途 | 优先级 |
|---|---|---|
| `anime-cinematic-style.md` | 动漫电影感风格（10KB） | ⭐⭐⭐ |
| `style-3d-plush.md` | 3D 毛绒风 | ⭐ |
| `magpie-murders-style.md` | 《喜鹊谋杀案》风格 | ⭐ |
| `终末地风格视频制作 Skill.md` | 终末地风格（6.5KB） | ⭐⭐ |
| `绘心绘角插画师.md` | 插画风角色 | ⭐⭐ |
| `GPT-image2电影级场景提示词.md` | GPT-Image2 电影级场景 | ⭐⭐ |

---

## E. 材质与氛围

| 文件 | 用途 | 优先级 |
|---|---|---|
| `texture-super-res.md` | 材质超分（7.7KB） | ⭐⭐ |
| `weather-control.md` | 天气控制（雨雪雾霓虹） | ⭐⭐ |

---

## F. 跨模块引用

| 文件 | 原目录 | 归属 |
|---|---|---|
| `anime-bg-unifier.md` | `角色/` | → 04 景（背景统一） |
| `cinematic-lighting-master.md` | 已本地归档 | → `03-分镜导演/源skill/` |

---

## 工作流定位（风格锁定 Gate）

```
【5.1】提取参考风格     ← style-extractor / 绘风指南
        ↓
【5.2】确定光影体系     ← cinematic-lighting-library + 情绪照明公式
        ↓
【5.3】确定调色与 LUT   ← cinematic-colorist / hollywood-lut
        ↓
【5.4】写定「风格英文锚点」  ← 全片所有生图 prompt 末尾强制追加
        ↓
【5.5】跨镜光影一致性校验 ← 分镜光影统一大师 + 熊猫的画风守护者
        ↓
*** 风格锁定 Gate：以上 9 项锁定后全片不得更改 ***
```

## 风格锚点参考（写死在每条 prompt 末尾）

```
cinematic lighting, muted color palette, UE5 render, 8k, highly detailed, film grain
```

## 建议抓取顺序

1. `style-extractor.md`（风格提取，最核心）
2. `cinematic-lighting-library.md`（光影库）
3. `cinematic-colorist.md`（调色）
4. `hollywood-lut.md`（LUT）
5. `分镜光影统一大师.md`（跨镜一致性）
6. `熊猫的画风守护者.md`（防漂移）
7. `anime-cinematic-style.md`（动漫风格专题）

