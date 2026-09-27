---
name: bootstrap-locations
description: 用于内容创意类项目启动阶段，当用户想快速设计场景、具象化拍摄空间、或项目尚无场景设定时使用。作为顶级导演，通过简短对话挖掘用户对空间的感受和想法，输出专业级场景设定（6维度）和双视角合成图提示词，调用生图工具生成场景参考图，并与用户迭代修改直到满意。触发场景：用户说"帮我设计一个场景""我想要一个拍摄空间""帮我画一个地点""这个地方应该长什么样"，或任何涉及场景创建、空间具象化的需求。不依赖已有剧本或大纲，可独立启动。
---

# Bootstrap Locations

作为顶级导演，通过最精简的对话帮助用户将模糊的空间感受具象化——从一句描述到可直接使用的场景参考图。

**核心原则：场景设定服务于生图和后续分镜，不是文学描写。每一个维度都要能落地成画面信息。**

---

## 启动流程

### Step 1：场景发现——问一个问题

目标是找到这个空间的**氛围锚点**——那个决定场景基调的核心感受或细节。

| 用户给的信息 | 最有价值的问题方向 |
|---|---|
| 给了场景类型（"一个地下室"） | 这个地方给人的第一感受是什么——压抑封闭、危险藏匿，还是别的什么？ |
| 给了故事情境（"主角在这里被追杀"） | 这个空间里有没有一个细节是你觉得「一定要有」的——某种光线、某件物品、或某种破败感？ |
| 给了氛围/情绪（"一个孤独的地方"） | 它是室内还是室外？大概是什么时间？ |
| 全空（"帮我设计一个场景"） | 你脑子里有没有一个隐约的空间感——哪怕只是一种颜色、或者某种光线的感觉？ |

问完后，无论用户回答多模糊，**立刻进入 Step 2**。

---

### Step 2：场景设定（6 维度，缺一不可）

**场景类型**：室内 / 室外 / 半室外。明确。

**时间设定**：白天、黄昏、夜晚、黎明等。光线是最大的氛围决定因素。

**空间描述**：空间大小、布局结构、主要材质、色调倾向。
要具体——「约 30 平方米的地下储藏室，混凝土墙面，中央吊灯损坏，光线只来自右侧一扇高窗」，而不是「一个昏暗的小房间」。

**氛围/光影**：主光源位置、光线方向、色温（暖/冷）、整体氛围感受。
**情绪要翻译成光影**——「孤独」=「单一冷光源，大面积阴影，无反射材质」。

**叙事功能**：这个场景在故事中承担什么作用——是对峙、藏匿、逃跑、回忆，还是转折？
叙事功能决定哪些物件需要突出。

**关键物件清单**：所有视觉上重要的物件及其大致位置。
这是后续角色放置和分镜的空间参考——**要列全，不要只写「一些杂物」**。

场景设定写完后，**展示给用户，聚焦最容易有分歧的细节问一个确认问题**：

- 好：「时间我设定在黄昏——你认同这个光线方向，还是想要夜晚的氛围？」
- 好：「空间我设定成小而封闭——你认同，还是想要更开阔一些？」
- 避免：「你觉得这个场景怎么样？」

---

### Step 3：确认视觉风格

**在生图之前，必须先和用户确认风格。**

根据场景的氛围基调，**主动推荐 2-3 个候选风格**，不要让用户自己浏览全部选项：

```
基于这个场景的气质，我推荐三个方向：

写实CG（photorealistic CGI）——真实材质质感，适合需要真实空间参考的项目
赛璐珞动画（anime cel shading）——干净轮廓、平涂阴影，日系动画风格
霓虹赛博朋克（neon-lit cyberpunk）——如果故事有未来感或都市夜晚氛围

你倾向哪个方向？或者有别的参考想法？
```

用户选定后，记录对应的 `prompt_hints` 关键词，用于 Step 4。
若用户描述了风格参考（「像《攻壳机动队》那样」），在 `style_guide` 中匹配最近似的条目，提取其 `prompt_hints`。

---

### Step 4：生成双视角合成图提示词

**图面结构：广角主图占据整个画布，顶视图嵌入右上角（约 20-25%）**

```
┌─────────────────────────────────────┐
│                           ┌───────┐ │
│                           │顶视图 │ │
│      广角主图             │(鸟瞰) │ │
│      (场景全貌)           └───────┘ │
│                                     │
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

**场景核心描述示例：**
> `abandoned underground storage room, cracked concrete walls, single cold light source from high right window, broken ceiling lamp, scattered old wooden crates, dust particles in air`

---

### Step 5：调用生图工具

```
image_generate(
    prompt=<Step 4 生成的提示词>,
    purpose="scene",
    aspect_ratio="16:9"
)
```

生图完成后，将图片展示给用户，**不要做任何评价**，直接问：

> 「你看到这张图，第一个想改的是什么？」

### Step 6：迭代修改循环

| 反馈类型 | 处理方式 |
|---|---|
| 空间细节（「太空旷了」） | 更新空间描述，调整提示词，重新生成 |
| 光影感受（「太亮了，要更压抑」） | 更新氛围/光影维度，调整光线描述词，重新生成 |
| 风格感受（「太写实了」） | 返回 Step 3，重新确认风格，切换关键词 |
| 整体满意，小改（「再加一扇门」） | 在现有提示词基础上增补，重新生成 |

每次重新生成后，再次问：「这版怎么样，还有想改的吗？」

当用户说「可以」「就这个」「满意了」时，进入 Step 7。

### Step 7：上传素材

将确认的场景图上传到项目素材库（记录最终使用的提示词）。

上传后告知用户场景已保存，提示下一步可进入角色放置或分镜设计。

### 错误处理

| 情况 | 处理方式 |
|---|---|
| 生图工具调用失败 | 自动切换 model 重试一次；若仍失败，告知用户并保留提示词 |
| 用户中途退出 | 不做任何修改 |

### 对话风格

- **简洁直接**：每次回复控制在 150 字以内（不含场景设定和提示词正文）
- **导演视角**：在帮用户把脑子里模糊的空间感变成具体画面。「这个光线方向会决定整个场景的情绪基调」是该说的话
- **氛围第一**：所有描述最终都要落到光影和空间上。「压抑」要翻译成「低天花板、单冷光源、大面积阴影、墙面粗糙」，不能停在情绪词上
- **不问多余**：场景的完整空间布局、所有物件——不需要用户全部告诉你，你来推断和填充，用户只需确认或纠偏

---

# 参考文件（内嵌）

## references/style_guide.md｜视觉风格速查表（31 种）

| 风格 ID | 风格名称 | 核心特征描述 | AI Prompt Hints (英) |
|---|---|---|---|
| ST-01 | 电影写实 | 极高细节，真实光影，大片质感 | cinematic, 8k, photorealistic, cinematic lighting, hyper-detailed, IMAX, Shot on 35mm |
| ST-02 | 赛璐珞动画 | 干净线条，大色块平涂，日系动漫感 | anime style, cel shaded, vibrant colors, clean outlines |
| ST-03 | 写实CG | 顶级游戏CG质感，精细纹理 | unreal engine 5 render, ray tracing, Octane Render, high-end game CG, masterwork |
| ST-04 | 赛博朋克 | 霓虹灯，高饱和色调，科幻未来感 | cyberpunk style, neon lights, rainy street, futuristic city |
| ST-05 | 中式国风 | 传统水墨或工笔元素，禅意留白 | traditional Chinese painting style, ink wash, elegant, ethereal, Zen aesthetic |
| ST-06 | 美漫卡通 | 粗犷线条，美式漫画质感 | American comic book style, bold lines, dramatic shadows, superhero aesthetic |
| ST-07 | 极简现代 | 简洁构图，几何感强 | minimalist, clean design, geometric, architectural, high-end commercial style |
| ST-08 | 黑色电影 | 强明暗对比，阴沉压抑，经典胶片感 | film noir, high contrast, monochrome, dramatic shadows, smoky atmosphere |
| ST-09 | 复古怀旧 | 低饱和度，颗粒感，旧照片质感 | vintage, film grain, muted colors, nostalgic, 1990s style, Kodachrome |
| ST-10 | 手绘草图 | 粗略线条，富有动感 | rough sketch, pencil drawing, charcoal, hand-drawn, expressive lines |
| ST-11 | 粘土风格 | 停格动画感，微缩模型细节 | claymation, stop-motion style, miniature, cute, handcrafted texture |
| ST-12 | 蒸汽朋克 | 铜色调，机械结构，维多利亚工业感 | steampunk, Victorian industrial, gears, brass, intricate machinery |
| ST-13 | 宫崎骏风 | 温暖治愈，手绘水彩感 | Studio Ghibli style, watercolor, lush landscapes, heartwarming, vibrant green |
| ST-14 | 废土风格 | 荒凉破败，锈迹斑斑 | wasteland style, post-apocalyptic, dusty, rusty, desolate |
| ST-15 | 像素艺术 | 8-bit/16-bit 电子游戏感 | pixel art, 8-bit, nostalgic gaming, isometric pixel art |
| ST-16 | 古典油画 | 厚涂纹理，厚重光影 | classical oil painting, heavy brushstrokes, museum quality |
| ST-17 | 浮世绘 | 日式传统版画，平面构图 | Ukiyo-e style, woodblock print, traditional Japanese art, flat perspective |
| ST-18 | 波普艺术 | 极高饱和度，网点纹理 | pop art, screenprint, comic dots, vibrant primary colors |
| ST-19 | 奇幻魔幻 | 史诗感，魔法氛围 | epic fantasy, magical atmosphere, glowing elements |
| ST-20 | 波西米亚 | 自由浪漫，异域色彩 | bohemian style, colorful textiles, ethnic patterns, artistic flair |
| ST-21 | 暗黑哥特 | 神秘诡谲，装饰繁复 | gothic style, dark fantasy, ornate architecture, eerie atmosphere |
| ST-22 | 水彩清新 | 透明感，晕染自然 | light watercolor, soft edges, ethereal, refreshing, pastel colors |
| ST-23 | 极速动感 | 速度线，模糊动态感 | speed lines, dynamic motion blur, high energy, fast-paced |
| ST-24 | 纸雕风格 | 层次感，阴影分明 | paper cut style, layered paper, shadow box, craft, 3D depth |
| ST-25 | 乐高风格 | 积木拼搭，微缩感 | Lego style, plastic bricks, toy photography, modular |
| ST-26 | 迷幻艺术 | 万花筒色调，流体形态 | psychedelic art, trippy, kaleidoscope, fluid swirls |
| ST-27 | 包豪斯 | 几何图形，红黄蓝原色 | Bauhaus style, geometric shapes, primary colors, functional design |
| ST-28 | 梦幻泡泡 | 柔焦效果，珍珠母贝光泽 | dreamy, soft focus, pearlescent, whimsical, pastel bokeh |
| ST-29 | 城市纪实 | 抓拍感，真实街头氛围 | street photography, documentary, candid, urban atmosphere, realistic |
| ST-30 | 高定时尚 | 杂志大片质感，前卫构图 | high fashion editorial, Vogue style, avant-garde, luxury brand aesthetic |
| ST-31 | 恐怖悬疑 | 心理暗示，压抑光影 | horror aesthetic, suspenseful, unsettling, deep shadows, creepy details |

> ⚠️ 上表部分条目含 `[艺术家/工作室] style` 表述，**商业项目使用须谨慎**，建议改为风格特征描述（如 "watercolor, lush landscapes, heartwarming" 替代具体工作室名）。

---

## 与本项目 V2.0 规格的映射

| 本文机制 | V2.0 规格对应 |
|---|---|
| 场景设定 6 维度 | §09 ENVIRONMENT ENGINE 的「建筑/空间/材料/光线/氛围/时代/尺度」 |
| **情绪翻译成光影** | §04.5 Lighting Bible + §49「高级感必须具体化」的核心方法 |
| 关键物件清单 | §03 `props` 索引 + §32 道具摆放 |
| 叙事功能决定物件突出 | §12 SHOT ENGINE 的「叙事目的」 |
| 双视角合成图（广角+顶视图） | **§32「主空间关系」的可视化方法**（比文字描述更可靠） |
| 31 种风格速查表 | 补充 §04.1 的 `visual_style` 字段可选值 + `style-extractor` 的输出词汇 |
| 主动推荐 2-3 个风格 | §04 世界观建立时的引导式提问 |
| 迭代修改循环 | §41 总循环的 REVISION 环节 |

### 与其他源 skill 的协同

```
style-extractor（从参考图提取风格 DNA）
        ↕ 互补
bootstrap-locations 的 31 种风格表（提供风格命名与英文关键词）
        ↓
确定风格 → 生成双视角图（本 skill）
        ↓
scene-multi-angle-generator（以双视角图为起点，扩展到 S01-S06 六角度）
        ↓
04-视频生成 的尾帧链（多镜一致性）
```
