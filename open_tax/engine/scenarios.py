"""场景枚举器 -- 确定性网格搜索，代替 AI 拍脑袋给"最优解"。

原理：
  场景 YAML 定义若干决策轴（离散取值 + 可选标签）与一组候选管线；
  枚举所有组合，每个组合完整跑一遍引擎管线；
  按 result_var 排序输出对比表。"最优"是穷举第一名，不是观点。

合规铁律：轴上只允许合法结构选项（纳税身份选择、合法节奏安排、
真实供应商选择）；任何依赖虚开发票/隐匿收入的"策略"不得进入取值。
"""
import itertools
import os

import yaml

from .calculator import fmt
from .pipeline import run_pipeline
from .primitives import F


# ---- 轻量加载器（管线/场景不是规则表，单独校验形状） --------------
def load_yaml_defs(root):
    defs = {}
    root = os.path.abspath(root)
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in sorted(files):
            if fn.endswith((".yaml", ".yml")) and not fn.startswith("."):
                with open(os.path.join(dirpath, fn), encoding="utf-8") as fh:
                    d = yaml.safe_load(fh)
                if isinstance(d, dict) and d.get("id"):
                    defs[d["id"]] = d
                elif d is not None:
                    raise ValueError(
                        "%s/%s: 缺少 id 字段" % (os.path.basename(dirpath), fn))
    return defs


class ScenarioResult(list):
    """行列表：每行 {combo, pipeline, result, steps}；附 .render()。"""

    def __init__(self):
        super().__init__()
        self.title = ""
        self.result_var = ""
        self.assumptions = []
        self.tx_date = None

    def render(self):
        lines = [
            "# %s -- 场景枚举结果" % self.title,
            "",
            "**交易日期**：%s　**排序目标**：%s（高者为优）"
            % (self.tx_date, self.result_var),
            "",
            "| 排名 | 方案组合 | %s | 说明 |" % self.result_var,
            "|---|---|---|---|",
        ]
        for i, row in enumerate(self, 1):
            labels = " ＋ ".join(row["combo"])
            notes = "；".join(row.get("flags") or [])
            lines.append("| %d | %s | %s | %s |"
                         % (i, labels, fmt(row["result"]), notes))
        lines.append("")
        lines.append("## 前提假设")
        lines.extend("- %s" % a for a in self.assumptions)
        lines.append("")
        lines.append("## 冠军方案审计链")
        best = self[0]
        lines.append("")
        lines.append("| 步骤 | 项目 | 数值 | 适用版本 | 文号 |")
        lines.append("|---|---|---|---|---|")
        for j, s in enumerate(best["res"].steps, 1):
            src = s.get("source") or {}
            lines.append("| %d | %s | %s | %s | %s |" % (
                j, s.get("desc") or s["as"], fmt(s["value"]),
                s.get("effective", "-"), src.get("doc_no", "-")))
        lines.append("")
        lines.append("> 本表为确定性枚举的第一名，所有算术在引擎内以精确"
                     "分数完成；仅代表所选轴范围内的最优，不构成税务建议。"
                     "若含限期政策（见文号），请在该政策到期后重新计算。")
        return "\n".join(lines)


def enumerate_scenario(scen_def, pipelines, tx_date, inputs,
                       calculator=None):
    """scen_def 来自 load_yaml_defs(data/scenarios)；pipelines 同法。"""
    res = ScenarioResult()
    res.title = scen_def.get("title", scen_def["id"])
    res.result_var = scen_def.get("result_var", "owner_net")
    res.tx_date = tx_date
    res.assumptions = list(scen_def.get("assumptions") or [])

    # 展开各轴为 (标签, 注入变量, 覆盖管线)
    axes = []
    for ax in scen_def.get("axes", []):
        var = ax["var"]
        items = []
        for val in ax.get("values", []):
            label = str(ax.get("labels", {}).get(str(val), "%s=%s"
                                                 % (var, val)))
            items.append((label, {var: str(val)}, None))
        for key, case in (ax.get("cases") or {}).items():
            items.append((str(case.get("label", "%s=%s" % (var, key))),
                          dict(case.get("vars") or {}),
                          case.get("pipeline")))
        axes.append(items)

    for combo in itertools.product(*axes) if axes else [()]:
        merged = dict(inputs)
        labels, pipe_override = [], None
        for label, inj, ov in combo:
            labels.append(label)
            merged.update(inj)
            if ov:
                pipe_override = ov
        pid = pipe_override or scen_def.get("pipeline")
        pdef = pipelines.get(pid)
        if pdef is None:
            raise KeyError("未知管线 %r" % pid)
        r = run_pipeline(pdef, tx_date, dict(merged),
                         calculator=calculator)
        if res.result_var not in r:
            raise KeyError("管线 %s 未产出 %s" % (pid, res.result_var))
        flags = collect_flags(r, tx_date)
        res.append({"combo": labels, "pipeline": pid,
                    "result": r[res.result_var], "res": r,
                    "flags": flags})
    res.sort(key=lambda x: x["result"], reverse=True)
    return res


def collect_flags(pipeline_result, tx_date):
    """限期政策到期预警：版本止期落在交易日未来18个月内则提示复核。"""
    import datetime as dt
    flags = []
    try:
        d = dt.date.fromisoformat(str(tx_date))
    except ValueError:
        return flags
    horizon = d + dt.timedelta(days=550)
    seen = set()
    for s in pipeline_result.steps:
        end = s.get("effective_end")
        if not end or end in seen:
            continue
        seen.add(end)
        try:
            ed = dt.date.fromisoformat(end)
        except (TypeError, ValueError):
            continue
        if d <= ed <= horizon:
            flags.append("限期政策 %s 到期，届满前复核是否延续"
                         % ed.isoformat())
    return flags[:2]
