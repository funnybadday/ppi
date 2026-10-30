# 跨日对比与事件台账

重复出现的采集记录仍属于该轮日报。是否再次推荐由编辑复核决定；脚本只提供链接和历史事实上下文，不代替语义判断。

## 采集与复核

从项目根目录运行（RUN_ID换成实际run目录名）：

```sh
python3 skills/lab-paper-workflow/scripts/radar_history.py window --project-root "$PWD"
python3 skills/lab-paper-workflow/scripts/radar_history.py compare --project-root "$PWD" --run-dir "$PWD/Horizon/data/mcp-runs/RUN_ID" --output "$PWD/Horizon/data/mcp-runs/RUN_ID/history-context.json"
```

window读取真实成功检查点，首次96小时；连续运行至少48小时；距上次成功采集的时间加24小时；周一至少96小时。中断超过一周时提示订阅保留范围的缺口，不假定扩大hours就能补齐所有旧论文。来源汇总成功也不能证明每条订阅成功。

检查点保守采用非空、评分完整且抓取汇总成功的运行。曾有RSS逐源连接失败但汇总仍报success的实际记录，所以空结果不能单独推进检查点；需先检查逐源日志。已采集到数据的汇总成功仍可能有局部来源缺口，另行记录。

compare保留本轮全部记录，与时间早于本轮的raw记录对比，标出同URL同内容、同URL内容变化、新URL，并附台账事件。URL只移除已知追踪参数和片段，不抹去业务查询参数或路径大小写。RSS摘要变化是回源提示，不等于实质进展；新URL也可能只是转载。当前没有跨run评分缓存，重复链接仍可能再次消耗DeepSeek评分。

RSS通常按发布日期入窗：原网页更新但日期未变，未必再次出现。对仍待核或用户明确关注的历史事件，可按实际需要定向查看其原始来源；扩大96小时窗口不能代替这种核查。

逐条审阅全量标题和可用摘要，结合history-context和台账，不只看模型高分。对可能推荐而内容不足的条目轻量回源，依据主体、具体行动/项目、对象和原始日期合并事件。同公司不同合作或不同试验不要合并；不同媒体转述同一公告应合并。

## 判断与交付

- new：此前未进入事件台账的候选。旧论文首次发现可以推荐解读专题，但明确原始日期及“首次发现”，不写成今天发布。
- update：已有事件出现具体新事实，如结果、适用范围、监管决定或部署进展。沿用event_key，写明相较历史新增了什么。
- repeat：无实质新增的再次出现，记录新来源或发现时间，不再作为新候选推送。
- pending：缺少必要材料或暂不能判断，保留待核原因，不包装成可直接写作的选题。

候选JSON使用events保存本轮正式推荐的new/update；history_review保存repeat/pending以及未作为新推荐的update（例如用户要求修订旧稿，回源补充了事实）。后一类更新也必须提供已有event_key和change_note，但不增加推荐历史。TXT主要展示events及必要覆盖说明，不把所有重复报道重新推给用户。无合适候选时events为空，仍交付Horizon日报与简短零候选结论。候选阶段不生成平台标题、文章提纲或图片方案。

不强制每天3—5条，也不固定国内外比例。内置分数保留原值；按需回源后推荐低分条目时解释判断依据。

## 记录格式

同一份候选JSON即可作为record输入；其他已有交付字段可以保留。示例仅说明字段，实际来源与时间必须使用本轮材料：

```json
{
  "source_run": "实际run_id；手动制作可为null",
  "observed_at": "带时区的本轮观察时间",
  "events": [
    {
      "event_id": "C01",
      "topic": "本次实际事件",
      "source_date": "原始发布日期，未确认则null",
      "source": {"url": "实际原始来源URL", "publisher": "实际发布方"},
      "additional_sources": [],
      "verified_facts": "本轮实际核实内容与归因",
      "change_type": "new",
      "status": "recommended",
      "discovery_items": [{"item_id": "实际采集ID", "discovery_url": "实际发现链接"}]
    }
  ],
  "history_review": []
}
```

event_id只在该文件内有效，不能拿另一轮的C01直接匹配。event_key跨日稳定：已有事件从台账继承；新事件未提供时工具用规范化首个来源URL和原始日期生成。事后发现日期不准确也保留既有key，在更新中修正日期。下一次制作时由候选文件/ID、来源及台账定位该key；不要改历史候选文件只为补key后又把整份当新记录提交。

update必须提供已有event_key和具体change_note；repeat也必须提供已有key。pending可以是新线索；缺来源时需明确key。重要的发现链接放discovery_items，原始公告及补充来源放source/additional_sources，便于后续识别不同入口。

```sh
python3 skills/lab-paper-workflow/scripts/radar_history.py record --project-root "$PWD" --review-file "本轮候选JSON的绝对路径"
```

工具更新 `选题池/事件台账.json`。处理记录保留候选文件、run、观察时间和内容哈希，重复提交相同内容不会新增推荐。脚本校验完整后原子替换并加本地锁；台账损坏时停止并报错，不能静默清空重建。不要修改历史JSON后重放整个new清单；新发现的更正用单独更新记录。

空候选完成记录必须同时含实际source_run、events:[]和history_review:[]，以区分已复核无推荐与尚未复核。observed_at省略时使用实际记录时间；回填历史采用有证据的历史观察时间，不把导入日期冒充首次发现日期。

## 稿件与后续状态

status取recommended、drafted、published、deferred、dismissed、pending。已采集、已推荐、已写稿、用户认可、已发布是不同状态；发布仅依据用户明确反馈。台账保留推荐和处理历史，不因换日清空。

已在台账的事件完成写稿后，在案例“制作记录”保存一份状态记录，source_run可为null，events为空，history_review中填event_key、change_type:repeat、status:drafted、article_directory及实际反馈。这样记录稿件关联不会新增一次论文推荐，也不会用重复记录的旧事实覆盖台账事实。文章有事实更新时在history_review用update记录新增事实及change_note；只有确实再次向用户推荐的更新才放入events。用户认可可写入处理记录和工作流状态，不能据此记为published。

手动网页入口先查台账和已有稿件。同事件沿用key；真正新事件通过history_review的pending建立记录，同时显式status:drafted并关联article_directory，保留实际来源、日期和核验事实。这表示来自手动制作，推荐历史为空，不虚构Horizon推荐。以后采集到相同事件，即可识别已写稿。

台账写入失败时保留日报、候选和Word，补记失败阶段；不重新采集或重写文章。每次完成后更新工作流状态.json中的最新交付路径，但历史运行、候选、稿件验收证据仍分别保留。

## 同一事件的两个平台

小红书从完成的公众号派生，沿用event_key与article_directory；换平台不是新论文或一次实质更新。完成或修订后使用单独的history_review repeat记录，不重放历史候选清单。事件status:drafted只描述已有稿件，平台认可与发布分别存入platform_outputs。工具按平台和字段合并；只传本次变化的平台，不用旧快照覆盖另一个平台。

```json
{
  "source_run": null,
  "events": [],
  "history_review": [{
    "event_key": "从台账继承的实际key",
    "change_type": "repeat",
    "status": "drafted",
    "article_directory": "稿件/本次论文名",
    "platform_outputs": {
      "xiaohongshu": {
        "directory": "稿件/本次论文名/小红书",
        "review_status": "awaiting_user_review",
        "published": false,
        "source_file": "本次公众号实际文件路径",
        "source_sha256": "本次实际哈希"
      }
    }
  }]
}
```

platform_outputs的键为wechat或xiaohongshu。review_status只取awaiting_user_review、approved；published为布尔值。用户明确认可某平台时只更新该平台的review_status:approved和实际反馈；实际发布后才记published:true、发布时间和链接。生成与检查通过不表示认可，认可不表示发布。已发布内容的后续修订保留原发布事实与记录，不把待审新版本写成从未发布。

用户只改小红书不改公众号；公众号后续修订也不自动改小红书，用户要求同步时重新检查对应原稿与派生记录。更新工作流状态的latest_xiaohongshu不覆盖无关的latest_article；历史每篇平台状态以同事件记录为准。
