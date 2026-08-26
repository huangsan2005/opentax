name: 补充规则（new rule）
about: 提交新税种/新辖区/新时间版本的规则数据
labels: ["new-rule"]
body:
  - type: input
    id: rule_id
    attributes:
      label: 规则 ID（拟）
      placeholder: us/federal/iit_2026
    validations:
      required: true
  - type: dropdown
    id: primitive
    attributes:
      label: 适用原语
      options:
        - flat
        - multiply
        - progressive
        - super_progressive
        - compound
        - tiered_cliff
        - threshold_exempt
        - 不确定，请维护者建议
    validations:
      required: true
  - type: textarea
    id: yaml
    attributes:
      label: YAML 内容
      description: 按 CONTRIBUTING.md 的结构填写；文号必填
    validations:
      required: true
  - type: textarea
    id: anchor
    attributes:
      label: 官方算例锚点
      description: 官方细则算例 / 已审申报表实例 / 两名执业人员独立复算一致的结果
    validations:
      required: true
