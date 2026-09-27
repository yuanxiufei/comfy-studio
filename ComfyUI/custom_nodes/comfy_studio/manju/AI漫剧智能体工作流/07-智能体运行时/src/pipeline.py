# -*- coding: utf-8 -*-
"""全流程编排（S0 → S5）：**小说 → 剧本 → 资产 → 分镜 → 首帧 → 出片 → 成片**。

工作流本来把 7 个模块写成 7 个能独立跑的 agent，但它们之间靠"人说一句话"交接。
真跑一部剧时，人那一步就是瓶颈 —— S4 的分镜表要手抄进 ComfyUI、S5 的 30 段
视频要手点 30 次。本模块把**能机械化的那几段**串起来，人只做两件事：写小说、审片。

    | 阶段 | 干什么 | 需要 LLM | 落点（对齐 `生产流程规范（S0-S7）.md` §一） |
    |---|---|---|---|
    | S0 建纲 | 小说 → 分集大纲／每集剧本／角色小传／ID 注册表／未决项表 | ✅ | `00_PROJECT/01_剧本/` `03_台账/` |
    | S1 资产 | 剧本 → 视觉圣经 + 四张索引 + 生图提示词 | ✅ | `00_PROJECT/02_资产索引/` `04_交付与出图/` |
    | S4 分镜 | 剧本 → 九列分镜表 + `shots_<EP>.json` | 可选 | `08_STORYBOARDS/` |
    | S4 首帧 | 每镜首帧 PNG（文生图，有资产图时挂参考图） | ❌ | `08_STORYBOARDS/frames_<EP>/` |
    | S5 出片 | 每镜 mp4（ComfyUI fl2v 时间线，逐镜一跑） | ❌ | `09_SHOTS/` |
    | S5 成片 | 按镜序拼成一部 mp4 | ❌ | `09_SHOTS/<EP>_成片.mp4` |

三条口径（写在这里，免得变成隐式约定）：

1. **分镜 JSON 是唯一事实源**：出图、出片都只认 `shots_<EP>.json`，不重新解析剧本。
2. **不覆盖已有产物**：默认跳过已存在的文件，`--重跑` 才覆盖 —— S0/S1 的产物是
   模型写、人又改过的交付物，悄悄覆盖等于吞掉人的劳动。
3. **缺前置就报错，不降级**：S0/S1 没模型可用时**明确拒绝**（不产出空壳交付物）；
   S4 的 LLM 增强是可选的，失败只在分镜表里记一行警告。

⚠️ 本模块**不代做** S3（表情/动作派生，只在主 ID ≥ DRAFT 时才建）与
S6（音频，口径在 `05-音乐音频/`），那两段留给各自 agent：
`python main.py run expression|audio`。
"""

from . import film, registry as agent_registry, storyboard
from .agent import AgentConfig, DramaAssetAgent
from .flow_core import *  # noqa: F401,F403 —— 常量/阶段/工具，见 flow_core.py
from .flow_core import _append_registry_rows, _load_cfg, _md_table, _read, _write  # noqa: F401
from .flow_prompts import *  # noqa: F401,F403 —— LLM 提问模板，见 flow_prompts.py
from .image_provider import get_provider as get_image_provider
from .project import find_workspace, list_projects, projects_root
from .runtime import Runtime
from .video_provider import find_comfy_root, get_video_provider

__all__ = ["Flow", "Stage", "STAGES", "ORDER", "StageError", "StageResult",
           "find_workspace", "projects_root", "list_projects", "default_ep"]


# ─────────────────────────────────────────────────────────────
# 编排主体
# ─────────────────────────────────────────────────────────────

class Flow:
    """从小说到成片的一条流水线。每个阶段方法都能单独跑（`run("分镜")`）。"""

    def __init__(self, project: str = "", *, ep: str = "", root=None, force: bool = False,
                 limit: int = 0, dry: bool = False, video_provider: str = "",
                 frames_provider: str = "", use_llm=None, novel: str = "",
                 quiet: bool = False, episodes: int = 0, novel_chars: int = 60000,
                 allow_truncate: bool = False, reference: str = "auto",
                 missing_shot: str = "error"):
        self.root = Path(root) if root else ROOT
        self.cfg = _load_cfg(self.root)
        self.project = self._resolve_project(project)
        self.ep = (ep or "").strip() or default_ep(self.project)
        if not re.fullmatch(r"EP\d{2}", self.ep):
            raise StageError(f"集号要写成 EP01 这种（收到：{self.ep!r}）")
        self.force = force
        self.limit = max(0, int(limit or 0))
        self.dry = dry
        self.quiet = quiet
        self.episodes = max(0, int(episodes or 0))
        self.novel_chars = max(2000, int(novel_chars or 60000))
        self.allow_truncate = allow_truncate
        self.novel_arg = novel
        self.ref_mode = reference                    # auto | on | off
        self.missing_shot = missing_shot             # error | still（缺镜怎么办）
        self._ref_ok = True                          # 工作流能不能吃参考图
        self._video_name = video_provider or ""
        self._frames_name = frames_provider or ""
        self._use_llm = use_llm
        self._video = None
        self._frames = None
        self._ag = None
        self._reg = None

    # ── 定位 ──

    def _resolve_project(self, project: str) -> str:
        if not project:
            raise StageError(
                "没给项目。用 `--项目 <项目名或路径>`；"
                f"当前项目根：{projects_root() or '（未探测到 projects/）'}\n"
                f"  可选：{'、'.join(list_projects()) or '（空）'}")
        p = os.path.abspath(project)
        if os.path.isdir(p):
            return p
        cand = os.path.join(projects_root(), project)
        if os.path.isdir(cand):
            return os.path.abspath(cand)
        raise StageError(f"项目目录不存在：{p}\n  可选项目："
                         f"{'、'.join(list_projects()) or '（没找到 projects/ 目录）'}")

    # ── 打印 ──

    def say(self, msg: str = "", level: int = 0) -> None:
        if not self.quiet:
            print(("  " * level) + msg, flush=True)

    def hr(self, title: str = "") -> None:
        if self.quiet:
            return
        print("\n" + "─" * 66, flush=True)
        if title:
            print(title, flush=True)
            print("─" * 66, flush=True)

    # ── 惰性资源 ──

    @property
    def ag(self) -> DramaAssetAgent:
        if self._ag is None:
            self._ag = DramaAssetAgent(AgentConfig.load(self.root))
        return self._ag

    @property
    def rules(self):
        return self.ag.rules

    @property
    def llm(self):
        return self.ag.llm

    @property
    def registry(self) -> asset_index.Registry:
        if self._reg is None:
            self._reg = asset_index.load_project_registry(self.project)
        return self._reg

    def _refresh_registry(self) -> None:
        self._reg = None

    def p(self, *parts: str) -> str:
        """项目内的路径。"""
        return os.path.join(self.project, *parts)

    def episodes_of(self) -> int:
        """本剧要拍几集：`--集数` > 物料单 > `config.flow.episodes` > 12。"""
        if self.episodes:
            return self.episodes
        n = len(asset_index.episode_targets(self.project))
        if n:
            return n
        cfg = (self.cfg.get("flow") or {}).get("episodes")
        return int(cfg) if cfg else 12

    def target_sec(self, ep: str = "") -> float:
        """该集目标时长（读项目物料单；没有就用 `storyboard.TARGET_SEC` 兜底）。"""
        t = asset_index.episode_targets(self.project).get(ep or self.ep)
        return float(t) if t else float(storyboard.TARGET_SEC)

    # ── LLM ──

    def need_llm(self, stage: str):
        if self._use_llm is False:
            raise StageError(f"`{stage}` 需要 LLM，但你显式关掉了（--不用LLM）")
        c = self.llm
        if not c.available:
            raise StageError(
                f"`{stage}` 要模型才能做，但没配 Key。\n"
                f"  设 `MODEL_API_KEY`（可选 `MODEL_BASE_URL` / `MODEL_NAME`，兼容 "
                f"Ollama / OpenAI / DeepSeek 等 `/chat/completions` 服务）后重跑。\n"
                f"  不想用模型：`python main.py run script \"<输入>\"` 会产出**可粘贴的"
                f"调用包**，人工贴回结果即可。")
        return c

    def want_llm(self) -> bool:
        """分镜增强要不要用 LLM：`None` = 自动档（有就用）。"""
        if self._use_llm is None:
            return self.llm.available
        if self._use_llm is True and not self.llm.available:
            raise StageError("你要 `--用LLM` 但没配 MODEL_API_KEY —— 拒绝假装增强过")
        return self._use_llm

    def _agent_system(self, key: str) -> str:
        """取某 agent 的**权威 System Prompt**（角色 + 权威文档原文 + 全局约束）。

        复用 `Runtime` 的装配，而不是自己拼一段 —— 判据来源只能是工作流那几份文档，
        自己拼等于另立一套标准。
        """
        spec = agent_registry.resolve(key)
        if spec is None:
            raise StageError(f"注册表里没有 agent「{key}」")
        return Runtime().build(spec, "（占位）").system_prompt

    def _ask_json(self, agent_key: str, ask: str) -> dict:
        from .llm_client import extract_json
        return extract_json(self.llm.chat(self._agent_system(agent_key), ask,
                                          json_mode=True))

    def _ask_md(self, agent_key: str, ask: str) -> str:
        return self.llm.chat(self._agent_system(agent_key), ask)

    # ── 文件策略 ──

    def _keep(self, path: str) -> bool:
        return os.path.isfile(path) and not self.force

    def _guard(self, path: str, what: str) -> bool:
        """True = 跳过。原因**一定打印**，不静默。"""
        if self._keep(path):
            self.say(f"⏭️  {what}已存在，跳过（要重做加 `--重跑`）：{self._rel(path)}")
            return True
        if self.dry:
            self.say(f"🧪 预演：将写入 {self._rel(path)}")
            return True
        return False

    def _rel(self, path: str) -> str:
        try:
            return os.path.relpath(path, self.project).replace("\\", "/")
        except ValueError:
            return path

    def _ensure_skeleton(self) -> list:
        made = []
        for d in SKELETON_DIRS:
            full = self.p(d)
            if not os.path.isdir(full):
                if not self.dry:
                    os.makedirs(full, exist_ok=True)
                made.append(d)
        return made

    # ── Provider ──

    def video_provider(self):
        if self._video is None:
            cfg = dict(self.cfg.get("video") or {})
            cfg.setdefault("width", 1344)
            cfg.setdefault("height", 768)
            cfg.setdefault("fps", 24)
            name = self._video_name or cfg.pop("provider", "") or "comfyui"
            cfg["provider"] = name
            self._video = get_video_provider(name, cfg)
        return self._video

    def frames_provider(self):
        if self._frames is None:
            flow_cfg = self.cfg.get("flow") or {}
            sub = dict(flow_cfg.get("frames") or {})
            img = (self.cfg.get("image") or {}).get("comfyui") or {}
            comfy = {"workflow": sub.get("workflow") or os.getenv("COMFYUI_FRAME_WORKFLOW") or "",
                     "base_url": sub.get("base_url") or img.get("base_url") or "",
                     "timeout": sub.get("timeout") or img.get("timeout") or 900,
                     "poll": sub.get("poll") or img.get("poll") or 1.5,
                     "overrides": sub.get("overrides") or {}}
            if not comfy["workflow"]:
                comfy["workflow"] = auto_frame_workflow()
            comfy = {k: v for k, v in comfy.items() if v not in ("", None)}
            name = (self._frames_name or flow_cfg.get("frames_provider")
                    or sub.pop("provider", "") or "comfyui")
            cfg = {"provider": name, "comfyui": comfy,
                   "width": int(sub.get("width") or (self.cfg.get("video") or {}).get("width")
                                or 1344),
                   "height": int(sub.get("height") or (self.cfg.get("video") or {}).get("height")
                                 or 768)}
            if sub.get("seed") is not None:
                cfg["seed"] = sub["seed"]
            self._frames = get_image_provider(name, cfg)
        return self._frames

    def frames_size(self) -> tuple:
        c = self.frames_provider().cfg
        return int(c.get("width") or 1344), int(c.get("height") or 768)

    # ═════════════════════════════════════════════════════════
    # S0 建纲：小说 → 分集大纲 / 每集剧本 / 角色小传 / ID 注册表 / 未决项表
    # ═════════════════════════════════════════════════════════

    OUTLINE_JSON = "00_PROJECT/01_剧本/_分集大纲.json"

    def novel_path(self) -> str:
        """小说原文：`--小说` > 工作区 `novel/` 下跟项目同名的文件 > 那儿唯一的文件。"""
        if self.novel_arg:
            p = os.path.abspath(self.novel_arg)
            if not os.path.isfile(p):
                raise StageError(f"--小说 指的文件不存在：{p}")
            return p
        ws = find_workspace()
        d = os.path.join(ws, "novel") if ws else ""
        if not d or not os.path.isdir(d):
            raise StageError(
                "没找到小说原文。用 `--小说 <文件路径>` 指一个，或把它放进工作区的 "
                f"`novel/` 目录（探测结果：{d or '未探测到'}）")
        files = sorted(f for f in os.listdir(d) if f.lower().endswith((".txt", ".md")))
        if not files:
            raise StageError(f"`{d}` 里没有 .txt/.md")
        name = os.path.basename(self.project)
        hit = [f for f in files if name in f or os.path.splitext(f)[0] in name]
        if len(hit) == 1:
            return os.path.join(d, hit[0])
        if len(files) == 1:
            return os.path.join(d, files[0])
        raise StageError(f"`{d}` 里有多个小说，认不出用哪个：{'、'.join(files)}\n"
                         f"  用 `--小说 <文件路径>` 明确指定")

    def _novel_text(self) -> str:
        src = self.novel_path()
        text = _read(src)
        if len(text) > self.novel_chars:
            if not self.allow_truncate:
                raise StageError(
                    f"小说 {len(text)} 字，超过单次喂给模型的上限 {self.novel_chars} 字。\n"
                    f"  看着办：①`--小说字数 {len(text)}` 放行（模型上下文要够）；"
                    f"②先把小说按卷/按集切小，再逐段跑；\n"
                    f"  ③确实只想拿前 {self.novel_chars} 字试跑，就显式加 `--截断`"
                    f"（**默认不截** —— 悄悄砍掉后半本书会产出一部莫名其妙的剧）。")
            self.say(f"⚠️  小说 {len(text)} 字 → 按 `--截断` 只取前 {self.novel_chars} 字")
            text = text[:self.novel_chars]
        self.say(f"📖 小说：{self._rel(src)} · {len(text)} 字")
        return text

    def stage_建纲(self) -> StageResult:
        """小说 → 建纲交付物。LLM 写内容，落盘与登记由本方法机械执行。"""
        res = StageResult("建纲")
        plan_path = self.p(self.OUTLINE_JSON)
        # ⚠️ 顺序要紧：**先校输入、再校环境**。路径写错和没配 Key 同时存在时，
        #    用户该先看到「文件不存在」（他自己马上能改），而不是「缺 Key」——
        #    否则他配完 Key 重跑，才发现真正的问题，白折腾一轮。
        #    只在**确实要读小说**时校验：大纲已存在就可以跳过建纲，
        #    那种情况下不该反过来要求小说还在。
        if not self._keep(plan_path):
            self.novel_path()          # 只做存在性校验，不读全文
        self.need_llm("建纲")
        made = self._ensure_skeleton()
        if made:
            self.say(f"📁 新建骨架目录 {len(made)} 个：{'、'.join(made[:4])}"
                     f"{'…' if len(made) > 4 else ''}")

        eps = self.episodes_of()
        plan_md = self.p(SCRIPT_DIR, "分集大纲与三表.md")

        # ① 分集大纲 —— JSON 是事实源（给后续"只补 EP03"用），md 是给人看的样子
        if self._keep(plan_path):
            plan = json.loads(_read(plan_path))
            self.say(f"⏭️  分集大纲已存在，跳过（要重做加 `--重跑`）：{self._rel(plan_path)}")
            res.skipped = True
        else:
            novel = self._novel_text()
            self.say(f"🤖 让模型分 {eps} 集（这一步定全剧骨架与角色号段）…")
            plan = self._ask_json("script", OUTLINE_ASK.format(
                eps=eps, target=self.target_sec(), novel=novel))
            ep_list = plan.get("集") or []
            if len(ep_list) != eps:
                raise StageError(
                    f"模型给了 {len(ep_list)} 集，要求 {eps} 集 —— 集数对不上就不落盘"
                    f"（宁可重跑，也不留一份自相矛盾的大纲）")
            if not self.dry:
                _write(plan_path, json.dumps(plan, ensure_ascii=False, indent=2))
                _write(plan_md, self._render_outline(plan))
                res.files += [plan_path, plan_md]
            self.say(f"✅ 分集大纲：{plan.get('剧名', '')} · {len(ep_list)} 集 · "
                     f"{len(plan.get('角色') or [])} 个角色")

        # ② ID 注册表 / 未决项表（先建表再登记，顺序不能反）
        reg_path, oi_path = self._ensure_ledgers()
        res.files += [p for p in (reg_path, oi_path) if p]

        # ③ 逐集剧本
        eps_plan = {str(e.get("集号")): e for e in (plan.get("集") or []) if isinstance(e, dict)}
        chars = plan.get("角色") or []
        wanted = self.ep if self.ep in eps_plan else ""
        targets = [wanted] if wanted else list(eps_plan)
        for epno in targets:
            ep_plan = eps_plan[epno]
            path = self.p(SCRIPT_DIR, f"{epno}-剧本.md")
            if self._guard(path, f"{epno} 剧本"):
                continue
            budget = int(self.target_sec(epno) * storyboard.CPS * LINE_SHARE)
            self.say(f"🤖 写 {epno}《{ep_plan.get('标题', '')}》（台词预算 ≤ {budget} 字）…")
            body = self._ask_md("script", SCRIPT_ASK.format(
                ep=epno, title=ep_plan.get("标题", ""), target=self.target_sec(epno),
                outline=json.dumps(ep_plan, ensure_ascii=False, indent=2),
                chars=self._chars_brief(chars), cps=storyboard.CPS, budget=budget,
                scenes=max(3, min(8, int(self.target_sec(epno) / 22)))))
            self._check_script(epno, body, res)
            _write(path, body)
            res.files.append(path)
            self.say(f"✅ {epno} 剧本已落盘：{self._rel(path)}")

        # ④ 从剧本里回填 CHR_ / ENV_ 登记（先登记再使用：不登记就没有号位）
        added = self._register_from_scripts(plan, targets)
        res.detail = f"大纲 {len(eps_plan)} 集 · 剧本 {len(targets)} 集 · 新登记 {added} 行"
        if res.notes:
            self.say("")
            for n in res.notes:
                self.say("⚠️  " + n)
        return res

    def _render_outline(self, plan: dict) -> str:
        """分集大纲 JSON → markdown（给人看的样子）。"""
        L = [f"# 分集大纲与三表 · {plan.get('剧名', '未命名')}", "",
             f"> 机器可读副本：`{self.OUTLINE_JSON}`（改大纲请改 JSON 再重跑，别只改这里）",
             f"> 一句话卖点：{plan.get('一句话卖点', '—')}", "",
             "## 一、分集大纲", "",
             "| 集号 | 标题 | 本集钩子 | 场次 | 出场角色 | 涉及道具 |",
             "|---|---|---|---|---|---|"]
        for e in (plan.get("集") or []):
            L.append("| {} | {} | {} | {} | {} | {} |".format(
                e.get("集号", "—"), e.get("标题", "—"), e.get("本集钩子", "—"),
                "、".join(e.get("场次") or []), "、".join(e.get("出场角色") or []),
                "、".join(e.get("涉及道具") or [])))
        L += ["", "## 二、角色三表（初稿）", "",
              _md_table(IDX_HEADERS["角色"], [
                  {"ID": c.get("ID", "—"), "姓名": c.get("名", "—"),
                   "别名": c.get("别名", "—"), "年龄(EP)": c.get("年龄", "—"),
                   "身份": c.get("定位", "—"), "社会地位": "待 02 定",
                   "外貌要点": c.get("外形一句话", "—"),
                   "关键特征": c.get("关键特征", "—"),
                   "出场集": c.get("首次出场", "—"), "资产状态": "☐ 待生成"}
                  for c in (plan.get("角色") or [])])]
        und = plan.get("未决") or []
        L += ["## 三、未决项（模型自己报的）", ""]
        L += [f"{i + 1}. {u}" for i, u in enumerate(und)] or ["（无）"]
        L += ["", "> ⚠️ 上面这些是**模型自报**的未决项；人复核后要抄进 "
                  "`03_台账/未决项表（OPEN-ISSUES）.md` 才算数。", ""]
        return "\n".join(L)

    @staticmethod
    def _chars_brief(chars: list) -> str:
        """角色设定摘要 —— 喂给「写这一集剧本」那一步，让台词与形象都照它走。

        建纲给的字段比这里显示的更多（`戏份级` / `主标签` / `辅助标签` / `记忆资产`
        这几套是 `智能体搭建参考md/AI剧本创作_完整迁移配置.md` §五~§八 的口径），
        一律**有则带上、无则跳过** —— 老项目里那份 `_分集大纲.json` 没这些键，
        不能因此报错（改大纲不必是破坏性的）。
        """
        if not chars:
            return "（无角色设定 —— 按小说里的人物性格写，外貌不要编细节）"

        def _tags(c: dict) -> str:
            main = str(c.get("主标签") or "").strip()
            aux = c.get("辅助标签") or []
            if isinstance(aux, str):
                aux = [aux]
            aux = "、".join(str(x).strip() for x in aux if str(x).strip())
            got = " ＋ ".join(x for x in (main, aux) if x)
            return f"　标签：{got}" if got else ""

        def _assets(c: dict) -> str:
            a = c.get("记忆资产")
            if not isinstance(a, dict):
                return ""
            items = "；".join(f"{k}：{v}" for k, v in a.items() if str(v or "").strip())
            return f"　记忆资产：{items}" if items else ""

        lines = []
        for c in chars:
            grade = str(c.get("戏份级") or "").strip()
            bits = [str(c.get("定位") or "?").strip()]
            if grade:
                bits.append(f"{grade} 级")
            bits.append(str(c.get("年龄") or "?").strip())
            lines.append(
                f"- {c.get('名', '?')}（{'，'.join(bits)}）：{c.get('外形一句话', '—')}；"
                f"{c.get('服装一句话', '—')}；记忆点：{c.get('关键特征', '—')}"
                f"{_tags(c)}{_assets(c)}")
        return "\n".join(lines)

    def _check_script(self, ep: str, body: str, res: StageResult) -> None:
        """拿 `storyboard.parse_script` 当场校验模型交的剧本 —— 格式不对就报警。

        **不阻断**：model 交的东西人可能要留着改；但一定要把"这份剧本解析不动"
        说清楚，否则等到分镜阶段才发现，中间白跑。
        """
        try:
            title, scenes = storyboard.parse_script(body)
        except ValueError as e:
            res.notes.append(f"{ep} 剧本**没通过格式校验**：{e} —— "
                             f"分镜阶段会读不出场次，请先按硬标准改格式")
            return
        lines = sum(1 for s in scenes for b in s.blocks if b["kind"] == "line")
        chars = sum(len(b["text"]) for s in scenes for b in s.blocks if b["kind"] == "line")
        est = chars / storyboard.CPS
        tgt = self.target_sec(ep)
        res.notes.append(
            f"{ep}《{title}》：{len(scenes)} 场 / {lines} 句台词 / 台词 {chars} 字 "
            f"≈ {est:.0f}s（目标 {tgt:.0f}s）")
        if est > tgt * (1 + storyboard.TOL):
            res.notes.append(
                f"⚠️ {ep} 的台词量约 {est:.0f}s，超目标 {tgt:.0f}s 的 "
                f"{storyboard.TOL:.0%} —— 成片会明显超长，回去压缩台词或加集"
                f"（实测 EP04 就是这么超的）")

    def _ensure_ledgers(self) -> tuple:
        """建 `ID注册表` 与 `未决项表`（从工作流模板拷贝，不自己发明格式）。"""
        out = []
        for src_name, dst in (("ID-REGISTRY.md", os.path.join(
                LEDGER_DIR, "ID注册表（ID-REGISTRY）.md")),
                ("OPEN-ISSUES.md", os.path.join(
                    LEDGER_DIR, "未决项表（OPEN-ISSUES）.md"))):
            src = WORKFLOW_ROOT / "01-剧本文本" / "模板" / src_name
            dst_full = self.p(dst)
            if os.path.isfile(dst_full):
                out.append(dst_full)
                continue
            if self.dry:
                self.say(f"🧪 预演：将建 {self._rel(dst_full)}（拷自 {src_name}）")
                out.append("")
                continue
            if not src.is_file():
                raise StageError(f"模板缺失：{src} —— 注册表格式以模板为唯一来源，"
                                 f"不自己造表")
            head = _read(src).split("---", 1)[0]
            _write(dst_full, head + "\n---\n\n"
                   f"> 本项目：**{os.path.basename(self.project)}** ｜ "
                   f"由 `flow --阶段 建纲` 从模板建立，行由建纲自动登记。\n")
            out.append(dst_full)
            self.say(f"📄 新建 {self._rel(dst_full)}")
        return tuple(out)

    def _register_from_scripts(self, plan: dict, eps_done: list) -> int:
        """把剧本里出现的**说话人**与**场景**登记进注册表（`RESERVED`）。

        口径来自模板 §六：ID 在**全剧**层面一次性分配，建纲就把号占掉。
        号位从现有最大号 +1 起，**永不复用**。
        """
        reg_path = self.p(LEDGER_DIR, "ID注册表（ID-REGISTRY）.md")
        if not os.path.isfile(reg_path):
            return 0
        reg = self.registry
        text = _read(reg_path)
        nxt = {"CHR": self._next_no(reg, "CHR"), "ENV": self._next_no(reg, "ENV")}
        names = {norm_key(k): v for k, v in reg.aliases.items()}
        speakers, places = {}, {}
        for epno in (eps_done or []):
            path = self.p(SCRIPT_DIR, f"{epno}-剧本.md")
            if not os.path.isfile(path):
                continue
            try:
                _title, scenes = storyboard.parse_script(_read(path))
            except ValueError as e:
                self.say(f"⚠️  {epno} 剧本解析不了，跳过登记（{e}）")
                continue
            for sc in scenes:
                if sc.place and norm_key(sc.place) not in names:
                    places.setdefault(sc.place, epno)
                for b in sc.blocks:
                    n = (b.get("speaker") or "").strip()
                    if n and norm_key(n) not in names:
                        speakers.setdefault(n, epno)

        chr_rows, env_rows = [], []
        for name, epno in speakers.items():
            chr_rows.append({"ID": f"CHR_{nxt['CHR']:03d}", "名称": name,
                             "定位": "待定（建纲自动登记）", "首次出场": epno,
                             "状态": "`RESERVED`", "建立集": "—",
                             "备注": "由 flow 建纲从剧本自动登记；定位/外貌待 01/02 补"})
            nxt["CHR"] += 1
        for name, epno in places.items():
            env_rows.append({"ID": f"ENV_{nxt['ENV']:03d}", "名称": name,
                             "类型": "待定", "首次出场": epno, "状态": "`RESERVED`",
                             "备注": "由 flow 建纲从剧本自动登记"})
            nxt["ENV"] += 1

        total = 0
        for prefix, rows in (("CHR", chr_rows), ("ENV", env_rows)):
            if not rows:
                continue
            if self.dry:
                self.say(f"🧪 预演：将往 `{prefix}_` 段追加 {len(rows)} 行")
                continue
            text, add = _append_registry_rows(text, prefix, rows)
            total += add
            self.say(f"📝 注册表登记 {prefix}_ 段 {add} 行")
        if total and not self.dry:
            _write(reg_path, text)
            self._refresh_registry()
        return total

    @staticmethod
    def _next_no(reg, prefix: str) -> int:
        nums = [int(m.group(1)) for aid in reg.by_prefix(prefix)
                for m in [re.match(rf"{prefix}_(\d+)$", aid)] if m]
        return (max(nums) + 1) if nums else 1

    # ═════════════════════════════════════════════════════════
    # S1 资产：剧本 → 视觉圣经 + 四张索引 + 生图提示词
    # ═════════════════════════════════════════════════════════

    def stage_资产(self) -> StageResult:
        """建 02 服化道的资产索引与视觉圣经。**认已有的为准**，只补缺的那几件。"""
        res = StageResult("资产")
        self.need_llm("资产")
        self._ensure_skeleton()
        script = self._all_scripts()
        if not script:
            raise StageError(f"`{SCRIPT_DIR}` 里没有剧本 —— 先跑 `--阶段 建纲`，"
                             f"或把剧本按 EPxx-剧本.md 放进去")
        idx_dir = self.p(INDEX_DIR)
        existing = ", ".join(sorted(os.listdir(idx_dir))) if os.path.isdir(idx_dir) else "（无）"
        reg_txt = self._registry_rows_text()

        # ① 四张索引（一次问齐 —— 四张表互相依赖，分开问会各说各话）
        todo = [k for k in IDX_HEADERS
                if not os.path.isfile(os.path.join(idx_dir, IDX_FILE[k]))]
        if not todo:
            self.say("⏭️  四张索引都在，跳过（要重做加 `--重跑`）")
        else:
            self.say(f"🤖 建资产索引（缺 {'、'.join(todo)}）：{len(script)} 字剧本喂进去…")
            data = self._ask_json("asset", ASSETS_ASK.format(
                script=script, registry=reg_txt, existing=existing))
            for kind in todo:
                rows = data.get(kind) or []
                if not rows:
                    res.notes.append(f"{kind}索引模型没给出任何行 —— 该表**没建**，"
                                     f"请人工补或重跑")
                    continue
                path = os.path.join(idx_dir, IDX_FILE[kind])
                _write(path, self._render_index(kind, rows))
                res.files.append(path)
                self.say(f"✅ {IDX_FILE[kind]}：{len(rows)} 行")

        # ② 视觉圣经（全片一致性的唯一基准，必须先于出图存在）
        bible = self.p(INDEX_DIR, "视觉圣经（VISUAL_BIBLE）.md")
        if self._keep(bible):
            self.say(f"⏭️  视觉圣经已存在，跳过：{self._rel(bible)}")
        else:
            self.say("🤖 写视觉圣经…")
            md = self._ask_md("asset", VISUAL_ASK.format(
                script=script, index=self._index_digest(),
                title=os.path.basename(self.project)))
            if "## 5." not in md:
                res.notes.append("视觉圣经缺 §5 色彩语言 —— 风格锚点会取不到色值，"
                                 "分镜提示词质量会掉，建议重跑")
            _write(bible, md)
            res.files.append(bible)
            self.say(f"✅ 视觉圣经 {len(md)} 字")

        # ③ 生图提示词 + 交付包
        prompts = self.p(DELIVERY_DIR, "生图提示词（第1批）.md")
        if self._keep(prompts):
            self.say(f"⏭️  生图提示词已存在，跳过：{self._rel(prompts)}")
        else:
            self.say("🤖 写生图提示词与交付包…")
            data = self._ask_json("asset", PROMPTS_ASK.format(
                index=self._index_digest(),
                bible=_read(bible) if os.path.isfile(bible) else "（视觉圣经还没建）"))
            rows = data.get("提示词") or []
            _write(prompts, self._render_prompts(rows))
            res.files.append(prompts)
            pack = (data.get("交付包") or "").strip()
            if pack:
                pp = self.p(DELIVERY_DIR, "交付包-01到02.md")
                _write(pp, pack)
                res.files.append(pp)
            self.say(f"✅ 生图提示词 {len(rows)} 条")

        # ④ 机械自检：三字段（缺字段不许出图）
        three = asset_index.three_fields(self.project)
        bad = [k for k, v in (three or {}).items() if v]
        if bad:
            res.notes.append(f"三字段体检没过：{'、'.join(bad)}（见 `--阶段 状态`）")
        res.detail = f"索引 {len(IDX_HEADERS)} 张 · 视觉圣经{'有' if os.path.isfile(bible) else '无'}"
        return res

    def _all_scripts(self) -> str:
        d = self.p(SCRIPT_DIR)
        if not os.path.isdir(d):
            return ""
        out = []
        for fn in sorted(os.listdir(d)):
            if re.fullmatch(r"EP\d+.*\.md", fn):
                out.append(f"<!-- {fn} -->\n" + _read(os.path.join(d, fn)))
        return "\n\n".join(out)[:40000]

    def _registry_rows_text(self) -> str:
        """已登记 ID 的紧凑清单（喂给模型，让它沿用号位）。"""
        lines = []
        for aid, row in sorted(self.registry.rows.items()):
            lines.append(f"- {aid} {self.registry.name_of(aid)} "
                         f"（{row.get('定位') or row.get('类型') or row.get('角色') or '—'}）")
        return "\n".join(lines) or "（空 —— 这是第一批）"

    def _index_digest(self) -> str:
        d = self.p(INDEX_DIR)
        if not os.path.isdir(d):
            return "（还没有索引）"
        out = []
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".md") and "视觉圣经" not in fn:
                out.append(f"<!-- {fn} -->\n" + _read(os.path.join(d, fn)))
        return "\n\n".join(out)[:20000] or "（还没有索引）"

    def _render_index(self, kind: str, rows: list) -> str:
        return (f"# {IDX_TITLE[kind]} · {os.path.basename(self.project)}\n\n"
                f"> 由 `flow --阶段 资产` 生成 ｜ 表头口径见 `02-服化道/模板/INDEX-TEMPLATES.md`\n"
                f"> ⚠️ 状态栏需 02 跑一致性 Gate 后才能升 `LOCKED`\n\n"
                f"## 一、{kind}索引\n\n"
                + _md_table(IDX_HEADERS[kind], rows))

    def _render_prompts(self, rows: list) -> str:
        head = ["# 生图提示词（第 1 批）", "",
                f"> 由 `flow --阶段 资产` 生成 ｜ 直接喂给 S2 出图（工作流 "
                f"`03 分镜首帧` / 定妆板）", ""]
        body = _md_table(["ID", "名称", "角度", "英文提示词", "负面词", "落点文件名"], rows)
        return "\n".join(head) + body

    # ═════════════════════════════════════════════════════════
    # S4 分镜：剧本 → 九列分镜表 + shots_<EP>.json
    # ═════════════════════════════════════════════════════════

    @property
    def fps(self) -> float:
        return float((self.cfg.get("video") or {}).get("fps") or 24.0)

    def stage_分镜(self) -> StageResult:
        """剧本 → 分镜。**规则版兜底 + LLM 可选增强**，落盘 JSON 供出图/出片读。"""
        res = StageResult("分镜")
        self._ensure_skeleton()
        path = self.p(SCRIPT_DIR, f"{self.ep}-剧本.md")
        if not os.path.isfile(path):
            raise StageError(f"没有 {self.ep} 的剧本：{self._rel(path)}\n"
                             f"  先跑 `--阶段 建纲`，或把剧本按 `EPxx-剧本.md` 放进去")
        title, scenes = storyboard.parse_script(_read(path))
        shots = storyboard.make_shots(scenes, fps=self.fps, ep=self.ep)
        if not shots:
            raise StageError(f"{self.ep} 剧本解析出了 {len(scenes)} 场，但一个镜头都没拆出来")
        if self.limit:
            shots = shots[:self.limit]
            res.notes.append(f"按 `--限制 {self.limit}` 只留前 {self.limit} 镜（试跑用）")

        storyboard.annotate_rules(shots, registry=self.registry)
        miss = storyboard.resolve_assets(shots, self.registry)
        unreg = storyboard.unresolved(shots, self.registry)
        note = "规则版（未接 LLM）"
        if self.want_llm():
            self.say(f"🤖 让模型补 {len(shots)} 镜的景别/摄影角度/运镜/叙事目的"
                     f"与英文提示词…")
            sys_p = self._agent_system("storyboard")
            shots, note = storyboard.enhance_shots(
                shots, lambda ask: self.llm.chat(sys_p, ask, json_mode=True))
            self.say(f"   {note}")

        md, js = storyboard.write_storyboard(
            self.project, self.ep, shots, title=title, fps=self.fps, model_note=note,
            missing=miss, unreg=unreg, target_sec=self.target_sec())
        res.files += [md, js]
        total = sum(s.seconds for s in shots)
        tgt = self.target_sec()
        res.detail = (f"{len(shots)} 镜 · {total:.1f}s（目标 {tgt:.0f}s，"
                      f"{total / tgt * 100:.0f}%）")
        self.say(f"✅ {self._rel(md)} · {self._rel(js)}")
        for k, n in miss.items():
            if n:
                res.notes.append(f"{n} 镜回填不到 {'ENV_/CHR_/CST_'[len(res.notes) % 1] or ''}"
                                 f"资产 ID（{k}）—— 号位没登记就不会自动配对，别怪机器")
        for kind, items in (("说话人", unreg.get("speaker") or {}),
                            ("场景", unreg.get("place") or {})):
            if items:
                top = "、".join(f"{k}×{v}" for k, v in
                                sorted(items.items(), key=lambda x: -x[1])[:6])
                res.notes.append(f"{len(items)} 个{kind}没登记 ID：{top}"
                                 f"（补 `03_台账/ID注册表` 后重跑分镜）")
        if total > tgt * (1 + storyboard.TOL):
            res.notes.append(f"总时长 {total:.0f}s 超目标 {tgt:.0f}s 的 "
                             f"{storyboard.TOL:.0%} —— 先改剧本再出片，别拿素材堆时长")
        res.notes.insert(0, note)
        return res

    # ═════════════════════════════════════════════════════════
    # S4 首帧：每镜一张首帧图（fl2v 的起点）
    # ═════════════════════════════════════════════════════════

    def frame_prompt(self, row: dict) -> str:
        """首帧提示词 = 分镜里的画面词 + 工作流强制的电影感/质量/文字屏蔽尾巴。

        尾巴**一字不改地追加**（`TURNAROUND-STANDARD` §六 + 文字屏蔽 §1.6）——
        全片提示词尾巴一致是画风统一的第 1 条。
        """
        base = (row.get("prompt_en") or row.get("prompt_cn") or "").strip()
        if not base:
            raise StageError(f"镜 {row.get('id')} 没有提示词 —— 拒绝出这种图（分镜没拆好）")
        tail = [self.rules.cinematic_concrete, self.rules.quality_params_en,
                self.rules.text_block_positive]
        for t in tail:
            t = (t or "").strip()
            if t and t not in base:
                base = f"{base}, {t}"
        return base

    def frame_negative(self, row: dict) -> str:
        """负面词 = 场景模块负面词 + 文字屏蔽强制反向词（含权重 1.8，§1.6）。"""
        neg = [self.rules.negative_for("environment", three_view=False),
               self.rules.text_block_negative]
        return ", ".join(dict.fromkeys(x.strip() for x in neg if x and x.strip()))

    def _shot_reference(self, row: dict) -> str:
        """这一镜的参考图：优先取主角的最新资产图（对外貌一致性最要紧的那个人）。"""
        if self.ref_mode == "off":
            return ""
        for aid in (row.get("chr_ids") or []):
            p = self.asset_image(aid)
            if p:
                return p
        return ""

    def asset_image(self, aid: str) -> str:
        """找某资产最新一版的图：先看项目里的资产目录，再看运行时的 `output/`。

        版本号取 `_v<n>` 里最大的（§一 命名规范），同版本取修改时间最新的。
        """
        cands = []
        prefix = aid[:3]
        d = self.p(ASSET_DIRS.get(prefix, ""))
        for base in (d, str(self.root / "output" / "images")):
            if not base or not os.path.isdir(base):
                continue
            for dirpath, _dirnames, files in os.walk(base):
                if prefix and aid not in dirpath and not os.path.basename(dirpath).startswith(aid):
                    continue
                for fn in files:
                    if fn.startswith(aid) and fn.lower().endswith(PNG_EXTS):
                        cands.append(os.path.join(dirpath, fn))
        if not cands:
            return ""

        def key(p):
            m = VER_RE.search(os.path.basename(p))
            return (float(m.group(1)) if m else 0.0, os.path.getmtime(p))

        return max(cands, key=key)

    def stage_首帧(self) -> StageResult:
        """按分镜表逐镜出首帧 PNG，并把文件名回写进 `shots_<EP>.json`。"""
        res = StageResult("首帧")
        data = storyboard.load_storyboard(self.project, self.ep)
        rows = data.get("shots") or []
        if not rows:
            raise StageError(f"{self.ep} 的分镜表是空的")
        if self.limit:
            rows = rows[:self.limit]
        out_dir = self.p(storyboard.frames_dir(self.ep))
        prov = self.frames_provider()
        info = prov.info()
        if not info.available:
            raise StageError(f"出图 provider `{info.name}` 不可用：{info.reason}")
        w, h = self.frames_size()
        if not self.dry:
            os.makedirs(out_dir, exist_ok=True)
        self.say(f"🖼️  出首帧：{len(rows)} 镜 · {w}×{h} · provider {info.name}")

        done, skipped, ref_used, failed = 0, 0, 0, []
        for i, row in enumerate(rows, 1):
            sid = str(row.get("id") or f"{self.ep}-S{i:02d}")
            short = sid.replace(f"{self.ep}-", "")
            out = os.path.join(out_dir, f"{short}.png")
            if os.path.isfile(out) and not self.force:
                skipped += 1
                continue
            if self.dry:
                self.say(f"🧪 预演：将出 {self._rel(out)}")
                continue
            ref = self._shot_reference(row)
            self.say(f"▶️  [{i}/{len(rows)}] {short} · {row.get('shot_size', '')} · "
                     f"{row.get('place', '')}{' · 参考图 ' + os.path.basename(ref) if ref else ''}")
            try:
                prov.generate(prompt=self.frame_prompt(row), negative_prompt=self.frame_negative(row),
                              width=w, height=h, out_path=out, n=1,
                              reference=ref or None)
            except Exception as e:                                   # noqa: BLE001
                if ref and self._is_no_loadimage(e):
                    self._ref_ok = False
                    self.say(f"⚠️  首帧工作流里没有 LoadImage 节点 —— **本次全部镜头"
                             f"不带参考图**（原因：{e}）")
                    prov.generate(prompt=self.frame_prompt(row),
                                  negative_prompt=self.frame_negative(row),
                                  width=w, height=h, out_path=out, n=1)
                else:
                    failed.append(f"{short}: {type(e).__name__}: {e}")
                    self.say(f"❌ {short} 出图失败：{e}")
                    continue
            else:
                ref_used += 1 if (ref and self._ref_ok) else 0
            row["first_frame"] = f"{short}.png"
            done += 1

        if not self.dry and done:
            storyboard.write_storyboard(
                self.project, self.ep, storyboard.rows_to_plans(rows),
                title=data.get("title", ""), fps=float(data.get("fps") or self.fps),
                model_note="首帧已出", target_sec=float(data.get("targetSec") or self.target_sec()))
            res.files.append(os.path.join(self.project, storyboard.STORYBOARD_DIR,
                                          f"shots_{self.ep}.json"))
        res.detail = f"新出 {done} 镜 · 跳过 {skipped} 镜 · 带参考图 {ref_used} 镜"
        if ref_used == 0 and not self._ref_ok:
            res.notes.append("本次**没有一镜带参考图** —— 人物外貌只靠文字约束，"
                             "跨镜漂移风险高（要么给工作流加 LoadImage，要么接受这个风险）")
        if failed:
            res.notes.append(f"{len(failed)} 镜失败：" + "；".join(failed[:5]))
            res.ok = False
        res.detail += f" · 落点 {self._rel(out_dir)}"
        return res

    @staticmethod
    def _is_no_loadimage(e: Exception) -> bool:
        return "LoadImage" in str(e) or isinstance(e, FileNotFoundError)

    # ═════════════════════════════════════════════════════════
    # S5 出片 + 成片
    # ═════════════════════════════════════════════════════════

    def shots_out_dir(self) -> str:
        return self.p(storyboard.SHOTS_DIR, self.ep)

    def stage_出片(self) -> StageResult:
        """逐镜出 mp4（ComfyUI fl2v 时间线）。已存在的镜直接跳过 —— 断点续跑。"""
        res = StageResult("出片")
        rows = storyboard.load_storyboard(self.project, self.ep).get("shots") or []
        if self.limit:
            rows = rows[:self.limit]
        shots = storyboard.to_shot_objects(rows, ep=self.ep, project_dir=self.project)
        if not shots:
            raise StageError("没有镜头可出 —— 分镜表是空的？")
        no_frame = [s.id for s in shots if not s.first_frame]
        if no_frame:
            res.notes.append(f"{len(no_frame)} 镜没有首帧（走纯文生视频）："
                             f"{'、'.join(no_frame[:8])} —— 想补就跑 `--阶段 首帧`")
        prov = self.video_provider()
        info = prov.info()
        if not info.available:
            raise StageError(f"视频 provider `{info.name}` 不可用：{info.reason}")
        out_dir = self.shots_out_dir()
        if self.dry:
            self.say(f"🧪 预演：将出 {len(shots)} 镜 → {self._rel(out_dir)}"
                     f"（provider {info.name}）")
            res.detail = f"预演 {len(shots)} 镜"
            return res
        paths = prov.render(shots, out_dir=out_dir, force=self.force)
        res.files = paths
        res.detail = f"{len(paths)} 镜 → {self._rel(out_dir)} · {sum(s.seconds for s in shots):.1f}s"
        res.notes.append(f"provider={info.name} · 工作流={os.path.basename(getattr(prov, 'workflow_path', '') or '—')}")
        return res

    def stage_成片(self) -> StageResult:
        """按镜序拼接成片。缺镜**默认报错**（不偷偷拿静帧充数）。"""
        res = StageResult("成片")
        rows = storyboard.load_storyboard(self.project, self.ep).get("shots") or []
        if self.limit:
            rows = rows[:self.limit]
        out_dir = self.shots_out_dir()
        paths, missing = [], []
        for i, r in enumerate(rows, 1):
            sid = str(r.get("id") or f"{self.ep}-S{i:02d}").replace(f"{self.ep}-", "")
            p = os.path.join(out_dir, f"{sid}.mp4")
            (paths if os.path.isfile(p) else missing).append(p if os.path.isfile(p) else sid)
        if missing:
            if self.missing_shot == "still":
                self.say(f"⚠️  {len(missing)} 镜缺片 → 按 `--缺镜用静帧` 拿首帧撑时长："
                         f"{'、'.join(missing[:8])}")
                for sid in missing:
                    row = next((r for r in rows
                                if str(r.get("id", "")).endswith(sid)), None)
                    ff = (row or {}).get("first_frame") or ""
                    fp = os.path.join(self.project, storyboard.frames_dir(self.ep),
                                      os.path.basename(ff)) if ff else ""
                    if not fp or not os.path.isfile(fp):
                        raise StageError(f"镜 {sid} 既没片也没首帧，撑不出静帧 —— "
                                         f"先跑 `--阶段 首帧`")
                    p = os.path.join(out_dir, f"{sid}.mp4")
                    film.still_clip(fp, float((row or {}).get("seconds") or 5.0), p,
                                    fps=int(self.fps))
                    paths.append(p)
            else:
                raise StageError(
                    f"{len(missing)} 镜还没出片：{'、'.join(missing[:10])}"
                    f"{' …' if len(missing) > 10 else ''}\n"
                    f"  先跑 `--阶段 出片`；确要用首帧撑时长，显式加 `--缺镜用静帧`"
                    f"（**默认不撑** —— 静帧会让成片变成 PPT，得你自己点头）")
        order = {str(r.get("id") or f"{self.ep}-S{i:02d}").replace(f"{self.ep}-", ""): i
                 for i, r in enumerate(rows, 1)}
        paths.sort(key=lambda p: order.get(os.path.splitext(os.path.basename(p))[0], 999))
        out = self.p(storyboard.SHOTS_DIR, f"{self.ep}_成片.mp4")
        if self.dry:
            self.say(f"🧪 预演：将拼接 {len(paths)} 段 → {self._rel(out)}")
            res.detail = f"预演 {len(paths)} 段"
            return res
        report = film.concat_videos(paths, out)
        res.files = [out]
        res.detail = report.line()
        self.say(f"🎬 {self._rel(out)} · {report.line()}")
        return res

    # ═════════════════════════════════════════════════════════
    # 跑 / 状态
    # ═════════════════════════════════════════════════════════

    def run(self, keys: list | None = None) -> list:
        """顺序跑（默认全跑）。某阶段抛错就**停下**，把已完成的阶段结果一起返回。"""
        import time as _t
        keys = list(keys or ORDER)
        unknown = [k for k in keys if k not in BY_KEY]
        if unknown:
            raise StageError(f"没有这些阶段：{'、'.join(unknown)}（可选 {'、'.join(ORDER)}）")
        results = []
        for k in keys:
            spec = BY_KEY[k]
            self.hr(f"【{k}】{spec.code} · {spec.what}")
            t0 = _t.time()
            try:
                r = getattr(self, f"stage_{k}")()
            except StageError as e:
                results.append(StageResult(k, ok=False, detail=str(e)))
                self.say(f"❌ 【{k}】失败：{e}")
                break
            except Exception as e:                                       # noqa: BLE001
                results.append(StageResult(k, ok=False,
                                           detail=f"{type(e).__name__}: {e}"))
                self.say(f"❌ 【{k}】异常：{type(e).__name__}: {e}")
                break
            r.detail = f"{r.detail} · {_t.time() - t0:.1f}s"
            self.say(f"── 【{k}】完成：{r.detail}")
            for n in r.notes:
                self.say("   ⚠️  " + n)
            results.append(r)
        self.hr()
        ok = all(r.ok for r in results) and len(results) == len(keys)
        self.say("🎉 全流程跑完" if ok else "⚠️  流程没跑完（见上面失败的那一步）")
        return results

    def status(self) -> list:
        """体检：每一阶段"有没有产物、够不够用"。不跑任何生成。"""
        L = []
        rows = []
        d = self.p(SCRIPT_DIR)
        scripts = sorted(f for f in os.listdir(d)) if os.path.isdir(d) else []
        # 正则**先编出来**：本例的 venv 是 Python 3.11，f-string 表达式里
        # **不许出现反斜杠**（PEP 701 才放开，要 3.12+）。写进 f-string 的后果
        # 不是这一行报错，而是**整个模块编译不过** —— `main.py -h` 都起不来。
        ep_pat = re.compile(r"EP\d+.*\.md")
        rows.append(("剧本", f"{sum(1 for f in scripts if ep_pat.fullmatch(f))} 集",
                     self._rel(d) if os.path.isdir(d) else "缺"))
        idx = self.p(INDEX_DIR)
        n_idx = len([f for f in os.listdir(idx) if f.endswith(".md")]) \
            if os.path.isdir(idx) else 0
        rows.append(("资产索引", f"{n_idx} 份 md", self._rel(idx) if n_idx else "缺"))
        try:
            data = storyboard.load_storyboard(self.project, self.ep)
        except FileNotFoundError as e:
            rows.append((f"{self.ep} 分镜", "缺", str(e)))
        else:
            js = data.get("shots") or []
            tot = sum(float(r.get("seconds") or 0) for r in js)
            rows.append((f"{self.ep} 分镜", f"{len(js)} 镜 / {tot:.1f}s",
                         f"目标 {self.target_sec():.0f}s"))
            fd = self.p(storyboard.frames_dir(self.ep))
            have = len([f for f in os.listdir(fd) if f.lower().endswith(PNG_EXTS)]) \
                if os.path.isdir(fd) else 0
            rows.append(("　首帧", f"{have}/{len(js)}", self._rel(fd) if have else "缺"))
            sd = self.shots_out_dir()
            clips = [f for f in os.listdir(sd) if f.endswith(".mp4")] \
                if os.path.isdir(sd) else []
            rows.append(("　出片", f"{len(clips)}/{len(js)}",
                         self._rel(sd) if clips else "缺"))
            fin = self.p(storyboard.SHOTS_DIR, f"{self.ep}_成片.mp4")
            rows.append(("　成片", "有" if os.path.isfile(fin) else "缺",
                         self._rel(fin) if os.path.isfile(fin) else "—"))
        reg = self.registry
        # ⚠️ `by_prefix` 返回的是 **dict**（`{ID: 行}`），`sorted()` 排出来的是它的**键**。
        #    原写法 `sorted(...)[-1:]` 取到的是**切片**（一个 list），拿去做 `join` 会抛
        #    `TypeError: expected str instance, list found`。
        #    ⚠️ 关键在于它**只在"项目已经有 ID 注册表"时才崩** —— 空项目跑这一步
        #       时 `by_prefix` 全是空 dict，`[-1:]` 是空 list，`join` 里没有非串项，
        #       于是照样通过。空跑自检因此永远抓不到它。
        def _top(prefix: str) -> str:
            ids = sorted(reg.by_prefix(prefix))
            return ids[-1] if ids else ""

        tops = "、".join(x for x in (_top(p) for p in ("CHR", "CST", "PRP", "ENV")) if x)
        rows.append(("ID 注册表", f"{len(reg.rows)} 个 ID", tops or "缺"))
        if reg.errors:
            rows.append(("注册表问题", f"{len(reg.errors)} 条", reg.errors[0]))
        return rows
