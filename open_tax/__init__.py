"""OpenTax -- 规则即数据(YAML) + 确定性原语 的计税引擎。

架构三层：
  data/rules/*.yaml   规则插件（税率、区间、生效期、来源文号）
  open_tax/engine     零知识引擎（六个原语 + 版本解析 + 审计链）
  open_tax/cli        LLM 编排入口（听懂问题/追问参数/渲染结果）

铁律：
  1. 引擎代码里没有任何具体税率；改税只改 YAML。
  2. 交易日期超出规则收录区间 -> OutOfScope 拒答，绝不硬算。
  3. 所有算术用 Fraction 精确执行，展示层才舍入两位。
"""

__version__ = "0.1.0"
