# bilibili-obsidian-notes

把课程/讲座视频整理成**可复习、可检索、可续做**的 Obsidian 笔记库，并且**能被脚本验证**。
以 B 站为主，任何 `yt-dlp` 能解析的源（YouTube 等）都走同一条链路。

English: an agent skill that turns lecture videos into a structured, verified Obsidian
knowledge base. Bilibili-first, but any yt-dlp-supported source works and keeps the same
pipeline. Transcription runs fully local (sherpa-onnx SenseVoice) — no audio leaves your
machine. It has been driven end-to-end over 100-lecture courses, so the batch pipeline and its
failure modes are documented from real runs, not designed on paper.

- 核心不是「转写全文」，而是**按讲师自己的结构**落成带出处、带截图、带自测的知识点笔记。
- 每一处产出都对得上磁盘：`verify_course.py` 要求 `HARD=0` 才算交付。
- 整门课（几十到上百讲）走批处理：主代理串行采集，子代理并行写笔记，索引由脚本回填。

## 它解决什么问题

一条 45 分钟的 B 站课程视频，常见做法的产出是「一坨转写文本 + 三段总结」。三个月后回来看，这些东西基本没用：

- 术语被 ASR 听成同音字，而且**错了你不知道**（坡印廷→坡形亭、媒质→酶质、时谐场→实写场）；
- 公式丢了单位和适用条件，矢量方向丢了判据；
- 想回看那块板书，但没留时间点，只能重刷整条视频；
- 分不清哪句是老师讲的、哪句是自己补的，复习时把补充内容当成课上原文；
- 笔记之间没有链接，或者链接在 Obsidian 里点不开、表格渲染成断列；
- 做到第 20 讲断了，重跑时前面 19 讲又做了一遍，或者不知道该接着做哪一讲；
- 硬盘里躺着十几个 G 的原片，不敢删、删了又后悔。

这个 skill 把一门课落成**一个库**：章 → 讲 → 多篇知识点正文 + 本讲索引 + 扩展笔记 + 关键截图，
每一层都有模板，而且**每一处都对得上磁盘**。核心机制是把「质量」变成可执行判据：

> `verify_course.py --strict` 跑到 `HARD=0`、退出码 0，才算这一讲/这门课做完。

## 能给你什么

| 你想要的 | 靠什么 |
|---|---|
| 一讲完整笔记：正文 + 本讲索引 + 考点/易错点/典型题 + 按需截图 | `SKILL.md` Step 1–8 |
| 整门课（几十到上百讲）可续跑、不重复劳动 | `scripts/course_prep.py`（幂等采集）+ `references/batch-pipeline.md` |
| 多个子代理并行写笔记不互相覆盖 | `references/subagent-rules.md`（四种真实失败与对策） |
| 术语不被同音字污染 | Step 3「转写只是草稿」+ 每课一张 ASR 纠错表 + `verify_course.py --asr` 扫残留 |
| 出处可查，能回到视频那一秒 | 每张图标「视频 mm:ss」；本讲索引给知识点→进度区间；frontmatter 带分 P 链接 |
| 不把自己补的内容当成课上原文 | 归属四分法（幻灯片 / 板书 / 口述 / 补充），自拟题必须标注 |
| 链接点不开、表格断列能自动修 | `scripts/fix_course_md.py`（幂等，`--dry-run` 可先看） |
| 索引统计和磁盘真实情况一致 | `scripts/fill_indexes.py` 按存在的文件回填，禁止手改、禁止 agent 口头汇报 |
| 删原片之前不丢东西 | `scripts/backup_workdir.py`：备份 → 校验 zip → SHA256 → 比对 vault 哈希，才允许删 |
| 内容层面的错（公式符号、图注不符、自拟题算错） | Step 8 派**只读**复核代理逐条对转写与总览图，报告必须引用现文原文 |

**实测规模**：单门课最多 100 讲；45 集 / 95 讲 / 14 讲三门课的分工、拆篇判据和坑表都由实跑校准出来的，
不是纸上设计。瓶颈是本机串行转写（CPU 推理，60 秒一段），不是笔记写作——所以采集放在主代理串行做，
写笔记才是可以并行的部分。

## 成品长什么样

取自仓库自带的虚构测试库（`evals/fixtures/skillfix/`），格式就是真笔记的格式：

```markdown
> [!warning] 待核对
> 视频 10:30 的板书把线电荷密度写成 $\lambda$，幻灯片下一页写的是 $\eta$。两种读法都可能：
> $\lambda$ 是一维线密度，$\eta$ 在本课程后面被用作面密度。考试口径按教材通例用 $\lambda$
> 记线密度，「待核对」保留以便回看时确认。

![检验电荷放入电场后受力示意（视频 04:10）](assets/1-1-01_检验电荷示意.png)

> [!question]- 自测
> 1. 把检验电荷电量放大一倍，测得的 $\vec{E}$ 会不会跟着变？
>    - 不会。$\vec{F}$ 同比增大，比值不变——前提是放大后的电荷仍能近似当作检验电荷。
```

「待核对」不是缺陷，是这个库的**可信度来源**：讲师口述与画面矛盾、课件疑似笔误、画面看不清，
都原样留下并写出两种读法，而不是为了让笔记看起来整洁而猜一个。

## 和别的做法比

| 做法 | 你会得到 | 缺什么 |
|---|---|---|
| 把视频/字幕丢给通用 AI 让它总结 | 一段读着顺的摘要 | 结构、出处、可验证性；同音字术语错得很自信 |
| `yt-dlp` + Whisper 脚本 | 素材（视频 + srt） | 素材不是笔记：没有知识点切分、没有截图挑选、没有索引与校验 |
| AI 笔记类 SaaS | 好看的界面 + 云端转写 | 音频要上传；术语纠错你改不动；产出回不到你自己的 vault，也没法续做下一讲 |
| Obsidian 插件 / 模板 | 展示与书写格式 | 不管采集：下载、转写、截帧、回填、校验全得自己接 |
| **这个 skill** | 一个能自证的库 + 11 个可单独调用的脚本 | 首次跑通要装环境；长课程受本机转写速度限制 |

## 同类开源项目（截至 2026-11）

这个方向很热闹，下面这些都在做「视频 → 笔记」。**先看别人做到哪，再决定要不要用这个**：

| 项目 | ★ | 形态 | 它做到哪 | 差异 |
|---|---|---|---|---|
| [ysyecust/lecture-to-notes](https://github.com/ysyecust/lecture-to-notes) | 300 | Claude Code skill | yt-dlp+cookie、Whisper/X-ASR、抽帧、硬字幕 OCR、smart-crop，**有可执行校验**（`verify_notes.py` / `verify_figures.py` / `check_srt_health.py`）和**子代理编排**（`subagent-workflow.md`、采集交 S0、长视频并行撰写） | 产物是单文件 `{title}.md` + 站点/PDF；仓库里没有 Obsidian / vault / wikilink / frontmatter / 索引层，所以不做库级链接与覆盖度门禁 |
| [mizorewww/course2md](https://github.com/mizorewww/course2md) | 489 | Rust 桌面应用 | YouTube/B 站/本地录屏 → 配图笔记，有 outline 层和 Windows CI | 产品化 GUI 管线，不是给 agent 用的 skill |
| [Rimagination/bili-note](https://github.com/Rimagination/bili-note) | 348 | agent skill | B 站 → 学习型 Markdown，全字幕 | 只有 `check_environment.py`，不校验产物结构 |
| [lucky-Luor/bilibili-douyin-notes](https://github.com/lucky-Luor/bilibili-douyin-notes) | 170 | agent skill | B 站/抖音/YouTube/小红书 → 课堂笔记 | 验证是 `docs/verification/*.md` 文档式记录，非可执行门禁；无整课编排 |
| [KIRVO-REPORTING/video-to-notes](https://github.com/KIRVO-REPORTING/video-to-notes) | 111 | CLI + codex skill | local-first 转写（字幕优先、Whisper 回退） | 重心在转写，不产结构化的库 |
| [haixiong1997/Bilibili-Obsidian-Clipper](https://github.com/haixiong1997/Bilibili-Obsidian-Clipper) | 602 | 浏览器扩展 | B 站字幕 → Markdown / 一键写进 Obsidian | 只做字幕搬运，无笔记结构、无校验 |
| [aidenlx/media-extended](https://github.com/aidenlx/media-extended) | 962 | Obsidian 插件 | 库内嵌视频、时间戳联动做笔记 | 采集与结构全靠你 |
| [JimmySadek/video-fetcher-to-markdown](https://github.com/JimmySadek/video-fetcher-to-markdown) | 519 | 可移植 agent skill | 多平台视频 → Markdown | 单视频粒度，无章/讲/索引四层 |

**所以这个仓库的差异化只在一件事上**：交付物是一个**能自证的 Obsidian 库**——章/讲/正文/索引四层结构 +
`verify_course.py` 对整个库跑死链、歧义链、缺图、未引用素材、结构完整性、frontmatter 一致、表格列数、覆盖度，
`HARD=0` 才算做完；索引由 `fill_indexes.py` 按磁盘真实状态回填，不让 agent 手改或口头汇报。
整门课规模的串行采集 + 并行写作经验写在 `references/subagent-rules.md`，包括四种真实失败。

上面这些结论是按各仓库的文件树和 skill 正文读出来的，不是看名字猜的；但它们在演进，数字也会变，
以你看到的当下为准。

## 什么时候别用它

- 只是想看**一条**短视频要点——直接丢给 AI 更快，这套流程的价值在「一门课」和「能复习」。
- 课程本身是英文且术语密集：SenseVoice 中文强、英文弱，`--asr` 热词表要你自己攒。
- 有官方课件 PDF + 出版教材：那条路直接读 PDF 更准，这个 skill 是为「只有视频」准备的。
- 需要转载/分发别人的课程内容：本仓库只提供方法论与工具，**不含任何课程正文**，UP 主的版权要求由你自己遵守。

## 安装

放到你的 agent skills 目录即可，例如：

```bash
git clone https://github.com/HDLDD/bilibili-obsidian-notes ~/.codex/skills/bilibili-obsidian-notes
# 也可以放进 Qoder / Claude Code / 其它 agent 的 skills 目录：整仓库就是一个 skill
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

### 非 B 站来源（YouTube 等 1700+ 站点）

```bash
python scripts/source_meta.py --url "<视频链接>" --out work/meta.json            # 单个视频
python scripts/course_prep.py meta --url "<播放列表链接>" --work work --playlist   # 列表 = 多讲
```

归一化后的 `meta.json` 与 B 站同构，后面 `manifest / acquire / keys / fill_indexes / verify` 一条命令都不用改，
下载格式与 referer 由 `acquire` 按来源自动选。

多出来的是 `pages[].chapters` —— **上传者自己标的章节**。整个方法都建立在「按讲师划的小节拆篇」上，
B 站大多没标记，只能从总览图推断；有章节时直接用它，比猜准：

```bash
python scripts/course_prep.py keys --work work e01 --from-chapters
# 官方章节 3 个 -> work/e01/chapters.txt
#   saved work/e01/keyframes/t3.png  | 电场强度的定义
#   saved work/e01/keyframes/t21.png | 检验电荷的两个要求
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
- **非 B 站来源怎么验的**：`source_meta.py` 靠 yt-dlp，理论上覆盖 1700+ 站点，但作者这台机器连不上境外站，
  所以 YouTube 路径是**离线验证**的——本地 HTTP 上的真实讲课切片走通了 `meta → manifest → acquire → 转写 → 截帧`
  全链路，章节功能用保存下来的 `yt-dlp -J` 结构加合成 `chapters` 验证。第一次真抓境外站点请你自己跑一遍；
  失败信息会原样来自 yt-dlp，不是我编的兜底。
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
scripts/                      11 个脚本，见 SKILL.md 的「参考文件」一节
evals/evals.json              6 条验收用例（1–4 需联网，5–6 离线）
evals/fixtures/skillfix/      故意做坏的示例库，离线验证校验器与修复器
```

## License

MIT
