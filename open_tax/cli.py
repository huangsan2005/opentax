"""open_tax.cli -- 命令行入口（LLM 编排层的裸骨版）。

示例::

    python -m open_tax single --date 2026-03-01 \
        --rule cn/lvat/four_bracket \
        --set amount=106833048 --set base=0

    python -m open_tax pipeline --pipeline engineering_to_owner \
        --date 2026-03-01 --set contract_gross=1000000

    python -m open_tax enumerate --scenario withdrawal_strategy \
        --date 2026-03-01 --set contract_gross=3000000
"""
import argparse
import os
import sys


def _data_root():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo, "data")


def _parse_sets(pairs):
    out = {}
    for kv in pairs or []:
        k, _, v = kv.partition("=")
        out[k] = v
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="open_tax",
                                 description="OpenTax 规则即数据计税引擎")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("single", help="单条规则计算")
    p1.add_argument("--date", required=True)
    p1.add_argument("--rule", required=True)
    p1.add_argument("--set", action="append", dest="sets",
                    metavar="K=V")

    p2 = sub.add_parser("pipeline", help="管线瀑布计算")
    p2.add_argument("--pipeline", required=True)
    p2.add_argument("--date", required=True)
    p2.add_argument("--set", action="append", dest="sets",
                    metavar="K=V")

    p3 = sub.add_parser("enumerate", help="场景枚举（确定性寻优）")
    p3.add_argument("--scenario", required=True)
    p3.add_argument("--date", required=True)
    p3.add_argument("--set", action="append", dest="sets",
                    metavar="K=V")

    ns = ap.parse_args(argv)
    sets = _parse_sets(ns.sets)

    from open_tax.engine.calculator import Calculator
    from open_tax.engine.pipeline import run_pipeline
    from open_tax.engine.scenarios import (
        enumerate_scenario,
        load_yaml_defs,
    )

    data_root = _data_root()
    pipelines = load_yaml_defs(os.path.join(data_root, "pipelines"))

    try:
        if ns.cmd == "single":
            calc = Calculator()
            val, step = calc.apply(ns.rule, ns.date, sets)
            print(calc.markdown_report())
            print("结果：%.2f" % float(val))
            return 0

        if ns.cmd == "pipeline":
            pdef = pipelines.get(ns.pipeline)
            if pdef is None:
                print("[错误] 未知管线 %r，可选：%s"
                      % (ns.pipeline, ", ".join(sorted(pipelines))))
                return 2
            print(run_pipeline(pdef, ns.date, sets).render())
            return 0

        if ns.cmd == "enumerate":
            scen_defs = load_yaml_defs(
                os.path.join(data_root, "scenarios"))
            sdef = scen_defs.get(ns.scenario)
            if sdef is None:
                print("[错误] 未知场景 %r，可选：%s"
                      % (ns.scenario, ", ".join(sorted(scen_defs))))
                return 2
            print(enumerate_scenario(sdef, pipelines,
                                     ns.date, sets).render())
            return 0
    except Exception as e:                      # noqa: BLE001
        print("[拒答/错误] %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
