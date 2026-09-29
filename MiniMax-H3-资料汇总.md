# MiniMax H3 资料汇总

整合自 5 篇飞书文档（原文抓取时间：2026-09-26；先经 `web_fetch` 取首屏，再用**无头浏览器滚动累积采集**补齐渲染后正文，5 篇的正文均已抓到，仅图片/视频块与登录墙内容无法文本化，已在文中标注）。

> 文档分两部分：**第 0～15 节**是按主题整理的速查与合成（其中**第 15 节为本机实测记录**，非文档摘录）；**附录 A～F** 是各篇文档的**逐段原文摘录**（原文是英文的附中英对照），要看细节直接跳到附录。

| # | 来源 | 标题 | 文档日期 |
|---|---|---|---|
| 1 | https://vrfi1sk8a0.feishu.cn/wiki/FIWjwgL33ipnkekzk30crmKUnIh | 🐚MiniMax H3 模型 - 使用手册 | 持续更新（9/1 更新 1.10） |
| 2 | https://my.feishu.cn/wiki/TowTwcCSwiEAh8k0bLCcsCvgnod | MiniMax H3 Open-Source Resources（中英双语） | 8/18 |
| 3 | https://my.feishu.cn/wiki/X5ZjwtT9FitKQFknfmYcRukknbd | Run MiniMax-H3 Locally: A Simple Hardware and 2K Workflow Guide | 9/2 |
| 4 | https://my.feishu.cn/wiki/AffJwqcYXiwEuTkyjHWccO98nof | H3 开源生态速查表 · Ecosystem Cheat Sheet | 8/18 |
| 5 | https://my.feishu.cn/wiki/VEoVwpfCKiTHvHkAGQ7cQJxCncf | MiniMax Design - 手册与指南 | 9/17 |

---

## 0. 速览：按显存选方案（合成自文档 3、4）

| 你的显存 | 建议下载/工具组合 | 预期速度 | 备注 |
|---|---|---|---|
| 5–8 GB | [WanGP](https://github.com/deepbeepmeep/Wan2GP)（5 秒片仅需 5–6 G）或 [DiffSynth NF4](https://huggingface.co/DiffSynth-Studio/MiniMax-H3-NF4)（8 G 起） | 能跑，要耐心 | 非 ComfyUI 主路径 |
| 8–12 GB | pruned int8 或 NF4 + RAM offload（<10 GB 用 WanGP / DiffSynth） | 低分辨率草稿，生成时间长 | 系统内存 ≥ 32 GB |
| 12–16 GB | pruned int8 DiT + nvfp4 TE + VAE（≈42.5 GB）；40 系可用 pruned fp8 | 3060 未调优 5s@480p ≈ **15 min**；调优后 **3–5 min/clip** | 常规本地使用的**最佳消费级起点** |
| 24 GB | int8 34G DiT + int8 TE | 4090 调优 5s ≈ **70–86 s**；3090 ≈ **135 s** | |
| 32 GB | pruned fp8，或 50 系[社区 NVFP4](https://huggingface.co/DmitryDB/MiniMax-H3-ComfyUI-Quants) | 5090 5s@0.4MP ≈ **50 s**；[Sol Engine](https://nvlabs.github.io/Sana/Sol-Engine/H3-OnDevice/) **4.52×** | 最快实用桌面档 |
| 48 GB+ | int8 或完整 bf16 | 可 1080p 但慢（H100 ≈ 10 min/5s） | 像素数依然昂贵 |
| Mac 16–32 G / 128 G+ | 16G：NF4（experimental）；128G+：MLX 8bit 69.3 G（含 [Ref2VA 版](https://huggingface.co/ddalcu/MiniMax-H3-REF2VA-MLX-Serve-8bit)） | M3 Ultra 15s ≈ **39 min**（全离线） | 走 MLX 运行时 |
| 多卡服务器 | [vLLM-Omni](https://recipes.vllm.ai/MiniMaxAI/MiniMax-H3) / [SGLang](https://github.com/sgl-project/sglang) | 4×B300：8.7s clip ≈ **87 s** 端到端 | OpenAI 兼容服务化 |

**三条硬约束（先满足再谈速度）**

1. 系统内存 ≥ **32 GB**，**64 GB** 对更大 checkpoint 更稳。
2. NVIDIA 驱动 **r580 分支或更新** + **PyTorch CUDA 13.0 wheels**；用 cu128 会**静默降速数倍**。
3. 最小实用组合 ≈ **42.5 GB** 磁盘，靠**分阶段加载**（text encoder → DiT → VAE）即可在 **12 GB 显存**上跑通。

> 社区测速受分辨率、量化、offload、kernel 配置影响极大，**上表任何单一数字只作数量级参考，不是承诺**（原文明示）。

---

## 1. 模型定位（来自文档 1）

MiniMax H3 是**新一代开放通用多模态视频模型**，从「特化任务模型」迈向「通用多模态智能」：

- 不再以图片 / 视频 / 声音的生成、编辑、参考等单一任务为边界；
- 面向由**文本 + 图像 + 视频 + 声音**共同构成的多模态上下文，统一理解创作意图，完成更自然、连贯的生成与表达。

已覆盖/新增场景（据更新日志）：动态图形 / MG 动画 / AE 特效、AR 现实增强创意视频、出海多语种场景、goodcase 若干。

**输出规格速览（文档 1 原文，详见附录 A4）**

| 维度 | 值 |
|---|---|
| 时长 | 最长 **15 秒** ｜ 帧率 **24 FPS** ｜ 全部**带声音**（原生双声道） |
| 画幅 | 首/尾帧模式**跟随输入图片比例**；文生视频 / 全能参考支持 21:9、16:9、4:3、1:1、3:4、9:16 |
| 分辨率 | 768p 模式（已开放）：短边 768，特殊比例下约 **1M 像素**（21:9 → 1536×672），可升级到 1440p；1440p 模式（官方推荐）：短边 1440，特殊比例下约 **3.7M 像素**（21:9 → 2976×1248） |
| 提示词 | ≤ **7000 字符** |
| 素材上限 | 首/尾帧：图片 0/1/2 张；全能参考：图片 ≤9 张、视频单段 [2,15] 秒且总长 ≤15 秒、音频 ≤3 段（须搭配图片或视频）、**混合总上限 12 个文件** |
| 单文件大小 | 视频 50MB ／ 图片 30MB ／ 音频 15MB（API 请求体 64MB） |

**提示词公式（文档 1 §四）**：`参考素材说明 + 核心创意 + 画面过程说明`——完整方法与踩坑清单见附录 A5。

---

## 2. 模型构成与下载（来自文档 2、3）

> 一套可运行的 H3 = **1 个扩散模型 + 1 个文本编码器 + 2 个 VAE**。

| 组件 | 可选档位 | 说明 |
|---|---|---|
| 扩散模型（DiT，33B） | FL2VA 或 Ref2VA；bf16 **66.3 GB** · int8 **34.0** · pruned bf16 **40.2** · pruned int8/fp8 **21.0** | 联合生成视频与音频，承担几乎全部重复计算 |
| 文本编码器（**Qwen3-VL-32B**） | bf16 **51.5** · int8 **27.1** · nvfp4 **15.7** | 在生成开始时一次性读取提示词与参考输入 |
| VAE（视频 + 音频，**必装**） | fp16 **5.2** + fp32 **0.6**（合计约 5.8 GB） | 在 latent 与最终像素/波形之间转换 |

- **FL2VA**：文生视频、首帧/尾帧控制；**Ref2VA**：需要参考图像、视频、音频或续写时使用。两者共用同一 text encoder 与 VAEs。
- 最小实用官方 ComfyUI 组合约 **42.5 GB 磁盘**（pruned int8 DiT + NVFP4 文本编码器 + 两个 VAE），仍可在 **12 GB GPU** 上跑——因为三者**分阶段分别加载**。
- 社区 GGUF / 4-bit 量化可低至约 **10 GB**（HF 搜 `MiniMax-H3`）。

### 体积账与选型经验（据上表核对/归纳）

- 文档 3 的「最小实用组合 **42.5 GB**」= pruned int8 DiT **21.0** + NVFP4 文本编码器 **15.7** + 两个 VAE **5.8**，口径自洽。
- 文档 4 中 RTX 3060 12G 用的正是这套组合，并配了[可直接套用的 3060 专用工作流](https://github.com/tlano-z/ComfyUI-MiniMax-H3-Workflows-For3060)。
- 选型经验（归纳，非原文）：**省显存**优先选 pruned 版 DiT + 低级量化 TE（nvfp4 15.7 最省）；**缺磁盘空间**时 DiT 走 pruned int8/fp8 21.0 是性价比拐点；bf16 全套（66.3 + 51.5 + 5.8）只适合 48 GB+ 档位。

### 下载源

| 资源 | 链接 |
|---|---|
| GitHub（官方） | https://github.com/MiniMax-AI/MiniMax-H3 （代码、9 个 agent skills、部署校验脚本、架构说明 README） |
| Hugging Face（原版权重，Diffusers 格式） | https://huggingface.co/MiniMaxAI/MiniMax-H3 |
| ModelScope（国内镜像） | https://modelscope.cn/models/MiniMax/MiniMax-H3 |
| **ComfyUI 重打包版**（单文件、按 ComfyUI 目录整理，含量化档） | https://huggingface.co/Comfy-Org/MiniMax-H3 |
| └ diffusion_models | https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/diffusion_models |
| └ text_encoders | https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/text_encoders |
| └ vae | https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/vae |
| 社区量化（GGUF / 4-bit） | https://huggingface.co/models?search=MiniMax-H3 |

---

## 3. 硬件速查与耗时预期（来自文档 3、4）

### 3.1 分档建议（文档 3）

| 硬件 | 推荐路径 | 预期 |
|---|---|---|
| 8–12 GB NVIDIA | pruned int8 或 NF4 + RAM offload；<10 GB 用 WanGP 或 DiffSynth | 可做低分辨率草稿，生成时间很长 |
| 16–24 GB NVIDIA | ComfyUI 中 pruned int8 或 fp8 | 常规本地使用的**最佳消费级起点** |
| 32 GB NVIDIA | pruned fp8 或 NVFP4 | 最快的实用桌面档位 |
| 48 GB+ | int8 或完整 bf16 | 质量与分辨率空间更大，但像素数依然昂贵 |
| Apple / AMD / 无本地 GPU | Apple 用 MLX 或 DiffSynth；受支持 AMD 用 SGLang；否则 Colab / 云 GPU | 需走独立运行时，而非默认 CUDA 方案 |

- 系统内存**至少 32 GB**，**64 GB** 对更大 checkpoint 更稳。
- 社区测速因分辨率、量化、offload、kernel 配置差异波动极大——**任何单一速度数字只作数量级参考**。

### 3.2 具体机型实测（文档 4）

| 机器 | 方案 | 预期 |
|---|---|---|
| 5–8 GB NVIDIA | [WanGP](https://github.com/deepbeepmeep/Wan2GP)（5 秒片仅需 5–6 G）或 [DiffSynth NF4](https://huggingface.co/DiffSynth-Studio/MiniMax-H3-NF4)（8 G 起） | 能跑，要耐心 |
| RTX 3060 12G | pruned int8 21G + nvfp4 TE 15.7G + VAE 5.8G；[3060 专用工作流](https://github.com/tlano-z/ComfyUI-MiniMax-H3-Workflows-For3060) | 5s@480p ≈ **15 min**（未调优） |
| 12–16 G（4070 / 5070Ti / 5080） | pruned fp8（40 系原生）或 pruned int8；[16G 实测笔记](https://github.com/Tomiigo/minimax-h3-16gb) | **3–5 min/clip**（调优后） |
| 24 G（3090 / 4090） | int8 34G + int8 TE；[3090 15 秒实录](https://github.com/tonyd2wild/minimax-h3-local) | 4090 调优后 5s ≈ **70–86 s**；3090 ≈ **135 s** |
| RTX 5090 32G | pruned fp8 或 [社区 NVFP4（50 系专属）](https://huggingface.co/DmitryDB/MiniMax-H3-ComfyUI-Quants) | 5s@0.4MP ≈ **50 s**；[Sol Engine 加速 4.52×](https://nvlabs.github.io/Sana/Sol-Engine/H3-OnDevice/) |
| 48–96 G 专业卡 | int8 / bf16；[RTX Pro 6000 单卡实践（中文）](https://github.com/eric8810/minimax-h3-deploy) | 可 1080p 但慢（H100 ≈ 10 min/5s） |
| DGX Spark | pruned int8 + nvfp4 TE；[调优仓](https://github.com/drowzeys/keys-heretic-MiniMax-H3-sol-engine-more-speed-upgrades-upscaler-finish-Single-DGX-Spark) · [SM121 recipe](https://github.com/joeynyc/MiniMax-H3-DGX-Spark) | 10s ≈ 3.5–10 min；Sol 3.92×；[双机协同](https://github.com/joeynyc/MiniMax-H3-2x-DGX-Spark) |
| Mac 16–32G / 128G+ | 16G：NF4（experimental）；128G+：[MLX 8bit 69.3G](https://huggingface.co/ddalcu/MiniMax-H3-FL2VA-MLX-Serve-8bit)（[Ref2VA 版](https://huggingface.co/ddalcu/MiniMax-H3-REF2VA-MLX-Serve-8bit)）· [RunH3onMac](https://github.com/HeyZhey/RunH3onMac) | M3 Ultra：15s ≈ 39 min（全离线） |
| AMD | Instinct：[SGLang 官方 ROCm 支持](https://docs.sglang.io/docs/sglang-diffusion/installation)；消费卡靠社区补丁 | 早期但真实 |
| 多卡服务器 | [vLLM-Omni](https://recipes.vllm.ai/MiniMaxAI/MiniMax-H3) / [SGLang](https://github.com/sgl-project/sglang) | 4×B300：8.7s clip ≈ 87 s 端到端 |

---

## 4. 本地部署（ComfyUI，来自文档 3）

```shell
git clone https://github.com/comfyanonymous/ComfyUI
cd ComfyUI
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu130
pip install -r requirements.txt
```

1. 下载 1 个 DiT + 1 个 text encoder + 2 个 VAE，放入 `ComfyUI/models` 对应目录。
2. **Workflow → Browse Templates → Video → MiniMax H3**，选生成模式对应模板，填提示词与条件媒体，排队。
3. 教程（含各工作流截图）：https://docs.comfy.org/tutorials/video/minimax/minimax-h3

### 装配清单（按顺序执行，来自文档 3）

| # | 动作 | 校验点 |
|---|---|---|
| 1 | 升级 NVIDIA 驱动到 **r580 分支或更新** | 量化 kernel 需要 CUDA runtime ≥ 13.0 |
| 2 | 拉 ComfyUI 代码 → `pip install torch torchvision torchaudio --index-url .../cu130` → `pip install -r requirements.txt` | 确认装的是 **cu130** 而非 cu128 |
| 3 | 启动 ComfyUI，看启动日志 | 确认 **量化后端已启用**，没有静默回退 |
| 4 | 下载 1 个 DiT（FL2VA 或 Ref2VA，按任务选）+ 1 个文本编码器 + 2 个 VAE | 放进 `ComfyUI/models` 下对应子目录：`diffusion_models/`、`text_encoders/`、`vae/` |
| 5 | **Workflow → Browse Templates → Video → MiniMax H3** | 选与生成模式匹配的模板（T2V / I2V / 首尾帧 / 参考） |
| 6 | 填提示词与条件媒体，排队 | 先跑 **0.5–0.8 MP 草稿**验证链路，再上精修通道 |

### 常见坑（重要）

- 量化 checkpoint 需 **NVIDIA 驱动 r580 分支或更新** + **PyTorch CUDA 13.0 wheels**。
- 最常见的性能失误：用 **PyTorch cu128**。量化 kernel 需要 **CUDA runtime ≥ 13.0**；用 cu128 时 ComfyUI 会**静默回退到普通 PyTorch 算子**——生成照常但**可能慢数倍**。
- 应检查启动日志，确认量化后端（quantization backend）已启用。

---

## 5. 性能优化优先级（来自文档 3）

H3 运行时大部分时间花在 **DiT 去噪循环**上，按收益从高到低：

1. **先验证 kernel**：正确的 CUDA wheels + 可用的编译 attention 后端，比微调细枝末节重要得多。
2. **加 SageAttention**：社区报告去噪循环约 **1.5–2×** 提升（取决于 GPU 与 build）。
3. **在合适时用 8-step Turbo LoRA**：显著缩短采样调度；剪枝模型须配剪枝转换的 LoRA；音频关键的场景保留完整步数路径。
4. **生成更少像素**：草稿约 **0.5–0.8 MP**，满意后再跑昂贵的精修通道。
5. 缓存、稀疏注意力、Sol Engine 移植、更激进的量化可继续提速，但有质量与兼容性取舍。

> 完整硬件与优化指南：https://vrfi1sk8a0.feishu.cn/docx/VJA3dLNNpo2gnDxkKfFcaCXbnTf
> （该 docx 链接本次抓取无正文返回，需登录后自行查看。）

---

## 6. 推荐出片流水线：混合本地 + 托管（来自文档 3）

```
H3-Context-IR（托管） → H3-Base 768p（本地） → H3-Regenerate-2K（托管）
```

思路：把昂贵的**迭代循环留在本地掌控**，只在最有价值处使用托管模型。Context-IR 与 Regenerate-2K 是托管服务，**底层实现未开源**。

**四步：**

1. **准备提示词**：把原始提示词与所有模式相关条件媒体发给 [H3-Context-IR](https://platform.minimax.io/docs/api-reference/video-generation-v2-h3-context-ir)，保留其返回的完整增强提示词。
2. **本地生成**：把完整提示词 + 相同条件媒体交给本地 H3-Base（文生视频/首尾帧用 FL2VA，参考生成用 Ref2VA），本地生成并审阅 768p 草稿。
3. **重生成选定 take**：把**未经改动**的 MP4 上传到短时有效的 HTTPS 位置；向 [H3-Regenerate-2K](https://platform.minimax.io/docs/api-reference/video-generation-v2-regeneration) 发送相同增强提示词、相同条件输入，以及**恰好一个**角色为 `base_video` 的视频。
4. **取回结果**：两个托管 API 都是**异步**的，需轮询任务直到成功或到达终态失败。

**交接规则（务必遵守）：**

- Context-IR 是**补充**条件媒体，不是替代；
- 重生成时**不要**切回原始提示词；
- **不要**对本地视频使用 `source_task_id`；
- **不要**裁剪、缩放、改帧率、移除音频或重度重压 768p 草稿。

**数据边界**：该流程会把条件媒体发给 Context-IR，把最终提示词 + 条件媒体 + 本地草稿发给 Regenerate-2K。使用敏感素材前须评估**云数据边界、API 成本与留存（retention）要求**。

**何时完全本地**：隐私、离线运行、可复现性或零边际 API 成本更重要时；收尾可用 **latent upscaler**（模型感知）或 **pixel upscaler**（更快）。

> 完整混合实现指南（含请求 payload 与对比示例）：https://vrfi1sk8a0.feishu.cn/docx/O6Aid7HxloyFRSxi9Nic2DDwnng
> （同上，本次抓取无正文返回；因此本节的请求字段、轮询细节均未取到原文。）

---

## 7. API 与平台（来自文档 2）

| Endpoint | 国际文档 | 国内文档 |
|---|---|---|
| Create H3-2K（2K 生成） | https://platform.minimax.io/docs/api-reference/video-generation-v2-create | https://platform.minimaxi.com/docs/api-reference/video-generation-v2-create |
| H3-Context-IR（指令精炼） | https://platform.minimax.io/docs/api-reference/video-generation-v2-h3-context-ir | https://platform.minimaxi.com/docs/api-reference/video-generation-v2-h3-context-ir |
| H3-Regenerate-2K（768p→2K 重生成） | https://platform.minimax.io/docs/api-reference/video-generation-v2-regeneration | https://platform.minimaxi.com/docs/api-reference/video-generation-v2-regeneration |

- 国际平台：https://platform.minimax.io · 定价：https://www.minimax.io/price
- 国内平台：https://platform.minimaxi.com
- 体验入口：MiniMax Design https://design.minimaxi.com/ （桌面端专属权益，免费 3 次 H3 视频生成，新用户 3000 积分）；海螺 AI https://hailuoai.com/

### 示例代码与工具链（文档 2）

| 资源 | 链接 | 说明 |
|---|---|---|
| 可直接运行的 API 脚本 | https://huggingface.co/MiniMaxAI/MiniMax-H3/tree/main/scripts/readme | 全任务 curl 脚本：T2VA / I2VA / Ref2VA，768p 与 2K 两条路径，含可复现请求校验 |
| 官方 agent skills ×9 | GitHub `/skills` | `npx skills add https://github.com/MiniMax-AI/MiniMax-H3 --skill h3-prompt-writing`，让 AI 助手按官方规范写提示词；另含 8 个风格化技能 |
| ComfyUI 工作流 | https://docs.comfy.org/tutorials/video/minimax/minimax-h3 | T2V / I2V / 首尾帧 / 参考 四种内置模板 + 图文教程 |
| vLLM-Omni 服务化 | https://recipes.vllm.ai/MiniMaxAI/MiniMax-H3 | OpenAI 兼容服务化部署与实测参考数据 |

---

## 8. 许可与商用（来自文档 2）

| 资源 | 链接 | 要点 |
|---|---|---|
| 许可全文（MiniMax H3 Community License） | https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE | 免版税、**可商用**；年收入 > **US$20M** 需书面授权；商用产品界面须标注 "MiniMax H3"；**产出不得用于训练其他 AI 模型** |
| 官方许可问答 | https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/QA-about-License.md | 解释 EU / UK / US / 韩国为何暂受限（"not yet, not not ever"）及 API 为何全球可用 |
| 受限地区授权申请 | https://platform.minimax.io/h3-license | 受限地区机构的正式授权申请入口 |

---

## 9. 开源边界与路线图（来自文档 2）

- **稀疏注意力实现**将在后续更新放出。
- **H3-Context-IR 不开源**（依赖多阶段托管服务）；提供 API 复现官方行为，并附 Prompting Guidance 供自建。
- **2K 模块尚未发布**，"就绪后将发布"。
- 发布记录：https://github.com/MiniMax-AI/MiniMax-H3/releases

---

## 10. MiniMax Design 平台（来自文档 5）

**定位**：由 **AI Agent 驱动的商业内容生产平台**，把多模态模型能力转化为真实可用的生产力。

核心优势是理解、拆解并执行商业内容生产任务：用户只需表达创作目标，Design Agent 就会规划任务、扩展 Prompt、选择合适的 Skill 与工具、调用适配模型，并组织素材、持续修改，推动内容从想法走向交付。

### 官网（国内 / 海外账号不联通）

| 版本 | 地址 |
|---|---|
| 国内版 | https://design.minimax.cn/ |
| 海外版 | https://design.minimax.io/ |

> 文档 1 中给出的体验入口写作 `https://design.minimaxi.com/`，与本篇的 `design.minimax.cn` 不一致，使用时以官网实际跳转为准。

### v3.0.16 更新要点（9/17）

**模型与 Agent**
- 新增 **Wan 3.0** 模型，年卡会员继续享受 8 折生成优惠。
- Agent 支持**自定义模型**，可接入自己的模型，无缝融入现有工作流。

**创作体验优化**
- 画布节点新增对齐参考线和自动吸附。
- 提示词可直接引用项目中的资产和主体，便于基于已有内容继续创作。
- 剪辑完成后可将视频或音频导出到画布或本地，也可直接让 Agent 完成导出。

**体验优化与修复**
- Windows 支持自定义关闭方式：隐藏到托盘或退出应用。
- 修复调色时图片上下颠倒、素材引用覆盖后续文字、浏览器插件语言未跟随应用设置等问题。
- 修复安装失败、无法退出等问题。

**其他**
- 在线更新失败时，可前往官网下载最新版手动安装。
- 年卡会员额外享有 **1 年 8 折生成优惠**。

---

## 11. 术语与缩略语

术语含义均取自上述 5 篇文档的原文描述，未在文档中展开的已在「出处/说明」列注明。

| 术语 | 含义 | 出处/说明 |
|---|---|---|
| **DiT（33B）** | H3 扩散 transformer，联合生成视频与音频，承担几乎全部重复计算 | 文档 3 |
| **Qwen3-VL-32B** | H3 的文本编码器，生成开始时一次性读取提示词与参考输入 | 文档 2、3 |
| **FL2VA** | DiT 变体，用于文生视频或首/尾帧控制 | 文档 3 |
| **Ref2VA** | DiT 变体，用于参考图像、视频、音频或续写；与 FL2VA 共用 TE 与 VAE | 文档 3 |
| **H3-Base** | 本地以 768p 运行的生成环节（C 端叫 H3-Base） | 文档 3 |
| **H3-Context-IR** | 托管的提示词精炼环节，**补充**条件媒体；底层未开源 | 文档 3、2 |
| **H3-Regenerate-2K** | 托管的 768p→2K 重生成环节；底层未开源 | 文档 2、3 |
| **`base_video`** | Regenerate-2K 请求中视频条目的角色，要求**恰好一个** | 文档 3 |
| **SageAttention** | 编译 attention 后端，社区报告去噪循环约 **1.5–2×** 提升 | 文档 3 |
| **8-step Turbo LoRA** | 缩短采样调度的加速 LoRA；剪枝模型须配剪枝转换版 | 文档 3 |
| **Sol Engine** | NVLabs 的加速实现：5090 **4.52×**、DGX Spark **3.92×** | 文档 2、4 |
| **稀疏注意力** | 官方 README 声明「将在后续更新放出」，暂未开源 | 文档 2 |
| **量化档位** | nvfp4 / int8 / fp8 / pruned / NF4 / GGUF，体积见第 2 节 | 文档 2、4 |
| **WanGP / DiffSynth** | 低显存运行工具：5–6 GB 出 5 秒片 / 8 GB 起 NF4 | 文档 4 |
| **MLX / SGLang / vLLM-Omni** | Apple / AMD / 多卡三条非默认 CUDA 路径 | 文档 3、4 |
| **latent / pixel upscaler** | 全本地收尾的两种放大方式：前者模型感知、后者更快 | 文档 3 |

---

## 12. 风险与限制清单

| 类别 | 具体限制 |
|---|---|
| 许可 | 免版税可商用；年收入 > **US$20M** 需书面授权；商用界面须标注 "MiniMax H3"；产出**不得**用于训练其他 AI 模型 |
| 区域 | EU / UK / US / 韩国**暂不受许可覆盖**（官方措辞 "not yet, not not ever"），但 API 全球可用；受限地区有[正式申请入口](https://platform.minimax.io/h3-license) |
| 开源边界 | 稀疏注意力未放出；**Context-IR 不开源**（仅 API + 自建教程）；**2K 模块尚未发布** |
| 工程坑 | 用 cu128 会**静默回退**普通算子、慢数倍；驱动需 r580+；须确认量化后端已启用 |
| 数据边界 | 混合流程会把条件媒体、最终提示词与本地草稿发给托管服务，需评估留存与合规 |
| 资源 | 系统内存 ≥ 32 GB；即便专业卡也很慢（H100 ≈ 10 min/5s）；像素数是最贵的维度 |
| 账号 | MiniMax Design 国内版与海外版**账号不联通**，需分别注册 |

---

## 13. 待补与注意

- 文档 1（**已完整抓取**）：正文、核心规格表、§四 提示词方法论全部拿到；仍缺的是以图片/视频块呈现的示例演示，以及个别被折叠的评论区答复。
- 文档 2（**已补齐**）：`Community & Support` 已抓取到（Discord、X、hailuoai.video、GitHub、联系邮箱等），见附录 B8。
- 文档 4（**已补齐**）：`二、Ecosystem Master Table` 全表 10 类条目与 81 个链接已入附录 D2。
- 文档 5：`【往期更新】` 列表在原文中未展开，仍缺；部分案例的完整示例提示词以长文/图片给出，未全部纳入。
- 文档 3 引用的两篇 docx（完整硬件与优化指南 `VJA3dLNNpo2gnDxkKfFcaCXbnTf`、完整混合实现指南 `O6Aid7HxloyFRSxi9Nic2DDwnng`）已用无头浏览器验证为**登录墙**（页面正文仅 231 字符引导文案）；因此混合流程的**请求字段与轮询细节**仍无公开来源。
- 原文表格中部分链接文本夹带零宽字符（如 `diffusion_models/`、`text_encoders/`），手动复制到浏览器若异常，请去掉隐藏字符。
- 文档 3 中给出的 shell 命令属原文安装示例，未在本机执行。

---

## 14. 链接总索引

### 官方与代码
- 官方 GitHub（代码 / 9 个 skills / 部署校验）：https://github.com/MiniMax-AI/MiniMax-H3
- 发布记录：https://github.com/MiniMax-AI/MiniMax-H3/releases
- 原版权重（HF，Diffusers）：https://huggingface.co/MiniMaxAI/MiniMax-H3
- 国内镜像（ModelScope）：https://modelscope.cn/models/MiniMax/MiniMax-H3
- ComfyUI 重打包版：https://huggingface.co/Comfy-Org/MiniMax-H3

### 模型分包（Comfy-Org）
- DiT / diffusion_models：https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/diffusion_models
- 文本编码器 / text_encoders：https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/text_encoders
- VAE / vae：https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/vae
- 社区量化检索：https://huggingface.co/models?search=MiniMax-H3
- 社区 NVFP4（50 系）：https://huggingface.co/DmitryDB/MiniMax-H3-ComfyUI-Quants
- DiffSynth NF4：https://huggingface.co/DiffSynth-Studio/MiniMax-H3-NF4
- MLX 8bit（FL2VA / Ref2VA）：https://huggingface.co/ddalcu/MiniMax-H3-FL2VA-MLX-Serve-8bit · https://huggingface.co/ddalcu/MiniMax-H3-REF2VA-MLX-Serve-8bit

### 教程与工作流
- ComfyUI 官方 H3 教程：https://docs.comfy.org/tutorials/video/minimax/minimax-h3
- 3060 专用工作流：https://github.com/tlano-z/ComfyUI-MiniMax-H3-Workflows-For3060
- 16G 实测笔记：https://github.com/Tomiigo/minimax-h3-16gb
- 3090 15 秒实录：https://github.com/tonyd2wild/minimax-h3-local
- RTX Pro 6000 单卡实践（中文）：https://github.com/eric8810/minimax-h3-deploy
- DGX Spark 调优仓 / SM121 / 双机：https://github.com/drowzeys/keys-heretic-MiniMax-H3-sol-engine-more-speed-upgrades-upscaler-finish-Single-DGX-Spark · https://github.com/joeynyc/MiniMax-H3-DGX-Spark · https://github.com/joeynyc/MiniMax-H3-2x-DGX-Spark
- RunH3onMac：https://github.com/HeyZhey/RunH3onMac
- Sol Engine（NVLabs）：https://nvlabs.github.io/Sana/Sol-Engine/H3-OnDevice/
- Wan2GP：https://github.com/deepbeepmeep/Wan2GP

### 服务化与运行时
- vLLM-Omni recipe：https://recipes.vllm.ai/MiniMaxAI/MiniMax-H3
- SGLang（GitHub / ROCm 安装）：https://github.com/sgl-project/sglang · https://docs.sglang.io/docs/sglang-diffusion/installation
- PyTorch CUDA 13.0 wheels：https://download.pytorch.org/whl/cu130
- ComfyUI：https://github.com/comfyanonymous/ComfyUI

### API / 平台 / 许可
- Create H3-2K：https://platform.minimax.io/docs/api-reference/video-generation-v2-create
- H3-Context-IR：https://platform.minimax.io/docs/api-reference/video-generation-v2-h3-context-ir
- H3-Regenerate-2K：https://platform.minimax.io/docs/api-reference/video-generation-v2-regeneration
- 国际平台 / 定价：https://platform.minimax.io · https://www.minimax.io/price
- 国内平台：https://platform.minimaxi.com
- 许可全文：https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE
- 许可问答：https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/QA-about-License.md
- 受限地区授权申请：https://platform.minimax.io/h3-license
- MiniMax Design 国内 / 海外：https://design.minimax.cn/ · https://design.minimax.io/
- 海螺 AI：https://hailuoai.com/

### 社区与支持
- 官方 Discord：https://discord.com/invite/dbMxutw7tP
- X：https://x.com/MiniMax_AI ｜ https://x.com/Hailuo_AI
- 在线体验：https://hailuoai.video ｜ 社区与反馈站：https://hub.minimaxi.com/
- 联系：`model@minimax.io`（模型）· `api@minimax.io`（授权）· https://platform.minimaxi.com/docs/faq/contact-us

### 官方提示词指南（开源仓库内）
- 基础模式：`VIDEO_PROMPT_WRITING_GUIDE_base_en.md`
- 参考模式：`VIDEO_PROMPT_WRITING_GUIDE_ref_en.md`
- 仓库：https://github.com/MiniMax-AI/MiniMax-H3

### MiniMax Design 平台
- 国内：https://design.minimaxi.com/ ｜ 海外：https://design.minimax.io/
- 订阅页：https://design.minimaxi.com/media-plan/subscribe ｜ https://design.minimax.io/media-plan/subscribe
- 活动页：https://design.minimaxi.com/campaign ｜ https://design.minimax.io/campaign

### 待补原文（需登录）
- 完整硬件与优化指南：https://vrfi1sk8a0.feishu.cn/docx/VJA3dLNNpo2gnDxkKfFcaCXbnTf
- 完整混合实现指南：https://vrfi1sk8a0.feishu.cn/docx/O6Aid7HxloyFRSxi9Nic2DDwnng

---

## 15. 本机落地实录：问题与解决（2026-09-29）

> **本节是实测记录，不是上述 5 篇飞书文档的摘录**。数据来源：`D:\code\voide\comfy-studio\ComfyUI\user\comfyui_8188.log` 等启动与运行日志，以及对共享模型库 `D:\Comfy-Desktop\ComfyUI-Shared\models` 的文件级校验。

### 15.1 本机环境（实测值）

| 项目 | 值 |
|---|---|
| ComfyUI | **0.37.0**（非 git 仓库安装，Manager 显示 Revision UNKNOWN） |
| Python | 3.11.9 |
| PyTorch | **2.14.0+cu130** ｜ torchvision 0.29.0+cu130 ｜ **torchaudio 未安装** |
| GPU | NVIDIA RTX A5000 ｜ **VRAM 23028 MB** ｜ `cudaMallocAsync` |
| 系统内存 | **95848 MB**（≈93.6 GB） |
| 注意力 | pytorch attention（未装 SageAttention / triton） |
| 量化后端 | `comfy-kitchen 0.2.35`，cuda 后端可用：`convrot_w4a4_linear`、`int8_linear`、`scaled_mm_nvfp4` 等 50+ 能力在线 |
| DynamicVRAM | **已启用**（`fast_disk=True`、async offload 2 streams、pinned memory 38339 MB） |
| 前端 / 模板 | comfyui-frontend 1.53.6 ｜ workflow-templates 0.11.70 ｜ `comfy-aimdo 0.5.5` |
| 模型库 | `D:\Comfy-Desktop\ComfyUI-Shared\models`（与 `ComfyUI\models` 合并索引） |

**对照第 3 节分档**：24 GB 显存 + 93.6 GB 内存，正落在「int8 34G DiT + int8 TE」推荐档。

**实测耗时（可作为本机基线）**：

| 任务 | 模型 | 实测 |
|---|---|---|
| H3 fl2v，124 帧 @ 24fps，1344×768，含音频 | `minimax_h3_fl2va_int8_convrot`（32427 MB staged）+ `qwen3vl_32b` TE（25882 MB）+ 双 VAE | **471.39 秒**（Prompt executed） |
| Qwen-Image 2.1 出图，25 步 | `qwen_image_2.1_int8_convrot`（6920 MB） | **21–35 秒/张** |

### 15.2 下载完整性校验方法（可复现，不靠"文件看起来在"）

对每个 `.safetensors`：读文件头 8 字节得到 JSON 头长度 `n` → 解析该 JSON → 取所有张量 `data_offsets[1]` 的最大值 `max_off` → 断言

```
max_off + 8 + n == 文件实际字节数
```

相等即**字节级完整**（可检出截断下载与尾部多余写入），且只需读文件头、**不加载权重**，秒级完成。

**校验结果**

| 文件 | 体积 | 张量数 | 头期望 = 实际 | 结论 |
|---|---|---|---|---|
| `diffusion_models\minimax_h3_fl2va_int8_convrot.safetensors` | 31.70 GB | 1035 | 34038892334 = 34038892334 | 完整 |
| `diffusion_models\minimax_h3_ref2va_int8_convrot.safetensors` | 31.70 GB | 1035 | 34038894550 = 34038894550 | 完整 |
| `diffusion_models\minimax_h3_fl2va_pruned_int8_convrot.safetensors` | 19.53 GB | 932 | 20970379616 = 20970379616 | 完整 |
| `diffusion_models\minimax_h3_ref2va_pruned_int8_convrot.safetensors` | 19.53 GB | 932 | 20970379616 = 20970379616 | 完整 |

- 全库 **无 `.part` / `.part.dl-meta` / `.orphan` 残留**（断点续传痕迹为零）
- `user\default\workflows\AIGC中国风漫剧\` 下 **11 个工作流**（01~09 + `01_Lightning` + `02_ZImage`）引用的模型文件**全部命中**，零缺失

### 15.3 问题及主要解决

#### ① 已解决 / 判定无需处理

| # | 问题 | 证据 | 处理结果 |
|---|---|---|---|
| 1 | ComfyUI-Manager 拉取 `custom-node-list.json` **超时失败** | `15:43:46` aiohttp `readany` 超时 → `TimeoutError` | **自动重试成功**：`15:49:12 [DONE]`、`15:49:13 All startup tasks completed`。纯网络抖动，无需干预 |
| 2 | `torchaudio` 未安装，疑似缺口 | `custom_nodes` 下**零处** `import torchaudio`；核心仅注释提及（`comfy/audio.py` 自带 DSP 实现） | **判定无需安装**，避免误装多余包 |
| 3 | `triton` 未安装 | `comfy_kitchen backend triton: {'available': False, 'disabled': True}` | **不影响**：可选加速后端，eager + cuda 均已可用 |
| 4 | 怀疑模型未下完 | 见 15.2 全部校验 | **已排除** |
| 5 | 怀疑自定义节点缺失（静态扫描曾报 19 项） | 启动日志 `IMPORT FAILED` 计数 = **0** | **误报，已作废**，见 ③ |
| 6 | Manager 报 `PyTorch is not installed` | 13:18 日志第 11 行；实际 torch 2.14.0+cu130 正常、VRAM 已正确识别 | Manager **自身依赖探测误报**，不影响运行 |

**已确认注册成功的自定义节点**：`ComfyUI-MiniMaxH3`、`ComfyUI_MiniMaxH3_Director`（`MiniMax H3 Director HTTP routes registered`）、`ComfyUI-H3-Motion-Context`、`ComfyUI-H3-Multishot`、`ComfyUI-MiniMaxH3-TeaCache`、`ComfyUI-GGUF`（`[H3] taught ComfyUI-GGUF the 'minimax_h3' architecture`）、`comfyui_controlnet_aux`、`ComfyUI_IPAdapter_plus`、`ComfyUI-Custom-Scripts`、`ComfyUI_JoyAI_Echo`、`comfy_studio`、`comfyui-openai-llm`。

#### ② 唯一真实异常：H3 文本编码器偶发设备不匹配（当前未复现）

```
Expected all tensors to be on the same device, but got index is on cuda:0,
different from other tensors on cpu  (wrapper_CUDA__index_select)
```

调用链：`ComfyUI-MiniMaxH3\nodes\conditioning.py:192` → `utils\encoder_use.py:109` → `models\text_encoder\encoder.py:329`
发生时间：9/29 `15:23:40`（13:18 那次会话）；**9/29 15:41 及之后的会话未再出现**，同一套 fl2v 流程 471 秒跑通。

**判定**：**不是模型文件损坏**（已通过 15.2 字节校验），而是 DynamicVRAM 部分加载（`25882MB Staged` / `Forced pre-loaded 310 weights`）状态下，编码器权重与索引张量落到不同设备的**时序问题**。

**若复现，按代价从低到高处理**（②③为基于日志的推断，尚未实测）：

1. **直接重跑**（当前已自愈，成本最低）
2. 让 TE 完整驻留：加 `--disable-dynamic-vram`，或调高 `--reserve-vram` 避免 32B 文本编码器被分片换出
3. 仍复现才改 `encoder_use.py`：在 `encode()` 入口统一把 `payload` 与模型参数 `to(device)`（属修改三方节点代码，非必要不动）

#### ③ 排查方法上的两次失误（非环境问题，记录下来避免重犯）

| 失误 | 根因 | 修正 |
|---|---|---|
| 静态扫描报 19 项"节点未找到" | 核心节点注册在**根目录 `nodes.py`**，只扫了 `comfy/`、`comfy_extras/`、`custom_nodes/` | 改以**启动日志**为准（`IMPORT FAILED` 计数） |
| "缺失节点"清单里混入 `COMBO`/`AUDIO`/`VIDEO`/`SIGMAS` | 递归时把所有 `"type"` 键都当节点类型，未区分 **widget 数据类型**与**节点类** | 只认 `class_types` 与带 `widgets_values` 的节点对象 |

> **方法论结论**：判断"节点是否齐全"应以**运行时启动日志**为唯一准据，静态扫描只适合查"模型文件是否缺"，且需明确"注册点在哪"。

### 15.4 本节结论

- 模型、节点、量化后端、torch/cu130 链路**全部验证通过**，且已由真实生成任务（H3 fl2v 471 秒成片 + Qwen-Image 2.1 连续出图）反向证明可用，**无需再下载任何文件**
- 硬件档位与本机实测耗时已记入 15.1，可作为后续调优对照基线
- 唯一遗留：H3 文本编码器偶发 device mismatch，**未复现则不动代码**；一旦复现按 15.3② 顺序处理

---

# 附录：各文档原文摘录

原始抓取只能拿到每篇文档**首屏（已渲染）部分**；下述内容为该部分能取到的全部细粒度材料，凡原文用英文写的均给出英文原句 + 中文。原文未出现的细节不在此处补写。

---

## 附录 A｜文档 1《🐚MiniMax H3 模型 - 使用手册》

链接：https://vrfi1sk8a0.feishu.cn/wiki/FIWjwgL33ipnkekzk30crmKUnIh ｜修改日期：9/1 ｜状态：持续更新中～

### A1. 更新日志（逐条）

| 日期 | 条目 |
|---|---|
| 9/1 新增 | **1.10 出海多语种场景** |
| 新增 | **1.3 动态图形、MG 动画、AE 特效** |
| 新增 | **1.4 AR 现实增强创意视频** |
| 新增 | **1.6 goodcase** |
| 新增 | **1.9 goodcase** |

### A2. 体验入口（逐条）

| 入口 | 链接 | 权益 |
|---|---|---|
| MiniMax Design | https://design.minimaxi.com/ | 桌面端专属权益；**免费体验 3 次 H3 视频生成**；新用户获 **3000 积分** |
| 海螺 AI 体验中心 | https://hailuoai.com/ | — |
| 开放平台 API | https://platform.minimaxi.com/docs/api-reference/video-generation-v2-create | 视频生成 V2 接口文档 |

### A3. 正文：一、模型定位（原文逐字）

> **MiniMax H3 是新一代开放通用多模态视频模型**，我们正在探索从"特化任务模型"迈向"通用多模态智能"的新范式。
>
> H3 不再以图片、视频、声音的生成、编辑、参考等单一任务为边界，而是面向由**文本、图像、视频与声音共同构成的多模态上下文**，统一理解创作意图，完成更加自然、连贯的生成与表达。
>
> H3，迈向更通用的多模态智能。

### A4. 核心规格与输入限制（原文表格）

| 维度 | 说明 |
|---|---|
| **输出时长** | 最长 **15 秒** |
| **输出长宽比** | 首/尾帧模式：**遵循输入图片的原始长宽比**；文生视频 / 全能参考：21:9、16:9、4:3、1:1、3:4、9:16（全能参考也可选「自动」，由 H3 自行判断） |
| **768p 模式（已开放）** | 宽高比在 16:9～9:16 之间时输出**短边 768 像素**；否则总面积约 **1M 像素**（21:9 → **1536×672**）。768p 结果**可升级至 1440p** |
| **1440p 模式（官方推荐 👍）** | 宽高比在 16:9～9:16 之间时输出**短边 1440 像素**；否则总面积约 **3.7M 像素**（21:9 → **2976×1248**） |
| **输出帧率** | **24 FPS** |
| **输出声音** | 所有结果**全部带声音**，原生**双声道** |
| **输入 · 首/尾帧入口** | 图片 **0、1、2 张**；宽高范围 **[256, 5760]**；宽高比 **5:2～2:5**；无图片输入即文生视频模式 |
| **输入 · 全能参考入口** | 图片 **≤ 9 张**；视频：**单段 [2, 15] 秒**、**总长 ≤ 15 秒**、宽高范围 [256, 5760]、宽高比 5:2～2:5（**段数上限原文被高亮块拆分，未完整取到**）；音频 **≤ 3 段**，且**必须搭配图片或视频、不能单独输入**，单段 [2, 15] 秒、总长 ≤ 15 秒；**混合输入总上限 12 个文件** |
| **输入格式** | 视频 H.264/AVC、H.265/HEVC，视频内音频 AAC、MP3；图片 JPG、JPEG、PNG、WEBP、HEIC、HEIF；音频 WAV、MP3 |
| **传入大小** | 视频单个 **50MB**、图片单个 **30MB**、音频单个 **15MB**（只限制单个素材，总量不限）；**API 请求体 64MB**，推荐用 url 传入素材 |
| **提示词上限** | **不超过 7000 字符** |
| **语言支持** | 支持多语言提示词输入与输出，适合海外品牌传播、多语种广告、跨语言短片与本地化产品介绍 |

**三大能力（原文）**

1. **多模态理解与生成**：支持文字、图片、音频、视频等多种输入，理解不同素材中的人物、动作、声音、情绪、镜头、风格与表达意图，并将多种参考信息自然融合，完成从素材理解到完整视听内容生成的一体化创作。
2. **多模态精准编辑与控制**：支持对人物、物体、场景、声音与节奏进行多维度编辑，具备精细化指令遵循能力，可在已有内容基础上持续修改迭代。
3. **面向真实商业内容场景**：覆盖影视、广告、品牌、电商与游戏，兼顾文字字幕、品牌信息、创意特效、产品展示、UI/UX 动态演示、游戏视觉及风格化表达，帮助创作者更快完成创意验证、视觉提案与内容制作。

---

### A5. §四 如何更好地使用 H3（提示词方法论，原文全文要点）

**1.1 整体公式**

```
完整提示词 = 参考素材说明 + 核心创意 + 画面过程说明
```

**1.2 参考素材说明**（没有上传素材时整段跳过）

- **写清素材编号**：按上传顺序，如 `@图片1`、`@音频2`、`@视频3`。
- **写清每个素材的用途**：人物参考（锁脸/形象）/ 物体参考（锁物体）/ 场景参考（锁场景）/ 关键帧（锁帧，有首尾帧需求要明确提出）/ 音色参考 / 故事版（按分镜生成镜头内容）/ 风格参考 / 构图参考 / 音频复用（生成视频的音频直接复用参考音频）/ 音频部分复用（某个声音轨道或某时间段部分复用）/ 动作参考 / 运镜参考 / 视频编辑（对视频内容增删改）等，其他要求也可按需写明。
- 示例：`@图片1 提供了 xx 角色的形象（如果有多个角色，需要能指代清楚），@视频2 提供了动作参考。`
- 素材中有**非常想保持的特征**要明确写出来，一致性更好；音频复刻/部分复刻若对白或歌词保持要求高，**强烈建议补充具体歌词文本**：`比如 @音频1 作为目标视频的音频复刻素材，具体歌词是：“ABCDEFGHIJKLMN”。`
- **运镜坑**：不建议直接说"环绕运镜"，建议写 `truck left + pan right` 或 `truck right + pan left`。

**1.3 核心创意（一句话锁定全片）**

必须包含：**谁/什么**（人/物/动物/其他）+ **地点**（在哪里）+ **在做什么** + **题材/风格**（写实/动画/电影感/广告片/纪录片……；特殊风格列举如赛博朋克/霓虹灯美学/涂鸦风）+ **特殊运镜**（航拍/一镜到底/慢动作……）。

- **默认会切镜**；运镜风格写清即可。
- **切镜风格**：普通切镜（cut）/ 叠化切镜（fade）/ 随节奏卡点切镜。
- 任何元素若与引用素材有直接关联，都用 `@图片1`/`@音频1`/`@视频1` 强调。
- 示例：`一位穿汉服的年轻女子（@图片1）在樱花纷飞的庭院里舞剑，古典国风，电影质感，一镜到底。`

**1.4 画面过程说明**

- 按**时间轴或故事线分段**写，每个分镜/时间段包含两部分：**（画面里要出现什么）**画面景别 + 内容 + 运镜 + 动作 + 台词 + 音效，以及**（视频里不要出现什么）**。
- 以**切镜 shot 作为时间戳分段**，每个 shot 内部写清景别、具体内容、shot 内运镜、人物台词、音效。
- **台词长短尽量和镜头长短对齐**（原文强调：很多口型问题来自这里）。
- 一句台词跨 shot 时，用"接着上个 shot 继续说"这类描述表明是跨 shot 对白。
- 画面中若需要具体文字、Logo、标题、标语、按钮文案，**一定要把文字原文写出来**：`画面中出现英文：“H3”`；`手机屏幕上显示标题：“AI Video Creation”，按钮文字为：“Start Now”。`
- 不想要背景音乐时要明确写明：`非叙事性音乐：N/A` 或英文格式 `"non_diegetic_music": N/A`，或 `不要额外添加背景音乐。`
- **少写比喻句，多写看得见的画面**——H3 更擅长理解明确的画面指令，而不是抽象比喻。
- 示例（时间轴写法）：
  - `0-3 秒：全景，女子（@图片1）从画面左侧缓步走入樱花庭院（@图片2），背景虚化，没有对白，只有脚步声。`
  - `3-8 秒：切镜到女子（@图片1）的中景，她拔出长剑（@图片3），缓缓起势，樱花瓣从树上飘落。镜头推进。`
  - `8-12 秒：切镜到特写，剑光一闪，慢动作，樱花被剑气激得四散。`

**1.5 容易踩的坑（原文表格）**

| 常见问题 | 怎么改 |
|---|---|
| 只写一段话没分段 | 按 3 段公式拆开写 |
| 素材上传了但没说用途 | 补一句「@图片1 是 XX 参考」 |
| 想用音乐但说「不要 BGM」 | 这两个要求矛盾，要么删一个，要么分场景写 |
| 想一镜到底但写了很多分镜 | 全文保持一段情节描述，删掉【镜头 N】结构 |
| 想要主角脸一致但没传图 | 一定要上传人物参考图，并标注「人物参考」 |
| 提示词太短（H3 没素材可参考时） | 至少写出主体外观 + 场景细节 + 动作 + 风格 |

**2. 特定风格 · 三类模式写法**

| 模式 | 写法要点（原文） |
|---|---|
| **多模态素材融合** | 可同时上传人物图 + 动作视频 + 场景图 + 音乐，**每个素材都要写清它的角色**：`@图片1 → 人物参考（锁脸）`、`@视频1 → 动作参考（锁动作）`、`@音频1 → 节奏/情绪参考`；示例：`@图片1 是人物参考（锁这位女子的脸），@视频1 是动作参考（用里面的舞剑动作），@音频1 是情绪参考（古风配乐）。让这位女子在樱花庭院里按视频里的动作舞剑。` |
| **上传图片生成视频** | 只上传 1 张图：说清楚是**视频开头画面**还是**视频结尾画面**；上传 2 张图（首+尾帧）：**H3 不会自动加切镜**，只补两帧之间的动作、光影、声音。示例：`@图片1 是首帧参考图：女子持剑站在樱花树下。让她从持剑起势到舞剑完毕，自然衔接，不要切镜。` |
| **文生视频** | 不依赖参考素材时，文字描述要**更具体**（主体外观、场景细节、动作描述都写清）；多用「大全景交代空间 + 中景承载动作 + 特写强调细节」的分层写法。示例：`写实自然纪录片风格，电影级真实光影。清晨的薄雾中，在广阔的湿地芦苇荡里，一只优雅的白鹤单腿站立在浅水中，缓慢转头看向镜头。柔和的逆光，雾气在光束里飘动。` |

**3. 切镜与一致性（官方补充建议）**

- H3 具备**基础的分镜能力**，且**对切镜点的遵从性较强**。
- 台词长短要与每个 shot 的画面变化逻辑匹配，**尽量不要出现在 3s 的 shot 里说很大一段话**，会非常影响效果。
- H3 **能响应跨 shot（J-cut、L-cut）的台词**，只要明确写出一句台词跨了哪些 shot。
- shot 内如果是画面内说话人要写清是哪个角色说的；画外说话人要写清"画外说话人"；发生画内外转化时明确写出，例如：`一个画外音响起说：Wake up Wake up。之后切镜到一个中年妇女的近景，她是画外音的主人，她继续说道：It's time to go to school!`
- **切镜一致性保持**：切镜时明确写出切到什么景别、具体主体是之前的哪个角色，有助于跨镜头一致性。

**4. 🐙 撰写提示词的「最佳方式」**

> 不想花大量时间研究提示词结构、镜头语言、素材引用方式与声音设计，可以直接在 MiniMax Hub 里用 H3 创作。MiniMax Design 会帮你理解创作意图、整理参考素材、补全镜头设计、优化提示词，并调动合适的生成能力完成视频创作。
>
> 下载地址：国内 https://design.minimaxi.com/ ｜海外 https://design.minimax.io/

---

### A6. §一～三 定位、能力与示例（原文要点）

**核心定位**：H3 支持文字、图片、音频、视频等多种输入，将**所有素材视作统一上下文**，理解信息、声音、情绪、画面与表达意图之间的关系，实现从内容理解到视听融合的一体化创作。

**覆盖场景（原文列举）**：电影预告片、TVC 广告片、品牌质感大片；创意短片、特效包装、审美 MV、视觉实验、热点内容及社媒素材；竖屏短剧、漫剧短片、角色演绎及 AI 配音；产品展示、卖点视频、品牌及投流素材；以及 AR 增强现实创意（巨物营销、户外视觉）。

**能力拆解（原文）**

- **多素材联合参考**：文字、图片、音频与视频自由组合，共同参与内容生成。
- **角色、动作与镜头参考**：参考主角形象、人物动作、镜头运动与画面构图。
- **音色迁移与克隆**：参考音频音色，丝滑更新角色声音；**TTS 精准覆盖 11 种语言**（中文、英语、日语、韩语、法语、德语、西班牙语等），可衍生探索阿拉伯语、泰语、印尼语、印地语等 **40 多种语言**。
- **氛围与剪辑理解**：参考原视频的视觉风格、叙事节奏、声音氛围与整体剪辑感。
- **编辑能力**：角色与物体编辑（替换/删除/增加）、场景与视觉效果编辑（替换背景、调整光影氛围、增删特效）、声音台词与音色修改、高精度指令控制（局部修改，未编辑内容保持相对稳定）。

**已在文档中收录的示例提示词**（含首尾帧、多模态参考、角色替换、动作参考、背景替换、光影替换、台词替换、高精度指令、TouchDesigner 追踪、动态海报、MG 动画、中文文字动效、短剧、电商广告等二十余例），例如：

- 参考剪辑：`图1图2图3图4图5图6，严格参考示例视频视频1的镜头节奏、转场风格及音乐。`
- 动作参考（DIY 表情包）：`参考视频1进行动作模仿。固定机位全景镜头，正视频中三个穿西装的男人替换为三只高度写实的水豚……`
- 音色克隆：`角色说话：Follow the wind, live free. Leave worries behind, enjoy the moment，音色参考音频1`
- 台词替换：`将视频1女生说的话：“我们之间不可能在一起的……”改成音频1的台词：“别走了，好吗？……”并略微调整对应的表演`
- 高精度指令：`将参考视频中的报纸替换为一本绿色封皮的书；人物所坐的椅子改为红色沙发；去掉人物佩戴的墨镜，保留清晰面部；移除汽车燃烧效果……`
- **官方小 Tips**：处理文字遇到**乱码**时，可尝试把文字**以图片形式**提供给 H3 作为参考图，并在提示词中明确"这张内容必须按『图片』来理解，不能按『文字』来处理"，通常能有效降低乱码。

---

### A7. 评论区高频问题与官方答复

| 提问 | 官方/作者回答（原文要点） |
|---|---|
| **人物的内心独白怎么写？老是自己说出话来** | 用正向/负向约束：明确"不要开口/不要说话/仅内心独白"，并在画面过程里写清嘴部与表演状态（原文答复区给出了具体约束写法） |
| **音效、配乐、音量怎么控制** | 用结构化字段描述：`integrated_multimodal_description`（画面内声音）、`overall_soundscape`（整体环境声）、`non_diegetic_music`（非叙事性配乐）；音量用**相对混音描述**表达，而非绝对数值 |
| **参考图怎么编号 / 怎么被引用** | 上传顺序 `ref_image_0` 在提示词中对应 `<Picture 1>`，提示词里**从 1 开始编号**，用 `@图片1` 这种方式指代 |
| **有概率出现字幕，写"不要字幕"也没用** | 官方建议不要写"不要字幕"这类负向描述；**双引号内的文字会出现在字幕里**，需要规避时不要用引号承载字幕意图 |
| **能不能视频扩图 / 消除视频字幕** | 不可以 |
| **新号 3000 积分怎么没了** | 3000 积分**保留三天**，过期会清零 |
| **提示词标准 / 指南在哪** | 官方指引：`VIDEO_PROMPT_WRITING_GUIDE_base_en.md`、`VIDEO_PROMPT_WRITING_GUIDE_ref_en.md`（开源仓库内） |
| **光照/效果不对怎么排查** | 官方给了分场景排查建议（先确认素材用途标注，再逐步加强画面约束描述） |

---

### A8. 本篇仍缺的部分

- 章节正文已通过浏览器渲染抓取到（含 §四 提示词方法论全文），但文档中大量**示例是以图片/视频块（图片1、图片2、图片3、各 mp4 演示）形式存在**，文本层无法还原，需回原页面观看。
- 具体某几段评论区答复在抓取时被折叠（显示为"展开"），仅有标题或截断。

---

## 附录 B｜文档 2《MiniMax H3 Open-Source Resources(中英双语)》

链接：https://my.feishu.cn/wiki/TowTwcCSwiEAh8k0bLCcsCvgnod ｜修改：8/18 18:22

### B1. Code & Models 代码与模型

| Resource | Link | What's there |
|---|---|---|
| **GitHub (official)** | https://github.com/MiniMax-AI/MiniMax-H3 | Code, **9 agent skills**, deployment validation scripts, full README with architecture notes |
| **Hugging Face** | https://huggingface.co/MiniMaxAI/MiniMax-H3 | Original weights (**Diffusers format**), docs, example scripts |
| **ModelScope** | https://modelscope.cn/models/MiniMax/MiniMax-H3 | Mirror for **mainland-China download speeds** |
| **ComfyUI repackage** | https://huggingface.co/Comfy-Org/MiniMax-H3 | Single-file builds sorted for ComfyUI folders, incl. quantized editions (**maintained by ComfyUI team**) |

### B2. Model Downloads 模型下载

原文核心句：

> A runnable H3 = one diffusion model + one text encoder + two VAEs.
> 一套可运行的 H3 = 扩散模型 + 文本编码器 + 两个 VAE，各选一个。

| Component | Options（体积 GB） | Download |
|---|---|---|
| **Diffusion model**（FL2VA 或 Ref2VA） | bf16 **66.3** ｜ int8 **34.0** ｜ pruned bf16 **40.2** ｜ pruned int8 / fp8 **21.0** | https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/diffusion_models |
| **Text encoder**（Qwen3-VL-32B） | bf16 **51.5** ｜ int8 **27.1** ｜ nvfp4 **15.7** | https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/text_encoders |
| **VAEs**（video + audio，**必装**） | fp16 **5.2** + fp32 **0.6** | https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/vae |

### B3. Community quantizations 社区量化

> Community quantizations (**GGUF / 4-bit**, down to **~10 GB**): search "MiniMax-H3" on Hugging Face
> 链接：https://huggingface.co/models?search=MiniMax-H3

### B4. Example Code 示例代码

| Resource | Description（原文） |
|---|---|
| **Ready-to-run API scripts**<br>https://huggingface.co/MiniMaxAI/MiniMax-H3/tree/main/scripts/readme | curl scripts for **every task** — T2VA / I2VA / Ref2VA, **768p and 2K** paths, incl. **reproducible-request validation**<br>全任务可直接运行的 curl 脚本，含 768p 与 2K 两条路径及复现校验脚本 |
| **Official agent skills ×9**<br>GitHub `/skills` | `npx skills add https://github.com/MiniMax-AI/MiniMax-H3 --skill h3-prompt-writing` — teaches Claude/Codex-type assistants to write spec-compliant prompts；另含 8 个风格化技能 |
| **ComfyUI workflows**<br>https://docs.comfy.org/tutorials/video/minimax/minimax-h3 | Bundled templates for **T2V / I2V / first-last-frame / reference**，with a step-by-step guide<br>四种任务内置模板与图文教程 |
| **vLLM-Omni serving recipe**<br>https://recipes.vllm.ai/MiniMaxAI/MiniMax-H3 | OpenAI-compatible serving with **measured reference numbers**<br>OpenAI 兼容服务化部署与实测参考数据 |

> 原文中的 `npx skills add ...` 只是给读者的使用说明，本次整理**未执行任何命令**。

### B5. API Docs API 文档

| Endpoint | EN docs | CN docs（国内） |
|---|---|---|
| **Create H3-2K**（2K 生成） | https://platform.minimax.io/docs/api-reference/video-generation-v2-create | https://platform.minimaxi.com/docs/api-reference/video-generation-v2-create |
| **H3-Context-IR**（指令精炼） | https://platform.minimax.io/docs/api-reference/video-generation-v2-h3-context-ir | https://platform.minimaxi.com/docs/api-reference/video-generation-v2-h3-context-ir |
| **H3-Regenerate-2K**（768p→2K 重生成） | https://platform.minimax.io/docs/api-reference/video-generation-v2-regeneration | https://platform.minimaxi.com/docs/api-reference/video-generation-v2-regeneration |

**Platform & pricing 平台与定价**：国际 https://platform.minimax.io （定价 https://www.minimax.io/price）；国内 https://platform.minimaxi.com

### B6. License & Commercial Use 许可与商用

| Resource | 要点（原文） |
|---|---|
| **License 全文**（MiniMax H3 Community License）<br>https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE | **Royalty-free incl. commercial use**；**>US$20M yearly revenue needs written authorization**；display **"MiniMax H3"** in commercial UIs；**outputs may not train other AI models**<br>免版税可商用；年收入超 2000 万美元需书面授权；商业产品界面须标注；产出不得用于训练其他模型 |
| **License Q&A**<br>https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/QA-about-License.md | Why the **EU / UK / US / South Korea** are temporarily excluded（**"not yet, not not ever"**），and why the API stays global<br>为何上述地区暂受限及 API 为何全球可用 |
| **Restricted-region licensing**<br>https://platform.minimax.io/h3-license | Formal license application for organizations in excluded regions<br>受限地区机构的正式授权申请入口 |

### B7. Release Notes & Roadmap 更新与路线

| Resource | 说明 |
|---|---|
| Releases<br>https://github.com/MiniMax-AI/MiniMax-H3/releases | Version history and changelogs |

**Stated in the README（官方已声明，逐条）**

1. **Sparse-attention implementation will be released in a future update**（稀疏注意力实现将在后续更新放出）。
2. **H3-Context-IR is not open-sourced**（multi-stage hosted workflow）— an API reproduces the official behavior, and the **Prompting Guidance** enables building your own（因依赖多阶段托管服务暂不开源，提供 API 复现 + 教程自建）。
3. **2K module "will be released once it is ready"**（2K 模块"就绪后将发布"）。

### B8. Community & Support 社区与支持（原文表格）

| Channel | 内容 / 链接 |
|---|---|
| **Official Discord 官方社区** | https://discord.com/invite/dbMxutw7tP |
| **X 动态** | https://x.com/MiniMax_AI ｜ https://x.com/Hailuo_AI |
| **Try it in-app 在线体验** | https://hailuoai.video |
| **Official GitHub 官方仓库** | 代码、技能包与 issue 反馈：https://github.com/MiniMax-AI/MiniMax-H3 |
| **Contact 联系** | `model@minimax.io`（模型）· `api@minimax.io`（授权 licensing）· 飞书 · 国内联系入口 https://platform.minimaxi.com/docs/faq/contact-us |

（本节此前因抓取只到首屏而显示为空，现已补齐。）

---

## 附录 C｜文档 3《Run MiniMax-H3 Locally: A Simple Hardware and 2K Workflow Guide》

链接：https://my.feishu.cn/wiki/X5ZjwtT9FitKQFknfmYcRukknbd ｜最近修改：9/2 14:41 ｜原文为英文

### C0. 引言（原文要点）

- You **do not need a datacenter GPU** to run MiniMax-H3.
- Quantized checkpoints, system-memory offload, and low-resolution drafts make local generation feasible on consumer hardware.
- For finished output, a **hybrid path** is recommended：① prepare prompts with **H3-Context-IR**；② run **H3-Base locally at 768p**；③ send only the approved take to **H3-Regenerate-2K**。
- Benefit：keep the expensive iteration loop local, use the hosted model only where it pays.

### C1. Can your hardware run H3?（原文表格 + 中文）

| Hardware | Recommended path | What to expect |
|---|---|---|
| **8–12 GB NVIDIA** | Pruned int8 or NF4 with RAM offload; WanGP or DiffSynth below 10 GB | Usable for lower-resolution drafts, but expect long generation times |
| **16–24 GB NVIDIA** | Pruned int8 or fp8 in ComfyUI | The best consumer starting point for regular local use |
| **32 GB NVIDIA** | Pruned fp8 or NVFP4 | The fastest practical desktop tier |
| **48 GB+** | Int8 or full bf16 | More room for quality and resolution, although pixel count remains expensive |
| **Apple, AMD, or no local GPU** | MLX or DiffSynth on Apple; SGLang on supported AMD hardware; Colab or cloud GPU otherwise | Viable through separate runtimes rather than the default CUDA recipe |

中文逐行：

- 8–12 GB NVIDIA：剪枝 int8 或 NF4 + RAM offload；显存 10 GB 以下用 WanGP 或 DiffSynth。可做低分辨率草稿，但生成时间很长。
- 16–24 GB NVIDIA：ComfyUI 中的剪枝 int8 或 fp8。常规本地使用的最佳消费级起点。
- 32 GB NVIDIA：剪枝 fp8 或 NVFP4。最快的实用桌面档位。
- 48 GB+：Int8 或完整 bf16。质量与分辨率空间更大，但像素数依然昂贵。
- Apple / AMD / 无本地 GPU：Apple 用 MLX 或 DiffSynth；受支持 AMD 用 SGLang；否则 Colab 或云 GPU。需走独立运行时而非默认 CUDA 方案。

其他要点：

- 对多数个人用户，**ComfyUI 是最容易的起点**——它能按需在系统 RAM 与 VRAM 之间搬运模型组件，完整下载不必一次性全塞进显存。
- 至少 **32 GB 系统内存**；**64 GB** 对更大的 checkpoint 更稳妥。
- 社区测速结果因分辨率、量化、offload、kernel 配置差异波动极大——**任何单一速度数字只能当作数量级参考，而非承诺**。

### C2. What do you need to download?

**三组组件（原文描述）：**

- **The H3 DiT**：33B diffusion transformer，**jointly generates video and audio**，承担了几乎全部重复计算。
- **The text encoder**：**Qwen3-VL-32B**，在生成开始时**一次性**读取提示词与参考输入。
- **The video and audio VAEs**：在 H3 的 latent 表示与最终像素/波形之间转换。

**下载来源：**

- 原始精度版：`MiniMaxAI/MiniMax-H3`（https://huggingface.co/MiniMaxAI/MiniMax-H3）
- ComfyUI 重新打包版：`Comfy-Org/MiniMax-H3`（https://huggingface.co/Comfy-Org/MiniMax-H3），提供桌面用户所需的目录结构与量化变体。

**模型选择：**

- **FL2VA**：文生视频或首/尾帧控制。
- **Ref2VA**：需要参考图像、视频、音频或续写时。
- 两者**共用同一 text encoder 和 VAEs**。

**体积与显存：**

- 最小的实用官方 ComfyUI 组合约 **42.5 GB 磁盘空间**：一个剪枝 int8 DiT、一个 NVFP4 文本编码器、两个 VAE。
- 它仍可在 **12 GB GPU** 上运行，因为 text encoder、DiT、VAE 是**在不同阶段分别加载**的。

### C3. Set up ComfyUI

前置：量化 ComfyUI checkpoint 需 **r580 分支或更新**的 NVIDIA 驱动，并安装 **PyTorch CUDA 13.0 wheels**。

```shell
git clone https://github.com/comfyanonymous/ComfyUI
cd ComfyUI
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu130
pip install -r requirements.txt
```

1. 从 ComfyUI 仓库下载 1 个 DiT、1 个 text encoder 和 2 个 VAE，放入 `ComfyUI/models` 下对应文件夹。
2. 打开 **Workflow → Browse Templates → Video → MiniMax H3**，选择与生成模式对应的模板，填入提示词与条件媒体，排队任务。
3. 官方教程（含各工作流截图）：https://docs.comfy.org/tutorials/video/minimax/minimax-h3

**常见性能错误（原文三条）：**

- 最常见的性能失误是使用 **PyTorch cu128**；量化 kernel 需要 **CUDA runtime 13.0 或更高**。
- 用 cu128 时 ComfyUI 可能**静默回退到普通 PyTorch 算子**：生成仍能工作，但可能**慢数倍**。
- 应检查启动日志，确认量化后端（quantization backend）已启用。

### C4. Keep optimization simple

- H3 运行时大部分时间花在 **DiT 去噪循环（denoising loop）** 上。先从效果最明确的改动开始：
  - **先验证 kernel**：正确的 CUDA wheels 与可用的编译 attention 后端，比微调细枝末节更重要。
  - **加入 SageAttention**：社区报告去噪循环约 **1.5–2×** 提升，取决于 GPU 与 build。
  - **在合适时使用 8-step Turbo LoRA**：显著缩短常规采样调度；剪枝模型需搭配**剪枝转换**的 LoRA；对音频关键的工作保留完整步数路径。
  - **生成更少像素**：草稿约 **0.5–0.8 megapixels**，确认满意后再跑一次昂贵的精修（finishing）通道。
- 缓存、稀疏注意力、Sol Engine 移植以及更激进的量化可进一步提速，但会带来**质量与兼容性取舍**。
- 完整硬件与优化指南：https://vrfi1sk8a0.feishu.cn/docx/VJA3dLNNpo2gnDxkKfFcaCXbnTf（抓取无正文，需登录）

### C5. Recommended: Context-IR → local H3 → Regenerate-2K

```
H3-Context-IR (hosted) → H3-Base at 768p (local) → H3-Regenerate-2K (hosted)
```

- 该安排让 Context-IR 获得完整提示词与多模态上下文；草稿生成与迭代留在本地硬件；只对要完成的那条 take 使用 Regenerate-2K。
- **Context-IR 与 Regenerate-2K 是托管服务，其底层实现并非开源。**

**四步：**

1. **准备提示词**：把原始提示词与所有模式相关的条件媒体发送给 H3-Context-IR（https://platform.minimax.io/docs/api-reference/video-generation-v2-h3-context-ir）。保留其返回的完整增强提示词。
2. **本地生成**：把该完整提示词与相同的条件媒体交给本地 H3-Base。文生视频或首/尾帧用 **FL2VA**；参考生成用 **Ref2VA**。在本地生成并审阅 768p 草稿。
3. **重生成选定的 take**：将**未经改动**的 MP4 上传到短时有效的 HTTPS 位置。向 H3-Regenerate-2K（https://platform.minimax.io/docs/api-reference/video-generation-v2-regeneration）发送相同的增强提示词、相同的条件输入，以及**恰好一个**角色为 `base_video` 的视频。
4. **取回结果**：两个托管 API 都是**异步**的，需轮询任务直到成功或到达终态失败。

**Important handoff rule（交接规则）：**

- Context-IR **补充**条件媒体，而非替代它们。
- 重生成时**不要**切回原始提示词。
- **不要**对本地视频使用 `source_task_id`。
- **不要**裁剪、缩放、更改帧率、移除音频或对 768p 草稿进行重度重新压缩。

**数据边界**：该工作流会把选定的条件媒体发给 Context-IR，然后把最终提示词、条件媒体与本地草稿发给 Regenerate-2K。使用敏感素材前须考虑**云数据边界、API 成本与留存（retention）要求**。

> 完整混合实现指南（含请求 payload 与对比示例）：https://vrfi1sk8a0.feishu.cn/docx/O6Aid7HxloyFRSxi9Nic2DDwnng（抓取无正文，需登录）

### C6. When should you stay fully local?

- 当**隐私、离线运行、可复现性或零边际 API 成本**最重要时，保持完全本地。
- 可用 **latent upscaler** 做模型感知的二次处理，或用 **pixel upscaler** 做更快的收尾。

**重要澄清（原文中文版）**：MiniMax 把 Regenerate-2K 描述为**基于模型的重新生成**，而**不是普通的像素放大**——它会把**已确认的 H3 草稿和原始生成上下文重新送入模型**，执行**更高分辨率的第二遍生成**。所以它不是你用本地放大器能等价替代的一步。

### C7. Next steps 后续步骤（原文）

- 先按 **ComfyUI 官方教程**把本地链路跑通：https://docs.comfy.org/tutorials/video/minimax/minimax-h3
- 再照官方**提示词编写指南**把提示词写规范，然后才走混合流程：
  - 基础模式：`VIDEO_PROMPT_WRITING_GUIDE_base_en.md`
  - 参考模式：`VIDEO_PROMPT_WRITING_GUIDE_ref_en.md`
  - （两份均在官方 GitHub 仓库内：https://github.com/MiniMax-AI/MiniMax-H3）
- 文档同时给出了面向 16 GB 级设备的实测笔记与合并后的中文完整版说明。

---

## 附录 D｜文档 4《H3 开源生态速查表 · Ecosystem Cheat Sheet》

链接：https://my.feishu.cn/wiki/AffJwqcYXiwEuTkyjHWccO98nof ｜修改：8/18

### D1. Hardware Cheat Sheet 硬件速查（全表，含原文链接）

| Machine | Download / tool | Expect |
|---|---|---|
| **5–8 GB NVIDIA** | [WanGP](https://github.com/deepbeepmeep/Wan2GP)（5-sec clips on 5–6 GB）或 [DiffSynth NF4](https://huggingface.co/DiffSynth-Studio/MiniMax-H3-NF4)（8 G 起） | Works, be patient（能跑，要耐心） |
| **RTX 3060 12G** | [pruned int8 21G](https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/diffusion_models) + [nvfp4 TE 15.7G](https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/text_encoders) + [VAE 5.8G](https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/vae)；[ready workflows](https://github.com/tlano-z/ComfyUI-MiniMax-H3-Workflows-For3060) | 5s@480p ≈ **15 min**（untuned 未调优） |
| **12–16 G（4070 / 5070Ti / 5080）** | [pruned fp8（40 系原生）/ pruned int8](https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/diffusion_models)；[16G measured notes](https://github.com/Tomiigo/minimax-h3-16gb) | **3–5 min/clip**（tuned 调优后） |
| **24 G（3090 / 4090）** | [int8 34G](https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/diffusion_models) + int8 TE；[3090 15-sec recipe](https://github.com/tonyd2wild/minimax-h3-local) | 4090 tuned 5s ≈ **70–86 s**；3090 ≈ **135 s** |
| **RTX 5090 32G** | [pruned fp8](https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/diffusion_models) 或 [community NVFP4（50 系专属）](https://huggingface.co/DmitryDB/MiniMax-H3-ComfyUI-Quants) | 5s@0.4MP ≈ **50 s**；[Sol Engine **4.52×**](https://nvlabs.github.io/Sana/Sol-Engine/H3-OnDevice/) |
| **48–96 G workstation 专业卡** | [int8 / bf16](https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/diffusion_models)；[RTX Pro 6000 单卡实践（中文）](https://github.com/eric8810/minimax-h3-deploy) | 1080p possible but slow（可 1080p 但慢，**H100 ≈10 min/5s**） |
| **DGX Spark** | pruned int8 + nvfp4 TE；copy the [tuning repo](https://github.com/drowzeys/keys-heretic-MiniMax-H3-sol-engine-more-speed-upgrades-upscaler-finish-Single-DGX-Spark) · [SM121 recipe](https://github.com/joeynyc/MiniMax-H3-DGX-Spark) | 10s ≈ **3.5–10 min**；Sol **3.92×**；[双机协同出一条片](https://github.com/joeynyc/MiniMax-H3-2x-DGX-Spark) |
| **Mac 16–32G / 128G+** | 16G：[NF4（experimental）](https://huggingface.co/DiffSynth-Studio/MiniMax-H3-NF4)；128G+：[MLX 8bit 69.3G](https://huggingface.co/ddalcu/MiniMax-H3-FL2VA-MLX-Serve-8bit)（[Ref2VA 版](https://huggingface.co/ddalcu/MiniMax-H3-REF2VA-MLX-Serve-8bit)）· [RunH3onMac guide](https://github.com/HeyZhey/RunH3onMac) | M3 Ultra：15s ≈ **39 min**（offline 全离线） |
| **AMD** | Instinct：[SGLang official ROCm](https://docs.sglang.io/docs/sglang-diffusion/installation)；consumer cards 消费卡靠社区补丁 | Early but real（早期但真实） |
| **Multi-GPU server 多卡** | [vLLM-Omni](https://recipes.vllm.ai/MiniMaxAI/MiniMax-H3) / [SGLang](https://github.com/sgl-project/sglang) | 4×B300：8.7s clip ≈ **87 s** end-to-end |

### D2. Ecosystem Master Table 开源生态大表（原文全表，含 ⭐/❤ 计数）

**🏛 Official 官方**

| Project | What it does（EN / 中文） |
|---|---|
| [MiniMax-AI/MiniMax-H3](https://github.com/MiniMax-AI/MiniMax-H3) ⭐867 | The official repository: code, 9 agent skills, deployment-validation scripts, architecture notes, releases / 官方仓库：代码、9 个官方技能包、部署校验脚本、架构说明与版本发布；所有工具的上游 |

**⚡ Speed 加速**

| Project | What it does |
|---|---|
| [Turbo LoRA](https://huggingface.co/larryvrh/MiniMax-H3-Turbo-Lora)（❤349）+ [sampler node](https://github.com/Larryvrh/ComfyUI-MiniMax-H3-Turbo) ⭐204 | Distilled "speed plugin": **8 steps instead of 20**, real time roughly halves; the bundled sampler keeps audio from crackling; pruned models need the [converted files](https://huggingface.co/drbaph/MiniMax-H3-Turbo-Lora-ComfyUI)（❤153）/ 蒸馏加速插件：20 步 → 8 步，实际耗时约减半；配套采样器防音频破音；pruned 模型要用转换版 |
| [Sol Engine (NVIDIA)](https://nvlabs.github.io/Sana/Sol-Engine/H3-OnDevice/) | NVIDIA's full speed package: **4.5× on 5090, 3.9× on Spark**, near-lossless / NVIDIA 官方整套加速：5090 快 4.5 倍、Spark 3.9 倍，画质几乎无差 |
| [ComfyUI-sol-attn](https://github.com/Saganaki22/ComfyUI-sol-attn) ⭐44 · [SolAttn_triton](https://github.com/kijai/ComfyUI-SolAttn_triton) | Skip unimportant attention math: **+20–30% over SageAttention, −37% peak VRAM**（5090-tested）；the Kijai port trades speed for big VRAM savings / 跳过不重要的注意力计算：比 SageAttention 再快 20–30%、显存峰值省 37%；Kijai 版主打省显存 |
| **Cache family 缓存系**：[Blockcache-T8](https://github.com/T8mars/comfyui-minimax-h3-blockcache-T8) ⭐61 · [FirstBlockCache](https://github.com/duckyshell/ComfyUI-MiniMaxH3-FirstBlockCache) ⭐23 · [H3-Cache](https://github.com/lihaoyun6/ComfyUI-MiniMaxH3-Cache) ⭐68 · [TE-Speed](https://github.com/HELPMEEADICE/TE-Speed-MiniMaxH3-OSS) ⭐169 · [Spectrum](https://github.com/xmarre/ComfyUI-Spectrum-MiniMax-H3) ⭐330 | "Lazy" acceleration: skip repeated math when frames barely change（**30–45% claims**）；Spectrum predicts steps mathematically — **lossy, A/B first**. **Don't multiply the claimed gains; never cache in Ref2VA** / "偷懒式"加速：画面变化小就跳过重复计算（宣称 30–45%）；Spectrum 用数学猜步数，有损先对比。**倍数不能相乘；参照模式别开缓存** |

**📦 Smaller files 量化**

| Project | What it does |
|---|---|
| **GGUF**：[Abiray](https://huggingface.co/Abiray/MiniMax-H3-GGUF)（196k dl）· [vantagewithai](https://huggingface.co/vantagewithai/MiniMax-H3-comfyUI-GGUF) · [realrebelai](https://huggingface.co/realrebelai/MiniMax-H3_GGUFs)（❤162） | Pick your compression（lower Q = smaller, worse）；**Q3_K_M 15.6G is the practical floor** / 压缩档任选（Q 越小文件越小画质越低）；**Q3_K_M 15.6G 是实用下限** |
| **4-bit**：[DmitryDB](https://huggingface.co/DmitryDB/MiniMax-H3-ComfyUI-Quants)（min 9.7G）· [rockerBOO NVFP4](https://huggingface.co/rockerBOO/minimax-h3-nvfp4) · [Abiray 合集](https://huggingface.co/Abiray/Minimax-H3-nvfp4-INT4-INT8-Convrot)（452k dl ❤114） | Extreme compression, **loads in stock ComfyUI** / 极限压缩，ComfyUI 直接能读不用改代码 |
| [TAE preview](https://huggingface.co/Kijai/MiniMax-H3-TAE)（10MB，❤85）· [Kijai experimental](https://huggingface.co/Kijai/MiniMax-H3-experimental)（❤91） | Watch the picture form mid-render；experimental **W4A8** quant lab / 生成中实时看片雏形；W4A8 实验量化 |

**🖥 Serving 服务化**

| Project | What it does |
|---|---|
| [vLLM-Omni recipe](https://recipes.vllm.ai/MiniMaxAI/MiniMax-H3) · [SGLang Diffusion](https://github.com/sgl-project/sglang) · [LightX2V](https://github.com/ModelTC/LightX2V) · [WanGP](https://github.com/deepbeepmeep/Wan2GP)（117k dl） | OpenAI-format serving（vLLM）；widest hardware incl. **AMD/Mac/Ascend**（SGLang）；third stack with a [prompt-rewriter LoRA](https://huggingface.co/lightx2v/MiniMax-H3-Prompt-Rewriter-LoRA)（❤21）；extreme low-VRAM GUI / OpenAI 兼容接口（vLLM）；硬件覆盖最杂含 AMD/Mac/昇腾（SGLang）；第三栈附提示词改写模型；极限低显存 GUI |

**🎬 Creation 创作**

| Project | What it does |
|---|---|
| [Motion-Context](https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context) | **Long videos**: next clip continues the last clip's motion and the very same audio waveform — chain into long pieces / 拍长视频：下一段接着上一段的动作和"同一段声音"继续，可接龙成长片 |
| **Directors 导演台**：[huangserva](https://github.com/huangserva/ComfyUI_MiniMaxH3_Director) ⭐301 · [AIMixer](https://github.com/AIMixer/ComfyUI_MiniMaxH3_Director) ⭐151（多段+场景检测+v2v）· [seesee75](https://github.com/seesee75-commits/ComfyUI-MiniMaxH3-Director) ⭐143（时间线） | Editing-suite style: tracks, per-shot prompts, live preview, retakes; AIMixer adds auto scene-split（PySceneDetect）and video-to-video / 剪辑软件式：轨道、逐镜头提示词、实时预览、重拍；AIMixer 版带自动分镜和视频改视频 |
| [audio-T8](https://github.com/T8mars/comfyui-minimax-h3-audio-T8) ⭐199 | **14-node audio suite**: AV conditioning, audio post, stable dual-clock sampling, Ref2VA still-image editing / 14 节点音频套件：音画条件、音频后处理、稳定双时钟采样、参照静态图编辑 |
| [MiniMaxH3-Easy](https://github.com/nkxx188/ComfyUI-MiniMaxH3-Easy) ⭐137 · [Multishot workflow](https://github.com/jlucasmcrell/ComfyUI-H3-Multishot)（❤38）· [joeygambino 版](https://huggingface.co/joeygambino/MiniMax-H3-Multishot-Workflow) | Every mode in one graph（**beginners: install this**）；one script → N seamless shots / 一张图搞定全部玩法（**新手首选**）；一份脚本连拍 N 镜无缝拼接 |
| **Upscale 放大**：[LatentUpscaler](https://github.com/Tr1dae/ComfyUI-MiniMaxH3_LatentUpscaler) · [Video Tiler](https://github.com/maDcaDDie2000/comfyui-video-tiler) | Generate small → refine large inside the model（faces stay intact in reference mode）；tile-based upscaling for small VRAM / 先小图生成再模型内放大精修（参照模式人脸不变形）；小显存分块放大 |
| **Image mode 图像玩法**：[SingleFrame](https://github.com/tori29umai0123/ComfyUI-MiniMaxH3-SingleFrame) · [Image Studio](https://github.com/astropuzzo/ComfyUI-MiniMax-H3-Image-Studio) ⭐18 · [Pseudo-T2I](https://github.com/tebasaki-oniku/ComfyUI-MiniMax-H3-Pseudo-T2I-Workflows) | Use the video model as an image generator/editor（**1248² in ~21s on a 5090；up to ~8000×8000**）/ 把视频模型当修图工具：只出一帧（5090 一张约 21 秒；最大约 8000²） |

**✍️ Prompts 提示词**

| Project | What it does |
|---|---|
| [Official skills ×9](https://github.com/MiniMax-AI/MiniMax-H3) | One command（`npx skills add … --skill h3-prompt-writing`）teaches Claude/Codex-type assistants to write spec-compliant prompts / 一条命令装进 AI 助手，按官方规范写提示词 |
| [awesome-h3-prompts](https://github.com/BeatAPI/awesome-minimax-h3-prompts) ⭐65 · [Promptor](https://github.com/1038lab/ComfyUI-MiniMax-H3-Promptor) ⭐95 · [H3-Guide](https://github.com/ethanfel/ComfyUI-MiniMax-H3-Guide) ⭐84 · [AgentSkill](https://github.com/benjiyaya/Minimax-H3-Prompt-AgentSkill) ⭐42 | Curated prompt gallery with video examples, by use case；cinema-grade prompt automation；guide-rule checking；agent skill variants / 带视频示例的分场景 prompt 大全；电影级提示词自动化；官方指南校验；技能包变体 |

**🧬 Training 训练**

| Project | What it does |
|---|---|
| [MiniMax-H3-FineTuning](https://github.com/IAmIronMan42/MiniMax-H3-FineTuning) ⭐160 | **First working community fine-tuning trainer**（~150-line rectified-flow trainer on official Diffusers + latent caching；documents **4 numeric traps that silently corrupt weights**）/ 社区第一个能用的微调训练器（基于官方 Diffusers，附踩坑文档 FIXES.md） |
| [AI-Toolkit](https://github.com/ostris/ai-toolkit) · [distill adapter](https://huggingface.co/ostris/minimax_h3_training_adapter) | The most mature consumer LoRA path（characters, styles）；its distillation training adapter is now the H3 default / 最成熟的 LoRA 训练链路，蒸馏训练适配器已设为默认 |

**🤖 Agents**

| Project | What it does |
|---|---|
| [wan2gp-mcp](https://github.com/Franzferdinan51/wan2gp-mcp) · [Codex-Drama](https://github.com/chiphoton/MiniMax-H3-Codex-Drama) · [SimpleLocalMediaAgent](https://github.com/Bamzzo/SimpleLocalMediaAgent) | Local H3 as an assistant-callable tool（**MCP**）；full production plugin（characters→storyboard→shots）；idea-to-film LangGraph pipeline / 本地 H3 变成 AI 助手可调用的工具；全流程制片插件；创意到成片流水线 |

**🚀 Deploy 部署**

| Project | What it does |
|---|---|
| [Windows 一键安装](https://github.com/dudulu2/MiniMaxH3-Installer) · [VideoAir（weight streaming）](https://github.com/Yi-111-a/VideoAir-MiniMax-H3-LowVRAM) · [RunPod template](https://github.com/Hearmeman24/comfyui-minimax) · [headless/Slurm](https://github.com/Playitcooool/minimax-h3-headless) · [MLX port](https://github.com/PipeNetwork/minimax-h3-mlx) ⭐32 · [Swift MLX](https://github.com/VincentGourbin/minimax-h3-swift-mlx) | One-click installs, cloud templates, no-GUI servers, Apple-native ports / 一键包、云模板、无界面服务器、Mac 原生移植 |

**🛰 Studios 工作台**

| Project | What it does |
|---|---|
| [Inline-Studio](https://github.com/inlineresearch/Inline-Studio) ⭐193 · [open-video](https://github.com/open-video-ai/open-video) · [web frontend](https://github.com/TheTerrasque/minimax-h3-frontend) · [multi-user webui](https://github.com/BobH233/minimax_h3_webui) · [一页式创作台](https://github.com/Langzaigg/minimax-h3-onepage-studio) | Node-canvas filmmaking app（local GPU + LoRA training, versioned takes）；"**Ollama for video**"；web dashboards for teams / 节点画布式制片应用（本地 GPU + LoRA 训练 + 版本化重拍）；视频界 Ollama；团队网页操作台 |

**🧪 Fun 脑洞**

| Project | What it does |
|---|---|
| [ds4-h3 factory](https://github.com/tonyd2wild/ds4-h3-video-gen-factory) ⭐14 · [2×Spark 协同](https://github.com/joeynyc/MiniMax-H3-2x-DGX-Spark) ⭐28 · [GB10 并发](https://github.com/3e3dev/MiniMax-H3-FP8-Concurrent-Gen-GB10) · [turbo-eval 对比图集](https://github.com/jo-nike/h3-turbo-eval) · [hybrid-cond](https://github.com/kitsune123150/minimax-h3-hybrid-cond) ⭐28 | Two-Spark home studio（DeepSeek directs, H3 renders）；one video generated cooperatively across two machines；concurrent dual-prompt tricks；speed-vs-quality evidence grids / 双 Spark 家用制片厂；两台机器协同出一条片；单机双任务；加速代价对比图集 |

---

## 附录 E｜文档 5《MiniMax Design - 手册与指南》

链接：https://my.feishu.cn/wiki/VEoVwpfCKiTHvHkAGQ7cQJxCncf ｜最近修改：9/17 22:36

### E1. 官网地址（原文）

> 注意，海外 or 国内版是**两个不同的账号，不联通**。

- 国内版：https://design.minimax.cn/
- 海外版：https://design.minimax.io/

### E2. 产品更新公告：MiniMax Design v3.0.16

**🎬 模型与 Agent**

- 新增 **Wan 3.0** 模型，年卡会员继续享受 **8 折**生成优惠。
- Agent 支持**自定义模型**，可接入自己的模型，无缝融入现有工作流。

**🎨 创作体验优化**

- 画布节点新增**对齐参考线和自动吸附**，布局调整更方便。
- 提示词**可直接引用项目中的资产和主体**，方便基于已有内容继续创作。
- 剪辑完成后，可将视频或音频**导出到画布或本地**，也可直接让 Agent 完成导出。

**🛠️ 体验优化与问题修复**

- Windows 支持自定义关闭方式：**隐藏到托盘或退出应用**。
- 修复调色时图片上下颠倒、素材引用覆盖后续文字、浏览器插件语言未跟随应用设置等问题。
- 修复安装失败、无法退出等问题。

**补充说明**

- 若在线更新失败，可前往官网下载最新版本并手动安装。
- 超高性价比——年卡会员额外享有 **1 年 8 折生成优惠**。

**【往期更新】⬇️**：原文此处**无具体内容展开**。

### E3. MiniMax Design 介绍（原文逐字）

> 🪄 MiniMax Design 是由 **AI Agent 驱动的商业内容生产平台**，将多模态模型能力转化为真实可用的生产力。
>
> Design 的核心优势，是**理解、拆解并执行商业内容生产任务**。用户只需表达创作目标，Design Agent 就能规划任务、扩展 Prompt、选择合适的 Skill 与工具、调用适配模型，并组织素材、持续修改，推动内容从想法走向交付。

### E4. 文档完整目录（四大板块 + 三个专项）

```
📢 产品更新公告
📖 MiniMax Design 介绍
   💫 亮点与能力 / 🎨 内容指南 / 🎬 视频案例速览
🧩 第一部分：快速入门
   1.1 认识创作界面 / 1.2 基础创作过程 / 1.3 导出、资产与项目管理
🎥 第二部分：实战商用案例
   🔥 适配 H3 的精选 Skill 与模版
   🎉 制作热销级「电商产品短视频」
   🛍️ 活人感「KOC 社媒投流广告」（中英）
   🌿 批量生产「KOC 推广、测评与种草视频」
   📱 灵感 + 界面图，生成「产品社媒广告」
   📘 制作「手绘漫画风格知识科普视频」（如抹茶工艺科普）
   🌍 全球化「多语言本地化广告」
   👾 全程完成「风格化动画 PV」
   🏃 H3 美学应用「特效包装 - AR 短片为例」
🚀 第三部分：进阶创作过程
   4.1 沉淀 Skill 与分享 / 4.2 精品插件：3D 导演台与 AI 剪辑
   4.3 Agent 编辑剪辑、导演台 / 4.4 精品工具：多角度、多宫格分镜、打光、水印等
🛠️ 第四部分：开源模型与本地化部署（Beta）
   H3 部署完整教程 ⬇️ / 基础介绍 / 基础使用步骤 / 补充帮助：商业内容制作
🙋 常见问题 Q&A
   Q：如何写好需求？ / Q：如何有效修改 / Q：商业内容质量检查 / 其他问题
💎 MiniMax Design 会员/积分订阅 ｜ MiniMax Design 团队版
```

### E5. 第一部分 快速入门（原文要点）

**1.1 认识创作界面（四分区）**

| 区域 | 说明 |
|---|---|
| Agent 对话与任务区（右侧） | 可和 Agent 对话、在画布上创作。Design 已接入**十多款顶尖模型**，Agent 根据任务自动匹配最优选项，也可手动切换 |
| 画布 + 内容预览与编辑区（中间） | 由 Agent 与你共同制作的内容（含上传文件）都会显示在画布上，并**自动按流程连线、展示步骤节点** |
| Skill 广场 + 模板中心 + 专业插件（左侧） | 既有 Design 精选的 Skills 与插件，也有创作者分享的技能与工作流 |
| 项目管理 + 本地资产库（左侧） | 资产中心可上传本地文件，**沉淀可复用的角色、场景、风格包、道具**等素材，在新项目里快速调用 |

**1.2 基础创作过程 · 四种开始方式**

| 方式 | 适合谁 / 怎么用 |
|---|---|
| 方法一：直接描述目标 | 适合已经知道自己想做什么的用户。示例：`为一款无线耳机制作一条 15 秒竖屏广告，突出轻便和降噪，风格简洁、有科技感。` |
| 方法二：从 Skill 开始 | 适合有明确任务、但不知道具体流程的用户 |
| 方法三：从提示词模板开始 | 不会写提示词、或觉得专业提示词太长太复杂时，用模板得到接近专业长提示词的效果：在**模板广场**找到模板 → 点「使用提示词」→ 按产品/场景/风格改 → 生成 |
| 方法四：导入已有素材或项目 | 适合希望继续编辑本地图片、视频、音频、3D 资产或历史项目的用户；**支持 Zip 导入** |

**什么是 Skill？** Skill 不是单个功能，而是**针对具体任务组织好的执行流程**。它可以是行业规范与标准（如短剧制作的完整流水线：剧本 → 分镜 → 角色与场景 → 图生视频 → 配音配乐 → 合成输出），也可以是创作偏好与审美准则（如"品牌视觉风格偏简洁、少文字"）。

**如何使用 Skill（原文给出三种路径，标题编号有重复）**

1. **在广场直接试用**：在 Skill 广场或「我的技能」中选中 Skill，点「去对话中试试」。
2. **快捷键调用**：在对话框输入 `/`，选择想要的 Skill，明确告诉 Agent 用哪个，再跟着引导操作。
3. **直接和 Agent 询问匹配**：如"我要做一个 KOC 视频，请帮我调用相应的 skill 完成"，Agent 就会调用「KOC 视频」技能。
4. **Agent 自动调用**：对已开启的 Skill，Agent 会根据对话内容自动判断该用哪个（如开启「海报设计」后，涉及海报任务时自动调用并写好提示词，无需手动触发）。

> 💡 所有下载保存的 Skill 都会存在「我的工具」里，用时可直接看到全部。

**1.3 导出、资产与项目管理**

- **存储与导出**：画布上所有素材**默认储存于本地**，同时可重新下载。
- **资产中心**：创作过程中沉淀的角色、场景、风格包、道具、某步过程等素材都可保存到资产中心（**右键即可看到相应选项**），在任何新项目里快速调取复用。
- **项目管理**：左侧项目栏创建、整合和管理；详见《MiniMax Design 项目库说明》。
- **通用制作流程**（Agent 会根据需求调整细化）：`商业目标 → 准备素材 → 选择 Skill/模板（自选） → 输入需求 → Agent 规划 → 执行与修改 → 最终效果 → 可复用方法`

### E6. 第二部分 实战商用案例（可复用模板与关键步骤）

**🔥 精选 Skill 与模版**：Design 开设了专门的**「Skill 与模版广场」**，提供适配 H3 的精选 Skill 与模版，覆盖广告、电商、品牌、营销、创意后期等商用场景；**开始创作前建议先浏览左侧 Skill 区**找匹配工具。

**可复用提示词模板公式（原文）**

- 电商产品图：`为一款面向【目标人群】的【产品】制作一组【图片数量与画幅】电商产品图，重点突出【核心卖点】，并结合【使用场景/展示方式】呈现产品。整体采用【视觉风格】，用于【电商平台或投放渠道】，画面中需要包含【品牌元素、产品文案或促销信息】。`
- 知识科普视频：`为面向【目标受众】的【知识主题】制作一条【时长】×【画幅】的【视频类型】，用【创意 Hook】引出【核心知识点与讲解逻辑】。整体风格为【内容风格】，使用【目标语言】，用于【投放平台与地区】。`

**案例拆解（原文关键步骤摘录）**

| 案例 | 关键做法 |
|---|---|
| 🛍️ 批量 KOC 推广/测评/种草 | ① Design 读取 KOC 制作规范并把附件 4 条案例整理成**可执行流程**（每条明确开场、人物、场景、逐字口播、分镜），产出 4 条可分别测试的版本；② 建立**人物锚 + 产品锚**（各 4 张，锁长相/环境/外观/展示关系，避免漂移）；③ 每组"人物锚 + 产品锚 + 脚本分镜"合成独立成片，统一 15 秒竖屏但在气质/场景/开场上差异化；④ 最终输出 4 条可投放、可 A/B、可达人验证的成片 |
| 🎉 电商产品短视频（耳机） | ① Agent 加载电商视频技能并确认参数：**15 秒、9:16 竖屏、极简白底/高保真 UI**、核心动作（点选色块/耳机变色/点击加购）、结尾（Logo + CTA），生成制作简报；② 生成首帧 UI 图与手部姿态参考图，锁定黑白两款耳机资产，预生成 Logo 与 CTA 矢量素材；③ 分段生成三段视频，用户反馈"穿模、反馈弱"后，Agent 调整手部锚点、增加颜色渐变过渡、按钮回弹与购物车跳动特效后重生成；④ 无缝拼接 + 极简背景柔和光影 + 结尾品牌 Logo 与呼吸灯效 CTA |
| 📘 手绘漫画风知识科普（抹茶） | ① 把模糊需求拆解为标准流程，多轮确认讲法（案例观察型）、时长（30 秒）、风格（手账插画）、旁白（女声/亲和教师）、画幅（16:9）；② 生成 5 张手账插画分镜；③ 反馈"没有动画感"→ 在提示词里补**翻页、漂移、流动箭头、粒子特效、镜头推进**；④ 指出"不合逻辑"→ Agent 自查 5 段视频，定位问题（干燥被画成晒干、去梗缺少去叶脉、筛选工序顺序错误）并按正确工序重做；⑤ 5 段无缝拼接成 30 秒成片 |
| 👾 风格化动画 PV / 特效包装（实验短片） | ① 解析参考视频的视觉结构（开场街景、人物动态方向、转场、图形风格、节奏卡点）+ 从人物图提取特征，确认 16:9、人物锁定、图形风格、英文文案由 Agent 生成；② 生成 3 个实验风英文短文案候选，产出三张 16:9 独立锚定照片（**避免四宫格拼贴干扰生成**）；③ 多 Skill 协同：**TVC 技能**规划叙事节奏与镜头语言、**品牌技能**锁定图形规范与调性、**Film Assets 技能**用图一锁身份、图二锁服装，生成正/侧/背三视图保持人物一致；④ 分段生成后拼接 |
| 🌍 多语言本地化广告 / 📱 产品社媒广告 / 🏃 AR 短片 | 均由 Agent 加载对应技能（如多语言、界面图 + 灵感图、AR 特效包装）确认参数 → 生成锚定素材 → 分段生成 → 拼接成片 |

**⚠️ 风险规避实例（原文）**：当提示词包含"蛛丝""模拟参考视频运镜"等**高风险表述**时，Agent 会自动加载提示词优化技能，识别 **IP 联想风险、版权复刻风险、动作过载风险**并给出安全改写：`蛛丝 → 细白色弹力绳`；`模拟参考视频运镜 → 快速横向跟拍、卡点闪切、平面空间穿梭感`；同时把复杂动作**拆成多段独立生成**以提高成功率。

### E7. 第三部分 进阶创作

**4.1 沉淀 Skill 与分享**

- **自定义 Skill 的四种方式**：
  1. 直接说需求让 Agent 做（如"我想做一个品牌宣传短片 skill"），最后检查保存。
  2. 先创作，再把过程存成 Skill（输入 `/skill-creator` 或说"把当前对话总结成 Skill"）。
  3. 修改已有 Skill：使用中随时叫停调整，满意后说"保存为我自己的 Skill"。
  4. 上传已有资料（经验文档、笔记或其他 `SKILL.md` 文件）让 Agent 生成。
- **分享 Skill 到社区**：进入「My Skills」→ 找到目标 Skill 进详情页 → 点右下角「投稿到社区」→ 完善投稿信息提交 → 等待官方审核；**审核通过后可能获得积分奖励**，并有机会展示在「用户精选」中。

**4.2 / 4.3 精品插件与 Agent 编辑**

- 入口：任意画布 → 添加节点 → 导演台/视频剪辑节点 → 点节点中的「打开导演台/视频剪辑」→ 用自然语言描述需求 → Agent 修改 → 点「导出」把产物导出到画布继续后续流程。
- **3D 导演台**：精准操控镜头、可多人；在 3D 场景中摆放角色素体、调度机位与姿态，快速搭建分镜参考。
- **视频剪辑**：支持自动剪辑与字幕生成——添加/修改字幕（内容、时间、位置）、添加转场/滤镜/贴纸、裁剪拼接与顺序调整、调整画面比例与布局。

**4.4 精品工具（Tools）**

| 工具 | 能力（原文） |
|---|---|
| 全景图预览 | belike 世界模型，360° 固定；交互式预览全景图，支持拖拽环视、滚轮缩放与自动旋转 |
| 重打光 | 输入图片或视频，快速生成不同灯光氛围与电影级打光效果 |
| 多角度 | 基于同一主体自动生成不同镜头与机位角度 |
| 水印工具 | 为图片与视频批量添加水印、Logo 与版权信息 |
| 多宫格分镜 | 生成多宫格分镜（与其他工具并列在节点 Toolbar 内调用） |

### E8. 第四部分 开源模型与本地化部署（Beta）

- Design 基于 MiniMax H3 开源模型，**开放本地部署与 ComfyUI 工作流能力**：可在自己设备上运行部分视频生成流程，并把 H3 能力接入 Design 的画布与 Agent 流程。
- 已配备多套**「官方精选工作流」**，覆盖**文生视频、首尾帧、多参考、超清、扩写、人像增强**等能力；按电脑配置/需求/成本偏好选**轻量版**或**满血版**（含官方超清、扩写等增强能力）。轻量版适合快速体验与普通设备；满血版效果更完整但对**显存、内存与本地存储**要求更高。
- **积分说明（原文）**：**部分工作流可以完全在本地运行，不产生额外生成消耗**；如果使用**官方超清、扩写等云端服务，则可能产生相应积分消耗**。下载工作流时系统会根据本机配置给出**推荐方案**（推荐仅供参考，不代表其他版本无法运行，只是流畅度、稳定性与最终效果可能受影响）。
- **安装使用五步**：① 选择工作流（可查看适用场景、输入要求、配置建议、局限性、依赖文件、来源与许可）→ ② 下载并管理（进入「我的工作流」）→ ③ 在画布中运行（Design 创建对应 ComfyUI 工作流节点，普通用户改提示词传素材即可，懂 ComfyUI 的可展开自定义节点）→ ④ 与画布和 Agent 联动（上游素材可作输入，生成结果可继续编辑/包装；Agent 能识别工作流并帮你调用）→ ⑤ 导入社区工作流或新建空白工作流（适合专业用户与开发者）。
- **完整教程站**（含操作录屏、步骤说明、工作流详情、依赖与许可信息、官方交流群入口）：https://design.minimaxi.com/ （教程页与交流群入口在文档内以链接形式给出）

### E9. 商业内容 Q&A（原文）

- **核心原则**：在 Design 中写好需求的关键是**从「描述画面」升级为「表达商业目标」**；可配合相应 Skill 让 Agent 更好理解需求。
- **推荐反馈公式**：`保留什么 + 修改什么 + 为什么 + 期望结果`
- **商业内容质量检查清单（9 项）**：① 商业目标是否明确 ② 前三秒是否有效 ③ 核心卖点是否突出 ④ 产品信息是否准确 ⑤ 品牌视觉是否统一 ⑥ 文字和字幕是否正确 ⑦ 节奏是否适合渠道 ⑧ 输出规格是否符合要求

### E10. 会员 / 积分订阅与团队版

- 订阅页（国内）：https://design.minimaxi.com/media-plan/subscribe
- 订阅页（海外）：https://design.minimax.io/media-plan/subscribe
- 活动页：国内 https://design.minimaxi.com/campaign ｜海外 https://design.minimax.io/campaign
- **团队版**（Team Account）：面向企业用户的账号体系，① 创建团队、管理成员；② 购买**团队积分，积分池成员共享**，每个成员可单独配置积分额度；③ 创建团队项目、资源共享（**开发中**）。

### E11. 评论区置顶：Windows 卸载/升级异常修复脚本（原文）

> 场景：卸载或升级 MiniMax Design 时出错、快捷方式残留、程序无法彻底清除。原文给出的 PowerShell 片段（抓取时有 1～2 行快捷方式目录条目被折叠，按原样补全即可）：

```powershell
$f=@(
  [Environment]::GetFolderPath('Desktop'),
  [Environment]::GetFolderPath('Programs'),
  [Environment]::GetFolderPath('Startup')
)
foreach($d in $f){ Get-ChildItem $d -Filter '*MiniMax*' | Remove-Item -Recurse -Force }
```

### E12. 评论区高频问题（原文提问，官方答复未随正文一起抓取）

- "本地部署需要耗费积分吗？"
- "本地部署是必须部署在本机么？能用局域网里的 ComfyUI 和 H3 么？"
- "我的免费三次使用哪里去了？"
- "为什么直接在『资产中心』添加资产时，在本地上传素材不能创建资产？"
- "新账号登录给了 3000 积分，第二天看莫名其妙没有了，消耗记录也没有，这是咋回事？"
- "积分和钱双扣？""怎么没有人工（客服）？"
- 官方在评论区给出的两个入口：反馈/讨论请加入**飞书群**；社区与反馈站 https://hub.minimaxi.com/
- 另有用户反馈"电脑端打不开、客服找不到"，属负面反馈，未见官方答复。

---

## 附录 F｜抓取过程与可信度说明

| 文档 | 抓到什么 | 仍缺什么 |
|---|---|---|
| 1 使用手册 | **全文正文**：更新日志、体验入口、一、模型定位、**核心规格与输入限制表**、§三 亮点能力与示例、**§四 提示词方法论（1.1～4）**、评论区官方答复 | 以**图片/视频块**形式给出的示例演示（图片1～3、各 mp4）无法文本化；个别评论区折叠答复 |
| 2 开源资源 | 全部 8 节，含 **Community & Support** | 无（正文已完整） |
| 3 本地运行指南 | C0～C7 全文（英文原文 + 中文版 §6/§7） | 两篇外链 docx 的正文（**需登录**） |
| 4 生态速查表 | Hardware Cheat Sheet + **Ecosystem Master Table 全部 10 类条目、81 个链接** | 极少数项目名在虚拟滚动瞬间丢失（已用 ❤/⭐ 计数与描述交叉定位） |
| 5 Design 手册 | 官网、v3.0.16、平台介绍、**完整目录**、四个部分（快速入门 / 实战商用案例 / 进阶创作 / 开源与本地化部署 Beta）、Q&A、会员与团队版、评论区置顶修复脚本 | 【往期更新】列表；部分案例的完整示例提示词（原文以长文/图片给出） |

**取数方式（本轮已升级，可复现）**

1. `web_fetch`：只能拿到**首屏已渲染**的 HTML，折叠与虚拟滚动内容取不到。
2. **`playwright-cli` 无头 Chrome + Node 脚本（本轮新增）**：打开页面后**逐步滚动**（同时驱动 `window` 与内层滚动容器），并且**每滚一步就采集一次 DOM 叶子文本 / 链接 / 图片并累积去重**——这样即使飞书把离屏块从 DOM 移除，内容也不会丢；结果先落盘到系统临时目录，再清洗（剔除 `<style>/<script>` 文本、去重、去掉被更长条目覆盖的碎片）后才合并进本文件。
3. 两篇 docx（`VJA3dLNNpo2gnDxkKfFcaCXbnTf`、`O6Aid7HxloyFRSxi9Nic2DDwnng`）**用无头浏览器打开后仍是登录墙**（页面正文仅 231 字符的引导文案），确认为非公开可读，其正文无法纳入。
4. 原文中夹带的零宽字符与跟踪像素（`px.ads.linkedin.com`）已剔除；抓取脚本与中间文件均放在系统临时目录，未写入仓库。
