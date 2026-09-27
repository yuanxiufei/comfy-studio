import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from src import asset_index as ai           # noqa: E402
from src import storyboard as sb            # noqa: E402

proj = os.path.abspath(os.path.join(HERE, "..", "..", "projects", "流氓天尊"))
reg = ai.load_project_registry(proj)
targets = ai.episode_targets(proj)
print("目标时长（读自项目自己的表）:", targets)

for ep in ("EP01", "EP02", "EP03", "EP04", "EP05"):
    p = os.path.join(proj, "00_PROJECT", "01_剧本", f"{ep}-剧本.md")
    title, scenes = sb.parse_script(open(p, encoding="utf-8").read())
    shots = sb.annotate_rules(sb.make_shots(scenes, ep=ep), registry=reg)
    unreg = sb.unresolved(shots, reg)
    tot = sum(s.seconds for s in shots)
    tgt = targets.get(ep, 105.0)
    print(f"{ep} 场次={len(scenes)} 镜数={len(shots)} 合计={tot:.1f}s "
          f"目标={tgt:g}s ({tot / tgt:.2f}x) 均={tot / len(shots):.2f}s/镜 "
          f"帧={sum(s.frames for s in shots)} "
          f"env空={sum(1 for s in shots if not s.env_id)} "
          f"未登记={list(unreg['speaker']) + list(unreg['place'])}")

# ⚠️ 落到**系统临时目录**、不在仓库内：本脚本每跑一次就重写这个目录，属产物。
#    放仓库里会被 `git add -f` 带进索引（`-f` 无视 .gitignore），污染版本库。
tmp = os.path.join(tempfile.gettempdir(), "manju_smoke_proj")
p = os.path.join(proj, "00_PROJECT", "01_剧本", "EP01-剧本.md")
title, scenes = sb.parse_script(open(p, encoding="utf-8").read())
shots = sb.annotate_rules(sb.make_shots(scenes, ep="EP01"), registry=reg)
md, js = sb.write_storyboard(tmp, "EP01", shots, title=title,
                             target_sec=targets.get("EP01", 105.0),
                             unreg=sb.unresolved(shots, reg))
print("\n写出:", md)
print("写出:", js)
