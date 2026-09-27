# -*- coding: utf-8 -*-
"""通用执行器 —— 一套逻辑驱动全部 agent。

═══════════════════════════════════════════════════════════════════
两种模式（都是"真能跑"，不是降级）
═══════════════════════════════════════════════════════════════════
  **llm**（配了 `MODEL_API_KEY`）
      真的调模型，直接产出该模块的交付物。

  **package**（未配 Key）
      产出**完整可直接粘贴的调用包**：System Prompt（角色 + 权威文档原文 +
      全局约束）+ User Prompt（本次任务）+ 交接清单骨架 + 门禁清单。
      用户粘进 ChatGPT / Claude / CodeBuddy 即可得到同样的结果。

  > 这不是"没配置就残废" —— 因为**这个 runtime 的核心价值是"装配"**：
  > 把散在工作流 6 个模块里的规范、ID 协议、门禁、交接要求**按 agent 组装好**。
  > 那件事不需要模型参与。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import handover
from .module_loader import ModuleLoader
from .registry import AgentSpec


@dataclass
class AgentResult:
    agent: str
    mode: str                                   # llm | package
    system_prompt: str
    user_prompt: str
    answer: str = ""
    notes: list[str] = field(default_factory=list)
    saved: dict[str, str] = field(default_factory=dict)

    @property
    def call_package(self) -> str:
        """完整调用包（可直接粘贴到任何支持 System Prompt 的平台）。"""
        return (f"# ─── SYSTEM PROMPT ───\n\n{self.system_prompt}\n\n"
                f"# ─── USER ───\n\n{self.user_prompt}\n")


class Runtime:
    """通用 agent 运行时。

    :param out_dir: 产出目录（默认本项目 `output/`）
    :param loader:  模块加载器（可注入以便测试）
    """

    def __init__(self, out_dir: str | os.PathLike | None = None,
                 loader: ModuleLoader | None = None):
        self.out_dir = Path(out_dir) if out_dir else \
            Path(__file__).resolve().parent.parent / "output"
        self.loader = loader or ModuleLoader()

    # ── 独立启动：该 agent 的开场白 ──
    def greet(self, spec: AgentSpec) -> str:
        return self.loader.init_instruction(spec)

    # ── 装配 ──
    def build(self, spec: AgentSpec, user_input: str, *, brief: bool = False) -> AgentResult:
        """装配该 agent 的完整调用包（含交接清单骨架与门禁清单）。"""
        sys_p = self.loader.system_prompt(spec, brief=brief)

        u = [f"# 本次任务\n\n{user_input.strip()}"]
        if spec.outputs:
            u += ["", f"# 期望交付物\n\n" + "\n".join(f"- {o}" for o in spec.outputs)]

        # ⚠️ 交接清单**每个模块都要**（`00-总控路由.md` §四：「每个模块交付时必须给出」），
        #    不能只在有门禁的模块给 —— 实测踩到：06 合规（无门禁）漏了交接清单。
        hd = ["", "# 交付时必须附「交接清单」（`00-总控路由.md` §四）"]
        if spec.gate:
            hd.append("并自检门禁「**%s**」：%s"
                      % (spec.gate, " · ".join(c.label for c in spec.gate_checks)))
        hd += ["", handover.skeleton(spec)]
        u += hd
        u += ["", "# 输出要求",
              "1. 全程中文，表格用 Markdown",
              "2. 严格按上文权威文档的格式与字段，**不要自创格式**",
              "3. 引用的资产 ID 必须来自统一规范（CHR_/CST_/PRP_/ENV_/EXP_/POS_/SHT_/VID_/AUD_）",
              "4. 不确定的地方**显式标注**为「待确认」，不要编造"]

        res = AgentResult(
            agent=spec.key,
            mode="package",
            system_prompt=sys_p,
            user_prompt="\n".join(u),
        )

        miss = self.loader.missing(spec)
        if miss:
            res.notes.append(f"登记但缺失的文档 {len(miss)} 份：{'、'.join(miss[:3])}"
                             + ("…" if len(miss) > 3 else ""))
        if not self.loader.root:
            res.notes.append("⚠️ 未找到工作流目录 —— 角色知识为空。"
                             "请把本项目与 `AI漫剧智能体工作流/` 一起复制。")
        return res

    # ── 执行 ──
    def run(self, spec: AgentSpec, user_input: str, *, brief: bool = False,
            llm=None, save: bool = True) -> AgentResult:
        """装配 + （有 Key 时）真调模型 + 落盘。"""
        res = self.build(spec, user_input, brief=brief)

        client = llm if llm is not None else self._try_llm()
        if client is not None:
            try:
                res.answer = client.chat(res.system_prompt, res.user_prompt)
                res.mode = "llm"
            except Exception as e:                                   # noqa: BLE001
                res.notes.append(f"LLM 调用失败 → 已回退为调用包模式：{str(e)[:120]}")
        else:
            res.notes.append("未配置 `MODEL_API_KEY` → 输出**可直接粘贴的调用包**"
                             "（粘进任意支持 System Prompt 的平台即可得到结果）")

        if save:
            res.saved = self._save(spec, res, user_input)
        return res

    def _try_llm(self):
        """尝试构造 LLM 客户端；没有 Key 或没有网络库时返回 None（**不抛错**）。

        注意 `LLMClient` 的属性名是 `available`（不是 `enabled`）。
        """
        try:
            from .llm_client import LLMClient
            c = LLMClient()
            return c if c.available else None
        except Exception:                                            # noqa: BLE001
            return None

    def _save(self, spec: AgentSpec, res: AgentResult, user_input: str) -> dict:
        d = self.out_dir / spec.key
        d.mkdir(parents=True, exist_ok=True)
        out: dict[str, str] = {}

        p = d / "call_package.md"
        p.write_text(res.call_package, encoding="utf-8")
        out["调用包"] = str(p)

        if res.answer:
            p2 = d / "answer.md"
            p2.write_text(res.answer, encoding="utf-8")
            out["模型输出"] = str(p2)

        meta = {
            "agent": spec.key, "no": spec.no, "name": spec.name,
            "mode": res.mode, "input": user_input,
            "workflow_root": str(self.loader.root or ""),
            "role_docs": spec.role_docs, "missing_docs": self.loader.missing(spec),
            "notes": res.notes,
        }
        p3 = d / "meta.json"
        p3.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        out["元数据"] = str(p3)
        return out
