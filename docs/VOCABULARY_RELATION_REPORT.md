# LexiLab 词汇关系与智能排序验收报告

验收日期：2026-11-14  
环境：WSL2 / Linux，Python 3.13.9（项目 `.venv`；`environment.yml` 使用 Python 3.12），Conda 25.9.1，WordNet 3.0，RapidFuzz 3.14.6，真实 CET6 词库 3991 条，ECDICT 770,611 条。

## 1. 原有排序问题

旧 `Planner` 通过 `ORDER BY m.rank, w.word_key` 选取新词，`rank` 来自 CET6 JSONL 的原始顺序，基本等于字母顺序。实际首词为：

```text
accountant, accrue, accurate, accuse, accustom, achieve, ...
```

它没有使用 ECDICT 词频、已学词的语义关系、形近干扰或个人错误，因此不适合作默认学习顺序。

## 2. 新增依赖

| 依赖 | 版本 | 作用 |
|---|---|---|
| `nltk` | 3.10.4 | NLTK WordNet 接口 |
| `rapidfuzz` | 3.14.6 | Damerau-Levenshtein 形近词 |
| WordNet 数据 | 3.0 | 离线语义关系；显式下载 |

已写入 `requirements.txt`、`pyproject.toml`、`environment.yml`。WordNet 数据不在启动时下载；`lexi relations download` 或 `lexi relations build --download` 才会下载。

## 3. 实际架构

```text
CET6/ECDICT
  ├── WordNetAnalyzer ─────────────┐
  ├── SpellingAnalyzer ────────────┤
  └── confusion_pairs (learning.db)┘
                    ↓
        vocab_relations / word_metrics
                    ↓
           RelationService
             ├── related 查询
             ├── 同义/形近/混淆辨析
             └── SmartNewWordOrderer
                    ↓
                 Planner
                    ↓
                FSRS（不变）
```

- 静态关系放 `vocabulary.db`，可重建。
- 个人混淆放 `learning.db`，不受词库重导入影响。
- 关系引擎不写 FSRS 字段、不改变到期队列。

## 4. WordNet 使用

实际使用以下 NLTK 接口：

- `wn.synsets()` / `synset.lemmas()`：同义；
- `lemma.antonyms()`：反义；
- `synset.hypernyms()` / `hyponyms()`：上下位，双向写入；
- `lemma.derivationally_related_forms()`：派生；
- `synset.similar_tos()`：语义相似，尝试 WUP；
- `synset.also_sees()`：语义相关。

每个关系保存 `source_sense`、`target_sense`，多义词不合并。跳过 WordNet 多词 lemma，避免把短语当作单词。

真实样例：

```text
mitigate:
  上位词 decrease / lessen (decrease.v.02)
  下位词 relieve / relieved (relieve.v.11)

predict:
  同义 anticipate, forecast, bode ...
  派生 prediction, predictive, predictor ...
  上位 guess, venture, hazard ...

bank:
  同义 camber/cant (bank.n.07), deposit/rely (其他义项)
  派生 banker
  形近 blank (0.80)
```

样例中 `bank` 的不同 synset 同时存在，证明没有把所有词义无条件合并。

## 5. RapidFuzz 使用

- 使用 `DamerauLevenshtein.normalized_similarity`，统一 0–1。
- 长度差 ≤ 2 的桶内比较；每词最多 10 个邻居。
- 解析 ECDICT `exchange`，排除 `play/plays/playing/played` 等同词形变化。
- 短词使用更严格阈值。
- 真实派生词（如 `manufacture/manufacturer`）不进入形近词辨析。

真实发现：

```text
adapt ↔ adopt  (0.80)
adapt ↔ adept  (0.80)
bank ↔ blank   (0.80)
preservation ↔ reservation
complement ↔ compliment
```

## 6. 数据库设计

```sql
CREATE TABLE vocab_relations (
  id INTEGER PRIMARY KEY,
  source_word TEXT NOT NULL,
  target_word TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  source_sense TEXT NOT NULL DEFAULT '',
  target_sense TEXT NOT NULL DEFAULT '',
  part_of_speech TEXT NOT NULL DEFAULT '',
  score REAL,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(source_word, target_word, relation_type, source_sense, target_sense, source)
);

CREATE TABLE relation_build_state (
  word_key TEXT PRIMARY KEY,
  wordnet_built_at TEXT,
  spelling_built_at TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE word_metrics (
  word_key TEXT PRIMARY KEY,
  frq INTEGER, bnc INTEGER, collins INTEGER, oxford INTEGER,
  updated_at TEXT NOT NULL
);

CREATE TABLE confusion_pairs (       -- learning.db
  id INTEGER PRIMARY KEY,
  source_word TEXT NOT NULL,
  target_word TEXT NOT NULL,
  skill TEXT NOT NULL DEFAULT 'recall',
  count INTEGER NOT NULL DEFAULT 1,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  UNIQUE(source_word, target_word)
);
```

`vocab_relations` 建 source/target/type/score 索引；`word_metrics` 解决 77 万行 ECDICT 反复扫描的问题。

## 7. 智能排序算法

```text
score =
  frequency_weight   × freq_score
+ relatedness_weight × related_score
+ confusion_priority × confusion_bonus
- interference_penalty × batch_interference
```

- `frq` 小 = 更常用；`frq` 缺失回退 `bnc`、词库 frequency、词书顺序。
- 关联分来自已学词到候选词的 WordNet 边。
- 个人混淆最多按 3 次封顶加分。
- 迭代选择时惩罚与已选词高度相似的候选；最后插入非相似填充词。
- 相同分数保留源词书稳定顺序，不重新按字母排序。

排序理由写入 `SessionPlan.notes` 和 `session_items.payload_json.recommendation`。

## 8. 记忆干扰控制

真实构造测试：

```text
候选：adapt, adopt, adept, mitigate, robust, constraint, subtle
结果：adapt, mitigate, robust, constraint, adopt, subtle, adept
```

`adapt/adopt/adept` 没有连续出现；测试对相似集合的相邻对进行断言。若批次填充词不足，不能数学上消除所有相邻相似对，但算法会先分散再保留稳定顺序。

## 9. 排序优化前后对比

数据：真实 CET6 3991 条，排除已学/已筛选 7 条，取前 50。完整 JSON 见 `reports/relation_acceptance.json`。

| 策略 | 前 10 个词 | 前 1000 高频词 | 中位词频排名 | 批次内形近对 | 同义对 | 与已学词相关 |
|---|---|---:|---:|---:|---:|---:|
| A 字母 | accountant, accrue, accurate, accuse, accustom, achieve, acquaintance, activate, acutely, addict | 3/50 | 4003 | 1 | 0 | 0 |
| B 随机 | butt, dwell, negligible, platform, mischief, clutch, assure, integrity, alert, ritual | 2/50 | 4859 | 0 | 0 | 0 |
| C 词频 | what, can, way, even, through, should, over, feel, between, start | 50/50 | 359 | 0 | 14 | 0 |
| D 智能 | what, can, way, through, should, over, feel, between, start, even | 49/50 | 391 | 0 | 6 | 1 |

解释：

- D 在同义集中度上从 14 对降到 6 对，并引入了 1 个与已学词有 WordNet 关系的词；代价是前 1000 高频词从 50 降到 49、中位排名从 359 变为 391。这是“多样性/关联收益”与“纯词频”之间的真实权衡。
- A 的前 50 个词只有 3 个进入 ECDICT 前 1000，中位排名 4003；说明字母顺序既不保证高频，也不保证与用户已有知识有关。
- B 随机排序的中位排名 4859，低于 A；随机并不会自动产生更好的学习顺序。
- C/D 仍包含 `what/can/way` 等功能词。这是“纯词频”的已知代价，后续可按词书/考试标签做过滤，但不能把词频说成学习效果。
- 本次只是**排序策略行为对照**，不是学习有效性实验。

## 10. 性能

| 测量项 | 结果 |
|---|---|
| 完整关系构建 | 3991 源词，254.3 秒（WSL `/mnt/e`） |
| WordNet 关系 | 138,736 条 |
| RapidFuzz 形近关系 | 1,516 条 |
| 总关系 | 140,252 条 |
| 关系表 + 索引 | 约 25.2 MB |
| 单词关系查询 | 约 48–65 ms |
| 冷启动计划生成 | 约 0.65 秒 |
| 热连接计划生成 | 约 0.22–0.30 秒 |
| 关系重建对 FSRS | cards 8 → 8，review_logs 3 → 3（不变） |

`word_metrics` 将候选载入从约 2.1 秒降到约 0.1 秒；关系构建仍是一次性初始化成本，已提供 `--no-wordnet` 和增量模式。

## 11. 自动化测试

结果见最终 `pytest -q`：**125 passed**（本报告生成时）。新增覆盖：

- WordNet 同义、反义、派生、上下位、多义词、未知词；
- RapidFuzz 归一化范围、字符交换、候选限制、词形变化排除；
- 关系唯一键去重、类型过滤、关系浏览器键盘操作；
- 增量构建、词库重建后个人混淆保留、FSRS 状态不变；
- 真实词混淆才记录、不存在的拼写不记录；
- 智能排序词频、关联、干扰、无词频降级、显式字母排序、到期优先。
- CLI 新增 `related`、`relations build/stats/download`、`drill synonyms/similar-spelling/confusion` 帮助与查询。

## 12. 新增命令

```bash
lexi learn --order smart|frequency|related|alphabetical
lexi related mitigate
lexi related mitigate --type synonym
lexi related adapt --type spelling
lexi drill synonyms
lexi drill similar-spelling
lexi drill confusion
lexi relations build [--force] [--no-wordnet] [--no-spelling] [--download]
lexi relations stats
lexi relations download
```

原有命令保持兼容；`--no-tui`、Textual 全键盘、粒子/抖动/Combo 均保留。

## 13. 学习科学依据

详见 `LEARNING_ORDER_DESIGN.md`。简要结论：

- 字母顺序没有学习理论依据；
- 随机顺序没有覆盖/关联/干扰控制；
- 词频有覆盖率价值，但功能词和用户水平会稀释收益；
- 语义关联可提供精细加工路径，但相似词可能产生干扰；
- 形近辨析应结合用户真实错误，而不是只看编辑距离；
- 新词学习与专项辨析应使用不同排序规则；
- 本次没有真实学习效果实验，不能声称智能排序提高考试成绩。

## 14. 尚未解决的问题

- WordNet 对部分 CET6 词没有直接关系；不编造。
- 词频排序会引入功能词；需要按考试标签/用户水平做可选过滤。
- 形近词只在当前词书内发现，跨词书扩展尚未实现。
- 关系构建 4 分钟对超大数据仍偏慢；可进一步并行化 WordNet 查询。
- 个人混淆只记录真实单词替换；更复杂的“词义混淆”仍依赖用户自评或后续研究。
- 缺少真实用户随机对照实验；当前结论仅限工程行为与静态指标。
