---
name: cinematic-lighting-master
display_name: 电影光影大师
enable: true
description: 专业电影光影知识库与布光指导系统，涵盖经典布光技法、情绪照明、电影大师风格分析，帮助用户掌握电影级光影设计
trigger: 当用户询问电影布光、光影技法、情绪照明、摄影灯光设置、或需要为场景设计光影方案时
---

# 电影光影大师 (Cinematic Lighting Master)

## Skill Goal

帮助用户掌握专业电影布光技法，提供从经典三点布光到情绪照明的完整知识体系，支持实际拍摄指导和AI绘画prompt生成。

## 核心能力

1. **经典布光技法库** - 提供31种专业布光方案
2. **情绪照明公式** - 光影与情绪的对应关系
3. **电影大师风格分析** - 罗杰·迪金斯、卢贝兹基等大师技法
4. **场景光影设计** - 根据剧情需求推荐最佳布光方案
5. **AI绘画光影提示词** - 生成适用于Midjourney/Stable Diffusion的专业光影prompt

## 执行步骤

### Step 1: 需求分析
- 识别用户场景类型（室内/室外/人像/风景/动作/对话）
- 确定情绪基调（紧张/浪漫/神秘/悲伤/希望等）
- 了解参考风格偏好

### Step 2: 布光方案推荐
根据分析结果，从知识库中选择最适合的布光方案：
- 主光（Key Light）位置与强度
- 辅光（Fill Light）补光策略
- 轮廓光/逆光（Rim/Back Light）设置
- 环境光/氛围光（Ambient/Practical）布置

### Step 3: 输出专业建议
提供包含以下要素的完整方案：
- 布光图示说明
- 灯光参数建议
- 情绪效果预期
- AI绘画prompt（如需要）

## 知识库内容

### 一、经典人像布光（Portrait Lighting）

#### 1. 伦勃朗光（Rembrandt Lighting）
- **特征**: 在人物面部阴影侧眼睛下方形成三角形光斑
- **布光**: 主光位于人物侧前方45度，略高于眼睛水平线
- **情绪**: 戏剧感、神秘感、古典油画质感
- **适用**: 肖像摄影、人物访谈、艺术短片
- **AI Prompt**: `Rembrandt lighting, dramatic shadows, classical portrait, chiaroscuro effect, warm key light from 45 degrees`

#### 2. 蝴蝶光/派拉蒙光（Butterfly/Paramount Lighting）
- **特征**: 主光从正上方投射，在鼻子下方形成蝴蝶状阴影
- **布光**: 主光位于人物正前方略高处
- **情绪**: 优雅、glamour、经典好莱坞风格
- **适用**: 美人照、时尚摄影、明星访谈
- **AI Prompt**: `Butterfly lighting, glamorous portrait, soft shadows under nose, classic Hollywood style, beauty lighting`

#### 3. 环形光（Loop Lighting）
- **特征**: 在鼻子侧面形成小环形阴影，不与脸颊阴影相连
- **布光**: 主光位于30-45度侧前方
- **情绪**: 自然、友好、通用性强
- **适用**: 标准人像、商务肖像、日常场景
- **AI Prompt**: `Loop lighting, natural portrait, soft shadows, flattering light on face, professional headshot`

#### 4. 分割光（Split Lighting）
- **特征**: 脸部一半亮一半暗，明暗分界线在面部中央
- **布光**: 主光位于人物正侧面90度
- **情绪**: 戏剧性、神秘感、男性化、强势
- **适用**: 戏剧场景、反派角色、男性肖像
- **AI Prompt**: `Split lighting, dramatic half-face illumination, mysterious atmosphere, film noir style, strong contrast`

#### 5. 宽光/窄光（Broad/Short Lighting）
- **宽光**: 照亮脸部较宽的一侧，显脸小
- **窄光**: 照亮脸部较窄的一侧，显立体
- **适用**: 根据脸型调整，窄光更显轮廓
- **AI Prompt**: `Short lighting technique, sculptural face definition, cinematic portrait, dimensional lighting`

### 二、三点布光系统（Three-Point Lighting）

#### 标准配置
1. **主光（Key Light）**: 主要光源，决定整体曝光和阴影方向
2. **辅光（Fill Light）**: 填充阴影，控制对比度（通常比主光暗1-2档）
3. **轮廓光/逆光（Rim/Back Light）**: 分离主体与背景，增加立体感

#### 变体方案
- **低调布光（Low Key）**: 辅光极少，高对比，神秘感
- **高调布光（High Key）**: 辅光充足，低对比，明亮感
- **无辅光**: 纯主光，强烈阴影，戏剧性

### 三、情绪照明公式（Mood Lighting Formulas）

#### 压迫感
- **角度**: 极低角仰拍 + 顶光
- **光影**: 伦勃朗光 + 强烈阴影
- **色调**: 冷色调 + 高对比
- **AI Prompt**: `Low angle shot, top lighting, Rembrandt lighting, oppressive atmosphere, cold color temperature, high contrast`

#### 孤独感
- **景别**: 极远大景别 + 负空间留白
- **光影**: 侧逆光 + 剪影效果
- **色调**: 去饱和 + 冷色调
- **AI Prompt**: `Wide shot with negative space, rim lighting, silhouette, lonely atmosphere, desaturated cool tones`

#### 不安感
- **角度**: 荷兰角倾斜
- **光影**: 频闪 + 晃动光效
- **色调**: 霓虹对比色
- **AI Prompt**: `Dutch angle, flickering lights, unstable atmosphere, neon color contrast, psychological tension`

#### 神性/庄严
- **构图**: 正面中心对称
- **光影**: 丁达尔光柱（God rays）+ 慢推
- **色调**: 金色暖光
- **AI Prompt**: `Centered symmetrical composition, god rays, volumetric lighting, divine atmosphere, golden warm light`

#### 恐惧/受困
- **角度**: 俯视 + 框中框构图
- **光影**: 阴影笼罩 + 前景虚化
- **色调**: 冷调背光
- **AI Prompt**: `High angle shot, frame within frame, shadow dominance, claustrophobic atmosphere, cold backlight`

#### 希望/新生
- **角度**: 仰视
- **光影**: 逆光光晕（Lens Flare）
- **色调**: 暖色调
- **AI Prompt**: `Low angle looking up, lens flare, backlight halo, hopeful atmosphere, warm golden tones`

#### 浪漫/暧昧
- **景别**: 浅景深特写
- **光影**: 柔光滤镜 + 粉紫氛围
- **色调**: 暖粉色调
- **AI Prompt**: `Shallow depth of field close-up, soft focus, romantic atmosphere, pink and purple tones, dreamy lighting`

#### 悬疑/神秘
- **构图**: 剪影
- **光影**: 烟雾遮挡 + 冷调背光
- **色调**: 蓝灰色调
- **AI Prompt**: `Silhouette composition, smoke and fog, mysterious atmosphere, cold blue backlight, noir style`

### 四、电影大师风格库

#### 罗杰·迪金斯（Roger Deakins）
- **风格**: 自然主义布光，追求真实感
- **代表作**: 《银翼杀手2049》《1917》《老无所依》
- **特点**:
  - 单光源自然光为主
  - 大面积柔光
  - 色彩层次分明
  - 实景布光大师
- **AI Prompt**: `Roger Deakins cinematography style, natural lighting, single source light, realistic atmosphere, muted color palette`

#### 艾曼努尔·卢贝兹基（Emmanuel Lubezki）
- **风格**: 一镜到底之王，自然光运用
- **代表作**: 《荒野猎人》《地心引力》《鸟人》
- **特点**:
  - 大量自然光/实景光
  - 长镜头流畅运镜
  - 逆光/轮廓光运用
  - 沉浸式体验
- **AI Prompt**: `Emmanuel Lubezki cinematography, natural light, long take, immersive atmosphere, golden hour lighting`

#### 黑色电影（Film Noir）
- **风格**: 高反差黑白布光
- **特点**:
  - 百叶窗投影阴影
  - 伦勃朗光
  - 烟雾氛围
  - 高对比度
- **AI Prompt**: `Film noir lighting, high contrast black and white, venetian blind shadows, cigarette smoke, dramatic chiaroscuro`

### 五、特殊光效技法

#### 1. 明暗对照法（Chiaroscuro）
- 强烈的明暗对比
- 源自文艺复兴绘画
- 创造立体感和戏剧性
- **AI Prompt**: `Chiaroscuro lighting, dramatic light and shadow, Renaissance painting style, sculptural form`

#### 2. 丁达尔效应/上帝之光（God Rays）
- 光束穿透介质（雾、尘、烟）
- 神圣、庄严氛围
- **AI Prompt**: `God rays, volumetric lighting, light beams through atmosphere, divine atmosphere, misty environment`

#### 3. 轮廓光/逆光（Rim Lighting）
- 从背后照亮主体边缘
- 分离主体与背景
- 创造光环效果
- **AI Prompt**: `Rim lighting, backlit silhouette, glowing edge light, separation from background, ethereal glow`

#### 4. 底光/鬼光（Uplighting）
- 从下方投射光线
- 恐怖、邪恶、非自然感
- **AI Prompt**: `Uplighting, light from below, horror atmosphere, unnatural lighting, ghostly appearance`

#### 5. 顶光（Top Lighting）
- 从正上方投射
- 眼窝阴影，骷髅效果
- 审讯、绝望场景
- **AI Prompt**: `Top lighting, overhead light, skull-like eye sockets, interrogation atmosphere, harsh shadows`

### 六、AI绘画光影Prompt模板

#### 基础模板结构
```
[主体描述], [布光类型], [光影质量], [情绪氛围], [色调], [摄影风格], [技术参数]
```

#### 示例Prompts

**经典人像**
```
Portrait of a woman, Rembrandt lighting with triangular light patch on cheek, soft shadows, dramatic but elegant, warm color temperature, cinematic photography, shallow depth of field, 85mm lens
```

**电影场景**
```
Interior scene, single source window light creating long shadows, film noir atmosphere, venetian blind patterns on wall, smoke in air, high contrast, Roger Deakins style, anamorphic lens flare
```

**情绪照明**
```
Lonely figure in vast space, silhouette against backlight, negative space composition, desaturated cool tones, rim lighting, contemplative mood, wide angle lens, cinematic aspect ratio
```

**动作场景**
```
Action sequence, dynamic lighting with practical sources, high contrast, motion blur, dramatic shadows, warm key light with cool fill, intense atmosphere, 24fps film grain
```

### 七、实用布光检查清单

#### 拍摄前检查
- [ ] 主光位置是否创造想要的阴影形状？
- [ ] 辅光是否过度填充阴影？
- [ ] 轮廓光是否分离主体与背景？
- [ ] 背景光是否增加层次感？
- [ ] 色温是否统一或有意对比？
- [ ] 是否有不需要的阴影或反光？
- [ ] 眼睛是否有眼神光（Eye Light）？

#### 情绪匹配检查
- [ ] 布光是否支持叙事情绪？
- [ ] 光影对比度是否符合场景氛围？
- [ ] 色调是否传达正确的心理暗示？
- [ ] 是否有意外的视觉干扰？

## 使用示例

### 示例1: 为悬疑场景设计布光
**用户需求**: "我要拍一个审讯室场景，要有压迫感和神秘感"

**系统输出**:
```
【布光方案】 主光: 顶光（Top Light）从正上方投射，创造眼窝阴影 辅光: 极少或无，保持高对比 轮廓光: 冷色调背光，分离人物与黑暗背景 环境光: 单盏荧光灯作为practical light，增加真实感

【情绪效果】
- 眼窝阴影营造骷髅般的压迫感
- 高反差暗示道德困境
- 冷色调传达冷漠和疏离

【AI Prompt】 Interrogation room scene, top lighting creating skull-like eye sockets, high contrast, cold color temperature, single fluorescent practical light, oppressive atmosphere, film noir style, dramatic shadows
```

### 示例2: 浪漫场景布光
**用户需求**: "想要拍一个夕阳下的浪漫约会场景"

**系统输出**:
```
【布光方案】 主光: 金色夕阳逆光（Golden Hour Backlight） 辅光: 金色反光板补光，保持暖色调 轮廓光: 自然阳光创造轮廓 环境光: 夕阳余晖染红天空

【情绪效果】
- 金色逆光创造浪漫光晕
- 柔光滤镜效果增加梦幻感
- 暖色调传达温馨和爱意

【AI Prompt】 Romantic couple at sunset, golden hour backlight, lens flare, warm color temperature, soft focus, dreamy atmosphere, shallow depth of field, silhouette rim lighting, pink and orange sky
```

## 技术说明

- 本Skill基于经典电影摄影理论和当代大师实践
- 所有布光方案均可根据实际条件调整
- AI Prompt模板适用于Midjourney、Stable Diffusion、DALL-E等主流AI绘画工具
- 建议结合实际拍摄测试，根据反馈微调
