# 贡献指南

OpenTax 的可信度建立在「每条规则可溯源、每个数字可复算」之上。
贡献前请理解一个原则：**宁可拒答，不可硬算**。

## 三种贡献方式（按门槛从低到高）

### 1. 报告错误（Issue，不需要写代码）

使用 Issue 模板「税率报错」，必须包含：

- 出错的规则（如 `cn/vat/small_goods`）与使用的交易日期；
- 本项目给出的结果 vs 你认为正确的结果；
- **依据文号 + 官方原文链接**（国家税务总局官网、政府网、人大网均可）。

没有文号的纠错无法被采纳——这是为了防止用另一个错误覆盖错误。

### 2. 补充规则（YAML PR，不需要写 Python）

复制任一现有规则文件的结构，新建 PR 包含两样东西：

**a) 规则文件** `data/rules/<辖区>/<税种>.yaml`

```yaml
meta: {jurisdiction: xx}
tables:
  - id: xx/cit/base_rate          # 辖区/税种/名称，全局唯一
    primitive: flat               # 七个原语之一
    description: 一句话说清口径
    effective: ["2008-01-01", null]   # 起=必填ISO日期，止=null表示至今
    priority: 0                   # 叠加型优惠用更高优先级
    source:
      title: 文件标题
      doc_no: 必须有文号           # 硬门槛，缺失直接拒收
      url: 官方链接（强烈建议）
    last_verified: "2026-08-27"
    verified_by: null             # 审核通过后由维护者填写，多次贡献者署名
    inputs: [base]
    params: {rate: "0.25"}
```

**b) golden 测试** `tests/test_golden.py` 里加至少一个锚点用例

```python
def test_my_rule(self):
    c = calc()
    val, _ = c.apply("xx/cit/base_rate", "2026-03-01", {"base": "100000"})
    self.assertEqual(val, F("25000"))
```

锚点数字必须来自：官方实施细则的算例、官方申报表的已审填报数、
或由两名执业人员独立手工复算一致的结果。

### 3. 成为核验人

连续 5 个有效 PR 后可在你核验过的规则的 `verified_by` 署名，
并在 README 核验人名单展示。我们希望你持续跟进该规则的版本变化。

## CI 会自动检查什么

- 全量 golden 回归（改坏任何数字立即红）；
- 数据完整性：文号必填、生效区间合法、原语存在；
- `data-stale.yml` 工作流每周扫描：限期政策（如 2027-12-31 到期的优惠）
  到期前 60 天自动开 Issue 提醒社区核实是否延续。

## 不收什么

- 无文号的"我记得是多少";
- 微信公众号/百科转述的税率;
- 地方口径入主表（请建 `<辖区>/local/*.yaml` 并注明适用地域);
- 任何"合理推测"的政策走向——没落地就不是规则。
