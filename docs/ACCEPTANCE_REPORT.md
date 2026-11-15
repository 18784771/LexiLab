# LexiLab 开发验收报告

验收日期：2026-11-15
环境：WSL2 / Linux，Python 3.13.9（当前 venv 运行测试）；项目提供 Conda 环境定义 `environment.yml`（Python 3.12，`conda env create --dry-run` 通过）；ffmpeg 6.1.1（含 libflite），ffplay；WordNet 3.0、RapidFuzz 3.14.6；无 `/dev/snd` 音频设备；未配置 DeepSeek API Key。

## 1. 结论摘要

| 交付项 | 结论 |
|---|---|
| 基础离线版本 | **PASS** |
| Textual 全键盘交互 + Power Mode 特效 | **PASS** |
| 极简主界面 + 方向键记忆交互 | **PASS** |
| 大字体与视觉舒适性 | **PASS** |
| 词汇关系引擎 + 智能新词排序 | **PASS** |
| Conda 环境定义 | **PASS**（dry-run 验证） |
| AI 扩展模块（实现 + Mock 验证） | **PASS** |
| AI 真实远程教学质量 | **BLOCKED**（无 API Key，未发起真实请求） |
| 语音扩展：合成与缓存 | **PASS** |
| 语音扩展：可听播放与真实听写体验 | **PARTIAL / BLOCKED**（无音频设备，无法确认实际可听输出） |

当前系统在以下配置下可正常使用：

1. **完全不配置 AI、无语音**：完整每日学习、方向键记忆评分、拼写、语境填空、统计、备份恢复。
2. **仅有本地语音**：在上述基础上增加发音、听音辨义、单词听写、本地例句句子听写。
3. **启用并完整配置 AI**：增加 AI 阅读、AI 写作、AI 听力文本生成与批改；听力仍需本地音频。
4. **关闭 AI 后**：历史材料、批改、错误、统计、FSRS 状态全部保留，可通过 `lexi materials` 离线查看。

## 2. 基础离线交付验收

| # | 检查项 | 结果 | 证据 |
|---|---|---|---|
| 1 | 未安装 AI 扩展依赖时正常启动 | PASS | 使用仅 `requirements.txt` 的新 venv 启动 `lexi --help`/`lexi doctor`；`openai` 未被导入 |
| 2 | 未安装语音扩展依赖时正常启动 | PASS | `pyttsx3` 未被导入；语音自动检测失败时功能隐藏 |
| 3 | 没有 API Key 时正常学习 | PASS | 默认 `[ai].enabled=false`；`lexi learn` 完成真实卡片与复习日志写入 |
| 4 | 完全断网时正常学习 | PASS | 学习路径不依赖网络；默认关闭 AI，启动不联网 |
| 5 | 主界面极简 | PASS | Textual/Rich 主菜单仅“开始今日学习 / 设置 / 退出”，默认焦点第一项 |
| 6 | 设置承载管理功能 | PASS | 学习计划、统计、词库、专项训练、AI/语音、界面特效、备份恢复全部在设置子菜单 |
| 7 | 快速筛选不再独立 | PASS | 主菜单/命令面板/学习计划无快速筛选；`lexi screen` 已移除；历史 `screening` 数据保留 |
| 8 | 每日自动流程 | PASS | 新词初学 → 到期复习 → 延迟回忆 → 错词强化 → 总结；支持 new_first/old_first/interleaved |
| 9 | 方向键记忆交互 | PASS | ← Again、↑ 核对后 Again/Hard、→ Easy；作答前不显示释义；单卡单评分 |
| 10 | 基础记忆与学习功能 | PASS | 真实六级词库、FSRS、复习、新词、拼写、语境填空、个人生词 |
| 11 | 记录、统计、备份恢复 | PASS | 自动化测试 + 实际 `lexi backup`；事务回滚、SHA-256、`integrity_check` |
| 12 | 不产生未经授权的 AI 请求 | PASS | `AIService.available()` 先检查 `enabled`；测试确认禁用时 provider 调用次数为 0 |
| 13 | 基础模块测试 | PASS | 134 项自动化测试全部通过 |
| 14 | Textual 全键盘学习 | PASS | `run_test` 覆盖新词、输入、评分、反馈、菜单、`Ctrl+Q`；文本输入不触发快捷键 |
| 15 | Power Mode 特效 | PASS | 粒子有界、快速输入增强、答错局部抖动、答对脉冲、Combo 仅未提示正确增加 |
| 16 | 特效不阻塞、可关闭 | PASS | `Ctrl+T` 即时开关；timer/worker 异步执行；关闭后学习落库不变 |
| 17 | TerminalTextEffects 适配 | PASS | 逐帧读取 ANSI 并转 Rich `Text`；测试确认不直接写终端 |
| 18 | 写作/阅读 Textual 流程 | PASS（Mock AI） | 加载状态、`Ctrl+Enter` 提交、粒子、批改、结果返回 |
| 19 | Conda 环境 | PASS | `conda env create -f environment.yml --dry-run` 退出码 0；Python 3.12 + 核心依赖 |
| 20 | 默认新词排序 | PASS | 默认为 `smart`，字母顺序仅显式 `--order alphabetical` |
| 21 | 词汇关系构建 | PASS | 真实词库 3991 源词，WordNet 138,736 条 + RapidFuzz 1,516 条，总 140,252 条 |
| 22 | 关系查询与全键盘浏览 | PASS | `lexi related` 与 Textual 关系浏览器；数字切类型、方向键、Enter、Esc |
| 23 | 近义/形近/个人混淆辨析 | PASS | `drill synonyms`、`drill similar-spelling`、`drill confusion`；真实混淆才记录词对 |
| 24 | 关系构建不改变 FSRS | PASS | 构建前后 cards 8→8、review_logs 3→3；测试覆盖增量/重建 |
| 25 | 主菜单默认 Enter 开始 | PASS | Textual `run_test` 无方向键按 Enter 返回 `study` |
| 26 | 设置可修改学习目标 | PASS | 自动化测试写入每日新词、时间、顺序、自适应、延迟回忆、错词强化并保存 TOML |
| 27 | 方向键状态机 | PASS | Right→Easy、Left→答案→Enter→Again、Up→Left→Again、Up→Right→Hard |
| 28 | 防重复/长按 | PASS | 同一卡 `_accepting_rating` 锁定，连续方向键只产生 1 条 review_log |
| 29 | 文本输入不受方向键影响 | PASS | 方向键仅作用于 recognition 状态；production 的 Input 保持光标编辑 |
| 30 | 退出恢复 | PASS | 已有 Ctrl+Q 保留 pending 项测试；每日计数来自真实 cards/review_logs，不重复统计 |
| 31 | 无 AI 可完整学习 | PASS | 基础测试全部使用 AI 关闭上下文；AI 仅设置入口 |
| 32 | 从其他目录调用统一数据库 | PASS | `cd /tmp && LEXILAB_CONFIG=/mnt/e/LexiLab/configs/settings.toml lexi stats --json` 返回同一 `total_words=3991`、`learned_total=4`；配置路径解析统一 data 目录 |
| 33 | 大字符单词 | PASS | `comfortable/large` 使用 5 行块状字模；`normal` 可关闭；区块字符只在单词区域 |
| 34 | 长词与窄屏回退 | PASS | `internationalization` 在 30 列回退普通文本；44×16 小窗口仍可完成评分 |
| 35 | 中文/音标可读 | PASS | 释义和音标使用普通可换行文本，不经过块状字模；高对比度样式 |
| 36 | 自适应布局 | PASS | 窄窗口隐藏粒子区域、切换单行方向键提示；宽窗口展示大字符与间距；运行时缩放即时重排且保留当前卡片 |
| 37 | 字体说明 | PASS | `docs/DISPLAY_GUIDE.md` + README 提供 Windows Terminal、VS Code、MobaXterm、Linux 终端设置 |
| 38 | 真实渲染截图 | PASS | `docs/screenshots/` 包含菜单、普通/舒适/大字符/小窗口 SVG |

### 真实词库与词典

- KyleBing/english-vocabulary 六级 JSONL：**5651 行**，合并同词多义后 **3991 个词条**，跳过异常 **0**；释义 6565、例句 8985。
- 词库 SHA-256 与来源、许可证写入 `source_metadata`。
- ECDICT CSV：**770,611 条**，查询、词形变化、词频字段可用。
- 词库重导入不修改 `learning.db`（有测试）。

### 基础学习实测

```text
lexi init --vocab-file data/raw/cet6.jsonl --skip-ecdict --yes
lexi learn --count 1            # 新词方向键初学 → 延迟回忆 → 评分
lexi stats                      # 真实统计：已学习 1，今日复习 1
lexi backup                     # 生成 manifest + 两个数据库快照
```

验证到 `cards` 两张（recognition 启用、recall 延迟）、`review_logs` 1 条且与卡片更新同事务。

### 真实终端与自动化证据

```text
$ LEXILAB_NO_TUI=1 lexi < /dev/null
┌──────────────────────────── LexiLab ────────────────────────────┐
│ 今日新词：0/20    今日复习：0/2                                  │
│ 学习时间：0 min   总体进度：0%                                   │
│ > 开始今日学习                                                   │
│   设置                                                           │
│   退出                                                           │
└─────────────────────────────────────────────────────────────────┘
非交互环境：请使用 lexi --help 查看命令。
```

方向键状态机测试：

```text
test_right_arrow_records_easy_and_advances PASSED
test_left_arrow_shows_answer_then_enter_records_again PASSED
test_up_then_left_is_again_not_hard PASSED
test_up_then_right_is_hard PASSED
test_repeated_direction_does_not_duplicate_review PASSED
test_new_intro_right_records_one_review_and_skips_delayed_recall PASSED
test_new_intro_up_then_right_records_hard_once PASSED
test_text_input_arrows_do_not_trigger_memory_rating PASSED
```

从其他目录调用统一数据库：

```bash
cd /tmp
LEXILAB_CONFIG=/mnt/e/LexiLab/configs/settings.toml lexi stats --json
# total_words=3991, learned_total=4（与项目目录一致）
```

## 3. AI 扩展验收

| 项目 | 结果 | 说明 |
|---|---|---|
| DeepSeek/OpenAI SDK 兼容实现 | PASS | 延迟导入 openai；base_url/model 来自配置；JSON mode |
| 模型名不硬编码 | PASS | `[ai].model` 为空时状态为 `unconfigured` |
| 密钥管理 | PASS | 仅从配置指定环境变量读取；配置/日志不写密钥 |
| 结构化输出与校验 | PASS | Pydantic schema + JSON 提取 + 有限重试 |
| 阅读生成/批改 | PASS（Mock） | 覆盖率校验、2–3 题、批改记录、语境训练回流 |
| 听力文本生成 | PASS（Mock） | 句子 + 翻译 + 目标词覆盖 |
| 写作生成/批改 | PASS（Mock） | 三级任务、错误/可接受/风格区分、错误回流 |
| 错误强化 | PASS（Mock） | `error_reinforcement` 结构化输出 |
| 缓存与离线查看 | PASS | `materials` 表 + `lexi materials --show` |
| 请求预算 | PASS | `max_requests_per_day` 配额 |
| 失败降级 | PASS | 错误状态可重试；命令提示本地拼写/语境训练或跳过 |
| 真实 DeepSeek 教学质量 | **BLOCKED** | 无 API Key；未消耗真实额度，未声称已验证 |

AI 状态区分：`disabled / unconfigured / unavailable / ready / error`。`ready` 仅表示本地配置完整，明确不表示远程服务已验证。

## 4. 语音扩展验收

| 项目 | 结果 | 说明 |
|---|---|---|
| 本地语音合成 | PASS | ffmpeg + libflite 实际生成 WAV；espeak/pyttsx3 为可选后端 |
| 音频缓存 | PASS | 相同文本/provider/voice/rate 命中同一缓存；不重复合成 |
| 播放器探测 | PASS | 探测到 ffplay |
| 可听播放 | **BLOCKED** | 环境无 `/dev/snd`；命令返回成功但无法确认实际可听输出 |
| 单词发音入口 | PASS（实现） | `lexi say`、学习页 `p`；不可用时隐藏 |
| 听音辨义 | PASS（交互与落库） | 真实 flite 合成 + 四选一 + `training_logs` |
| 单词听写 | PASS（实现） | 本地 TTS + 拼写判定 |
| 句子听写 | PASS（实现） | 使用本地例句，不调用 AI |
| 语音不可用时降级 | PASS | 隐藏入口；`lexi drill listening` 给出简洁说明 |

语音扩展结论：**PARTIAL**。软件层合成、缓存、训练与降级可验证；实际可听输出受外部音频设备阻塞，不据此判定基础版本失败。

## 5. 配置组合测试矩阵

| 场景 | 启动 | 菜单 | 快捷键 | 每日计划 | 模块调用 | 异常处理 | 数据保存 | 降级 |
|---|---|---|---|---|---|---|---|---|
| AI 关闭 / 语音不可用 | PASS | 固定三入口 | 方向键稳定 | 仅本地词汇 | 不调用 AI/音频 | 简洁提示 | PASS | PASS |
| AI 关闭 / 语音可用 | PASS | 固定三入口 | 稳定 | 本地词汇 + 设置中的语音训练 | 仅本地 TTS | 播放失败提示 | PASS | PASS |
| AI 可用 / 语音不可用 | PASS | 固定三入口 | 稳定 | 设置中显示 AI 配置/训练 | Mock 验证 | AI 错误可重试/跳过 | PASS | PASS |
| AI 可用 / 语音可用 | PASS | 固定三入口 | 稳定 | 完整增强路径 | Mock + flite 验证 | PASS | PASS | PASS |
| AI 网络异常 | PASS | 固定三入口，设置内显示 error | 稳定 | 不阻塞词汇 | 抛错并记录 | 提供重试/本地降级 | 不受影响 | PASS |
| 语音播放异常 | PASS | 固定三入口 | 稳定 | 不阻塞 | 返回失败 | 提示且可继续 | 不受影响 | PASS |
| 历史 AI 材料 / AI 关闭 | PASS | 固定三入口 | 稳定 | 设置中可查看材料 | 不请求 AI | 离线查看 | PASS | PASS |

## 6. 自动化测试

命令：

```bash
pytest -q
```

结果：**134 passed**。覆盖：

- 真实六级词库导入、幂等、词义合并、异常行。
- ECDICT CSV 导入、换行解码、lemma 回退、词形变化。
- FSRS 四档评分、序列化、到期队列、事务回滚、elapsed/scheduled days。
- Planner：可配置 new_first/old_first/interleaved、到期优先（old_first）、错词优先、动态新词限制、learn 不被到期阻塞、时间预算、交错回忆、无强制 VERIFY。
- LearningSession：新词方向键初学、跳过、Again 短期强化、退出恢复、重复提交保护、首次浏览不伪造成功。
- 方向键：Right=Easy、Left=Again、Up+Left=Again、Up+Right=Hard、长按/重复去重、文本输入方向键不评分。
- 答案判定、拼写诊断、听力词错误率。
- 能力状态、动态菜单、禁用 AI 零调用、AI 错误状态。
- AI：Mock 阅读/写作、缓存、无效 JSON 重试、超时/不可用、覆盖率拒绝、提示词版本、配额。
- 音频：flite 合成、缓存键、无 provider、无播放器、禁用状态。
- 备份/恢复、篡改检测、恢复前快照、词库重导入不破坏学习数据。
- CLI：全部命令 `--help`、doctor、AI 关闭提示、音频关闭提示、配置写入、真实离线学习、可选 SDK 启动未导入。
- 缓存材料离线查看、非交互菜单隐藏 AI。
- Textual：新词会话、输入不触发快捷键、关闭粒子后仍可完成、`Ctrl+Q` 保留未完成题、菜单方向键/数字键、`Ctrl+T` 不改变输入、提示答对不计连击。
- Power Mode：粒子有界、快速输入增强、错误抖动、正确脉冲、Combo 状态。
- 写作 Textual：Mock AI 加载、`Ctrl+Enter` 提交、粒子、反馈与结果返回。
- TTE：逐帧 ANSI 数据可转换为 Rich `Text`，不直接写终端。
- WordNet：同义/反义/派生/上下位/多义词/未知词。
- RapidFuzz：归一化范围、字符交换、短词、词形变化排除、候选数量上限。
- 关系库：唯一键去重、类型过滤、增量构建、重建后保留个人混淆、FSRS 状态不变。
- 智能排序：高频优先、已学关联提升、形近干扰惩罚、无词频降级、显式字母排序、到期卡优先。
- 极简主界面：仅三入口、默认 Enter、设置子菜单、快速筛选入口移除。
- 方向键状态机：Right/Easy、Left/Again、Up+Left/Again、Up+Right/Hard、重复按键去重、文本输入不触发评分。
- 每日计划：new_first 自动衔接、new/old/interleaved 配置、到期优先测试、无强制 VERIFY。
- 设置计划：每日新词/时间/顺序/自适应/延迟回忆/错词强化写回配置。
- 显示：块状字模宽度、长词回退、模式开关、44×16 小窗口可用、Textual 大字符渲染与文本输入不冲突。
- 显示配置：`display_mode`、`large_word_display`、`high_contrast`、`compact_mode` 默认值与渲染行为。
- 真实渲染截图：`docs/screenshots/*.svg`，由 Textual `export_screenshot()` 生成。
- 关系交互：Textual 关系浏览器数字切换、方向键与 Enter 选择；CLI 查询/统计/构建帮助。

## 7. 交付物

- 可运行 Python 包（`src/lexilab`）与 `lexi` 命令。
- `environment.yml`（Conda 环境）、`requirements.txt`、`requirements-ai.txt`、`requirements-audio.txt`、`requirements-dev.txt`、`pyproject.toml`。
- 真实六级词库与 ECDICT 导入工具。
- FSRS 记忆系统、学习流程、Textual 全键盘 TUI、Power Mode 特效、本地训练、AI 训练、语音、统计、备份恢复。
- `README.md`、`docs/ARCHITECTURE.md`、`docs/LEARNING_DESIGN.md`、`docs/INTERACTION_DESIGN.md`、`docs/DATA_SCHEMA.md`、`docs/PROJECT_CHECK.md`、`docs/VOCABULARY_RELATION_DESIGN.md`、`docs/LEARNING_ORDER_DESIGN.md`、`docs/VOCABULARY_RELATION_REPORT.md`、本报告。
- `scripts/relation_acceptance.py` 与 `reports/relation_acceptance.json`（真实排序对照）。
- `scripts/render_ui_screenshots.py` 与 `docs/screenshots/*.svg`（真实 Textual 渲染截图）。
- `docs/DISPLAY_GUIDE.md`（终端字体与显示模式指南）。
- 自动化测试与真实数据验收记录。

## 8. 已知限制

- 六级词表为第三方整理列表，不是官方考试大纲；合并重复义项后约 3991 个词条。
- 默认学习参数与目标保持率是初始建议，不是科学最优值；每日新词默认 20，可按设置调整。
- 方向键默认不展示 Good 按钮；FSRS 的 Good 仍保留给文本训练/高级评分，不删除。
- 快速筛选业务表和历史数据保留，但不再有用户入口。
- 自动化交互通过 `App.run_test` 验证；真实 Windows Terminal 的字体/输入法仍建议人工冒烟。
- 终端真实字体大小由终端程序控制，LexiLab 只能通过内部布局/块状字模和终端字体设置说明改善可读性。
- 块状字模只支持有限英文/数字字符；长词、窄屏和特殊字符使用普通文本回退。
- MockProvider 只用于行为验证，不代表真实模型教学质量；真实 DeepSeek 调用因无密钥标记 BLOCKED。
- 合成语音不等同真实交流环境；本环境无法确认实际可听输出。
- Textual 交互通过 `App.run_test` 自动化验证；真实 Windows Terminal / PowerShell 的
  字体、输入法与终端尺寸差异仍建议人工冒烟。
- 关系构建约 254 秒，属于显式初始化成本；日常启动不会重建。
- 词频排序可能选中功能词；后续可按考试标签/用户水平过滤，但当前不伪造“学习效果”。
- 排序对照仅验证行为指标，不宣称已在真实学习者中证明提高记忆效果。
- 阅读/写作的开放题批改依赖 AI；关闭 AI 后仅能离线查看历史材料与参考答案，不做自动批改。
