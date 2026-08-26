"""YAML 规则加载与校验。

规则文件形态（一个文件可含同一规则的多个时间版本）：

meta:
  jurisdiction: cn
tables:
  - id: cn/vat_small_scale
    primitive: flat
    description: 小规模纳税人增值税征收率
    effective: ["2016-05-01", null]
    source:
      title: 营业税改征增值税试点有关事项的规定
      doc_no: 财税〔2016〕36号附件2
      url: https://www.chinatax.gov.cn/...
    last_verified: "2026-08-27"
    verified_by: null            # PR 审核后署名
    params: {rate: "0.03"}
    inputs: [base]

校验失败的文件直接拒绝加载（宁可启动失败，不可带毒运行）。
"""
import datetime as _dt
import os
import sys

import yaml

from .primitives import TaxEngineError


class RuleValidationError(TaxEngineError):
    pass


_REQUIRED_TABLE_KEYS = ("id", "primitive", "effective", "source")


def _parse_date(s, ctx):
    if s in (None, ""):
        return None
    try:
        d = _dt.date.fromisoformat(str(s))
    except ValueError:
        raise RuleValidationError("%s: 非法日期 %r" % (ctx, s))
    return d


def _parse_num(v, ctx):
    """数值一律经字符串进 Fraction，杜绝二进制浮点污染。"""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    return v


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
            raise RuleValidationError("%s: 缺少来源文号（一手来源硬门槛）" % ctx)
        t["_start"], t["_end"] = start, end
        rules[t["id"]] = t
    return rules


def load_all(root):
    """递归扫描 root 下全部 yaml，返回 {rule_id: [版本定义,...]}。"""
    registry = {}
    root = os.path.abspath(root)
    for dirpath, _, files in os.walk(root):
        for fn in sorted(files):
            if fn.endswith((".yaml", ".yml")) and not fn.startswith("."):
                p = os.path.join(dirpath, fn)
                for rid, tbl in load_rule_file(p).items():
                    registry.setdefault(rid, []).append(tbl)
    # 同一规则多版本时保证按起始日期排序
    for rid in registry:
        registry[rid].sort(key=lambda t: t["_start"])
    return registry


def resolve(registry, rule_id, tx_date):
    """解析某交易日期应使用的规则版本；无覆盖即 OutOfScope 拒答。

    多版本同时命中时取最后核验日期最新的一个（last_verified 最高优先）。
    """
    versions = registry.get(rule_id)
    if not versions:
        raise TaxEngineError("未知规则: %s" % rule_id)
    d = _parse_date(tx_date, rule_id)
    hits = [
        v for v in versions
        if v["_start"] <= d and (v["_end"] is None or d <= v["_end"])
    ]
    if not hits:
        raise OutOfScope(
            rule_id, d, [(v["_start"], v["_end"]) for v in versions]
        )
    best = max(
        hits,
        key=lambda v: (
            int(v.get("priority") or 0),
            str(v.get("last_verified") or ""),
        ),
    )
    return best
