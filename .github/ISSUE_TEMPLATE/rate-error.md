name: 税率报错（rate error）
about: 报告某条规则计算结果与官方口径不符
labels: ["data-error"]
body:
  - type: input
    id: rule_id
    attributes:
      label: 出错规则 ID
      placeholder: cn/vat/small_goods
    validations:
      required: true
  - type: input
    id: tx_date
    attributes:
      label: 使用的交易日期
      placeholder: "2026-03-01"
    validations:
      required: true
  - type: textarea
    id: numbers
    attributes:
      label: 本项目结果 vs 你认为正确的结果
      placeholder: |
        输入参数：base=310000
        本项目输出：3100
        正确应为：xxxx
    validations:
      required: true
  - type: textarea
    id: source
    attributes:
      label: 依据文号与官方链接（必填）
      description: 无文号的纠错无法被采纳——防止用另一个错误覆盖错误
      placeholder: 财政部 税务总局公告2023年第19号 https://...
    validations:
      required: true
