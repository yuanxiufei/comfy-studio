"""静态核对 ComfyUI 工作流 JSON 的图结构是否自洽。

为什么需要：工作流是手改或脚本改出来的（本次就给 06 插了一个 LoRA 节点、把一条
链接的终点从 BSA 改到了 LoRA），而 JSON 能解析**不代表**图是自洽的 ——
ComfyUI 要等到载入甚至执行时才报错，更糟的情况是静默按缺输入跑。
这里离线核对，八张工作流一起过。

核对的量：
  1. JSON 能解析
  2. 每条 link：两端节点存在；源节点的 outputs[srcSlot].links 含这条 id；
     目标节点的 inputs[dstSlot].link 等于这条 id；两端类型串一致
  3. 每个节点的输入：link 非空时，必有一条 id 相同的 link 且终点是本节点本槽位
  4. 每个节点的输出：links 里每个 id 都必须存在且起点是本节点本槽位
  5. last_node_id / last_link_id 等于实际最大值（否则 UI 里新增节点会撞号）

退出码：0 = 全部通过；1 = 存在失败项。
"""
import json
import sys

import paths

WORKFLOWS = paths.workflows()


def check(path):
    problems = []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return ["JSON 解析失败: {}".format(exc)]

    nodes = {n["id"]: n for n in doc.get("nodes", [])}
    links = {l[0]: l for l in doc.get("links", [])}

    for lid, l in links.items():
        _, src, src_slot, dst, dst_slot, ltype = l[:6]
        outs = (nodes.get(src) or {}).get("outputs") or []
        ins = (nodes.get(dst) or {}).get("inputs") or []
        if src not in nodes:
            problems.append("link {}: 源节点 {} 不存在".format(lid, src))
        elif src_slot >= len(outs):
            problems.append("link {}: 源节点 {} 无输出槽 {}".format(lid, src, src_slot))
        elif lid not in (outs[src_slot].get("links") or []):
            problems.append("link {}: 源节点 {} 输出槽 {} 的 links 里没有它".format(lid, src, src_slot))
        elif (outs[src_slot].get("type") and ltype
              and "*" not in (outs[src_slot]["type"], ltype)
              and outs[src_slot]["type"] != ltype):
            problems.append(
                "link {}: 类型 {} 与源槽类型 {} 不一致".format(lid, ltype, outs[src_slot]["type"])
            )
        if dst not in nodes:
            problems.append("link {}: 目标节点 {} 不存在".format(lid, dst))
        elif dst_slot >= len(ins):
            problems.append("link {}: 目标节点 {} 无输入槽 {}".format(lid, dst, dst_slot))
        elif ins[dst_slot].get("link") != lid:
            problems.append(
                "link {}: 目标节点 {} 输入槽 {} 的 link 是 {!r}".format(
                    lid, dst, dst_slot, ins[dst_slot].get("link")
                )
            )

    for nid, n in nodes.items():
        for slot, item in enumerate(n.get("inputs") or []):
            if item.get("link") is None:
                continue
            l = links.get(item["link"])
            if l is None:
                problems.append("节点 {} 输入槽 {} 指向不存在的 link {}".format(nid, slot, item["link"]))
            elif l[3] != nid or l[4] != slot:
                problems.append(
                    "节点 {} 输入槽 {} 指向 link {}，但该 link 终点是 {}/{}".format(
                        nid, slot, item["link"], l[3], l[4]
                    )
                )
        for slot, item in enumerate(n.get("outputs") or []):
            for lid in item.get("links") or []:
                l = links.get(lid)
                if l is None:
                    problems.append("节点 {} 输出槽 {} 指向不存在的 link {}".format(nid, slot, lid))
                elif l[1] != nid or l[2] != slot:
                    problems.append(
                        "节点 {} 输出槽 {} 指向 link {}，但该 link 起点是 {}/{}".format(
                            nid, slot, lid, l[1], l[2]
                        )
                    )

    if nodes:
        if doc.get("last_node_id") != max(nodes):
            problems.append(
                "last_node_id {!r} 不等于最大节点号 {}".format(doc.get("last_node_id"), max(nodes))
            )
    if links and doc.get("last_link_id") != max(links):
        problems.append(
            "last_link_id {!r} 不等于最大链接号 {}".format(doc.get("last_link_id"), max(links))
        )
    return problems


def main():
    paths = sorted(WORKFLOWS.glob("*.json"))
    if not paths:
        raise SystemExit("没找到工作流：{}".format(WORKFLOWS))
    bad = 0
    for path in paths:
        problems = check(path)
        if problems:
            bad += 1
            print("[FAIL] {}".format(path.name))
            for p in problems:
                print("       " + p)
        else:
            print("[ ok ] {}".format(path.name))
    print("--- {} 张工作流，{} 张有问题 ---".format(len(paths), bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
