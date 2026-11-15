# LexiLab 词汇关系引擎设计

## 1. 目标与边界

词汇关系引擎负责回答四个问题：

1. 一个词与哪些词有可靠的语义关系？
2. 哪些词在拼写上容易混淆？
3. 用户实际把哪个词误写成了哪个真实单词？
4. 这些关系如何影响“下一次学哪些新词”和“做什么专项训练”？

它**不负责**：

- 修改 FSRS 状态、`due`、`stability` 或评分；
- 替代到期复习队列；
- 用大模型生成关系或学习顺序；
- 声称关系数量越多，学习效果越好。

FSRS 决定“何时复习”，关系引擎决定“学哪些新词、如何编排名义相关/形近的训练”。

## 2. 依赖与初始化

| 依赖 | 用途 |
|---|---|
| `nltk` + WordNet | 同义、反义、上下位、派生、语义相似/相关 |
| `rapidfuzz` | Damerau-Levenshtein 形近词 |
| ECDICT | 词频、词性、词形变化（`exchange`） |
| SQLite | 静态关系与个人混淆持久化 |

安装：

```bash
pip install -r requirements.txt
python -m nltk.downloader wordnet
lexi relations build
```

WordNet 下载是显式初始化步骤。正常启动、`lexi learn`、`lexi related` 都不会触发下载。若数据缺失：

- `relations build` 的 WordNet 部分报告明确错误；
- RapidFuzz 形近词仍可构建；
- 新词排序降级到 ECDICT 词频/词书顺序；
- 基础 FSRS 学习不受影响。

## 3. 数据模型

### 3.1 静态关系 `vocabulary.db.vocab_relations`

| 字段 | 含义 |
|---|---|
| `source_word` / `target_word` | 规范化 `word_key` |
| `relation_type` | `synonym` / `antonym` / `hypernym` / `hyponym` / `derivation` / `similar` / `related` / `orthographic_similar` |
| `source_sense` / `target_sense` | WordNet synset 标识；形近词为空 |
| `part_of_speech` | `n` / `v` / `a` / `s` / `r` |
| `score` | WordNet 明确关系为固定分；`similar` 可用 WUP；形近词为 0–1 |
| `source` | `wordnet` / `rapidfuzz` |

唯一键包含两个 sense，因此同一对词在不同词义下的关系不会被无条件合并。展示时按“关系类型 + 目标词”去重，但保留首个有效词义标识，避免同义词表出现重复行。

### 3.2 构建状态

`relation_build_state(word_key, wordnet_built_at, spelling_built_at, updated_at)` 支持增量构建：

- 新导入词只补齐尚未构建的源词；
- `--force` 清空后重建；
- 修改形近词阈值/邻居数会清除 RapidFuzz 关系并重建；
- 构建静态关系不会触碰 `learning.db`。

### 3.3 个人混淆 `learning.db.confusion_pairs`

只有以下条件同时满足才记录：

1. 用户答错；
2. 输入答案是另一个**真实存在**的单词（CET6/ECDICT）；
3. 与目标词不同。

例如 `adapt → adopt` 被记录；`adapt → adoptt` 只算拼写错误，不创建混淆对。混淆对是方向性的，重复出现会累加 `count`，供专项训练排序。

## 4. WordNet 分析

### 4.1 实际使用的关系

- synset 内 lemma 之间：同义；
- `lemma.antonyms()`：反义；
- `synset.hypernyms()` / `hyponyms()`：上下位，构建时同时写反向类型；
- `lemma.derivationally_related_forms()`：派生；
- `synset.similar_tos()`：语义相似，尝试 WUP similarity，`None` 时使用保守分数；
- `synset.also_sees()`：语义相关。

没有把“词形前缀相同”当作派生关系，也没有把语义相似度直接当同义词。

### 4.2 多义词

每个关系保留 `source_sense` 和 `target_sense`。例如 `bank` 的 `bank.n.07`（河岸/倾斜）与金融义项的关系不会合并；`lexi related bank` 会显示 `sense=bank.n.07` 等依据。

### 4.3 规模限制

- 每个词最多读取 12 个 synset（`WordNetAnalyzer.max_synsets`）。
- 跳过带下划线的多词 lemma，避免把 WordNet 短语当作单词词条。
- 构建结果按唯一键去重。

## 5. RapidFuzz 形近词

### 5.1 相似度

统一使用：

```python
DamerauLevenshtein.normalized_similarity(word_a, word_b)  # 0.0 ~ 1.0
```

不使用百分制与归一化分数混用。阈值比较包含 epsilon，规避 `0.8` 被浮点计算成 `0.799999...` 的边界问题。

### 5.2 候选控制

- 只对当前词书（默认 CET6）的单词两两比较；不对 77 万 ECDICT 全量两两比较。
- 按单词长度分桶，只比较长度差 ≤ 2 的桶。
- 每个词最多保留 `max_neighbors` 个候选。
- 解析 ECDICT `exchange`，排除 `play/plays/playing/played` 等同词形变化。
- 短词（长度 ≤ 4）使用更严格的阈值。
- 真实 WordNet 派生关系（如 `manufacture/manufacturer`）在“形近词辨析”中排除，避免把派生词误当拼写混淆。

### 5.3 形近 ≠ 易混淆

- `orthographic_similar`：算法发现的形近候选。
- `user_confusion`：用户实际产生的真实替换。

二者分开存储，训练优先级也不同。

## 6. 查询与展示

`RelationService.groups(word)` 返回按关系类型分组的视图，包含：

- 目标词、ECDICT/CET6 释义、词性；
- 源/目标 synset；
- 关系来源；
- 个人混淆次数。

CLI/Textual 关系浏览器支持 `1–9` 切换关系类型、方向键选择、`Enter` 进入目标词学习、`Esc` 返回，不引入鼠标依赖。

## 7. 性能与重建

真实六级词库（3991 个词）实测：

- WordNet 关系 138,736 条；
- RapidFuzz 形近关系 1,516 条；
- 总计 140,252 条；
- 完整构建约 254 秒（WSL `/mnt/e`，含 WordNet 查询与 SQLite 写入）；
- 静态关系表及索引约 25.2 MB；
- `relations stats` / 单词关系查询通常在几十毫秒；
- 智能计划生成冷启动约 0.65 秒，热连接约 0.2–0.3 秒。

`word_metrics` 缓存 ECDICT 的 `frq/bnc/collins/oxford`，避免每次计划生成扫描 77 万行 ECDICT。

## 8. 已知限制

- WordNet 对某些 CET6 词没有直接同义/派生关系；系统不会编造。
- 形近词只在当前词书内发现；跨词书候选需要显式扩展。
- 关系构建耗时可以用 `--no-wordnet` 或增量模式控制。
- 语义相似度分数来自 WordNet 结构，不等同于学习者主观难度。
- 个人混淆依赖用户真实输入；不会从“拼写相似”自动推断用户混淆。
