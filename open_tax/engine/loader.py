"""YAML 规则加载、校验与版本解析。

一条规则的多个时间版本共存于不同文件也行，loader 按 effective 区间
挑出覆盖交易日期的版本；多个版本同时命中时以 priority 大者优先
（用于"阶段性优惠政策叠加在基础税率上"的表达），priority 相同再比
last_verified 新旧。

校验失败的文件直接拒绝加载：宁可启动失败，不可带毒运行。
"""
import datetime as _dt
import os

import yaml

from .primitives import DISPATCH, OutOfScope, TaxEngineError


class RuleValidationError(TaxEngineError):
    pass


_REQUIRED_TABLE_KEYS = ("id", "primitive", "effective", "source")


def _parse_date(s, ctx):
    if s in (None, ""):
        return None
    try:
        return _dt.date.fromisoformat(str(s))
    except ValueError:
        raise RuleValidationError("%s: 非法日期 %r" % (ctx, s))


def load_rule_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict) or "tables" not in raw:
        raise RuleValidationError("%s: 缺少 tables 节" % path)
    rules = {}
    for t in raw["tables"]:
        ctx = "%s[%s]" % (os.path.basename(path), t.get("id"))
        for k in _REQUIRED_TABLE_KEYS:
            if k not in t:
                raise RuleValidationError("%s: 缺少必填键 %s" % (ctx, k))
        if t["primitive"] not in DISPATCH:
            raise RuleValidationError(
                "%s: 未知原语 %r（可用：%s）"
                % (ctx, t["primitive"], ", ".join(DISPATCH))
            )
        eff = t["effective"]
        if not (isinstance(eff, (list, tuple)) and len(eff) == 2):
            raise RuleValidationError("%s: effective 必须是 [起, 止]" % ctx)
        start = _parse_date(eff[0], ctx)
        end = _parse_date(eff[1], ctx)
        if start is None:
            raise RuleValidationError("%s: effective 起始日期必填" % ctx)
        if end and end < start:
            raise RuleValidationError("%s: 生效区间倒挂" % ctx)
        if not (t.get("source") or {}).get("doc_no"):
            raise RuleValidationError(
                "%s: 缺少来源文号 -- 一手来源是硬门槛，无文号不入库" % ctx
            )
        t["_start"], t["_end"] = start, end
        # 同一 id 的多时间版本累积（列表），load_all 里再按文件合并
        rules.setdefault(t["id"], []).append(t)
    return rules


def load_all(root):
    """递归扫描 root 下全部 yaml -> {rule_id: [版本定义(按起始日排序)]}。

    参数化变量以 "{input_name}" 形式留在 params 中延迟求值。
    """
    registry = {}
    root = os.path.abspath(root)
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in sorted(files):
            if fn.endswith((".yaml", ".yml")) and not fn.startswith("."):
                p = os.path.join(dirpath, fn)
                for rid, tbls in load_rule_file(p).items():
                    registry.setdefault(rid, []).extend(tbls)
    for rid in registry:
        registry[rid].sort(key=lambda t: t["_start"])
    return registry


def resolve(registry, rule_id, tx_date):
    """解析某交易日期应使用的规则版本；无覆盖即抛 OutOfScope。"""
    versions = registry.get(rule_id)
    if not versions:
        raise TaxEngineError("未知规则: %s" % rule_id)
    d = _parse_date(tx_date, rule_id)
    hits = [
        v for v in versions
        if v["_start"] <= d and (v["_end"] is None or d <= v["_end"])
    ]
    if not hits:
        raise OutOfScope(rule_id, d,
                         [(v["_start"], v["_end"]) for v in versions])
    best = max(
        hits,
        key=lambda v: (
            int(v.get("priority") or 0),
            str(v.get("last_verified") or ""),
        ),
    )
    return best
