# 整课批处理流水线（一门课 14～95 讲）

单讲流程在 SKILL.md 里。这一篇讲**怎么把整门课一次做完**——这是三门课（STM32 45 集、高频 95 讲、电磁场 14 讲）反复验证过的分工。

## 为什么必须改流程

一讲一讲手动做，14 讲还行，95 讲做不完。放多个子代理并行写笔记又会撞三件事：

1. 采集（下载 + 本机 SenseVoice 转写）很慢，子代理把它丢后台就结束回合，**素材永远等不到**；
2. 同一章的两讲并行写 `00-本章索引.md`，**后写的把先写的覆盖掉**；
3. 子代理会越界写别人的章，还会报告与磁盘不符（说改了其实没改，行号是编的）。

所以：**主代理串行采集，子代理只读素材写笔记，索引一律脚本回填，一切以磁盘为准。**

## 阶段

### 1 取元数据，先出全课结构

```bash
python scripts/course_prep.py meta --url "<链接>" --work "<work>"
```

打印每个分 P 的标题和时长。**先把全部章节列出来给用户看**，再开始写笔记——用户通常要先确认结构。

### 2 写章节映射，生成 manifest 与库骨架

章节归属只有看标题才知道（`01 第一章 矢量分析（1）`→第 1 章），所以手写一个 map：

```json
[
  {"chapter": "1", "topic": "矢量分析", "pages": [1, 2],
   "lesson_titles": {"1": "矢量分析（1）", "2": "矢量分析（2）"}},
  {"chapter": "0", "topic": "全书思维导图", "pages": [14],
   "lesson_titles": {"14": "全书思维导图"}}
]
```

`chapter: "0"` 是附录（思维导图、总复习、勘误），目录名会变成 `附录-…`。视频原标题有错字（如「平面电磁场」应为「平面电磁波」）时，在 `lesson_titles` 里写正确叫法，原标题仍会保留在索引表和 `00-本讲索引` 的「本讲信息」里。

```bash
python scripts/course_prep.py manifest --work "<work>" --map <work>/chapters.json \
        --vault "<vault>/<course_dir>"
```

生成 `manifest.json`（每讲：`slug/part/folder/lesson_path/work/url/duration`）、章/讲文件夹骨架、`assets/`、各章索引桩和课程索引桩。骨架先建好，子代理就不用猜路径，也不会互相发明结构。

### 3 串行采集（只有主代理做）

```bash
SENSE_THREADS=2 python scripts/course_prep.py acquire --work "<work>" e07 7
```

幂等：`video.mp4` 在就跳过下载，`audio_16k.wav` 在就跳过抽音轨，`transcript.txt` 在就跳过转写，总览拼图在就跳过。**中断后重跑同一命令即可续做。**

一次跑多讲时写个小驱动串行调用（不要并行，见 subagent-rules.md）：

```python
for ep, page in [("e08", 8), ("e09", 9)]:
    if not (work / ep / "transcribe" / "transcript.txt").exists():
        subprocess.run([sys.executable, "course_prep.py", "acquire", "--work", str(work), ep, str(page)])
```

看进度：

```bash
python scripts/course_prep.py status --work "<work>"
```

关键事实：`transcript.txt` **只在整段转写结束时一次性落盘**，中途没有半成品可读。所以判断"讲完了没有"就查这个文件存不存在，别看日志尾巴。

### 4 派子代理写笔记

按 manifest 分组派单，一单 4～6 讲，任务书必须写清：**素材已就绪，不要运行 acquire**；只准写自己那几个讲文件夹；**不要碰章索引和课程索引**。详见 subagent-rules.md 的模板。

### 5 回填索引

```bash
python scripts/fill_indexes.py --vault "<vault>/<course_dir>" --manifest "<work>/manifest.json" --date $(date +%F)
```

按磁盘实际存在的 `00-本讲索引.md` 回填章索引「笔记」列、整理状态、课程索引状态列与总进度。可反复跑。

### 6 修 Markdown 缺陷 + 三重校验

```bash
python scripts/fix_course_md.py --vault "<vault>" --manifest "<work>/manifest.json"   # 相对链接、表格竖线
python scripts/verify_course.py --vault "<vault>" --manifest "<work>/manifest.json" \
        --asr "解条(?!件),悬度,酶质" --strict
```

`verify_course.py` 一次报完：链接（死链/歧义/相对写法）、图片缺引、每讲结构完整性、frontmatter 与 H1/分 P/时长是否一致、表格列数、正文是否被本讲索引收录、章/课程索引覆盖、未引用素材、占位文字、ASR 残留、待核对计数。`HARD=0` 且退出码 0 才算完成。

### 7 技术复核（内容与转写/幻灯片对得上）

派**只读**复核代理，按章分工，让它逐条回查 `transcript.txt` 与 `overview_*.jpg`。要点：

- 复核报告必须**引用现文原文**，不接受只给行号——子代理报的行号经常是编的或过期的；
- 收到报告后先 `grep` 验证它引的句子真的在文件里，再动手改；
- 优先级：公式系数/正负号/单位 → 边界条件与适用条件归属 → 「板书/幻灯片原话」是否真有依据 → 自拟题能否复算；
- 改完重跑 `verify_course.py`。

三门课里复核真正常抓到的：板书字母误读、自拟数值题算错、把子问题的边界条件写成原问题的、图注描述与图内容不符、把「口述」写成「幻灯片原文」、术语用了教材通名却标成课上原话。

### 8 交付与媒体处置

- 章索引三节（本章主线/公式速查/易错点）与课程索引「复习路线」补完；
- 工作目录（视频+音频）通常 1～3 GB：先备份、再哈希、后删，见 SKILL.md Step 8；
- vault 只留笔记、截图、字幕原文。
