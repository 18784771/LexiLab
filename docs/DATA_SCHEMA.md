# LexiLab 数据库设计

## 1. 总览

| 文件 | 用途 | 是否可重建 |
|---|---|---|
| `data/vocabulary.db` | 词库、释义、例句、ECDICT | 是 |
| `data/learning.db` | 卡片、日志、材料、错误、会话 | 否（必须备份） |

连接参数：`PRAGMA foreign_keys=ON`、`journal_mode=WAL`、`busy_timeout=5000`。内部时间统一存 UTC ISO-8601 字符串（带 `+00:00`）。

学习数据通过稳定键 `word_key`（规范化词条，例如 `mitigate`）关联词库，**不使用** `words.id`。

## 2. vocabulary.db

### words

| 列 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 内部自增 |
| word_key | TEXT UNIQUE NOT NULL | 规范化词条，跨库稳定键 |
| headword | TEXT NOT NULL | 展示词形 |
| phonetic_uk / phonetic_us | TEXT | 音标 |
| pos | TEXT | 词性汇总 |
| translation | TEXT | 中文释义汇总 |
| definition_en | TEXT | 英文释义汇总 |
| frequency | INTEGER | ECDICT frq（若可合并） |
| source | TEXT | `cet6` / `custom` / `personal` |
| source_word_id | TEXT | 上游词条 ID |
| raw_json | TEXT | 原始数据保留 |
| created_at / updated_at | TEXT | UTC |

索引：`word_key`、`headword COLLATE NOCASE`、`source`。

> 同一 headword 的多个义项合并到一行；原始每个义项保存在 `raw_entries`。

### 其他词库表

- `definitions(id, word_id, pos, meaning_cn, meaning_en, sort_order)`：一词多义。
- `examples(id, word_id, sentence_en, sentence_cn, source, sort_order)`。
- `phrases(id, word_id, phrase, translation, source)`。
- `word_relations(id, word_id, rel_type, value, translation)`：`synonym` / `derivative`。
- `raw_entries(source, source_id, word_key, payload_json, imported_at, UNIQUE(source, source_id))`。
- `word_books(id, code UNIQUE, name, description, source_url, license, source_version, imported_at)`。
- `word_book_memberships(word_book_id, word_id, rank, PRIMARY KEY(word_book_id, word_id))`。
- `source_metadata(key PRIMARY KEY, value)`：下载 URL、内容 SHA-256、抓取时间、上游说明。
- `screening` 不在词库库；属于学习库。

### vocab_relations（静态词汇关系）

```sql
CREATE TABLE vocab_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
```

- `source`：`wordnet` / `rapidfuzz`。
- `source_sense` / `target_sense`：WordNet synset（如 `mitigate.v.02`）；多义词不合并。
- 形近词为对称关系，双向写入；查询无需再做无向展开。
- 索引：`source_word`、`target_word`、`score`。
- `relation_build_state(word_key, wordnet_built_at, spelling_built_at, updated_at)` 支持增量构建。
- `word_metrics(word_key, frq, bnc, collins, oxford, updated_at)` 是 ECDICT 的轻量排序缓存，避免每次计划生成扫描 77 万行 ECDICT。

### learning.db 的个人混淆

```sql
CREATE TABLE confusion_pairs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_word TEXT NOT NULL,
    target_word TEXT NOT NULL,
    skill TEXT NOT NULL DEFAULT 'recall',
    count INTEGER NOT NULL DEFAULT 1,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(source_word, target_word)
);
```

只有用户输入了另一个真实存在的单词时才记录，例如 `adapt → adopt`；不存在的拼写只进入 `training_logs/word_errors`。该表属于学习记录，词库重导入或关系重建不会删除它。

### ecdict

| 列 | 说明 |
|---|---|
| id INTEGER PK | |
| word TEXT UNIQUE COLLATE NOCASE | |
| phonetic | 音标 |
| definition | 英文释义（多行） |
| translation | 中文释义（多行） |
| pos | 词性 |
| collins / oxford | 柯林斯星级 / 牛津 3000 |
| tag | cet4 cet6 ky toefl ielts gre 等 |
| bnc / frq | 词频 |
| exchange | 词形变化，如 `p:perceived/0:perceive` |
| detail / audio | 扩展信息 |

索引：`word COLLATE NOCASE`、`frq`。

## 3. learning.db

### cards

| 列 | 说明 |
|---|---|
| id INTEGER PK | |
| word_key TEXT NOT NULL | 稳定词条键 |
| direction TEXT | `recognition` / `recall` |
| card_id INTEGER | FSRS card_id |
| state INTEGER | FSRS State |
| step INTEGER | FSRS step |
| stability REAL | FSRS stability |
| difficulty REAL | FSRS difficulty |
| due TEXT | UTC |
| last_review TEXT | UTC |
| suspended INTEGER | 0/1 |
| created_at / updated_at | UTC |

约束：`UNIQUE(word_key, direction)`；索引 `due`、`(direction, suspended, due)`。

### review_logs

| 列 | 说明 |
|---|---|
| id | |
| card_row_id | 关联 cards.id |
| word_key / direction | 便于统计 |
| rating | 1–4 |
| review_datetime | UTC |
| review_duration_ms | 作答耗时 |
| elapsed_days | 与上次复习的实际间隔 |
| scheduled_days | 本次调度间隔 |
| state_before / state_after | FSRS 状态 |
| log_json | 官方 ReviewLog 序列化 |

### training_logs

`skill`：`recognition` / `recall` / `spelling` / `listening` / `context` / `production`。

字段：`word_key, skill, correct, hinted, duration_ms, error_type, detail_json, material_id, session_id, created_at`。

### word_errors

`word_key, skill, error_type, detail, resolved, created_at, resolved_at`。

### personal_words

`word_key UNIQUE, headword, translation, phonetic, note, source, added_at`。

个人生词只影响学习范围，不复制词库数据。

### screening

`word_key UNIQUE, status, verify_at, step, verified_at, fail_count, created_at`。

用于“已认识”词汇的延迟抽查，不创建未经验证的永久掌握状态。

### sessions / session_items

- `sessions(id TEXT PK, kind, started_at, ended_at, status, plan_json, stats_json, last_seen_at)`。
- `session_items(id, session_id, seq, item_type, word_key, direction, card_row_id, status, payload_json, attempts, created_at, updated_at)`。

`status`：`pending` / `done` / `skipped` / `failed`。重启时加载 `pending` 项继续。

### materials / material_attempts

- `materials(id TEXT PK, kind, target_words_json, topic, difficulty, body, questions_json, model, provider, prompt_version, created_at, status, meta_json)`。
- `material_attempts(id, material_id, question_index, user_answer, grade_json, correct, hinted, created_at)`。
  `hinted` 区分独立作答与查词/提示后的作答。

材料正文和参考答案完整缓存，离线可重做。

### ai_request_logs

`provider, model, purpose, prompt_version, status, latency_ms, error, cached, created_at`。不记录 API 密钥或完整请求正文。

### settings

`key TEXT PRIMARY KEY, value TEXT, updated_at`。存放当前词书、上次训练类型、预生成开关等。

### schema_versions

`version INTEGER PRIMARY KEY, applied_at TEXT`。启动时按顺序应用迁移。

## 4. 备份与恢复

- `lexi backup` 对两个数据库分别调用 SQLite `backup()`，输出到 `data/backups/<timestamp>/`，并写入 `manifest.json`（文件大小、SHA-256、schema 版本）。
- `lexi restore <path>` 先校验 manifest 和数据库 `PRAGMA integrity_check`，再把现有库复制到 `data/backups/pre-restore-<timestamp>/`，然后原子替换。
- 恢复失败时保留原库，不删除任何学习记录。
- 词库导入只操作 `vocabulary.db`；即使执行 `lexi init` 也不会覆盖 `learning.db`。

## 5. 数据目录

```
data/
├── vocabulary.db
├── learning.db
├── raw/            # 下载的原始词库、ECDICT CSV
├── audio/          # TTS 缓存 (sha256.wav)
└── backups/
```
