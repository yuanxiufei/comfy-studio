# ComfyUI 出图流程 · 第一张图开始

> ⚠️ **前提声明（如实说明，不编）**：
> ① 仓库里**没有** ComfyUI 相关材料（我搜过，0 处命中）—— 以下是通用做法，不假设你装了哪些模型；
> ② 本环境**没有出图工具**，所以我给的是**可执行流程 + 拼好的提示词**，图要你在 ComfyUI 里出；
> ③ 我不知道你 ComfyUI 的版本与已装模型 —— 凡是需要"你自己选"的地方我都标了 🔧。

---

## 零、你要准备的两样东西

| 项 | 🔧 说明 |
|---|---|
| **一个写实向 checkpoint** | 本剧要**写实/拟真人**（规格默认），不要动漫风模型。SDXL 或 SD1.5 写实模型都行 |
| **一个中文→英文的心算** | ⚠️ SD/SDXL **只认英文提示词** → 用我给的**英文段**粘贴，中文段只给你自己看的 |

---

## 一、最简节点链路（ComfyUI 默认工作流就是这个）

```
Load Checkpoint ─┬─→ CLIP Text Encode（正向）─┐
                 ├─→ CLIP Text Encode（负向）─┼─→ KSampler ─→ VAE Decode ─→ Save Image
                 └─→ VAE ─────────────────────┘        ↑
                                        Empty Latent Image（尺寸在这改）
```

**你只需要动 5 个地方**（其余别碰）：

| 节点 | 改什么 |
|---|---|
| Load Checkpoint | 🔧 选你的写实模型 |
| CLIP Text Encode（**正向**） | 粘贴下面 §三 的**英文**提示词 |
| CLIP Text Encode（**负向**） | 粘贴下面 §二 的负向词 |
| Empty Latent Image | 尺寸改 **832 × 468**（16:9；SDXL 可用 1024×576） |
| KSampler | seed **固定**（例 `12345`）、steps 28、CFG 6.5、sampler `dpmpp_2m`、scheduler `karras` |

然后点 **Queue Prompt**。

---

## 二、负向提示词（所有资产都用这一条）

```text
text, letters, numbers, logo, watermark, caption, subtitle, label, UI, interface,
typography, signature, distorted anatomy, extra fingers, missing fingers, extra limbs,
duplicate body parts, deformed face, asymmetrical eyes, inconsistent character design,
inconsistent costume, incorrect perspective, malformed hands, blurry details, low resolution
```

> ⚠️ 这条是规格 §19 / 工作流 `NEGATIVE-PROMPT-LIBRARY` 的通用段 —— **每个资产都带着它**，
> 尤其 `text, letters, numbers, logo, watermark` 那几项：本剧**禁止任何文字进画面**（含三视图旁的
> FRONT/SIDE/BACK 标注）。

---

## 三、⚡ 第一张图：CHR_002 萧易（正面）—— 提示词已拼好，直接抄

**正向（英文，直接粘贴）**
```text
(photorealistic:1.2), a 35-year-old Chinese man with ordinary but pleasant features,
NOT an idol face, short square jawline, thick slightly drooping eyebrows,
narrow double eyelids with bloodshot sclera, straight nose bridge with slightly wide nostrils,
thin lips, natural sallow skin tone with shadowed under-eyes,
short black slightly messy hair with an unruly front strand, dark brown eyes,
about 182 cm, lean build with medium-wide shoulders, wearing a worn grey wool coat over a
cotton shirt, natural standing pose, arms relaxed at sides,
pure white background, soft even cinematic studio lighting, minimal hard shadows,
realistic light falloff, physically plausible highlights and material reflections,
8K UHD, extremely detailed, clean edges, realistic skin and fabric texture,
single full-body front view, full length, centered
```

**负向**：抄 §二 那一整条。

**参数**：`832 × 468`｜steps `28`｜CFG `6.5`｜sampler `dpmpp_2m`｜karras｜seed `12345`

**出图后存到**：
```
02_CHARACTERS/CHARACTER_002/CHR_002_v1_front.png
```
> 命名跟随骨架规范：`<ID>_v<n>_<角度>.png`（骨架 README §二「组合示例」）

---

## 四、三视图怎么出（⚠️ 实话：别指望一张图里画三个视角）

**规格要求"左侧细节 + 右侧三视图"，但一次生成三视图在 ComfyUI 里非常不可靠**
（模型会画成三个不同的人 ✗）。**推荐做法**：

| 步 | 做法 |
|---|---|
| ① | **同一 seed、同一提示词**，只把结尾的 `single full-body front view` 换成 `side view` / `back view`，各出一张 |
| ② | 三张出来后**用拼图工具并排**（左：脸部细节裁切，右：正面/侧面/背面）→ 得到规格要的那张版式 |
| ③ | 有 ControlNet 的话：用 **openpose / lineart** 锁姿态，能进一步减少三视图之间的人体差异（🔧 可选） |

> ⚠️ 三张图之间**必须能看出是同一个人**（脸型/五官/发型/服装一致）——
> 这是 `角色索引（INDEX_CHARACTER）.md` 的锚点表要核对的东西，**不一致就重出**。

---

## 五、一致性怎么做（5 条，按重要性）

| # | 做法 | 为什么 |
|---|---|---|
| 1 | **固定 seed** | 同角色所有图用同一个 seed = 最大的一致性来源 |
| 2 | **同一 checkpoint** | 中途换模型 = 换脸 |
| 3 | **Character Anchor 文本原样带上** | `生图提示词（第1批）.md` §一 的锚点段逐字复制，**不许改写** |
| 4 | **出图后人工比对锚点表** | 抠细节只能靠人眼：眼型 / 眉眼距 / 发际线 |
| 5 | 🔧 进阶：IPAdapter（参考图）或 LoRA | 做长剧建议给主要角色训一个 LoRA（要 20–40 张同角色图） |

---

## 六、场景怎么出（和角色不一样！）

⚠️ **场景不用纯白背景**，也**不做三视图**：

```
① 用 02_资产索引/场景索引（INDEX_ENVIRONMENT）.md §二 的「锁定项表」逐条写进提示词
   （建筑 / 门窗 / 家具 / 地面 / 光源 / 主空间关系 —— 六项缺一不可）
② 六角度（或 3 角度）= 「同一套锁定项 + 只改机位描述」
③ 🔧 全屋广角建议 1024×576 起，横版
```

**第一条建议先做 `ENV_008 萧家客厅`**（四集主战场）——
⚠️ 但记住：它必须**普通到不起眼**，画精致了 EP04 的喜剧就没了。

---

## 七、第一天的清单（照着打勾）

- [ ] 打开 ComfyUI，确认能跑通默认工作流
- [ ] 抄 §二 负向词 → 固定成你的负向模板
- [ ] 出 **CHR_002 萧易 正面**（§三 提示词）→ 存 `02_CHARACTERS/CHARACTER_002/`
- [ ] 改结尾视角出 **侧面 / 背面** → 拼三视图
- [ ] 回 `角色索引（INDEX_CHARACTER）.md` 把 CHR_002 的 ☐ 改 ✅
- [ ] 再出 **CHR_003 李茜**（主体段见 `生图提示词（第1批）.md` §一）
- [ ] 顺手记下你用的 checkpoint / seed / 步数（**下一次要一样**）

---

## 八、出问题了看这里

| 症状 | 先查 |
|---|---|
| 图里出现文字/水印 | 负向词漏了 `text, letters, numbers, logo, watermark`（§二 整条都要） |
| 三张视角不是同一个人 | ① 换过 seed？② 提示词里人物描述是不是少了几句？③ 用 §四 的 openpose 方案 |
| 脸太"网红" | 提示词里 `NOT an idol face` 被模型忽略了 → 加大权重或换 checkpoint |
| 场景太精致 | 萧家必须"看着不宽裕"：把 `laminate flooring, veneer panels, plastic storage boxes` 明确写进去，**删掉**任何 `marble / solid wood / decor` |
| 出图很慢 | 降尺寸（先 640×360 试构图，定稿再放大）或降 steps |
