# LexiLab 开发验收报告

验收日期：2026-11-14  
环境：WSL2 / Linux，Python 3.13.9（venv），ffmpeg 6.1.1（含 libflite），ffplay；无 `/dev/snd` 音频设备；未配置 DeepSeek API Key。

## 1. 结论摘要

| 交付项 | 结论 |
|---|---|
| 基础离线版本 | **PASS** |
| AI 扩展模块（实现 + Mock 验证） | **PASS** |
| AI 真实远程教学质量 | **BLOCKED**（无 API Key，未发起真实请求） |
| 语音扩展：合成与缓存 | **PASS** |
| 语音扩展：可听播放与真实听写体验 | **PARTIAL / BLOCKED**（无音频设备，无法确认实际可听输出） |

当前系统在以下配置下可正常使用：

1. **完全不配置 AI、无语音**：完整词汇学习、复习、筛选、拼写、语境填空、统计、备份恢复。
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
| 5 | 主界面自动隐藏不可用功能 | PASS | 无 AI/无语音时菜单仅含基础项与 `[c] 配置` |
| 6 | 每日计划不含不可执行任务 | PASS | `Planner` 只产生词汇/复习/筛选抽查/强化项 |
| 7 | 基础记忆与学习功能 | PASS | 真实六级词库、FSRS、复习、新词、筛选、拼写、语境填空、个人生词 |
| 8 | 记录、统计、备份恢复 | PASS | 自动化测试 + 实际 `lexi backup`；事务回滚、SHA-256、`integrity_check` |
| 9 | 不产生未经授权的 AI 请求 | PASS | `AIService.available()` 先检查 `enabled`；测试确认禁用时 provider 调用次数为 0 |
| 10 | 基础模块测试 | PASS | 76 项自动化测试全部通过 |

### 真实词库与词典

- KyleBing/english-vocabulary 六级 JSONL：**5651 行**，合并同词多义后 **3991 个词条**，跳过异常 **0**；释义 6565、例句 8985。
- 词库 SHA-256 与来源、许可证写入 `source_metadata`。
- ECDICT CSV：**770,611 条**，查询、词形变化、词频字段可用。
- 词库重导入不修改 `learning.db`（有测试）。

### 基础学习实测

```text
lexi init --vocab-file data/raw/cet6.jsonl --skip-ecdict --yes
lexi learn --count 1            # 新词 intro → 主动回忆 → 评分
lexi stats                      # 真实统计：已学习 1，今日复习 1
lexi backup                     # 生成 manifest + 两个数据库快照
```

验证到 `cards` 两张（recognition 启用、recall 延迟）、`review_logs` 1 条且与卡片更新同事务。

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
| AI 关闭 / 语音不可用 | PASS | 隐藏 3/4/5 | 基础键稳定 | 仅本地词汇 | 不调用 AI/音频 | 简洁提示 | PASS | PASS |
| AI 关闭 / 语音可用 | PASS | 显示 3 | 稳定 | 本地词汇 + 语音训练建议 | 仅本地 TTS | 播放失败提示 | PASS | PASS |
| AI 可用 / 语音不可用 | PASS | 显示 4/5，隐藏 3 | 稳定 | 本地词汇 + AI 文本训练建议 | Mock 验证 | AI 错误可重试/跳过 | PASS | PASS |
| AI 可用 / 语音可用 | PASS | 显示 3/4/5 | 稳定 | 完整增强路径 | Mock + flite 验证 | PASS | PASS | PASS |
| AI 网络异常 | PASS | AI 入口保留（error） | 稳定 | 不阻塞词汇 | 抛错并记录 | 提供重试/本地降级 | 不受影响 | PASS |
| 语音播放异常 | PASS | 入口可用但播放报错 | 稳定 | 不阻塞 | 返回失败 | 提示且可继续 | 不受影响 | PASS |
| 历史 AI 材料 / AI 关闭 | PASS | 显示 9 | 稳定 | 不含 AI 任务 | 不请求 AI | 离线查看 | PASS | PASS |

## 6. 自动化测试

命令：

```bash
pytest -q
```

结果：**76 passed**。覆盖：

- 真实六级词库导入、幂等、词义合并、异常行。
- ECDICT CSV 导入、换行解码、lemma 回退、词形变化。
- FSRS 四档评分、序列化、到期队列、事务回滚、elapsed/scheduled days。
- Planner：到期优先、错词优先、动态新词限制、learn 不被到期阻塞、时间预算、交错回忆。
- LearningSession：新词、跳过、Again 短期强化、退出恢复、重复提交保护、筛选抽查失败。
- 答案判定、拼写诊断、听力词错误率。
- 能力状态、动态菜单、禁用 AI 零调用、AI 错误状态。
- AI：Mock 阅读/写作、缓存、无效 JSON 重试、超时/不可用、覆盖率拒绝、提示词版本、配额。
- 音频：flite 合成、缓存键、无 provider、无播放器、禁用状态。
- 备份/恢复、篡改检测、恢复前快照、词库重导入不破坏学习数据。
- CLI：全部命令 `--help`、doctor、AI 关闭提示、音频关闭提示、配置写入、真实离线学习、可选 SDK 启动未导入。
- 缓存材料离线查看、非交互菜单隐藏 AI。

## 7. 交付物

- 可运行 Python 包（`src/lexilab`）与 `lexi` 命令。
- `requirements.txt`、`requirements-ai.txt`、`requirements-audio.txt`、`requirements-dev.txt`、`pyproject.toml`。
- 真实六级词库与 ECDICT 导入工具。
- FSRS 记忆系统、学习流程、CLI/TUI、本地训练、AI 训练、语音、统计、备份恢复。
- `README.md`、`docs/ARCHITECTURE.md`、`docs/LEARNING_DESIGN.md`、`docs/INTERACTION_DESIGN.md`、`docs/DATA_SCHEMA.md`、本报告。
- 自动化测试与真实数据验收记录。

## 8. 已知限制

- 六级词表为第三方整理列表，不是官方考试大纲；合并重复义项后约 3991 个词条。
- 默认学习参数与目标保持率是初始建议，不是科学最优值。
- MockProvider 只用于行为验证，不代表真实模型教学质量；真实 DeepSeek 调用因无密钥标记 BLOCKED。
- 合成语音不等同真实交流环境；本环境无法确认实际可听输出。
- 阅读/写作的开放题批改依赖 AI；关闭 AI 后仅能离线查看历史材料与参考答案，不做自动批改。
