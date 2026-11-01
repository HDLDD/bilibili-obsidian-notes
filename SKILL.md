---
name: bilibili-obsidian-notes
description: "把课程/讲座视频整理成 Obsidian 笔记库（B 站为主，也吃任何 yt-dlp 能解析的源，如 YouTube）：短讲一讲一篇，长讲按讲师自己划的小节拆成多篇知识点正文 + 本讲索引 + 扩展笔记，按章归档并回填章索引与课程索引，可选多讲并行批处理；含本地 SenseVoice 转写、1080p 关键帧提取（上传者标了章节时按章节自动取帧）、三重校验（链接/结构/内容复核）与删除前备份。只要用户给出 b23.tv/B站/YouTube 等视频链接并要求「整理成笔记」「拆解这门课」「把这门课都做了」「继续下一讲/下一章」「提取字幕精华」「做某一讲」，或要求把视频课程放进指定的 Obsidian vault，就用本 Skill——整门课的需求不要只按单讲流程做。转写默认走本地 sherpa-onnx SenseVoice，无需联网、不上传音频。"
compatibility: "Python 3.11 + sherpa_onnx + numpy; yt-dlp, ffmpeg/ffprobe; an Obsidian vault (path set by you). Windows-first: the pitfalls table and encoding notes are from Windows + Git Bash; macOS/Linux work for download/frames/verify, transcription is portable."
---

# Bilibili → Obsidian 课程笔记

把 B 站课程整理成可复习、可检索、可继续扩展的 Obsidian 笔记库。核心不是"转写全文"，而是**按讲师自己的结构**把视频落成带出处、带截图、带自测的知识点笔记，并且**能被脚本验证**。

两种模式，先判断走哪条：

| 需求 | 走哪条 | 先读 |
|---|---|---|
| 一讲/一集，做完交付 | 单讲流程（下面 Step 1–8） | `references/note-structure.md` |
| 整门课（十几讲到几十讲） | 先出全课结构 → 串行采集 → 派子代理写 → 脚本回填校验 | `references/batch-pipeline.md` + `references/subagent-rules.md` |

整门课**必须**换流程：单讲流程逐讲做几十遍做不完，而直接放多个代理并行会撞上四种失败（代理后台等待后结束回合、同章并行覆盖索引、越界写别人的章、报告与磁盘不符）。这些坑与对策都在 `subagent-rules.md`。

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

短讲（≤10 分钟）可以一讲一篇正文；长讲按讲师划的小节拆 2–9 篇。**拆几篇的判据、三种结构的选择、完整模板见 `references/note-structure.md`**——不要凭感觉重排讲师的结构。

单讲的 `01-视频讲解.md` + `02-扩展笔记.md` 双笔记模式仍然可用（模板：`references/01-video-template.md`、`references/02-extension-template.md`），适合边看边补深度的课。

> vault 只放笔记、关键截图、字幕原文。整段视频/音频留在工作目录，按 Step 8 备份后再删。

课程与路径默认值在 `references/course-config.json`（**开箱是空的，第一次用先填 `vault` 和 `sensevoice_model_dir`**）；用户另给课程或 vault 时以用户为准。**每门新课单独建目录**，不要混进已有课程库。

## 输入

- 一个 B 站或 `b23.tv` 链接（可以是分 P 链接）；**其它平台**（YouTube 等 yt-dlp 能解析的站点）走 `source_meta.py`
- 要做的讲次/章节；链接已指向某一 P 时可从 metadata 取
- 目标 vault（必填；可从 `references/course-config.json` 读默认值）

用户只说"继续下一讲"时，先读 `00-课程索引.md` 找到下一讲的分 P 与标题再动手。

## 单讲工作流

### Step 1 · 取元数据，确认讲次

```bash
# B 站（快速路径，直接走 web 接口，拿全部分 P）
python scripts/bili_meta.py --url "<链接>" --out "<work>/meta.json"
python scripts/course_prep.py meta --url "<链接>" --work "<work>"          # 整门课
# 其它站点（YouTube 等 1700+ 源）
python scripts/source_meta.py --url "<链接>" --out "<work>/meta.json"
python scripts/course_prep.py meta --url "<链接>" --work "<work>" --playlist   # 播放列表=多讲
```

两条路都落成同一个 `meta.json`（`bvid` / `title` / `owner` / `series_url` / `pages[]`），后面所有步骤不分来源。
确认 `part` 标题、`duration`、`url`。**分 P 序号不一定等于讲次**（一章可能跨多个 P，一个 P 也可能含多讲）：
文件名用讲号 `章-序`，链接用分 P。

> **有 `chapters` 就用它**：非 B 站来源常常带上传者自己标记的章节，`meta.json` 里会存成
> `pages[].chapters`。这正是"按讲师划的小节"的权威答案——比从总览图推断准，Step 4/5 直接用它，不要再自己重排。

### Step 2 · 下载 1080P 视频和音轨

```bash
# B 站（30080=HEVC 1080P，30280=音频；course_prep 会自动用这套）
yt-dlp -f "30080+30280/bv*[height<=1080]+ba" --merge-output-format mp4 \
  --referer "https://www.bilibili.com/" -o "<work>/video.mp4" "<selected.url>"
# 其它站点：先要 1080P mp4，逐级回退（course_prep acquire 按来源自动选，不用手敲）
yt-dlp -f "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b" \
  --merge-output-format mp4 -o "<work>/video.mp4" "<selected.url>"
ffmpeg -y -i "<work>/video.mp4" -vn -ac 1 -ar 16000 -c:a pcm_s16le "<work>/audio_16k.wav"
```

1080P 的 AVC 有时要登录，HEVC/AV1 免登录就够用，ffmpeg 能解码。别为画质卡住流程，必要时降级 720P。

### Step 3 · 字幕优先，没有字幕再转写

```bash
yt-dlp --write-subs --write-auto-subs --sub-langs "zh,zh-Hans,zh-Hant,en" \
  --skip-download -o "<work>/sub" "<selected.url>"
```

拿到 VTT/SRT 就解析成带时间戳文本，跳到 Step 4。没有字幕（这类课常见）时用本地 SenseVoice（音频不出机器）：

```bash
python scripts/transcribe_sensevoice.py --input "<work>/audio_16k.wav" --out-dir "<work>" \
  --chunk-seconds 60 --model-dir "<models>"     # 或 export SENSEVOICE_MODEL_DIR
# 或整课模式：SENSE_THREADS=2 python scripts/course_prep.py acquire --work "<work>" e07 7
```

输出 `transcript.txt`（`[mm:ss] 文本`）与 `transcript.json`（带 start/end）。

> 转写全程本地推理，不调用任何云端 API、不需要 Key。任何时候都不要把密钥写进笔记、manifest 或 vault。

`transcript.txt` **只在整段转写完成后一次性落盘**，中途没有半成品——判断进度就查这个文件是否存在。长视频按 60 秒分段；某段被截断就降到 30。

**转写只是草稿。** SenseVoice 会把术语听成同音字（麦克斯韦←麦克斯/麦克威、坡印廷←坡形亭、时谐场←实写场、媒质←酶质、趋肤←曲幅、唯一性←维星…）。写笔记前先按幻灯片校正，并为该课整理一张纠错表放进工作目录的 GUIDE 里。

### Step 4 · 缩略总览 + 按需截帧

```bash
bash scripts/frames.sh contact-sheet "<work>/video.mp4" "<work>/frames"     # 5 秒/格
# 长讲用 15 秒/格更省事：SHEET_INTERVAL=15 python scripts/course_prep.py acquire --work "<work>" e07 7
bash scripts/frames.sh snapshots "<work>/video.mp4" "<work>/keyframes" 35 170 300
python scripts/course_prep.py keys --work "<work>" e07 "35,170,300"
python scripts/course_prep.py keys --work "<work>" e07 --from-chapters       # 有官方章节时：一节一帧
```

每张总览 4×3=12 格；5 秒档第 N 格 ≈ `(N-1)×5` 秒，15 秒档 ≈ `(N-1)×15` 秒。先看总览定分节，再挑关键时间点截 1080p 原帧。

`--from-chapters` 会按每个章节起点 +3 秒（`--chapter-offset` 可调，避开翻页动画）各截一帧，并把
`[mm:ss] 小节名` 写进 `<work>/EP/chapters.txt`——这张表就是 Step 5 的拆篇依据，比看总览猜准。
没有章节时它直接告诉你回退到总览图。

本机**不要给 ffmpeg 加 `drawtext`**（fontconfig 不全，会段错误）；时间靠格子序号换算。

选图原则：优先定义页、对比表、框图、公式推导、波形/场图、例题板书；每篇 1–3 张、每讲 3–6 张；每张在笔记里写"视频 mm:ss：这张图说明了什么"，并核对**该时刻画面真的是这个内容**。

### Step 5 · 写正文 + 本讲索引 + 扩展笔记

按 `references/note-structure.md` 的模板落笔。要点：

- **忠于视频**：分节顺序跟讲师走；视频没讲的不塞进正文，要补就放进 `99-扩展笔记.md` 并标"补充/自拟"。
- **归属四分法**：幻灯片原文 / 板书 / 口述 / 笔记补充，不要互相冒充（把口述写成"幻灯片给出"是最常见的返工点）。
- **待核对**：口述与画面矛盾、画面看不清、课件疑似笔误 → 标「待核对」，写清两种读法和判断依据。这是可信度来源，不要为了整洁删掉。
- **公式与单位**：符号含义、单位、适用条件写全；矢量方向（法向/切向、右手螺旋、旋向判据）最容易错。
- **表格与链接的竖线**：表格内绝对值写 `\lvert x \rvert`，wikilink 写 `[[a\|b]]`，绝不能有裸 `|`；wikilink 不支持 `[[../x]]` 这种相对写法。详见 `references/obsidian-pitfalls.md`。
- 图片用相对路径 `assets/N-M-01_说明.png`；跨讲导航用库内全路径（全库都叫 `00-本讲索引.md`，只写文件名必然歧义）。
- Callout：`> [!info]`、`> [!abstract]`、`> [!tip]`、`> [!warning]`、`> [!question]-`（可折叠自测）。
- 流程/关系用 Mermaid（`flowchart LR`），Obsidian 原生渲染。

`99-扩展笔记.md` 固定四段：考点清单（★★★/★★/★）、公式速查表、易错点（错在哪→为什么错→怎么判断）、典型题（优先视频原题；自拟必须标注）。

### Step 6 · 更新索引

单讲模式手工改三处：课程目录该讲的状态列、已完成表、进度数字。整课模式**不要手改**，跑脚本：

```bash
python scripts/fill_indexes.py --vault "<vault>/<course_dir>" --manifest "<work>/manifest.json" --date $(date +%F)
```

它按磁盘上真实存在的 `00-本讲索引.md` 回填章索引「笔记」列、整理状态、课程索引状态与进度。可反复跑，幂等。

### Step 7 · 校验

```bash
python scripts/fix_course_md.py --vault "<vault>/<course_dir>" --manifest "<work>/manifest.json"
python scripts/verify_course.py --vault "<vault>/<course_dir>" --manifest "<work>/manifest.json" \
        --asr "解条(?!件),悬度,酶质" --strict
```

`fix_course_md.py` 修两类高频缺陷：`[[../x]]` 相对链接 → 库内全路径；表格行里的 `\left|`/`\right|`/未转义 `[[a|b]]` → `\lvert`/`\rvert`/`[[a\|b]]`。两者幂等，已修过的不会被二次处理。

`verify_course.py` 一次报完：死链/歧义链/相对链、缺图与未引用素材、每讲结构完整性（00/99/正文篇数）、frontmatter 与 H1·分 P·时长是否一致、表格列数、正文有没有被本讲索引收录、章/课程索引覆盖、占位文字、ASR 残留、「待核对」计数。要求 `HARD=0`、退出码 0。

单讲也可以用轻量的 `python scripts/check_obsidian_links.py --vault "<vault>/<course_dir>"`。

最后在 Obsidian 里看一眼：Mermaid 能渲染、表格不溢出、图片不丢、跳转有效。

### Step 8 · 内容复核（整课模式必做；单讲可选）

派**只读**代理按章回查：逐条对 `transcript.txt` 与 `overview_*.jpg`，重点看公式系数与正负号、单位与适用条件、边界条件归属、自拟题能否复算、图注与画面是否相符。

- 复核报告必须**引用现文原文**；只给行号的一律先 `grep` 验证（代理报的行号常过期或是编的）。
- 改完重跑 Step 7。
- 三门课复核最常抓到的：板书字母误读、自拟数值题算错、把子问题的边界条件写成原问题的、图与图注不符、口述冒充幻灯片原文、教材通名冒充课上原话。

## 整门课批处理

用户说"把这门课拆解了""整门课都要"时，按 `references/batch-pipeline.md` 的 8 步走：

1. `course_prep.py meta` 取全课元数据，**先把全部章节列出来**（用户通常要先确认结构）；
2. 写章节映射 json → `course_prep.py manifest` 生成 manifest + 库骨架 + 索引桩；同时按
   `references/course-guide-template.md` 给这门课写一份 `NOTE_GUIDE.md`（口径手册 + ASR 纠错表），
   任务书第一句就让代理读它；
3. **主代理串行 `acquire`**（幂等，可续跑），子代理不参与采集；
4. 按 4–6 讲/单派子代理写笔记，任务书第一句写"素材已就绪，不要运行 acquire"；
5. `fill_indexes.py` 回填索引；
6. `fix_course_md.py` + `verify_course.py --strict`；
7. 只读复核代理按章验内容，逐条验证后再改；
8. 补章索引三节与课程索引复习路线，再处置媒体。

批次大小、资源限制（`SENSE_THREADS=2`、`OPENBLAS_NUM_THREADS=1`、各代理独立 work 目录）、任务书模板、收尾清单都在 `references/subagent-rules.md`。派单前必读——四种失败的成因和对策都在里面。

## 质量线

- **忠于视频**：术语用幻灯片校正；不编造讲师没说过的话、不做视频没讲的题。
- **出处可查**：每张图标"视频 mm:ss"；本讲索引给视频进度区间；frontmatter 带 `source` 分 P 链接。
- **诚实标记**：不一致、看不清、疑似课件笔误 → 「待核对」+ 两种读法 + 考试口径。
- **结构一致**：讲号、目录名、索引行、frontmatter 互相咬合，下次续做不用猜。
- **可验证**：`verify_course.py` 到 `HARD=0`；未引用素材 0；表格无裸竖线。
- **媒体不落 vault**：vault 只放笔记/截图/字幕；原片备份后删除。
- **先备份后删除**：备份成功 + vault 哈希前后一致，才允许删。

## 故障排查

| 现象 | 处理 |
|---|---|
| 1080P 下载失败 | 换 HEVC/AV1；`--cookies-from-browser chrome`；或降 720P |
| 控制台中文乱码 / `UnicodeEncodeError` | 终端是 GBK，不是数据坏了：`PYTHONIOENCODING=utf-8` 并重定向到文件再读 |
| 脚本里的 `\right` 变成回车、`\lvert` 变成 `<CR>ert` | heredoc 吞了反斜杠。**含 LaTeX 反斜杠的脚本用 Write 工具落盘再执行** |
| 表格某列内容跑到下一列 | 表格内有裸 `|`（`\left\|`、`\|AF\|`、未转义 wikilink）→ 跑 `fix_course_md.py --pipes` |
| 链接在 Obsidian 里点不开，但路径看着没错 | 用了 `[[../x]]`（不支持）或只写文件名导致歧义 → 跑 `fix_course_md.py --links` |
| 多行字符串 `replace` 静默失配 | 文件是 CRLF：读时 `newline=""`，逐行处理 |
| `robocopy` 返回 16 什么都没拷 | 换 Python `shutil.copytree(..., dirs_exist_ok=True)` |
| ffmpeg fontconfig 报错/段错误 | 去掉 `drawtext`，别往图上烧时间字 |
| SenseVoice 某段被截断 | `--chunk-seconds 30`；确认 16k 单声道 |
| 多个转写进程互相拖慢 / `OpenBLAS malloc failed` | `SENSE_THREADS=1~2` + `OPENBLAS_NUM_THREADS=1`；采集串行 |
| 同一 work 目录并发 acquire 报 `WinError 32` | 一个讲一个目录；主代理串行采集 |
| 子代理说"等转写完成"就结束、什么都没写 | 代理停止调用工具即结束，后台任务不会唤醒它——采集必须主代理先做完 |
| 子代理报告与磁盘不符（行号对不上、声称修过没修） | 一切以磁盘为准：`ls`/`grep`/`verify_course.py` 核验，别信报告 |
| 章索引被并行代理互相覆盖 | 子代理不许改索引，统一 `fill_indexes.py` |
| 校验器报 ASR 残留但内容是对的 | 中文无词边界，两字热词会命中正常词（`解条`命中「定解条件」）；`--asr` 收正则，用 `解条(?!件)` |
| 标题跳转失效 | 标题与 `[[#…]]` 逐字一致；标题里别放反引号/加粗/全半角混排 |

## 参考文件

流程与规范：

- `references/note-structure.md`：三种结构怎么选、时长→拆篇数表、正文/本讲索引/扩展笔记/章索引/课程索引模板
- `references/batch-pipeline.md`：整门课 8 步（元数据→章节映射→串行采集→派单→回填→校验→复核→交付）
- `references/subagent-rules.md`：子代理四种失败、批次大小、资源限制、任务书模板、收尾清单
- `references/obsidian-pitfalls.md`：表格竖线、相对 wikilink、中文标点、CRLF、GBK 控制台、heredoc 吞反斜杠、归属四分法
- `references/course-config.json`：默认 vault / 课程 / 模型目录（**出厂为空，按需填写**）
- `references/course-guide-template.md`：单门课的口径手册 + ASR 纠错表模板
- `references/01-video-template.md`、`references/02-extension-template.md`：单讲双笔记模板

脚本：

- `scripts/course_prep.py`：整课驱动 `meta` / `manifest` / `acquire` / `keys` / `status`（幂等，可续跑）
- `scripts/verify_course.py`：一次跑完链接、图片、结构、frontmatter、表格、覆盖、卫生度检查（`--strict` 决定退出码）
- `scripts/fix_course_md.py`：修相对链接与表格竖线（幂等，`--dry-run` 可先看）
- `scripts/fill_indexes.py`：按磁盘状态回填章索引与课程索引
- `scripts/renumber_articles.py`：把误用 `00-` 开头的正文重排为 `01..NN`，同步改 frontmatter、wikilink、别名与索引表编号（幂等，`--dry-run` 可先看）
- `scripts/bili_meta.py`：解析 b23/B站链接，列分 P
- `scripts/source_meta.py`：其它站点（YouTube 等）归一成同一个 `meta.json`，带 `chapters`；`--from-json` 可离线调试
- `scripts/transcribe_sensevoice.py`：本地 SenseVoice 分段转写（sherpa-onnx，无需联网）
- `scripts/frames.sh`：总览拼图与单帧/多帧截图
- `scripts/check_obsidian_links.py`：轻量链接与锚点校验（单讲够用）
- `scripts/backup_workdir.py`：删除前备份、校验 zip、生成 SHA256 清单
