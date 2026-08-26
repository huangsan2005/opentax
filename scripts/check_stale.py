#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描 data/rules 下 60 天内到期的限期政策，输出 Markdown 清单。

CI 用途：非空输出 -> 自动开 Issue 提醒。也可本地手动运行。
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAYS = 60


def main():
    today = dt.date.today()
    horizon = today + dt.timedelta(days=DAYS)
    lines = []
    root = os.path.join(REPO, "data", "rules")
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in sorted(files):
            if not fn.endswith((".yaml", ".yml")):
                continue
            p = os.path.join(dirpath, fn)
            with open(p, encoding="utf-8") as fh:
                doc = yaml.safe_load(fh) or {}
            for t in doc.get("tables") or []:
                eff = t.get("effective") or [None, None]
                try:
                    end = dt.date.fromisoformat(str(eff[1])) \
                        if eff[1] else None
                except ValueError:
                    continue
                if end and today <= end <= horizon:
                    lines.append(
                        "- `%s`（%s）止期 **%s**（剩余 %d 天）\n"
                        "  来源：%s\n"
                        "  待办：确认政策是否延续；延续则新增版本条目，"
                        "不修改旧版。\n" % (
                            t.get("id"), t.get("description", ""),
                            end.isoformat(), (end - today).days,
                            (t.get("source") or {}).get("doc_no", "?")))
    if lines:
        print("expiring<<EOF")
        print("以下限期政策将在 %d 天内到期，请社区核验：\n" % DAYS)
        print("\n".join(lines))
        print("EOF")
    else:
        print("expiring=")


if __name__ == "__main__":
    main()
