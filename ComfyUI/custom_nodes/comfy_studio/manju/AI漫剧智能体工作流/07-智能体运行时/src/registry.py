"""Agent 注册表 —— **声明式**定义七个流程 agent。

⭐ 设计要点（这是"通用"的落点）：
    工作流的**每个模块本身就是一个独立 agent**（各有主控 + 引擎 + 模板 + 输出纪律 +
    初始化指令）。本运行时**不为任何模块写专门代码** —— 它只按这张表**加载**：

        key      标识（命令行用）      dir      模块目录
        role_docs 角色知识（主控+引擎）  templates 输出模板
        outputs  交付物                gate     该模块的门禁

    于是「新增/改造一个流程 agent」= **在此表加一条**，运行时、CLI、门禁、
    交接清单、路由会**自动**支持它。零代码改动。

⚠️ 只读原则（同 `rule_source.py`）：
    本表只登记**路径**，不复制任何规则内容。内容一律在运行时从工作流读取 ——
    工作流改了，agent 立刻跟上（见 `module_loader.py`）。
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GateCheck:
    """一条门禁检查项。

    :param label:  人读的检查项名（如「九列完整」）
    :param any_of: **实际判据** —— 交付物里命中任一关键词即算检出。

    ⚠️ 为什么要有 `any_of`：最初直接从 `label` 里拆词去匹配，结果报出
    「未在交付物中检出：九列完整」这种废话 —— `label` 是**人话**，不是判据。
    """

    label: str
    any_of: list[str]


@dataclass(frozen=True)
class AgentSpec:
    """一个流程 agent 的声明。"""

    key: str                      # 命令行标识（英文短名）
    no: str                       # 模块编号 "00".."06"（= 执行顺序）
    name: str                     # 中文名
    dir: str                      # 模块目录（相对工作流根；根用 "."）
    summary: str                  # 一句话职责

    # ── 角色知识：扮演这个 agent 必须读的文档（主控在前，引擎在后）──
    role_docs: list[str] = field(default_factory=list)

    # ── 补充素材：按需加载（引擎规则集 / 输出模板 / 项目骨架）──
    ref_docs: list[str] = field(default_factory=list)

    # ── 交付物与门禁 ──
    outputs: list[str] = field(default_factory=list)
    gate: str = ""
    gate_checks: list[GateCheck] = field(default_factory=list)

    # ── 路由：用户这么说 → 进这个 agent ──
    triggers: list[str] = field(default_factory=list)
    input_forms: list[str] = field(default_factory=list)

    # ── 该模块的「结构化超能力」由插件提供（目前只有 02 有）──
    plugin: str = ""


# ═════════════════════════════════════════════════════════════
# 七个 agent（编号 = 执行顺序，与 `00-总控路由.md` §一 一致）
# ═════════════════════════════════════════════════════════════
REGISTRY: list[AgentSpec] = [
    AgentSpec(
        key="orchestrator",
        no="00",
        name="全流程总控",
        dir=".",
        summary="判定阶段 → 路由模块 → 校验交接 → 推进门禁",
        role_docs=["00-总控路由.md"],
        outputs=["路由判定", "交接校验", "门禁推进"],
        triggers=["怎么做一部", "全流程", "从零做", "帮我做一部漫剧", "这个小说做成漫剧",
                  "接下来做什么", "下一步", "整个流程"],
        input_forms=["一句话创意", "小说", "剧本", "分镜表", "成片"],
    ),
    AgentSpec(
        key="script",
        no="01",
        name="剧本文本引擎",
        dir="01-剧本文本",
        summary="创意 → 大纲 → 剧本 → 分集（含工业化 40 集）",
        role_docs=[
            "01-剧本文本/00-主控智能体.md",
            "01-剧本文本/01-工业化编剧引擎.md",
        ],
        ref_docs=[
            "01-剧本文本/模板/剧本与角色小传模板.md",
            "01-剧本文本/模板/ID-REGISTRY.md",
            "01-剧本文本/模板/OPEN-ISSUES.md",
        ],
        outputs=["剧本", "角色小传", "分集大纲", "ID 注册表", "未决项跟踪表"],
        gate="剧本门禁",
        gate_checks=[
            GateCheck("有完整分集结构", ["分集", "EP01", "第1集", "第 1 集", "集数规划"]),
            GateCheck("每个角色有小传", ["小传", "角色档案", "人物档案", "角色卡"]),
            GateCheck("有钩子设计", ["钩子", "悬念", "下一集为什么"]),
        ],
        triggers=["写剧本", "剧本", "大纲", "分集", "小说改编", "创意", "故事", "编剧",
                  "角色小传", "40 集", "工业化"],
        input_forms=["一句话创意", "小说", "已有剧本"],
    ),
    AgentSpec(
        key="asset",
        no="02",
        name="服化道引擎",
        dir="02-服化道",
        summary="剧本 → VISUAL_BIBLE + 角色/服装/道具/场景资产",
        role_docs=[
            "02-服化道/00-主控智能体.md",
            "02-服化道/01-资产库出图引擎.md",
        ],
        ref_docs=[
            "02-服化道/引擎/TURNAROUND-STANDARD.md",
            "02-服化道/引擎/NEGATIVE-PROMPT-LIBRARY.md",
            "02-服化道/引擎/PROMPT-TEMPLATES.md",
            "02-服化道/引擎/CONSISTENCY-CHECKLIST.md",
            "02-服化道/引擎/LOCK-SYSTEM.md",
            "02-服化道/引擎/PROJECT-PIPELINE.md",
            "02-服化道/模板/VISUAL_BIBLE.md",
            "02-服化道/模板/ASSET_CARD.yaml",
            "02-服化道/模板/CHANGELOG.yaml",
            "02-服化道/模板/PROJECT_STATE.yaml",
        ],
        outputs=["VISUAL_BIBLE", "角色资产", "服装资产", "道具资产", "场景资产",
                 "场景 360° 全景基准（§4.6）", "表情集 EXP_", "动作集 POS_",
                 "风格锁定表", "批量生产（§十八）"],
        gate="资产门禁",
        gate_checks=[
            GateCheck("VISUAL_BIBLE 锁定", ["VISUAL_BIBLE", "视觉圣经"]),
            GateCheck("角色过一致性 Gate", ["一致性", "指纹", "LOCK", "锁定"]),
            GateCheck("风格锁定表 9 项齐全", ["风格锚点", "风格锁定", "STYLE", "画风"]),
        ],
        triggers=["生成角色", "三视图", "角色", "服装", "道具", "场景", "资产",
                  "视觉资产", "出图", "表情", "动作", "资产库", "环境",
                  "表情集", "动作集", "姿势", "三视图资产"],
        input_forms=["剧本", "小说", "一张参考图"],
        plugin="asset",           # ⭐ 唯一带结构化超能力的模块（资产卡 + 出图）
    ),
    AgentSpec(
        key="storyboard",
        no="03",
        name="分镜导演",
        dir="03-分镜导演",
        summary="剧本 + 资产 → 九列分镜表 + AI 提示词包",
        role_docs=[
            "03-分镜导演/分镜导演-完整合并版.md",
            "03-分镜导演/视觉分镜引擎.md",
            "03-分镜导演/主工作流/storyboard-director-pro.md",
        ],
        ref_docs=[
            "03-分镜导演/引擎/镜头技法扩充库.md",
        ],
        outputs=["九列分镜表", "AI 提示词包", "用户镜头号 ↔ SHT_ 映射表"],
        gate="分镜门禁",
        gate_checks=[
            # 九列的**实际列名**才算数 —— 光写「九列」不是交付物
            GateCheck("九列完整", ["镜号", "景别", "运镜", "画面内容", "叙事目的"]),
            GateCheck("引用资产 ID", ["CHR_", "CST_", "PRP_", "ENV_", "EXP_", "POS_"]),
            GateCheck("每镜有叙事目的", ["叙事目的", "叙事"]),
        ],
        triggers=["分镜", "拆分镜", "这场戏怎么拍", "镜头", "运镜", "景别",
                  "视觉分镜", "九宫格", "storyboard"],
        input_forms=["剧本", "资产库"],
    ),
    AgentSpec(
        key="video",
        no="04",
        name="视频生成引擎",
        dir="04-视频生成",
        summary="分镜 → 视频提示词 + 生成脚本 + 尾帧链",
        role_docs=["04-视频生成/00-主控智能体.md"],
        ref_docs=[
            "04-视频生成/引擎/情绪过渡提示词库.md",
            "04-视频生成/引擎/动作戏提示词库.md",
            "04-视频生成/模板/视频生成脚本模板.md",
        ],
        outputs=["视频提示词", "生成脚本", "尾帧库"],
        triggers=["视频", "出视频", "转视频", "首尾帧", "尾帧", "图生视频",
                  "运行时", "运动强度", "镜头连贯"],
        input_forms=["分镜表", "资产库"],
    ),
    AgentSpec(
        key="audio",
        no="05",
        name="音乐音频引擎",
        dir="05-音乐音频",
        summary="剧本 + 成片 → 歌词 / BGM / 配音 / 调音",
        role_docs=[
            "05-音乐音频/00-主控智能体.md",
            "05-音乐音频/01-声音设计引擎.md",
            "05-音乐音频/02-Suno歌词引擎.md",
        ],
        ref_docs=["05-音乐音频/模板/音频工程规范模板.md"],
        outputs=["BGM", "歌词", "配音轨", "音频工程规范"],
        triggers=["音乐", "配乐", "歌词", "主题曲", "BGM", "Suno", "曲风",
                  "配音", "声线", "环境声", "Foley", "调音", "响度", "混音"],
        input_forms=["剧本", "成片"],
    ),
    AgentSpec(
        key="compliance",
        no="06",
        name="合规审核引擎",
        dir="06-合规审核",
        summary="全部提示词 + 成片 → 过审优化 + IP 检查",
        role_docs=["06-合规审核/00-主控智能体.md"],
        ref_docs=["06-合规审核/模板/风险报告模板.md"],
        outputs=["优化后提示词", "风险报告"],
        triggers=["过审", "审核", "合规", "风险", "侵权", "被限", "限流", "封号",
                  "平台适配", "发布前", "违规", "敏感", "下架", "版权"],
        input_forms=["提示词包", "成片"],
    ),
]

AGENTS: dict[str, AgentSpec] = {a.key: a for a in REGISTRY}

# 命令行别名（用户可能用编号或中文名）
ALIASES: dict[str, str] = {}
for _a in REGISTRY:
    ALIASES[_a.key] = _a.key
    ALIASES[_a.no] = _a.key
    ALIASES[_a.name] = _a.key
    ALIASES[_a.no.lstrip("0") or "0"] = _a.key


def resolve(name: str) -> AgentSpec | None:
    """把命令行参数解析成 AgentSpec（支持 key / 编号 / 中文名）。"""
    key = ALIASES.get((name or "").strip())
    return AGENTS.get(key) if key else None
