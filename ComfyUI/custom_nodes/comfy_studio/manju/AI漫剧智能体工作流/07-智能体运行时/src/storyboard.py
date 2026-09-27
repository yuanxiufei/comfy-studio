"""分镜（S4）：把文字剧本拆成「能交给 ComfyUI 出片的镜头表」。

格式以 `01-剧本文本/模板/剧本与角色小传模板.md` §一为**硬标准**：
`【场景X：地点／时间】` 标题、`（　）` 包住的动作描写、`角色名：台词`、`角色名（情绪）：台词`。
所以这里按行首标记解析，不猜语义。

为什么规则拆镜就够用：剧本已经是结构化的（场次头 + 动作段 + 台词行），
关键信息都在标记里；规则拆镜保证**每镜都能指回原文某一行**（可驳回、可追溯）。
LLM 只用来锦上添花（景别/运镜/英文提示词），拿不到就留空 —— 不编。

切镜口径（会写进分镜表抬头，别让它变成"隐式约定"）：
  · 一「场」= 一个连续时空，不跨场合并；
  · 一个动作段（`（）`）= 一镜的**起点**；相邻动作段若都短，合并成一镜省镜头；
  · 台词**自己成一镜**，排在"同场最近的动作"之后（保证镜头顺序 = 剧本顺序）；
    一句台词太长（超过 `max_sec`）按标点拆成多镜；
  · 时长 = 台词字数/语速（或动作长度）+ 起手停顿，夹到 [min_sec, max_sec]，
    最后**吸附到 17k+5 帧**（MiniMax 的换算），免得"分镜写 5s、出片 5.17s"对不上。

景别/摄影角度/运镜/叙事目的四列**先由规则给默认值**（`annotate_rules`），
再用 `enhance_shots` 让 LLM 覆盖 —— 顺序不能反：LLM 挂了也必须有一张能拍的表格。
规则版是**可读、可驳回**的默认值，所以分镜表抬头会写明它是规则版。

资产 ID（ENV_/CHR_/CST_/PRP_）由 `asset_index.Registry` 从项目的
`03_台账/ID注册表（ID-REGISTRY）.md` + `02_资产索引/*.md` 查出后回填 ——
S4 门禁要求"每镜标了景别/机位/时长/**对应 ENV/CST/PRP**"；
查不到就留空并计数，**不编 ID**（号位永不复用是硬规则）。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field, fields

from .video_provider import Shot, minimax_frames

__all__ = ["Scene", "ShotPlan", "annotate_rules", "enhance_shots", "make_shots",
           "parse_script", "resolve_assets", "shots_markdown", "to_shot_objects",
           "write_storyboard", "STORYBOARD_DIR", "frames_dir"]

SCENE_RE = re.compile(r"^【\s*场景\s*(\d+)\s*[：:]\s*(.*?)\s*】\s*$")
LINE_RE = re.compile(r"^([^（()：:]{1,12}?)\s*(?:[（(]([^）)]{1,16})[）)])?\s*[：:]\s*(.+)$")
ACTION_RE = re.compile(r"^[（(](.+)[）)]\s*$")
# `---` / `***` / `___` 这类分隔线不是动作描写；`【本集完】` 这类括注也不是场次头。
HR_RE = re.compile(r"^([-*_=])\1{2,}$")
BRACKET_ONLY_RE = re.compile(r"^【.+】$")
LEAD_TONE_RE = re.compile(r"^[（(]([^）)]{1,20})[）)]\s*(.*)$")
SENT_SPLIT = re.compile(r"(?<=[。！？!?…；;])\s*")
MD_EMPHASIS_RE = re.compile(r"\*\*|__|`")

# ── 项目骨架里的固定落点（`生产流程规范（S0-S7）.md` §一 / §七）──
STORYBOARD_DIR = "08_STORYBOARDS"
SHOTS_DIR = "09_SHOTS"

# ── 节奏常数（改了会直接改总时长，改完必须重跑分镜并核对时长列）──
# ⚠️ 本段是**台词语速与目标时长的唯一来源**：
#    · `CPS`       —— `pipeline` 算台词字数预算与时长估计时读它（`storyboard.CPS`）
#    · `TARGET_SEC`—— `pipeline.target_sec()` 的兜底值 + `shots_markdown` 默认值
#    2026-09-27 之前 `flow_core` 另存了 `LINE_CPS = 4.5` 与 `TARGET_SEC = 105.0`
#    两份同值副本（三处 105.0 中的两处），已删 —— 同值副本的失效模式是
#    "改一处、另几处静默失效"，而本项目反复吃过这个亏。
ACT_BASE = 0.9        # 动作段起手：镜头切过去、眼睛跟上，约 0.9s
ACT_CPS = 18.0        # 动作段读画面速度（字/秒）
CPS = 4.5             # 台词配音语速（字/秒）
MIN_SEC, MAX_SEC = 2.6, 6.5   # 单镜时长上下限（秒）
PACK_SEC = 4.0        # 装箱目标：≈ 4s/镜（与物料单"时长 ÷ 4s/镜"的估算一致）
TOL = 0.30            # 总时长对目标的容差：超 30% 才算"剧本写长了"，要回去改剧本
TARGET_SEC = 105.0    # 物料单缺失时的兜底目标（2 分钟级短剧）


def frames_dir(ep: str) -> str:
    """每镜首帧图的落点（相对项目根）：`08_STORYBOARDS/frames_<EP>/`。

    为什么放 S4 的目录而不是 `02_CHARACTERS/`：首帧图**不是角色资产**，
    它是一镜一次的产物（角色资产是可复用的三视图）。混在一起会让
    "资产索引回填"分不清哪些该打勾。
    """
    return f"{STORYBOARD_DIR}/frames_{ep}"


@dataclass
class Scene:
    no: int
    place: str = ""      # 地点（用于映射 ENV_XXX）
    time: str = ""       # 时间（进分镜表的"时间"信息里）
    blocks: list = field(default_factory=list)   # {"kind","text","speaker","tone"}


@dataclass
class ShotPlan:
    """一镜的完整交代：出图要什么、出视频要什么、这段话是谁说的。"""
    id: str
    scene_no: int
    place: str
    time: str
    seconds: float
    frames: int
    kind: str                    # "action" / "line"
    text: str                    # 屏幕里要发生的事（台词镜 = 台词原文）
    prev_action: str = ""        # 之前发生的动作，给首帧画面当上下文
    speaker: str = ""
    tone: str = ""
    shot_size: str = ""          # 景别（规则默认值，LLM 可覆盖）
    camera: str = ""             # 摄影角度
    movement: str = ""           # 运镜
    purpose: str = ""            # 叙事目的（门禁要求非空且具体）
    prompt_cn: str = ""          # 出图/出视频用的中文提示词
    prompt_en: str = ""          # 英文提示词（可选增强）
    first_frame: str = ""        # 首帧图路径（出图阶段回填）
    env_id: str = ""             # ENV_XXX（由 asset_index 回填）
    chr_ids: list = field(default_factory=list)   # CHR_XXX
    cst_ids: list = field(default_factory=list)   # CST_XXX
    prp_ids: list = field(default_factory=list)   # PRP_XXX
    note: str = ""

    def assets(self) -> list:
        return [*self.chr_ids, *self.cst_ids, *self.prp_ids] + ([self.env_id] if self.env_id else [])

    def voice(self) -> str:
        """分镜表「声音」列：台词镜给「谁 + 怎么说 + 说什么」。"""
        if self.kind != "line":
            return "—（环境音待 S6）"
        tone = f"（{self.tone}）" if self.tone else ""
        return f"{self.speaker or '画外'}{tone}：{self.text}"

    def size_cam(self) -> str:
        return " · ".join(x for x in (self.shot_size, self.camera) if x) or "—"

    def note_line(self) -> str:
        return " · ".join(x for x in (self.shot_size, self.speaker + self.tone) if x)


def _clean(s: str) -> str:
    """去掉 markdown 强调符（正文里会出现 `**悬在半空**` 这种写法）。"""
    return MD_EMPHASIS_RE.sub("", s or "").strip()


def parse_script(text: str) -> tuple:
    """按硬标准解析剧本：返回 (标题, 场次列表)。解析不出场次就报错。"""
    title, scenes, cur = "", [], None
    for raw in (text or "").splitlines():
        ln = raw.strip()
        if not ln:
            continue
        if not title and ln.startswith("#"):
            title = ln.lstrip("# ").strip()
            continue
        m = SCENE_RE.match(ln)
        if m:
            cur = Scene(no=int(m.group(1)))
            head = m.group(2)
            if "／" in head or "/" in head:
                cur.place, cur.time = re.split(r"\s*[／/]\s*", head, maxsplit=1)
            else:
                cur.place = head
            cur.place, cur.time = cur.place.strip(" ·"), cur.time.strip()
            scenes.append(cur)
            continue
        if cur is None:
            continue                              # 抬头/表格/说明段：不进正文
        if ln.startswith(">") or ln.startswith("|") or ln.startswith("#"):
            continue                              # 引用块 / 表格 / 小节标题
        if HR_RE.match(ln) or BRACKET_ONLY_RE.match(ln):
            continue                              # 分隔线 / `【本集完 · EP01】`
        am = ACTION_RE.match(ln)
        if am:
            cur.blocks.append({"kind": "action", "text": _clean(am.group(1)),
                               "speaker": "", "tone": ""})
            continue
        lm = LINE_RE.match(ln)
        if lm:
            tone, body = (lm.group(2) or "").strip(), _clean(lm.group(3))
            # 实测剧本有两种写法：`角色名（情绪）：台词` 与 `角色名：（动作）台词`。
            # 后者的括注落在冒号**后面**，上面那条正则抓不到 → 这里补抓，
            # 免得括注混进台词里（S6 配音要的是一句干净的台词）。
            if not tone:
                m2 = LEAD_TONE_RE.match(body)
                if m2:
                    tone, body = m2.group(1).strip(), m2.group(2).strip()
            cur.blocks.append({"kind": "line", "text": body,
                               "speaker": lm.group(1).strip(), "tone": tone})
            continue
        cur.blocks.append({"kind": "action", "text": _clean(ln), "speaker": "", "tone": ""})

    if not scenes:
        raise ValueError("剧本里一场都没解析出来 —— 检查场次标题是否是 "
                         "`【场景1：地点／时间】` 这种硬标准格式")
    return title or "未命名", scenes


def _raw_secs(text: str, kind: str, cps: float) -> float:
    """单块素材的"原始"时长：台词按语速算，动作段按"看得清 + 起手"算。

    这里**不夹** [min, max] —— 上下限是给**整镜**的（`_shot_secs`）。
    要是每块动作都先垫到 3.2s，一镜里塞三块就直接爆表（第一版就是这么把
    EP01 算成 133s、EP04 算成 400s，跟"每集约 105 秒"的硬指标打架的）。

    常数出处：台词语速 4.5 字/秒（中文配音常规区间 4–5 字/秒）；
    动作段按 18 字/秒读画面 + 0.9s 起手（`每集物料单（EP01-EP05）.md` §一
    按 **4s/镜**估算分镜数，EP01≈26 镜 / 105s，就是拿这个尺度定的）。
    这两个数是**可调参数**，改了要重跑分镜并核对时长列。
    """
    n = len(re.sub(r"\s", "", text or ""))
    return (n / cps + 0.4) if kind == "line" else (ACT_BASE + n / ACT_CPS)


def _split_long_line(text: str, *, cps: float, max_sec: float) -> list:
    """一口气说不完的台词按标点切成几条 —— 保证"一镜一句"不超时。"""
    buf, out = "", []
    for ch in SENT_SPLIT.split(text):
        ch = ch.strip()
        if not ch:
            continue
        if buf and _raw_secs(buf + ch, "line", cps) > max_sec:
            out.append(buf)
            buf = ch
        else:
            buf += ch
    if buf:
        out.append(buf)
    return out


def _shot_secs(cur: dict, *, cps: float, min_sec: float, max_sec: float) -> float:
    """整镜时长 = max(动作总时长, 台词时长)，再夹到 [min_sec, max_sec]。

    取 max 而不是相加：一镜里只有**一条**音轨（S6 一句配音），
    动作是在说这句话的同时发生的，不额外占时间。
    """
    acts = sum(_raw_secs(a, "action", cps) for a in cur["acts"])
    line = _raw_secs(cur["line"], "line", cps) if cur["line"] else 0.0
    return max(min_sec, min(max_sec, max(acts, line)))


def make_shots(scenes: list, *, fps: float = 24.0, min_sec: float = MIN_SEC,
               max_sec: float = MAX_SEC, pack_sec: float = PACK_SEC, cps: float = CPS,
               ep: str = "EP01") -> list:
    """场次 → 镜头表。

    切镜用**装箱**：把动作段/台词段按剧本顺序灌进同一镜，直到
    「这镜已经有台词了」或「已经够 `pack_sec` 秒」就收口。
    为什么不是"一块一镜"：那样 105 秒的一集会被切成 34 镜（EP04 到 80 镜 / 400s），
    跟 S1 的"每集约 105 秒"硬指标直接打架；
    为什么一镜最多一句台词：一镜只配**一条**音轨（S6），多句会挤在同一条里。

    时长吸附到 17k+5 帧后**回写为秒** —— 分镜表上写的秒数就是出片真实时长。
    """
    shots: list = []

    for sc in scenes:
        units: list = []
        for b in sc.blocks:
            if b["kind"] == "line":
                for part in _split_long_line(b["text"], cps=cps, max_sec=max_sec):
                    units.append(("line", part, b["speaker"], b["tone"]))
            else:
                units.append(("action", b["text"], "", ""))

        cur: dict | None = None
        last_action = ""

        def flush(buf, _sc=sc):
            if not buf or not (buf["acts"] or buf["line"]):
                return
            sec = _shot_secs(buf, cps=cps, min_sec=min_sec, max_sec=max_sec)
            fr = minimax_frames(sec, fps)
            acts = "；".join(buf["acts"])
            if buf["line"]:
                who = (f"{buf['speaker']}（{buf['tone']}）" if buf["tone"]
                       else (buf["speaker"] or "画外"))
                body = f"{acts}；{who}开口说：「{buf['line']}」。" if acts else \
                       f"{who}开口说：「{buf['line']}」。"
                kind, text = "line", buf["line"]
            else:
                body, kind, text = acts, "action", acts
            shots.append(ShotPlan(
                id=f"{ep}-S{len(shots) + 1:02d}", scene_no=_sc.no, place=_sc.place,
                time=_sc.time, seconds=round(fr / fps, 3), frames=fr, kind=kind, text=text,
                prev_action=buf["prev"],
                speaker=buf["speaker"] if buf["line"] else "",
                tone=buf["tone"] if buf["line"] else "",
                prompt_cn=f"{_sc.place}。{body}"))

        for kind, text, spk, tone in units:
            if cur is not None and (cur["line"] or _shot_secs(cur, cps=cps, min_sec=min_sec,
                                                              max_sec=max_sec) >= pack_sec):
                flush(cur)
                cur = None
            if cur is None:
                cur = {"acts": [], "line": "", "speaker": spk, "tone": tone,
                       "prev": last_action}
            if kind == "line":
                cur["line"], cur["speaker"], cur["tone"] = text, spk, tone
            else:
                cur["acts"].append(text)
                last_action = text
        flush(cur)
    return shots


# ── 规则版景别/机位/运镜/叙事目的（LLM 没接上也得有一张能拍的表格）──

DETAIL_WORDS = ("烟头", "手指", "手", "腕", "眼睛", "眼", "挂钟", "钟", "脚", "门缝",
                "戒指", "项链", "请柬", "襁褓", "杯", "手表")
WIDE_WORDS = ("走廊", "大厅", "街道", "院子", "水潭", "小屋", "庄园", "客厅", "书房",
              "教室", "门口", "广场")

SIZE_BY_FIRST = ("全景", "平视", "固定")
SIZE_BY_DETAIL = ("特写", "平视", "缓推")
SIZE_BY_LINE = ("中近景", "平视", "固定")
SIZE_BY_WIDE = ("全景", "平视", "固定")
SIZE_DEFAULT = ("中景", "平视", "固定")


def _camera_for(s: ShotPlan, first_of_scene: bool) -> tuple:
    if first_of_scene:
        return SIZE_BY_FIRST
    if s.kind == "line":
        return SIZE_BY_LINE
    if any(w in s.text for w in DETAIL_WORDS):
        return SIZE_BY_DETAIL
    if any(w in s.text for w in WIDE_WORDS):
        return SIZE_BY_WIDE
    return SIZE_DEFAULT


def _purpose_for(s: ShotPlan, first_of_scene: bool) -> str:
    """叙事目的：门禁要「非空 + 具体到视听手段」，所以这里**引用本镜的实物**
    （景别/地点/道具/台词首句），不写"推动剧情"这种谁都能套的空话。"""
    where = f"「{s.place}」" + (f"（{s.time}）" if s.time else "")
    if first_of_scene:
        return f"交代：用 {s.shot_size}+{s.movement} 先立住 {where} 的空间关系与在场人物"
    if s.kind == "line":
        head = s.text[:12] + ("…" if len(s.text) > 12 else "")
        return (f"推进：以 {s.shot_size} 接住 {s.speaker or '画外'} 这句「{head}」，"
                f"观众要同时听见内容、看见口型与反应")
    hit = next((w for w in DETAIL_WORDS if w in s.text), "")
    if hit:
        return f"强调：把「{hit}」放进画面（{s.shot_size}），它是这一幕的视觉记号"
    head = s.text[:14] + ("…" if len(s.text) > 14 else "")
    return f"渲染：以 {s.shot_size}+{s.movement} 呈现「{head}」的动作细节，压住节奏"


def resolve_assets(shots: list, registry) -> dict:
    """回填 ENV_/CHR_/CST_/PRP_。返回查不到的计数 —— **不编 ID**（号位永不复用）。"""
    miss = {"env": 0, "chr": 0, "cst": 0}
    for s in shots:
        if not s.env_id:
            s.env_id = registry.env_for(s.place) or ""
            if not s.env_id:
                miss["env"] += 1
        if not s.chr_ids:
            for n in ([s.speaker] if s.speaker else []) + registry.known_names(s.text):
                cid = registry.char_for(n)
                if cid and cid not in s.chr_ids:
                    s.chr_ids.append(cid)
        if s.kind == "line" and not s.chr_ids:
            miss["chr"] += 1
        if not s.cst_ids:
            for cid in s.chr_ids:
                for cst in registry.costumes_of(cid, scene_no=s.scene_no):
                    if cst not in s.cst_ids:
                        s.cst_ids.append(cst)
            if s.kind == "line" and not s.cst_ids:
                miss["cst"] += 1
        if not s.prp_ids:
            s.prp_ids = registry.props_in(s.text)
    return miss


def annotate_rules(shots: list, *, registry=None) -> list:
    """给每镜补规则版景别/摄影角度/运镜/叙事目的（+ 有 registry 时回填资产 ID）。

    已填的字段**不覆盖** —— 这样"人工改过的分镜表"重跑不会被规则冲掉。
    """
    for i, s in enumerate(shots):
        first = i == 0 or shots[i - 1].scene_no != s.scene_no
        size, ang, mov = _camera_for(s, first)
        s.shot_size = s.shot_size or size
        s.camera = s.camera or ang
        s.movement = s.movement or mov
        s.purpose = s.purpose or _purpose_for(s, first)
    if registry is not None:
        resolve_assets(shots, registry)
    return shots


# ── 落盘 ──

MD_COLUMNS = ["镜号", "景别", "摄影角度", "运镜", "画面内容", "声音", "时长", "叙事目的", "备注"]


def _cell(x: str) -> str:
    """表格转义：竖线会截断单元格，换行会截断整行。"""
    return str(x or "—").replace("|", "／").replace("\n", " ").strip() or "—"


def unresolved(shots: list, registry) -> dict:
    """查不到 ID 的**名字**清单（说话人 / 场景）—— 用来告诉人"去补哪几行登记"。

    为什么不做同义猜测：实测 EP04 的 `老头` 与注册表的 `老人（九幻真人）` 是同一人，
    但机器无权替人认定这件事（号位一旦复用/错挂，后面所有集都会跟着错）。
    """
    spk, place = {}, {}
    for s in shots:
        if s.speaker and not registry.char_for(s.speaker):
            spk[s.speaker] = spk.get(s.speaker, 0) + 1
        if s.place and not registry.env_for(s.place):
            place[s.place] = place.get(s.place, 0) + 1
    return {"speaker": spk, "place": place}


def shots_markdown(title: str, shots: list, *, ep: str, fps: float,
                   model_note: str = "", missing: dict | None = None,
                   target_sec: float = TARGET_SEC, unreg: dict | None = None) -> str:
    """写成分镜表（人看的那份）。

    主表是工作流硬标准的**九列**（`03-分镜导演/00-主控智能体.md`：镜号/景别/摄影角度/
    运镜/画面内容/声音/时长/叙事目的/备注），S4 门禁扫的就是这几列；
    出片参数（帧数/首帧/提示词）另起一张表 —— 免得把机器字段混进九列里。
    """
    total = sum(s.seconds for s in shots)
    miss = missing or {}
    # 去掉标题开头重复的 `EP01 · ` / `EP01-`。正则**必须提到 f-string 外面**：
    # Python 3.11 的 f-string `{}` 表达式里**不许出现反斜杠**（PEP 701 才放开，
    # 要 3.12+）—— 写在里面不是这一行报错，而是**整个模块编译不过**。
    # 另：原写法里的 `s*` 是丢了反斜杠的 `\s*`（那是个静默失效的正则）。
    _head_pat = re.compile(rf"^\s*{re.escape(ep)}\s*[·\-—]\s*")
    head = [
        f"# {ep} 分镜表 · {_head_pat.sub('', title or ep)}", "",
        "> 由 `07-智能体运行时/main.py flow --阶段 分镜` 从剧本生成；**改这里不会回改剧本**。",
        f"> 拆镜口径：按剧本顺序**装箱**（动作段+台词段灌进同一镜），"
        f"一镜最多一句台词、灌满 {PACK_SEC:g} 秒或已有台词即收口；"
        f"单镜夹在 [{MIN_SEC:g}, {MAX_SEC:g}] 秒。",
        f"> 节奏常数：台词 {CPS:g} 字/秒、动作段 {ACT_BASE:g}s 起手 + {ACT_CPS:g} 字/秒"
        f"（物料单按 4s/镜估算分镜数，就是拿这个尺度定的）。",
        f"> 帧数 = `max(5, round(秒×{fps:g}))` 吸附 17k+5（与 MiniMax 换算一致）"
        f"；表上的秒数就是出片真实时长。",
        "> 景别/摄影角度/运镜/叙事目的 = **规则版默认值**（可用 LLM 覆盖，见 `enhance_shots`）。",
        f"> 镜头数 **{len(shots)}** · 合计 **{total:.2f}s**（≈ {total / 60:.2f} 分钟）"
        f" · 帧数合计 **{sum(s.frames for s in shots)}**。",
    ]
    if target_sec:
        head.append(f"> 本集目标时长 **{target_sec:g}s**（读自项目物料单）→ 实际 "
                    f"**{total / target_sec:.2f}×**。")
        if abs(total - target_sec) > target_sec * TOL:
            head.append(f"> ❌ **时长对不上 S1 硬指标**（超 {TOL:.0%}）：目标 {target_sec:g}s，"
                        f"实际 {total:.1f}s。分镜不负责删台词 —— 要回去改**剧本**"
                        f"（合并/删减台词行）后重跑本步。")
    if any(miss.values()):
        head.append(f"> ⚠️ 资产 ID 有查不到的：ENV ×{miss.get('env', 0)} · "
                    f"CHR ×{miss.get('chr', 0)} · CST ×{miss.get('cst', 0)} "
                    f"—— 表里留空，**没有编 ID**；请先补 `03_台账/ID注册表`。")
    unreg = unreg or {}
    if unreg.get("speaker") or unreg.get("place"):
        head.append("> ⚠️ 注册表里没有的名字（**机器不猜**，请人工确认后补登记）：")
        for nm, n in sorted(unreg.get("speaker", {}).items()):
            head.append(f">   · 说话人 `{nm}`（{n} 镜）")
        for nm, n in sorted(unreg.get("place", {}).items()):
            head.append(f">   · 场景 `{nm}`（{n} 镜）")
    if model_note:
        head.append(f"> {model_note}")
    head += ["", "## 一、分镜表", "",
             "| " + " | ".join(MD_COLUMNS) + " |",
             "|" + "---|" * len(MD_COLUMNS)]
    for s in shots:
        body = s.prompt_cn
        if body.startswith(s.place + "。"):
            body = body[len(s.place) + 1:]          # 地点已经进了【S01 …】前缀，别再写一遍
        content = (f"【S{s.scene_no:02d} {s.place}" + (f"／{s.time}" if s.time else "")
                   + f"】{body}")
        head.append("| {id} | {sz} | {cam} | {mv} | {body} | {vo} | {sec:.2f}s（{fr}帧） | "
                    "{pur} | {note} |".format(
                        id=s.id, sz=_cell(s.shot_size), cam=_cell(s.camera), mv=_cell(s.movement),
                        body=_cell(content), vo=_cell(s.voice()), sec=s.seconds, fr=s.frames,
                        pur=_cell(s.purpose),
                        note=_cell(" · ".join(s.assets()) or "待补资产 ID")))
    head += ["", "## 二、出片参数（机器读这张 · 与 `shots_%s.json` 同源）" % ep, "",
             "| 镜号 | 秒 | 帧 | 首帧 | 出片提示词（送 ComfyUI 的就是它） |",
             "|---|---|---|---|---|"]
    for s in shots:
        head.append("| {id} | {sec:.2f} | {fr} | {ff} | {p} |".format(
            id=s.id, sec=s.seconds, fr=s.frames,
            ff=_cell(os.path.basename(s.first_frame) if s.first_frame else "待出图"),
            p=_cell(s.prompt_en or s.prompt_cn)))
    return "\n".join(head) + "\n"


def write_storyboard(project_dir: str, ep: str, shots: list, *, title: str = "",
                     fps: float = 24.0, model_note: str = "",
                     missing: dict | None = None, target_sec: float = TARGET_SEC,
                     unreg: dict | None = None) -> tuple:
    """落盘：`08_STORYBOARDS/分镜表_<EP>.md` + `08_STORYBOARDS/shots_<EP>.json`。"""
    out_dir = os.path.join(project_dir, STORYBOARD_DIR)
    os.makedirs(out_dir, exist_ok=True)
    md = os.path.join(out_dir, f"分镜表_{ep}.md")
    js = os.path.join(out_dir, f"shots_{ep}.json")
    with open(md, "w", encoding="utf-8") as f:
        f.write(shots_markdown(title or ep, shots, ep=ep, fps=fps, model_note=model_note,
                               missing=missing, target_sec=target_sec, unreg=unreg))
    with open(js, "w", encoding="utf-8") as f:
        json.dump({"ep": ep, "title": title, "fps": fps, "targetSec": target_sec,
                   "totalSec": round(sum(s.seconds for s in shots), 3),
                   "shots": [asdict(s) for s in shots]}, f, ensure_ascii=False, indent=2)
    return md, js


def load_storyboard(project_dir: str, ep: str) -> dict:
    """读回分镜 JSON（出图/出片阶段用；不存在就报错，不静默返回空）。"""
    js = os.path.join(project_dir, STORYBOARD_DIR, f"shots_{ep}.json")
    if not os.path.isfile(js):
        raise FileNotFoundError(f"没有分镜表：{js} —— 先跑 `flow --阶段 分镜`")
    with open(js, encoding="utf-8") as f:
        return json.load(f)


def rows_to_plans(rows: list) -> list:
    """分镜 JSON 的行 → `ShotPlan` 列表（改完再交给 `write_storyboard` 落盘）。

    为什么要这条回路：出图阶段会把首帧图名写回 JSON，而分镜表（md）也该跟着更新
    —— 否则人看表格还以为"待出图"。字段按名对上，JSON 里多出来的键忽略。
    """
    names = {f.name for f in fields(ShotPlan)}
    out = []
    for r in rows or []:
        kw = {k: v for k, v in r.items() if k in names}
        for lst in ("chr_ids", "cst_ids", "prp_ids"):
            if kw.get(lst) is None:
                kw[lst] = []
        out.append(ShotPlan(**kw))
    return out


def to_shot_objects(rows: list, *, ep: str, project_dir: str,
                    frames_sub: str | None = None) -> list:
    """分镜 JSON → 出片用的 `Shot`（把首帧图路径补成项目内的绝对路径）。"""
    sub = frames_sub or frames_dir(ep)
    out = []
    for r in rows:
        sid = str(r.get("id") or f"{ep}-S{len(out) + 1:02d}")
        ff = r.get("first_frame") or ""
        if ff and not os.path.isabs(ff):
            ff = os.path.join(project_dir, sub, os.path.basename(ff))
        out.append(Shot(
            id=sid.replace(f"{ep}-", ""),          # 产物名用 S01 这种短的
            prompt=(r.get("prompt_en") or r.get("prompt_cn") or "").strip(),
            seconds=float(r.get("seconds") or 5.0),
            first_frame=os.path.abspath(ff) if ff and os.path.isfile(ff) else "",
            seed=r.get("seed"),
            note=" · ".join(x for x in (r.get("place", ""),
                                        r.get("size_cam") or r.get("shot_size", ""),
                                        r.get("speaker", "")) if x)))
    return out


def enhance_shots(shots: list, chat) -> tuple:
    """可选：让 LLM 覆盖「景别 / 摄影角度 / 运镜 / 叙事目的」并补英文提示词。

    `annotate_rules` 已经先给过一套**规则版**默认值，这里是模型版覆盖 ——
    所以 LLM 挂了绝不能拦流程（见下面的 `except`）。

    ⚠️ 景别与摄影角度是**两个字段**（`shot_size` / `camera`）：九列分镜表里
    「景别」「摄影角度」本来就是两列（`03-分镜导演/00-主控智能体.md`），
    第一版把它们塞进同一个字段，等于白丢一列。

    下面提示词里的枚举与硬要求照 `智能体搭建参考md/分镜导演助手_完整迁移配置.md`
    的口径写（§九~§十八 的枚举、§三十三 前景/中景/背景、§二十四 一致性、
    §二十七 不要都是正面肖像）—— 那是**对外迁移规格**，不是本仓权威；
    与工作流冲突时以工作流为准。失败降级为警告，不拦流程。
    """
    if not shots or chat is None:
        return shots, "未启用"
    rows = [{"id": s.id, "场": s.place, "时间": s.time, "内容": s.text, "说话人": s.speaker}
            for s in shots]
    ask = (
        "你是分镜导演。下面是一部中国风漫剧的镜头列表。为每个镜头补五项，"
        "只输出 JSON 数组，不要解释：\n"
        '[{"id":"<原样>","景别":"中近景","摄影角度":"平视","运镜":"固定",'
        '"叙事目的":"这一镜在叙事上干什么，要具体到视听手段",'
        '"英文提示词":"给文生图模型的英文提示词，含人物外貌、服装、场景、光线、镜头"'
        '与前景／中景／背景，逗号分隔，80 词内"}]\n'
        "\n枚举（照抄其中一个，不要自造）：\n"
        "- 景别：大特写 / 特写 / 中近景 / 中景 / 全景 / 大远景\n"
        "- 摄影角度：平视 / 低角度仰视 / 高角度俯视 / 主观视角 / 过肩 / 倾斜角 / 顶拍\n"
        "- 运镜：固定 / 缓推 / 缓拉 / 跟拍 / 横摇 / 竖摇 / 变焦 / 手持 / 环绕 / 升降\n"
        "\n规则：\n"
        "1) 同一人物在不同镜头里的**外貌与服装必须逐字一致**；同一场景的**环境、光线、"
        "时间、天气也必须一致**（跨镜漂移是这条链上最容易崩的地方）；\n"
        "2) 每镜可以不同：**不要所有镜头都同景别**，也**不要都是正面人物肖像** —— "
        "该给全景、过肩、背影、道具特写的就给；\n"
        "3) 「叙事目的」要具体到视听手段（用什么景别／运镜去干什么），"
        "禁止「推动剧情」这种谁都能套的空话；\n"
        "4) 英文提示词里不要出现真实人名、不要标注 FRONT/SIDE/BACK 这类字样、"
        "不要把画面里要出现的文字写进去；末尾固定补上："
        "cinematic realism, photorealistic, ultra-detailed, high dynamic range, "
        "8K filmic quality, professional cinematography, natural skin texture, "
        "cinematic color grading, no text, no watermark, no letters, no logo；\n"
        "5) 镜头有台词的**原样保留**，不要增删改台词；只补画面。\n\n"
        + json.dumps(rows, ensure_ascii=False)[:12000])
    try:
        raw = chat(ask)
        data = json.loads(raw[raw.index("["):raw.rindex("]") + 1])
    except Exception as e:                                              # noqa: BLE001
        return shots, f"LLM 增强失败，已跳过（{type(e).__name__}: {e}）"
    by_id = {str(d.get("id")): d for d in data if isinstance(d, dict)}
    n = 0
    for s in shots:
        d = by_id.get(s.id)
        if not d:
            continue
        if d.get("景别"):
            s.shot_size = str(d["景别"]).strip()
        # 摄影角度：也认「机位」这个叫法 —— 第一版提示词就是这么写的，
        # 别因为模型沿用了旧词就把这一列丢掉（丢了不报错，只是分镜表少一列）。
        ang = d.get("摄影角度") or d.get("机位")
        if ang:
            s.camera = str(ang).strip()
        if d.get("运镜"):
            s.movement = str(d["运镜"]).strip()
        if d.get("叙事目的"):
            s.purpose = str(d["叙事目的"]).strip()
        if d.get("英文提示词"):
            s.prompt_en = str(d["英文提示词"]).strip()
            n += 1
    return shots, (f"LLM 补全 {n}/{len(shots)} 镜的景别/摄影角度/运镜/叙事目的"
                   f"与英文提示词")
