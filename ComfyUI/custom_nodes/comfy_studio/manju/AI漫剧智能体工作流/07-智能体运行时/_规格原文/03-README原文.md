# AI漫剧资产库 Agent

## 项目用途

这是一个用于 AI 漫剧、AI 动画、游戏和影视前期制作的视觉资产智能体。

主要用于生成：

- 角色三视图
- 角色立绘设定
- 角色头像
- 角色服装设定
- 角色装备
- 道具三视图
- AI 绘图 Prompt
- 资产库标准化描述

---

# 一、项目结构

```text
AI漫剧资产库Agent/
│
├── README.md
│
├── SYSTEM_PROMPT.md
│
├── config.json
│
├── PROMPT_TEMPLATE.md
│
├── CHARACTER_RULES.md
│
└── EXAMPLES.md
```

---

# 二、如何在 CodeBuddy 使用

将整个：

```text
AI漫剧资产库Agent/
```

文件夹复制到 CodeBuddy 项目中。

然后让 CodeBuddy 首先读取：

```text
SYSTEM_PROMPT.md
```

再读取：

```text
config.json
PROMPT_TEMPLATE.md
CHARACTER_RULES.md
EXAMPLES.md
```

之后要求 Agent：

> 按照项目中的 SYSTEM_PROMPT.md 执行，并将其作为本项目 AI 漫剧资产库 Agent 的核心行为规范。

---

# 三、推荐 CodeBuddy Agent 规则

在 CodeBuddy 中创建 Agent 时，将：

```text
SYSTEM_PROMPT.md
```

作为核心 System Prompt。

项目中的其他 Markdown 文件作为参考知识。

---

# 四、换电脑迁移

迁移时直接复制整个：

```text
AI漫剧资产库Agent
```

文件夹。

在另一台电脑：

1. 安装 CodeBuddy
2. 打开项目
3. 让 Agent 加载 SYSTEM_PROMPT.md
4. 加载其他配置文件
5. 即可恢复主要工作逻辑

---

# 五、ChatGPT 使用

如果需要在 ChatGPT 中重新创建：

将：

```text
SYSTEM_PROMPT.md
```

中的内容作为自定义 Agent/GPT 的核心 Instructions。

其他文件可以作为知识库文件上传。

推荐上传：

```text
SYSTEM_PROMPT.md
PROMPT_TEMPLATE.md
CHARACTER_RULES.md
EXAMPLES.md
config.json
```

---

# 六、图像生成

如果运行环境具有图像生成能力：

用户只需要输入类似：

```text
一个30岁的废土女佣兵，机械左臂，穿破旧军用风衣
```

Agent 自动完成：

```text
角色解析
↓
视觉设定补全
↓
服装设计
↓
材质设计
↓
装备设计
↓
颜色设计
↓
三视图布局
↓
完整绘画 Prompt
↓
图像生成
```

---

# 七、用户不需要使用固定格式

支持自然语言。

例如：

```text
帮我做一个赛博朋克女医生
```

```text
一个来自火星殖民地的年轻工程师
```

```text
给我设计一个废土世界的老兵
```

```text
一个东方奇幻世界的女剑客
```

```text
设计一把未来主义能源步枪
```

Agent 应自动理解。

---

# 八、修改已有资产

例如：

```text
把她的头发改成银白色
```

应该只修改头发。

例如：

```text
把服装改成黑色皮质
```

应该只修改服装。

例如：

```text
增加一个机械右臂
```

应该在原设计基础上增加机械右臂。

---

# 九、跨平台原则

本项目不依赖某一个具体 AI 平台的内部数据。

核心资产是：

```text
SYSTEM_PROMPT.md
```

因此可以迁移到：

- CodeBuddy
- ChatGPT
- API Agent
- 本地 LLM
- 其他支持 System Prompt 的 Agent 平台

具体图像生成能力取决于运行平台所连接的图像模型。

---

# 十、重要说明

Markdown 本身是配置和知识载体。

它不是一个独立的 AI 模型。

因此：

```text
Markdown
+
AI 模型
+
Agent Runtime
+
图像生成能力
```

才能组成完整的可运行智能体。

如果以后希望做到：

> 双击程序 → 输入角色 → 自动生成资产图

则可以在这个项目基础上进一步开发成：

```text
Web Agent
Desktop Agent
API Agent
```

---

# 十一、推荐长期架构

后续项目可以继续扩展：

```text
AI漫剧资产库Agent/
│
├── agent/
│   ├── system_prompt.md
│   ├── character_agent.md
│   ├── prop_agent.md
│   └── scene_agent.md
│
├── prompts/
│   ├── character/
│   ├── prop/
│   ├── costume/
│   └── scene/
│
├── assets/
│   ├── characters/
│   ├── props/
│   ├── costumes/
│   └── scenes/
│
├── config/
│   └── config.json
│
└── examples/
    └── examples.md
```

这样以后可以从单纯的“角色三视图 Agent”发展成完整的：

> AI 漫剧资产生产 Agent。