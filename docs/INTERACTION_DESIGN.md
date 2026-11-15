# LexiLab 交互设计

## 1. 设计目标

每天使用的工具，首屏到开始学习最多一次按键；一道题最多一次按键进入答案、一次按键评分。默认 Textual 界面中，全部核心路径均可只用键盘完成，不要求鼠标。

## 2. 输入状态机

```
QUESTION
    ├── Right → Easy → SAVE → NEXT
    ├── Left  → Again → SHOW_ANSWER → Enter → NEXT
    └── Up    → CHECK_ANSWER
                      ├── Left  → Again → SAVE → NEXT
                      └── Right → Hard  → SAVE → NEXT
```

- **菜单选择状态**：`Enter` 进入当前项，`↑/↓` 导航；默认高亮始终是第一项“开始今日学习”。
- **方向键记忆状态**：单词页只显示英文、音标、进度和方向键提示；不预先展示中文释义。
- **文本输入状态**：`PowerInput` / `PowerTextArea` 获得焦点后，方向键只移动光标，不触发评分；进入文本任务时评分状态机已关闭。
- **反馈状态**：文本题仍可用 `Enter` 采用建议、`1`–`4` 覆盖评分；方向键题使用左/上/右。
- **防重复**：每张卡第一次方向键后立即锁定；保存完成才展示下一卡，忽略长按重复事件。
- **非 TTY / CI**：自动回退到 Rich 行式界面，并接受 `left/right/up` 文本键名用于自动化。

## 3. 统一快捷键

| 键 | 功能 |
|---|---|
| `Enter` | 开始今日学习 / 提交 / 下一词 / 采用建议 |
| `←` | 不记得（Again） |
| `↑` | 不太确定（先核对答案） |
| `→` | 容易（Easy，直接下一词） |
| `↑` / `↓` | 菜单与选项导航 |
| `1`–`9` | 设置/子菜单快捷选择；文本反馈页高级评分 |
| `Tab` / `Shift+Tab` | 焦点切换 |
| `P` / `F2` | 播放发音 |
| `E` | 当前词详情（会标记提示状态） |
| `F1` | 文本题提示 |
| `F3` | 听力重播 |
| `Ctrl+Enter` | 提交多行写作 |
| `Ctrl+T` | 开/关动画特效 |
| `Ctrl+P` | 全局命令面板 |
| `Ctrl+Q` | 保存并退出 |
| `Esc` | 取消 / 返回 |

## 4. 主界面（Textual）

```
╭──────────────────────────────────────────────╮
│                  LexiLab                     │
├──────────────────────────────────────────────┤
│ 今日新词  4/20     今日复习  0/12            │
│ 学习时间  8 min    总体进度  32%             │
│                                              │
│ > 开始今日学习                                │
│   设置                                        │
│   退出                                        │
│                                              │
│ Enter 开始   ↑/↓ 选择   Esc 退出              │
╰──────────────────────────────────────────────╯
```

主菜单只有三个入口，不再把复习、新词、统计、词库、筛选、听写、阅读、写作拆成独立按钮。默认焦点为“开始今日学习”，按 Enter 直接进入完整每日流程。

设置包含：学习计划、学习统计、词库管理、专项训练、AI 配置、语音配置、界面与特效、数据备份与恢复、返回。所有子菜单均可用方向键、Enter 和数字键完成。

## 5. 方向键记忆界面

问题状态只显示：

```
──────────────────────────────
LEXILAB           NEW  5 / 20

            mitigate

          /ˈmɪtɪɡeɪt/

            ↑
          不太确定

     ←                →
   不记得             容易

──────────────────────────────
P 发音    E 详情    Esc 返回
```

- `→`：独立轻松回忆，记录 `Easy`，立即进入下一张，不额外展示释义。
- `←`：未回忆，记录 `Again`，显示核心释义、搭配和例句，按 Enter 进入下一词。
- `↑`：先核对答案，然后 `←` 记 `Again`，`→` 记 `Hard`。看到答案后才想起来不能被记成 Hard。
- 作答前不显示中文释义、例句或搭配；`P`/`E` 是显式提示，会标记 `hinted`。
- 每张卡只产生一次正式 FSRS 评分；长按方向键不会连续跳词。

文本任务（中译英、拼写、听写、写作）继续使用文本编辑和原有实时打字特效；方向键在输入框中只移动光标。

## 6. 中译英界面

```
RECALL                         08 / 20

缓解；减轻（动词）

We need to ______ the risk.

[Enter] 提交   [F1] 提示   [F2] 发音   [Ctrl+Q] 退出

Your answer: mitigete

Correct answer: mitigate
拼写错误：第 5 个字母 a 被误写为 e

[Enter] 采用建议 [1]   [1-4] 覆盖评分   [Ctrl+Q] 退出
```

- 判定顺序：精确匹配 → 规范化匹配 → 合法词形 → 拼写近似。
- 拼写近似视为错误，但给出字符级诊断；评分建议 `Again`，用户可覆盖。
- 同义表达无法自动判定时，展示参考答案并允许用户自行判定（`Y` 正确 / `N` 错误）。
- 使用 `F1` 提示或 `F2` 发音后，即使答对也不增加 Combo。

## 7. 新词界面

```
NEW                            03 / 10

                mitigate

你认识这个单词吗？

[1] 认识   [2] 不确定   [3] 不认识   [Ctrl+Q] 退出
[F2] 发音
```

展示核心信息后，该词被放入至少 3 个其他学习项之后，再要求主动回忆。新词先做初识
自评，再进入真实主动回忆；自评本身不写入 FSRS 评分。

## 8. 听力与写作

- 听力默认隐藏原文；`F2` 播放、`F3` 重播、`F1` 提示。提交或放弃后才显示原文。
- 写作使用多行 `PowerTextArea`；`Ctrl+Enter` 提交，输入过程中 `Enter` 只换行。
- 写作 AI 生成与批改期间显示加载/流式状态；`Esc` 可取消，取消后保留已输入内容。
- 批改结果按“错误 / 可接受 / 建议”分开显示，不把风格差异称为错误。

### 8.2 总结页

```text
SESSION COMPLETE

复习卡片: 12
新学单词: 20
用时: 27 min

[Enter] 返回主界面   [R] 继续复习   [N] 额外学习新词   [D] 错词强化
```

不会自动无限追加学习任务；只有用户明确选择才继续。

## 8.1 Power Mode 特效

| 事件 | 表现 | 约束 |
|---|---|---|
| 输入字符 | 输入区粒子；快速连打增强 | 有最大粒子数，关闭特效后为 0 |
| 答对 | 绿色脉冲、粒子、Combo +1 | 仅未使用提示且自动判定正确 |
| 答错 | 局部左右抖动约 200ms、红色边框 | 不抖动整个终端，不阻塞输入 |
| 使用提示/跳过 | 不增加 Combo，清零 | 提示状态传递给反馈层 |
| 切换卡片 | 轻量过渡；Power 预设可播放 TTE 装饰动画 | 动画失败静默降级 |
| 会话完成 | TTE Beams 装饰标题 | 不写数据库，不影响评分 |
| AI 生成 | 加载/流式/打字机效果 | `Esc` 取消，不阻塞其他快捷键 |

`Ctrl+T` 可在会话内即时开关特效。特效开关不改变学习数据、FSRS 状态或评分建议。
`[effects] reduced_motion=true` 时禁用抖动与强动画。

## 9. 终端兼容

| 场景 | 处理 |
|---|---|
| Windows Terminal / PowerShell | Textual 驱动；UTF-8 输出 |
| Linux / WSL | Textual 驱动；`--no-tui` 时使用 `tty.setcbreak` 回退 |
| 窄终端 | 宽度 < 60 时使用紧凑布局；不画宽边框 |
| 不支持颜色 | 尊重 `NO_COLOR`、`--no-color`、非 TTY |
| 中文宽度 | 使用 Rich/Textual 的显示宽度计算，不手工按字节 |
| Ctrl+C | Textual 捕获中断；当前未提交题不记录，已提交记录保留 |
| Ctrl+Q | 保存并退出；未完成会话下次可恢复 |
| Ctrl+D / EOF | 视为安全退出 |
| 异常退出 | 每题即时提交；重新启动可恢复 |
| 非交互 | 打印状态或明确错误，不阻塞等待输入 |

## 10. 减少操作成本的具体规则

- 主界面 `Enter` 直接开始今日学习，不需要选择复习或新词。
- 每阶段自动衔接：新词初学 → 到期复习 → 新词延迟回忆 → 错词强化 → 总结。
- 方向键评分只需一次按键；Right 不展示答案，直接下一张。
- Left 显示答案后只需 Enter；Up 后只需再按一次 Left/Right。
- 总结页提供 `Enter 返回 / R 继续复习 / N 额外新词 / D 错词强化`，不自动无限追加。
- AI/语音不可用不阻断基础流程；专项训练只在设置中按需进入。
- `Ctrl+T` 随时关闭特效；关闭后所有输入、评分、导航键保持不变。

## 11. 主菜单与设置的能力状态

主菜单固定只显示“开始今日学习 / 设置 / 退出”。AI、语音、缓存材料等可选能力不再改变主导航，只在设置中的对应入口显示可用状态或提示。

设置入口使用同一套 Textual 菜单：↑/↓ 选择，Enter 进入，数字键快捷，Esc 返回。未启用的 AI/语音模块仍可在设置中进入配置流程；直接执行未启用命令时只输出：

```
AI 阅读模块尚未启用。

如需使用，请执行：
  lexi config ai
```

不输出 Python 异常堆栈。

## 12. 可选模块配置入口

```bash
lexi config          # 查看当前配置与能力
lexi config ai       # 启用/禁用、provider、model、base_url、密钥环境变量名
lexi config audio    # 启用/禁用、provider、voice、rate、player
lexi doctor          # 详细检测
```

`configs/settings.toml` 中与交互相关的配置：

```toml
[learning]
new_words_per_day = 20
daily_minutes = 30
plan_order = "new_first"  # new_first / old_first / interleaved
adaptive_new_words = true
delayed_recall = true
mistake_drill = true
enable_drills = true
new_word_order = "smart"

[ui]
textual = true

[effects]
enabled = true
intensity = "normal"   # off / minimal / normal / power
typing_particles = true
shake_on_error = true
pulse_on_correct = true
combo = true
startup_animation = true
reduced_motion = false
max_particles = 240
```

密钥只通过环境变量读取；配置界面只显示变量名，不读取或打印密钥值。

## 13. 关联词汇与辨析界面

`lexi related <word>` 在 TTY 中使用 Textual 关系浏览器：

```
┌────────────────────────────────────────────┐
│ LEXILAB / WORD RELATIONS                   │
├────────────────────────────────────────────┤
│                 mitigate                   │
│               vt. 缓和；减轻                 │
│                                            │
│ [1] 同义词(2)  [2] 派生词(3)  [3] 形近词(4)  │
│                                            │
│   alleviate    减轻；缓和                   │
│   lessen       减少；变少                   │
│                                            │
│ ↑/↓ 选择   Enter 学习该词   Esc 返回        │
└────────────────────────────────────────────┘
```

- `1`–`9` 切换关系类型；`↑/↓` 选择；`Enter` 直接进入该词的拼写学习；`Esc`/`Ctrl+Q` 返回。
- 关系来自本地 `vocab_relations`，不是示例硬编码；同时显示源词义标识、目标义词标识和词性。
- 同义/反义/派生/上下位来自 WordNet；形近词来自 RapidFuzz；个人易混淆来自真实学习历史。

命令行入口：

```bash
lexi related mitigate
lexi related mitigate --type synonym
lexi related adapt --type spelling
lexi drill synonyms
lexi drill similar-spelling
lexi drill confusion
lexi relations build       # 显式构建/增量补齐；不会在启动时自动运行
lexi relations stats
```

辨析训练沿用 Textual 输入/粒子/抖动/Combo 体系；作答前只显示一个对比词，不展示完整候选列表。
