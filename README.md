# bilibili-obsidian-notes

把 B 站课程/讲座视频整理成**可复习、可检索、可续做**的 Obsidian 笔记库，并且**能被脚本验证**。

English: an agent skill that turns Bilibili lecture series into a structured, verified Obsidian
knowledge base. Transcription runs fully local (sherpa-onnx SenseVoice) — no audio leaves your
machine. It has been driven end-to-end over 100-lecture courses, so the batch pipeline and its
failure modes are documented from real runs, not designed on paper.

- 核心不是「转写全文」，而是**按讲师自己的结构**落成带出处、带截图、带自测的知识点笔记。
- 每一处产出都对得上磁盘：`verify_course.py` 要求 `HARD=0` 才算交付。
- 整门课（几十到上百讲）走批处理：主代理串行采集，子代理并行写笔记，索引由脚本回填。

## 它能给你什么

| 你想要的 | 靠什么 |
|---|---|
| 一讲笔记：正文 + 本讲索引 + 扩展笔记 + 关键截图 | `SKILL.md` Step 1–8 |
| 整门课：章/讲两级结构、可续跑、不重复劳动 | `references/batch-pipeline.md` |
| 多个子代理并行不互相踩 | `references/subagent-rules.md`（四种真实失败与对策） |
| 笔记在 Obsidian 里链接/表格真的能渲染 | `scripts/fix_course_md.py` + `scripts/verify_course.py` |
| 删掉几个 G 的原片之前不丢东西 | `scripts/backup_workdir.py`（备份 → 校验 → 哈希比对，才允许删） |

## 安装

放到你的 agent skills 目录即可，例如：

```bash
git clone <this-repo-url> ~/.codex/skills/bilibili-obsidian-notes   # 或 Qoder / Claude Code 的 skills 目录
```

依赖：

```bash
pip install -r requirements.txt      # yt-dlp, sherpa-onnx, numpy
# 外部命令：ffmpeg / ffprobe（Python 依赖之外的唯一硬要求）
```

## 配置

编辑 `references/course-config.json`（出厂为空），或直接用命令行参数/环境变量：

| 键 / 环境变量 | 说明 |
|---|---|
| `vault` | 你的 Obsidian 库路径，例如 `/docs/my-vault` 或 `D:/Notes/vault` |
| `sensevoice_model_dir` / `SENSEVOICE_MODEL_DIR` | 含 `model.int8.onnx` 与 `tokens.txt` 的目录 |
| `YTDLP` / `FFMPEG` / `FFPROBE` | 覆盖默认命令名 |
| `SENSE_THREADS` / `OPENBLAS_NUM_THREADS` | 转写并发，默认 2 / 1（防止多个进程互相拖垮） |
| `SHEET_INTERVAL` | 总览拼图的抽帧间隔秒数，默认 15 |

### Transcription model

SenseVoice 模型一次下载，之后全离线：

```bash
# ModelScope（国内快）
python -c "from modelscope import snapshot_download; \
  snapshot_download('sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17', local_dir='./models')"
# 或 Hugging Face: csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17
export SENSEVOICE_MODEL_DIR=./models
```

想换别的 ASR（Whisper 等）：只需要产同一种中间产物——`transcript.txt`（每行 `[mm:ss] 文本`）
和 `transcript.json`（`{start, end, text}`）。后续步骤只吃这两个文件。

## 快速上手（单讲）

```bash
python scripts/bili_meta.py --url "<b23.tv 或 B站链接>" --out work/meta.json
yt-dlp -f "30080+30280/bv*[height<=1080]+ba" --merge-output-format mp4 \
  --referer "https://www.bilibili.com/" -o work/video.mp4 "<该分P的url>"
yt-dlp --write-subs --write-auto-subs --sub-langs "zh,zh-Hans,zh-Hant,en" \
  --skip-download -o work/sub "<该分P的url>"        # 有字幕就别转写了
python scripts/transcribe_sensevoice.py --input work/video.mp4 --out-dir work/transcribe
bash scripts/frames.sh contact-sheet work/video.mp4 work/frames
```

然后按 `references/note-structure.md` 的模板写笔记，最后：

```bash
python scripts/verify_course.py --vault "<vault>/<course>" --manifest work/manifest.json --strict
```

## 试一把，不用联网

仓库带了一个**故意做错**的示例课程库，专门用来验证链接与表格修复：

```bash
python scripts/verify_course.py --vault evals/fixtures/skillfix/vault \
  --manifest evals/fixtures/skillfix/manifest.json
#   HARD=2：一个 [[../x]] 相对链接 + 一个表格内裸竖线导致的断列

python scripts/fix_course_md.py --vault evals/fixtures/skillfix/vault \
  --manifest evals/fixtures/skillfix/manifest.json
#   修完再跑校验 → HARD=0 SOFT=0，退出码 0；重跑修复 = 0 改动（幂等）
```

⚠️ 上面这两条命令会改掉 fixture 里的缺陷文件。想反复演示，先 `cp -r evals/fixtures/skillfix /tmp/`。

## 产出结构

```text
<vault>/<course_dir>/
├─ 00-课程索引.md
└─ 第N章-主题/
   ├─ 00-本章索引.md          （本章主线 / 公式速查 / 易错点）
   └─ N-M-讲标题/
      ├─ 00-本讲索引.md        （知识点表 + 视频进度 + 本讲速记）
      ├─ 01-….md … 09-….md    （多篇知识点正文）
      ├─ 99-扩展笔记.md        （考点清单 / 公式速查 / 易错点 / 典型题）
      └─ assets/N-M-01_说明.png
```

## 已知边界

- **平台**：全流程在 Windows + Git Bash 上跑通并长期使用者；编码坑（GBK 控制台、CRLF、heredoc 吞反斜杠）
  是 Windows 特有的。下载/截帧/校验在 macOS/Linux 上应当可用，但**未经实测**，欢迎报 issue。
- **B 站登录与画质**：1080P 的 AVC 分片有时需要 cookie，HEVC/AV1 通常免登录；`--cookies-from-browser chrome`
  或降级 720P 就够。请遵守 B 站服务条款与UP 主的版权要求。
- **不含任何课程正文**：仓库只有方法论 + 脚本 + 空模板。示例库 `evals/fixtures/` 是为测试编造的虚构内容。
- **ASR 只是草稿**：SenseVoice 会把术语听成同音字。写笔记前必须用幻灯片校正，并为每门课留一张纠错表
  （模板 `references/course-guide-template.md`）。
- **子代理相关章节**（`references/subagent-rules.md`）默认你在用有子代理能力的 coding agent；
  纯手动也能跑，只是整课模式串行会慢。

## 目录

```
SKILL.md                      给 agent 读的入口：模式判定 + 单讲 8 步 + 整课 8 步 + 故障排查表
references/note-structure.md  三种结构怎么选、时长→拆篇数、五层模板
references/batch-pipeline.md  整门课的 8 步
references/subagent-rules.md  并行子代理的四种失败与对策、任务书模板
references/obsidian-pitfalls.md  表格竖线 / wikilink / CRLF / GBK / 归属四分法
references/course-config.json    默认路径（开箱为空）
references/course-guide-template.md  单门课口径手册 + ASR 纠错表模板
references/01-video-template.md · 02-extension-template.md  单讲双笔记模板
scripts/                      9 个脚本，见 SKILL.md 的「参考文件」一节
evals/evals.json              6 条验收用例（1–4 需联网，5–6 离线）
evals/fixtures/skillfix/      故意做坏的示例库，离线验证校验器与修复器
```

## License

MIT
