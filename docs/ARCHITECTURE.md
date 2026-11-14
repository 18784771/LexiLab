# LexiLab 架构设计

## 1. 目标与约束

LexiLab 是一个本地单机 CLI 英语学习工具。核心目标是：用成熟的间隔重复算法管理记忆调度，用确定性程序保证学习效率，用可选 AI 创造语境并提供开放式反馈。

设计约束：

- 完全离线也能完成词汇学习、复习、拼写与本地词典查询。
- AI 是增强项，不是启动、复习或数据保存的必要条件。
- 不实现账户、云同步、Web 前端、微服务。
- 不自行实现 FSRS，不把启发式分数称为记忆概率。
- CLI 不写 SQL，UI 不调用 AI，AI 不写数据库。

## 2. 分层与模块

```
┌────────────────────────────────────────────┐
│ CLI (Typer)                                │
│ 命令解析、参数校验、组装 AppContext         │
└───────────────┬────────────────────────────┘
                │
┌───────────────▼────────────────────────────┐
│ UI (Rich + Prompt Toolkit + tty)           │
│ 页面渲染、按键/文本输入、会话适配器         │
└───────────────┬────────────────────────────┘
                │ SessionUI 协议
┌───────────────▼────────────────────────────┐
│ Services                                   │
│  Learning / Training / Materials / Stats   │
└───┬─────────┬──────────┬─────────┬─────────┘
    │         │          │         │
┌───▼───┐ ┌───▼────┐ ┌───▼───┐ ┌───▼──────┐
│Memory │ │Vocab   │ │AI     │ │Audio     │
│FSRS   │ │lookup  │ │provider│ │TTS/cache │
└───┬───┘ └───┬────┘ └───┬───┘ └───┬──────┘
    │         │          │         │
┌───▼─────────▼──────────▼─────────▼───────┐
│ Storage (sqlite3 repositories)            │
│ vocabulary.db        learning.db          │
└───────────────────────────────────────────┘
```

### 2.1 CLI 层（`lexilab/cli`）

只负责：

- 解析命令和选项。
- 构造 `AppContext`（配置、两个数据库、仓储、服务）。
- 把结果交给 Rich 渲染。
- 捕获 `KeyboardInterrupt` 并保证已提交的学习记录不丢。

不直接拼接 SQL，不直接调用 OpenAI SDK。

### 2.2 UI 层（`lexilab/ui`）

- `TerminalUI`：真实终端实现，基于 Rich 渲染、`tty`/`msvcrt` 单键读取、`input()` 文本输入。
- `ScriptedUI`（测试）：按脚本返回输入，供学习流程测试使用。
- 学习流程只依赖 `SessionUI` 协议，因此记忆与调度逻辑可以在无终端环境中测试。

关键原则：单键快捷状态和文本输入状态严格分离。进入文本输入后，`p/q/s` 就是普通字母。

### 2.3 学习引擎（`lexilab/learning`）

- `Planner`：决定今天做什么。到期旧词优先，按错误历史加权；新词数量受到期量与时间预算约束。
- `LearningSession`：执行新词、复习、短时强化、筛选验证；每个结果立即写入数据库。
- `ScreeningService`：处理“已认识”词汇的延迟抽查，不把未测试的自评当作永久掌握。

学习引擎只依赖仓储协议，不知道 Rich、Typer 或 DeepSeek 的存在。

### 2.4 记忆引擎（`lexilab/memory`）

- 封装 `fsrs.Scheduler`、`Card`、`Rating`、`ReviewLog`。
- 每个单词最多两张 FSRS 卡片：`recognition`（英→中）与 `recall`（中→英）。
- 卡片的 `word_key` 是规范化词条字符串，不依赖可重建词库的自增 ID。
- FSRS 状态以官方 `Card.to_dict()` 序列化字段存储，保证可恢复。
- 卡片更新与 `review_logs` 写入在同一个 SQLite 事务中完成。
- 内部时间为 UTC，展示时转换本地时区。

### 2.5 词库（`lexilab/vocabulary`）

- `cet6.py`：解析 KyleBing/english-vocabulary 的完整 JSONL，合并同词多义项，保留原始 JSON。
- `ecdict.py`：流式导入 ECDICT CSV 或兼容的 SQLite 字典，提供查询与词形变化。
- `service.py`：统一查询（六级 → ECDICT → 个人生词），提供词形候选和例句。
- 词库数据库可重建；学习数据库永远不会被词库导入覆盖。

### 2.6 AI（`lexilab/ai`）

- `AIProvider` 协议：`generate(AIRequest) -> AIResponse`。
- `DeepSeekProvider`：OpenAI SDK 兼容接口，JSON mode，有限重试，超时控制。
- `MockProvider`：确定性生成与启发式批改，供测试和离线演示；界面明确标注“模拟”。
- `prompts.py`：从 `ai/prompts/*.txt` 加载模板并记录版本（文件内容哈希）。
- `schemas.py`：Pydantic 校验所有结构化输出。
- `materials.py`：材料生成、校验、缓存与作答记录。AI 输出只作为数据，不执行任何代码或命令。

### 2.7 音频（`lexilab/audio`）

- `TTSProvider` 协议；实现 `flite`（ffmpeg 内置 libflite，完全离线）、`espeak`、`pyttsx3`、`Null`。
- 缓存键 = SHA-256(文本 + provider + voice + rate + 音频参数)，相同内容不重复合成。
- 播放器自动探测 `ffplay` / `aplay` / `paplay` / `afplay` / PowerShell。
- 合成或播放失败只影响听力功能，不影响其他学习功能。

### 2.8 统计（`lexilab/analytics`）

只从真实记录计算：

- 复习日志（FSRS 评分、耗时、间隔）。
- 训练日志（技能维度、正确性、提示使用）。
- `word_errors`（未解决错误）。
- 材料作答记录（阅读/写作结果）。

样本不足时明确显示“数据不足”，不生成虚构百分比。

## 3. 两个数据库

| 数据库 | 内容 | 重建策略 |
|---|---|---|
| `vocabulary.db` | 词条、释义、例句、短语、同近义词、词书、ECDICT | 可重建、可重复导入 |
| `learning.db` | 卡片、复习日志、训练日志、错误、材料、会话、设置 | 永不因词库操作被覆盖；备份/恢复单独处理 |

关联键为规范化词条 `word_key`，例如 `mitigate`。这样即使重新导入词库导致自增 ID 变化，学习记录仍然有效。

## 4. 数据流

### 复习

```
Planner 查询到期卡片
  → LearningSession 展示问题
  → SessionUI 返回答案/评分
  → MemoryService 调用 FSRS 计算新状态
  → 同一事务：更新 cards + 插入 review_logs
  → 下一题
```

### 新词

```
Planner 选词
  → 初次识别自评（认识/不确定/不认识）
  → 展示精简核心信息
  → 插入间隔（interleave_gap）后的主动回忆
  → 真实评分 → 首次 FSRS 复习
  → recall 卡片按配置延迟启用
```

### AI 阅读/听力/写作

```
目标词选择（SQL，确定性）
  → 查缓存材料；无缓存才请求 AI
  → Pydantic 校验 + 确定性覆盖率校验
  → 保存材料
  → 用户作答
  → AI 批改（或 Mock）
  → 保存作答 + 训练日志/错误记录
  → 学习引擎下次优先安排强化
```

## 5. 事务与故障处理

- 所有“状态变更 + 日志”组合操作使用 `BEGIN IMMEDIATE` 事务；异常回滚。
- 每次提交学习结果立即保存，不依赖退出时批量写入。
- Ctrl+C：当前题未评分则不记录；已完成题目已提交，不会丢失。
- 中断后重新执行 `lexi study` 自动检测未完成会话并继续。
- 备份使用 `sqlite3.Connection.backup()`，不直接复制正在写入的数据库文件。

## 6. 依赖方向规则

```
cli → ui / services
ui → services (Model/View) ; ui 不依赖具体 AI
learning → memory / vocabulary / storage 协议
memory → fsrs + storage
ai → schemas/prompts ; 不依赖 storage
storage → sqlite3 ; 不含学习策略
```

## 7. 测试策略

- 单元：词条解析、答案判定、词形覆盖、FSRS 封装、Planner 规则。
- 集成：导入幂等、事务回滚、会话恢复、材料缓存、备份恢复。
- 交互：脚本化 UI 验证快捷键与文本输入分离；非 TTY 回退。
- AI：MockProvider、无效 JSON、空响应、超时、有限重试、覆盖率不足。
- E2E（可选，真实网络/密钥）：真实导入、真实 DeepSeek 调用、真实 TTS。默认测试不消耗付费额度。

## 8. 可选能力与功能分级

系统能力分为三层，并由 `lexilab/capabilities.py` 的轻量 `CapabilityRegistry` 统一检测：

| 层级 | 能力 | 依赖 |
|---|---|---|
| Level 0 | 词库、ECDICT、FSRS、学习流程、筛选、拼写、语境填空、统计、备份 | 仅核心依赖 |
| Level 1 | 发音、单词听写、听音辨义、本地例句句子听写 | 本地 TTS + 播放器 |
| Level 2 | AI 阅读/写作/听力生成与批改、错误分析、强化训练 | 用户启用 AI + `requirements-ai.txt` + model + key |

能力状态明确区分：

- `disabled`：用户主动关闭。
- `unconfigured`：缺少 model、密钥等配置。
- `unavailable`：缺少依赖或运行环境（如未安装 openai、无 TTS/播放器）。
- `ready`：本地配置满足条件，但不代表远程服务已验证。
- `error`：最近一次实际请求失败；可重试，也可降级到本地训练。

启动路径不导入 `openai`、不初始化 `pyttsx3`、不发网络请求。`AIService.available()` 首先检查 `[ai].enabled`，MockProvider 也不例外。`AppContext` 只在需要时创建音频服务；`CapabilityRegistry` 只做本地检测。

依赖拆分：`requirements.txt`（核心）、`requirements-ai.txt`（openai）、`requirements-audio.txt`（pyttsx3）、`requirements-dev.txt`（测试）。`pyproject.toml` 的 optional extras 与之一致。

## 9. 依赖方向补充

- `capabilities` 只依赖配置、仓储与可选的音频服务状态，不反向依赖 CLI。
- 动态菜单由 UI 根据能力字典生成，不直接探测依赖。
- AI/音频失败只影响对应训练入口；Planner 从不安排不可执行的 AI/音频任务。
- 本地缓存材料通过 `materials` 与主界面入口离线访问，不触发模型请求。

