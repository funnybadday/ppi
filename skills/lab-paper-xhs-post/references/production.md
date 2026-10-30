# 输入、制作与状态

## 论文版图表裁剪（默认流程，先于图组制作）

论文图表（Figure/Table）从论文PDF裁剪，必须走坐标定位，禁止视觉估计：

```sh
# 表格类：标题起、后续正文止（next-text填图表之后正文的开头几个词）
Horizon/.venv/bin/python skills/lab-paper-xhs-post/scripts/crop_paper_figure.py \
  --pdf "稿件/<案例>/素材/论文全文.pdf" --page 4 \
  --caption "Table 2" --next-text "Friedman test" \
  --output "稿件/<案例>/公众号/配图/论文Table2_基准设置.png"

# 论文首页（封面图）：第1页顶部到指定百分比
... --pdf ... --page 1 --caption "<首页任一稳定词>" --bottom 0.57 --output 论文首页_标题与作者.png
```

脚本自带断言（首行=图表标题、后续正文零混入、区域非空），断言不过非零退出。Figure类图形本体用pdfplumber的lines/curves/rects对象范围定位（正文结束后、caption结束前），同样300dpi渲染裁剪。裁剪产物仍要逐张目检。教训记录：①视觉模型定位两次误判"裁剪完整"，实际Table1主体是正文、Figure1上混正文下截caption；②正文提及图表编号的句子（"Table 6 gives..."）不是标题，脚本已按冒号优先+行首优先匹配规避（2026-10-23批量制作后又修：分词式标题"Table 3."需短语级行首匹配，已进脚本三轮回退链）；③引用句数字必须对照表头列序逐项核对（曾把Neural/Linear成本写反）；④个别PDF的pdfplumber文字提取会系统性乱码数字（如9→E、7→6），关键数字需与pdftotext提取或HTML摘要页交叉验证后才可引用；⑤出版商页面有WAF质询时回退链：NCBI E-utilities（PubMed记录权威源）→playwright驱动本机Chrome→Europe PMC；⑥图注在图下方的期刊（如Science Advances的Fig.）用图形对象范围定位（caption之后、下一正文行之前）。

## 论文版四章节结构（默认）

正文按"创新点／方法／结果／结论"四章节组织为heading+精简段落（每章1—3段，从公众号解读浓缩），每章配图按内容对应（定义/基准/主结果/成本与局限），图文引用式插入：引用句（"……见论文Table N"）引出，图紧随该段之后。article JSON的blocks即按此顺序排heading、paragraph、image。

## 取当前版本

完整读用户指定的公众号正文及同案例来源。若只有DOCX，使用documents技能提取正文并检查图片；已有TXT/JSON可辅助，但先比对与指定版本的正文、标题、图片及修改时间，不以时间戳代替文本比对。图中正文默认不删减、不改写。排版换行、分段或改小标题时不改变事实；用户要求实质改稿才另行处理。

结构提取中去掉公众号文档自带标题、图片占位文字和文末来源区等排版包装，分别映射为封面、image块及sources，不把包装重复排进正文。记录提取范围和任何实际文字调整。原稿若已更新，重新提取全文并更新SHA256；不能只改manifest中的哈希却保留旧正文。哈希仅证明版本未变，不能证明提取正确或稿件已重新核验。

读取项目 `语气参考/小红书认可样例.json`（论文版，指向本项目论文解读案例）、其中实际文案文件及图片。公众号正文few-shot由公众号skill负责；不把小红书标题风格反向套到公众号。

## 封面和短正文

标题用“谁＋做了什么／探索什么”，正文涉及拟议合作、经验分享、产品说明、研究计划时沿用实际性质，不强行包装成突破或重大结论。封面摘要补充最具体的对象、任务、场景或进展，避免重复标题。标题按语义安排换行，检查中英文混排时是否留下孤字，不依赖自动换行碰运气。发布标题可与封面相同；无需为平台刻意另造噱头。

短正文通常先写主事实，再写一个具体应用场景或机制，必要时补一句与本篇材料直接相关的观察。可直接沿用原稿清楚的导语；不必每篇三段，也不强制结尾评价。保留“拟”“计划”“公司表示”等事实强度。用具体内容表达判断，不添加“需要警惕”“尚不能证明”等无必要叠甲，也不把未实现的计划写成结果。标签少而相关，不虚构账号口号、实验室名称、水印或关注引导。

封面图片（论文版默认）＝论文首页（标题+作者页）300dpi截图，从论文PDF第1页按封面图区比例裁剪，标题与作者完整可读；次选同案例真实来源图。新插画按项目配图规范制作；不伪造官网、真人照片或效果证据。图片不加“AI生成”标签。内页图表按四章节图文引用式编排（见上），重复的封面图不再出现；文字仍须完整。

## 归一化与运行

准备本次文章结构JSON和单独编辑的文案JSON。原始文章JSON接受 `paragraph/heading/image`，兼容既有 `p/h`。每个文字块有type、text；图片有type、file、caption；文章有title、blocks、sources。sources每项含label、publisher、date、url中的实际可用信息，保留完整链接。Word/TXT先由执行者全文提取为结构JSON，工具本身不自动解析Word。

文案JSON必填 `cover_title`、`cover_summary`、`post_title`、`post_body`，可含 `source_line`、`hashtags`。不要把旧case JSON当空模板而留下旧事实。至少提供一条有效sources或非空source_line，避免漏掉末页来源。来源简短署名与完整链接分开：末页显示短名称、发布日期，完整URL保存到来源链接TXT。避免source_line与sources逐条重复同一来源；只有署名而缺完整链接时先核对同案例来源，不虚构URL。

从项目根运行，变量替换为本次实际路径；输出manifest与渲染目录必须是尚不存在的新路径：

```sh
python3 skills/lab-paper-xhs-post/scripts/prepare_input.py \
  --article-json "$ARTICLE_JSON" --copy-json "$COPY_JSON" \
  --source-file "$CURRENT_WECHAT_FILE" --cover-image "$COVER_IMAGE" \
  --asset-dir "$CASE_DIR/公众号/配图" --asset-dir "$CASE_DIR/素材" \
  --output "$NEW_MANIFEST"
node skills/lab-paper-xhs-post/scripts/render_pages.cjs \
  --input "$NEW_MANIFEST" --output-dir "$NEW_RENDER_DIR"
```

使用项目已配置或Codex提供的Node/Playwright/本机Chrome，可用依赖发现工具读取当前路径；renderer接受 `--node-module-dir` 和 `--browser-executable` 指定已有依赖，不联网安装。浏览器遇到沙箱权限限制时使用正常工具审批，不将启动失败报告为排版通过。

prepare_input输出约定：

```json
{
  "schema_version": 1,
  "source": {"path": "本次公众号实际文件绝对路径", "sha256": "实际64位哈希"},
  "article": {
    "title": "本篇标题",
    "blocks": [{"type": "paragraph", "text": "本篇完整正文"}],
    "sources": [{"label": "实际来源", "url": "https://example.org/source"}]
  },
  "copy": {"cover_title": "本篇标题", "cover_summary": "一句具体摘要", "post_title": "发布标题", "post_body": "较短正文"},
  "cover": {"mode": "image", "image": "本篇封面图绝对路径", "caption": "必要图片出处"}
}
```

媒体从文章JSON所在目录或显式asset-dir解析，相对路径需唯一；缺图、歧义或未知块类型要修正，不静默跳过。封面默认必须有图；纯文字封面只有用户明确要求时才传 `--cover-mode text`。theme可调整受控字号、间距和颜色，默认认可值已在renderer中；画幅保持3:4，不把某篇的标题长度、图片高度或页数设成规则。

## 检查与整理

renderer生成 `图片/`、`分页排版.html`、`逐页内容.json`、`排版检查.json`、`来源链接.txt`，失败保留failure-report。检查实际PNG为1080×1440；逐字Range重组与输入正文相同，正文顺序正确，无重复或遗漏；段落按完整行跨页，小标题与后文相连，图片不被切开，来源只在最后可见页。无需每篇都出现跨页段落；短稿无小标题也有效。长文页数由排版决定，不通过删正文凑固定5页。

逐张打开实际PNG。看封面图片主体、标题与摘要是否拥挤或过空，看所有正文的字形、密度、图注、高亮、断行和来源是否正常。总览便于比较密度，不能代替逐张看。发现标题孤悬或封面拥挤时调整受控排版参数再渲染新目录，不删诊断、缩字硬塞或默默交付失败图。发布时平台可用图数如有限制，按用户实际操作再处理，不预设未经验证的上限。

整理到同案例 `小红书/`：`图片/`、`图片总览.jpg`、`发布标题与正文.txt`、`来源链接.txt`、图文ZIP；制作记录保存输入manifest、实际文案JSON、排版HTML、逐页内容及检查证据。ZIP只含本版PNG、文案、来源，不混旧版或内部记录。图组总览是检查用拼图，不是上传单页。

首次制作可将新的渲染目录检查后整理为小红书目录；修订先在新的制作目录生成并核查，再将受影响旧版归入该案例的历史版本，更新本版图片、文案、总览和ZIP。只改文案不需无意义重渲染未受影响的正文。实际source路径/哈希、渲染命令、检查结果、逐张查看路径、继承材料和本轮补查都记到 `制作记录/制作与检查记录.json`，不复制历史“已检查”布尔值。

## 事件、认可与恢复

同一论文沿用原event_key、案例目录和来源，不新增推荐。参照总控 `references/cross-run.md`，用台账脚本 `record` 提交单独状态记录：events为空，history_review中event_key、change_type:repeat、status:drafted、article_directory，以及platform_outputs.xiaohongshu对象。新增图文或修订为review_status:awaiting_user_review、published:false（未发布的新稿）；用户明确认可更新review_status:approved，实际发布依据用户明确反馈另记published:true及时间。已发布旧稿修订要保留真实发布历史，不用本轮待审状态抹去发布记录。

platform_outputs只更新本次平台；不覆盖公众号认可、发布或其他平台字段。用户认可本次稿件也不等于其他案例通过。新建缺台账的已有公众号时先核对来源并按总控的手动制作记录规则建立事件，不能编造Horizon推荐。工作流状态增加latest_xiaohongshu及对应记录，不把latest_article强行换成旧的公众号案例。

公众号后来修订不自动同步所有小红书；用户要求同步时比对最新正文与记录哈希，重做受影响部分并重新待审。只有图片生成、排版、台账或打包失败时，复用其余成功阶段；无新事实不重新采集、回源和改写公众号。定时仍只在用户明确要求时由总控配置，默认交付日报与候选。
