# Node Examples

## 1. Parse Text to Numbers, Then Sum

This is the sample flow requested for dashboard/manual testing.

```yaml
metadata:
  name: example-parse-sum
  version: 1.0.0

types:
  TriggerIn:
    text: string
  NumbersOut:
    numbers: list<number>
  SumOut:
    sum: number
    count: number

node_types:
  parse_numbers@v1:
    in: TriggerIn
    out: NumbersOut
    provider: text.parse_numbers
    version: v1
    config_schema: {}

  sum_numbers@v1:
    in: NumbersOut
    out: SumOut
    provider: math.sum_numbers
    version: v1
    config_schema: {}

nodes:
  parse:
    type: parse_numbers@v1
    config: {}

  sum:
    type: sum_numbers@v1
    config: {}

trigger: parse

edges:
  - from: parse
    to: sum
    with:
      numbers: parse.out.numbers
```

## 2. Web Search in Dry-Run Mode

```yaml
types:
  SearchIn:
    query: string
  SearchOut:
    query: string
    results: list<object>
    source: string

node_types:
  search@v1:
    in: SearchIn
    out: SearchOut
    provider: tool.web_search
    version: v1
    config_schema:
      top_k: number
      dry_run: bool

nodes:
  search:
    type: search@v1
    config:
      top_k: 3
      dry_run: true

trigger: search
edges: []
```

## 3. Email Notification in Dry-Run Mode

```yaml
types:
  EmailIn:
    to: string
    subject: string
    body: string
  EmailOut:
    sent: bool
    dry_run: bool
    to: string
    from: string
    subject: string
    message_id: string

node_types:
  notify@v1:
    in: EmailIn
    out: EmailOut
    provider: notify.email
    version: v1
    config_schema:
      from: string
      dry_run: bool

nodes:
  notify:
    type: notify@v1
    config:
      from: "noreply@example.com"
      dry_run: true

trigger: notify
edges: []
```
