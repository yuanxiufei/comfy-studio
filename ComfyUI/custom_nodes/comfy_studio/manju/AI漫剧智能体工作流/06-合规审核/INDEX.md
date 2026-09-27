# 06 · 合规审核 · 源文件映射清单

> 职责：提示词过审、内容合规筛查、风险优化
> 状态：✅ **模块已可用**（`00-主控智能体.md` + `模板/`）。本文件为**能力扩充素材清单**，列出仓库 `SD2审核筛查/` 目录 7 个可抓取的源 skill。
> 完整能力说明见 `./README.md`

---

## A. 提示词过审（核心）

| 文件 | 用途 | 优先级 |
|---|---|---|
| `seedance-prompt-filter.md` | Seedance 提示词过滤器（5.3KB，核心） | ⭐⭐⭐ |
| `seedancepromptoptimizer.md` | 提示词优化器完整版（27KB） | ⭐⭐⭐ |
| `seedance-prompt-optimizer-i2.md` | 过审优化器 v2（5.1KB） | ⭐⭐⭐ |
| `SD视频提示词过审核优化器.md` | 过审优化中文版（2.3KB） | ⭐⭐ |
| `seedance-prompt-template.md` | 提示词模板（13KB） | ⭐⭐ |
| `lingjian-prompt-inspector.md` | 提示词检查器（27KB） | ⭐⭐ |
| `seedance-compliance-director.md` | 合规导演（5.3KB） | ⭐⭐ |

---

## B. 其他合规相关（跨模块）

| 文件 | 路径 | 用途 |
|---|---|---|
| `ip-guardian-director.md` | `文档/` | IP 侵权风险守护 |
| `fact-checker.md` | `文档/` | 事实核查 |
| `SD2审核筛查/` 全目录 | — | 已全量纳入本模块 |

---

## 工作流定位

```
【6.1】原始提示词（来自 03/02/03 各模块）
        ↓
【6.2】风险扫描     ← seedance-prompt-filter / lingjian-prompt-inspector
        ↓
【6.3】过审优化     ← seedancepromptoptimizer（保留创作意图前提下替换敏感表述）
        ↓
【6.4】模板规范化   ← seedance-prompt-template
        ↓
【6.5】IP 风险检查  ← ip-guardian-director
        ↓
→ 输出可安全用于公开平台的提示词
```

## 抓取模板

```
https://raw.githubusercontent.com/021gink/short-drama-ai-skills/main/SD2%E5%AE%A1%E6%A0%B8%E7%AD%9B%E6%9F%A5/<文件名>
```

## 建议抓取顺序

1. `seedance-prompt-filter.md`（过滤器）
2. `seedancepromptoptimizer.md`（优化器完整版）
3. `seedance-prompt-template.md`（模板）
4. `ip-guardian-director.md`（IP 风险）
