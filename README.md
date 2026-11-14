# LexiLab

本地化、以词汇为核心的英语学习命令行工具。

LexiLab 首先是一个完整的离线背单词工具：导入真实六级词库与 ECDICT，使用 Py-FSRS 调度复习，提供英译中、中译英、拼写、语境填空、快速筛选、统计与备份恢复。AI 阅读/写作/听力是可选的增强层，**不配置任何 AI 也能完整使用基础功能**。

- 基础离线学习：始终可用。
- 语音增强：检测到本地 TTS 与播放器时启用。
- AI 增强：用户显式启用并配置后才可能发起请求。

## 1. 安装（Conda 管理 Python 环境）

要求 Python 3.11+。项目统一使用 **Conda 创建/管理 Python 环境**，环境内的依赖仍由 `pip` 安装。

```bash
conda env create -f environment.yml
conda activate lexilab
pip install -e .
```

`environment.yml` 已包含核心运行依赖（Typer、Rich、Prompt Toolkit、Pydantic、Py-FSRS、Textual、TerminalTextEffects、tomli-w）。如果修改了 `requirements.txt`，也可以重新执行：

```bash
pip install -r requirements.txt
pip install -e .
```

### Windows PowerShell / CMD

```powershell
conda env create -f environment.yml
conda activate lexilab
pip install -e .
```

如果 PowerShell 阻止 conda 的初始化脚本，可先执行：

```powershell
conda init powershell
```

然后重新打开终端，再运行 `conda activate lexilab`。

### WSL

```bash
cd /mnt/e/LexiLab
conda env create -f environment.yml
conda activate lexilab
pip install -e .
```

在 WSL 中使用 WSL 自己的 Conda 环境，不要把 Windows 的 Python/Conda 环境与 WSL 混用。如果 `/mnt/e` 上的文件权限或性能异常，可把项目复制到 WSL 家目录后安装。

### 不使用 Conda 时的兼容方式

如果当前机器没有 Conda，也可以使用 `venv` 作为临时替代；项目本身不依赖 Conda 专有包：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```


## 2. 可选扩展

AI（OpenAI SDK，用于 DeepSeek 兼容接口）：

```bash
pip install -r requirements-ai.txt
```

语音（pyttsx3；ffmpeg/espeak-ng 为系统依赖）：

```bash
pip install -r requirements-audio.txt
```

没有安装这些扩展时，程序仍可启动；对应功能显示为不可用或被自动隐藏。

语音合成优先级：`ffmpeg` 内置 `libflite` → `espeak-ng/espeak` → `pyttsx3`。播放器自动探测 `ffplay` / `aplay` / `paplay` / `afplay`。可用 `lexi config audio` 查看检测结果。

## 3. 初始化

```bash
lexi init
```

默认动作：

1. 下载 KyleBing/english-vocabulary 的完整六级 JSONL（约 5651 行，合并同词多义后约 3991 个词条）。
2. 下载并导入 ECDICT 完整 CSV（约 66 MB，约 77 万条）。
3. 创建 `data/vocabulary.db` 与 `data/learning.db`。

`lexi init` **不会覆盖 `learning.db`**。如果只想跳过某部分：

```bash
lexi init --skip-ecdict
lexi init --vocab-file ./data/raw/cet6.jsonl --ecdict-file ./data/raw/ecdict.csv
lexi init --force-vocab --yes
```

AI 不是初始化的一部分，不需要任何密钥。

也可以使用独立脚本（适合在没有安装 `lexi` 命令时）：

```bash
python scripts/setup_vocabulary.py --download
python scripts/import_ecdict.py --download
```

检查环境：

```bash
lexi doctor
```

状态含义：

| 状态 | 含义 |
|---|---|
| `OK` / ready | 本地配置满足使用条件（AI 的 ready 不代表远程服务已验证） |
| `OFF` | 用户主动关闭 |
| `SETUP` | 尚未配置完整（例如缺少 model 或 API key） |
| `N/A` | 可选依赖或运行环境不可用 |
| `ERROR` | 实际执行时发生错误 |

## 4. 日常使用

直接运行：

```bash
lexi
```

主界面只显示当前可执行的任务。默认数字快捷键保持稳定：

- `[Enter]` 开始今日学习
- `[1]` 单词复习 `[2]` 新词学习
- `[3]` 听音辨义/听写（仅音频可用时）
- `[4]` AI 阅读 `[5]` AI 写作（仅 AI 已启用且配置完整时）
- `[6]` 统计 `[7]` 词库管理 `[8]` 快速筛选
- `[9]` 本地材料（存在缓存时）
- `[c]` 配置 `[q]` 退出

常用命令：

```bash
lexi study --minutes 30      # 到期复习优先，再学新词
lexi review                  # 只复习
lexi learn --count 10        # 只学新词
lexi screen                  # 快速筛选已认识的词
lexi lookup mitigate         # 六级词库 → ECDICT → 个人生词
lexi add perturbation        # 加入个人生词与学习队列
lexi drill spelling          # 拼写
lexi drill recall            # 中译英主动提取
lexi drill context           # 本地例句语境填空
lexi drill listening         # 听音辨义（本地 TTS）
lexi drill dictation         # 单词听写（本地 TTS）
lexi drill sentence          # 本地例句句子听写
lexi say mitigate            # 播放本地发音
lexi stats                   # 学习统计
lexi mistakes                # 未解决错误
lexi materials               # 查看缓存材料（可离线）
lexi backup                  # 备份
lexi restore <path> --yes    # 恢复
```

所有命令都支持 `--help`。

### 全键盘与 Textual 界面

在真实 TTY 中运行时，`lexi` 与学习会话默认使用 Textual 全键盘界面；非 TTY/CI 自动使用行式界面。可用 `lexi --no-tui` 强制旧界面。

| 按键 | 作用 |
|---|---|
| `Enter` | 提交 / 下一步 / 翻面（界面会标注当前含义） |
| `Space` | 翻开单词卡片 |
| `1`–`4` | 记忆评分 / 菜单快捷选择 |
| `↑` / `↓` | 菜单导航 |
| `Tab` / `Shift+Tab` | 切换焦点 |
| `Esc` | 取消 / 返回 |
| `Ctrl+P` | 全局命令面板 |
| `Ctrl+Q` | 保存并退出 |
| `Ctrl+Enter` | 提交多行写作 |
| `Ctrl+T` | 开/关动画特效 |
| `F1` | 当前题提示 |
| `F2` | 播放发音 |
| `F3` | 听力重播 |

文本输入状态与全局快捷键严格分离：在英文输入框中，`p`、`q`、`s` 等字母只是输入内容，不会触发快捷键。

### 打字特效与连击

- 拼写、中译英、写作输入时，输入区域下方产生有界字符粒子；快速连续输入会适度增强，但有最大数量限制。
- 答错时仅输入区域/题目区域产生约 200ms 的局部左右抖动和红色边框，不抖动整个终端。
- 答对时绿色脉冲、粒子与进度/Combo 更新；动画不阻塞下一题。
- 只有**未使用提示的独立答对**才增加 Combo；使用提示、跳过或查看答案会中断连击。
- Combo 仅用于反馈，不参与 FSRS 计算，也不影响记忆评分。
- `[effects]` 配置支持 `off`、`minimal`、`normal`、`power`；关闭后所有学习功能仍正常。

### 复习评分

`1` Again、`2` Hard、`3` Good、`4` Easy。`Hard` 是成功回忆但很困难，不是答错；完全忘记或看答案后才想起应记 `Again`。

### 快速筛选

标记“已认识”不会直接永久掌握，而是安排 1、3、7、14、30、90 天的延迟抽查；抽查失败会创建/恢复卡片并记录错误。

## 5. 启用 AI（可选）

```bash
lexi config ai
```

或非交互：

```bash
lexi config ai --enable --provider deepseek --model <官方文档中的模型名>
export DEEPSEEK_API_KEY=...
```

要点：

- `[ai].enabled` 默认 `false`。
- 模型名不硬编码；请从 DeepSeek 官方文档选择当前模型名后填入 `model`。
- 密钥只从环境变量读取，不写入源码、数据库或日志。
- AI 默认每天最多 30 次请求（`max_requests_per_day`），可在配置中调整。
- 启用但缺少依赖/model/key 时，菜单隐藏 AI 入口；直接运行 `lexi read` 会给出简洁说明，不输出异常堆栈。
- AI 请求失败后，命令会提示改用本地拼写/语境训练或跳过；缓存材料仍可离线查看。

测试或离线演示可把 `provider = "mock"`，此时使用确定性的 MockProvider，界面会明确标注“模拟”。

## 6. 配置

配置文件查找顺序：

1. `--config <path>`
2. 环境变量 `LEXILAB_CONFIG`
3. `configs/settings.toml`
4. `~/.config/lexilab/settings.toml`
5. 内置默认值

数据目录可用 `--data-dir` 或环境变量 `LEXILAB_DATA_DIR` 覆盖。

```bash
lexi config             # 查看
lexi config --init      # 写入 configs/settings.toml（已存在则不覆盖）
lexi config ai          # 配置 AI
lexi config audio       # 配置语音
```

## 7. 数据与备份

```
data/
├── vocabulary.db   # 可重建的词库
├── learning.db     # 学习记录，必须备份
├── raw/            # 下载的原始词库
├── audio/          # TTS 缓存
└── backups/
```

- 每次学习结果立即写入，程序中断不会丢失已提交记录。
- 备份使用 SQLite `backup()`，不会粗暴复制正在写入的数据库。
- 恢复前会校验 manifest / SHA-256 / `integrity_check`，并自动快照当前数据库。
- 关闭 AI 不会删除历史材料、写作批改、错误记录、统计或 FSRS 状态。

### 交互与特效配置

`configs/settings.toml` 可调整 Textual 与 Power Mode：

```toml
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

`lexi --no-tui` 可临时回退旧行式界面；`reduced_motion = true` 会关闭抖动与强动画。
特效仅影响显示，不改变 FSRS 评分或学习记录。

## 8. 测试

```bash
pip install -r requirements-dev.txt
pytest
```

测试默认使用临时数据库，不会污染 `data/`。真实六级词库导入测试在 `data/raw/cet6.jsonl` 存在时运行；真实 ECDICT 全量导入需手动验收，测试中使用小样本 CSV。

## 9. 已知限制与说明

- 六级词库来自第三方整理项目 KyleBing/english-vocabulary（BSD-3-Clause），**不是官方考试大纲**。
- ECDICT 来自 skywind3000/ECDICT（MIT）。
- TTS 使用本地合成语音，不等同于真实英语交流环境。
- MockProvider 是离线测试替身，其批改质量不代表真实模型。
- FSRS 的目标保持率与每日参数是初始建议，不是对所有学习者最优的证明。
- 统计区分“未评估”“数据不足”，不把 FSRS 预测概率当作真实测试正确率。

## 10. 卸载/清理

```bash
conda deactivate
conda env remove -n lexilab
```

删除 `data/` 会删除全部真实学习记录，请先 `lexi backup`。如果曾使用临时 venv，也可删除 `.venv/`。
