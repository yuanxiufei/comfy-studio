# VISUAL_BIBLE — 视觉圣经

> 对应规格 §04｜WORLD BUILDER｜世界观引擎
> 完整项目开始时**必须先建立视觉世界**。世界观一旦锁定，后续所有模块自动继承。

---

## 4.1 基础世界观

| 项 | 内容 |
|---|---|
| 时代 | |
| 地域 | |
| 文明 | |
| 社会结构 | |
| 科技水平 | |
| 宗教 / 神话 | |
| 政治结构 | |
| 经济 | |
| 生活方式 | |

---

## 4.2 建筑

| 项 | 内容 |
|---|---|
| 建筑类型 | |
| 结构 | |
| 比例 | |
| 屋顶 | |
| 门窗 | |
| 梁柱 | |
| 地面 | |
| 墙体 | |
| 家具 | |
| 装饰 | |

---

## 4.3 材料

| 材料 | 视觉特征（颜色/质感/反光/磨损基准） |
|---|---|
| 木材 | |
| 石材 | |
| 金属 | |
| 玻璃 | |
| 陶瓷 | |
| 皮革 | |
| 布料 | |
| 纸张 | |

---

## 4.4 色彩 Color Bible

| 角色 | 色值 | 用途 |
|---|---|---|
| Primary | `#` | 主色（占画面 60%） |
| Secondary | `#` | 辅色（30%） |
| Accent | `#` | 点缀色（10%） |
| Skin | `#` | 肤色基准 |
| Shadow | `#` | 阴影色倾向 |
| Highlight | `#` | 高光色倾向 |
| Environment | `#` | 环境基调色 |

---

## 4.5 灯光 Lighting Bible

| 项 | 内容 |
|---|---|
| Key（主光） | 方向：　性质：　强度： |
| Fill（辅光） | |
| Rim（轮廓光） | |
| Ambient（环境光） | |
| Temperature（色温） | |
| Shadow（阴影） | |
| Atmosphere（氛围） | 空气感/雾气/尘埃 |

---

## 4.6 镜头 Camera Bible

| 项 | 内容 |
|---|---|
| Lens feeling（镜头感） | |
| Depth（景深） | |
| Framing（构图） | |
| Camera height（机位高度） | |
| Movement（运动） | |

---

## 4.7 场景坐标系（来源：`源skill库/景/scene-multi-angle-generator.md`）

> **所有场景必须建立固定坐标系**，否则多角度生成必然空间错乱。

```
  N（主采光面 / 主窗）
  ↑
W ←·→ E
  ↓
  S（入口 / 门）
```

**铁则：**
- 所有物品描述使用 **N/S/E/W 绝对方位**
- 提示词中**禁止单独使用 left/right**（必须加方位前缀：`on the north wall` / `facing east`）
- 坐标系建立后**全程不变**，镜头切换不影响物品的绝对位置

| 场景 ID | N 面 | E 面 | S 面 | W 面 | 主光源方位 | 投影朝向 |
|---|---|---|---|---|---|---|
| ENV_001 | | | | | | |
| ENV_002 | | | | | | |

**材质词锁定表**（写定后全程唯一，禁止同义词替换）：

| 物品类别 | 锁定用词 | 禁用同义词 |
|---|---|---|
| 例：容器 | 陶壶 | 罐 / 器皿 / 坛子 |
| | | |

---

## 4.8 风格 DNA / 风格锚点（来源：`源skill库/风格/style-extractor.md`）

**风格锁定三选一，不得混用：**

- ☐ **A 风格 DNA**（有参考图时用）— 五维解构结果：
  ```
  电影摄影学：______  色彩理论：______  灯光技术：______
  媒介与质感：______  艺术与类型美学：______
  ```
  **组合优先级**：`[媒介] > [艺术风格] > [光照] > [色彩] > [质感] > [构图]`
  **DNA 字符串**：
  ```
  ________________________________________________
  ```

- ☐ **B LUT 预设**（无参考图时用）— 选一种：
  Teal and Orange / Golden Hour / Noir / Black and Gold / Cyberpunk Neon / Desaturated War

- ☐ **C 光影六维**（精细控制时用）— 六步组合结果：
  ```
  ①基础风格：______ ②光源：______ ③方向光质：______
  ④氛围：______ ⑤特殊光效：______ ⑥固定附加：subtle backlight, 微微逆光
  ```

**风格英文锚点（全片所有 prompt 末尾强制追加，一字不改）：**

```
____________________________________________________________
```

---

## 4.9 visual_style 可选值（31 种风格速查）

> 来源：`源skill库/景/bootstrap-locations.md`（含完整英文 prompt hints，需要时查原文）
> 用途：填写上文 `visual_style` 字段时从此表选取，**不要让用户浏览全部选项**——根据氛围主动推荐 2-3 个。

### 写实 / 摄影系

| ID | 风格 | 关键英文词 |
|---|---|---|
| ST-01 | 电影写实 | `cinematic, 8k, photorealistic, cinematic lighting, IMAX, Shot on 35mm` |
| ST-29 | 城市纪实 | `street photography, documentary, candid, urban atmosphere, realistic` |
| ST-30 | 高定时尚 | `high fashion editorial, avant-garde, luxury brand aesthetic` |

### 动画 / 插画系

| ID | 风格 | 关键英文词 |
|---|---|---|
| ST-02 | 赛璐珞动画 | `anime style, cel shaded, vibrant colors, clean outlines` |
| ST-13 | 宫崎骏风 | `watercolor, lush landscapes, heartwarming, vibrant green` |
| ST-22 | 水彩清新 | `light watercolor, soft edges, ethereal, pastel colors` |
| ST-10 | 手绘草图 | `rough sketch, pencil drawing, charcoal, hand-drawn` |
| ST-06 | 美漫卡通 | `American comic book style, bold lines, dramatic shadows` |
| ST-17 | 浮世绘 | `Ukiyo-e style, woodblock print, flat perspective` |
| ST-15 | 像素艺术 | `pixel art, 8-bit, isometric pixel art` |
| ST-28 | 梦幻泡泡 | `dreamy, soft focus, pearlescent, pastel bokeh` |

### 3D / CG 系

| ID | 风格 | 关键英文词 |
|---|---|---|
| ST-03 | 写实CG | `unreal engine 5 render, ray tracing, Octane Render, high-end game CG` |
| ST-11 | 粘土风格 | `claymation, stop-motion style, miniature, handcrafted texture` |
| ST-24 | 纸雕风格 | `paper cut style, layered paper, shadow box, 3D depth` |
| ST-25 | 乐高风格 | `Lego style, plastic bricks, toy photography, modular` |

### 类型片系

| ID | 风格 | 关键英文词 |
|---|---|---|
| ST-04 | 赛博朋克 | `cyberpunk style, neon lights, rainy street, futuristic city` |
| ST-08 | 黑色电影 | `film noir, high contrast, monochrome, dramatic shadows, smoky atmosphere` |
| ST-14 | 废土风格 | `wasteland style, post-apocalyptic, dusty, rusty, desolate` |
| ST-31 | 恐怖悬疑 | `horror aesthetic, suspenseful, unsettling, deep shadows, creepy details` |
| ST-19 | 奇幻魔幻 | `epic fantasy, magical atmosphere, glowing elements` |
| ST-12 | 蒸汽朋克 | `steampunk, Victorian industrial, gears, brass, intricate machinery` |
| ST-21 | 暗黑哥特 | `gothic style, dark fantasy, ornate architecture, eerie atmosphere` |
| ST-23 | 极速动感 | `speed lines, dynamic motion blur, high energy, fast-paced` |

### 传统 / 艺术系

| ID | 风格 | 关键英文词 |
|---|---|---|
| ST-05 | 中式国风 | `traditional Chinese painting style, ink wash, elegant, ethereal, Zen aesthetic` |
| ST-16 | 古典油画 | `classical oil painting, heavy brushstrokes, museum quality` |
| ST-09 | 复古怀旧 | `vintage, film grain, muted colors, nostalgic, Kodachrome` |
| ST-18 | 波普艺术 | `pop art, screenprint, comic dots, vibrant primary colors` |
| ST-20 | 波西米亚 | `bohemian style, colorful textiles, ethnic patterns, artistic flair` |
| ST-26 | 迷幻艺术 | `psychedelic art, trippy, kaleidoscope, fluid swirls` |

### 设计 / 现代系

| ID | 风格 | 关键英文词 |
|---|---|---|
| ST-07 | 极简现代 | `minimalist, clean design, geometric, architectural` |
| ST-27 | 包豪斯 | `Bauhaus style, geometric shapes, primary colors, functional design` |

> ⚠️ 原表中部分条目含 `[艺术家/工作室] style` 表述，**商业项目使用须谨慎**，建议改为风格特征描述。

### 双视角合成图（场景风格确认工具）

场景风格确认后，可生成**双视角合成图**辅助空间判断：

```
图面结构：广角主图占据整个画布，顶视图嵌入右上角（约 20-25%）

┌─────────────────────────────────────┐
│                           ┌───────┐ │
│                           │顶视图 │ │
│      广角主图             │(鸟瞰) │ │
│      (场景全貌)           └───────┘ │
└─────────────────────────────────────┘
```

**提示词结构：**
```
[场景核心描述], [风格关键词],
wide-angle establishing shot occupying full canvas showing [场景全貌], no humans,
clear horizon line, sharp object edges, [光影描述],
inset upper-right corner (20-25% of canvas) top-down bird's eye view of same location
showing floor plan layout with key objects,
spatial arrangement matching between wide shot and top-down view,
thin white border frame around inset view,
16:9 cinematic composition, ultra-realistic details, clean design, correct proportions
```

---

## ✅ 世界观锁定确认

- [ ] 六大项全部填写完毕
- [ ] 已写入 `PROJECT_STATE.yaml` 的 `visual_style` / `*_bible` 字段
- [ ] 已在 `locked_assets` 中登记 `LOCK_WORLD`

> **锁定后：后续所有 Character / Costume / Props / Environment / Shot 自动继承，不得无理由偏离。**
