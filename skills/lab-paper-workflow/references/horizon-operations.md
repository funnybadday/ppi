# 本项目的Horizon分阶段操作

先读取已安装的 **horizon** 技能及其 pipeline 参考。当前checkout为项目下的 `Horizon/`，解释器为 `Horizon/.venv/bin/python`。适配器使用checkout自带的 `Horizon/skills/horizon/scripts/horizon_ops.py`（本机无 ~/.agents/skills/horizon 安装）。采集依赖本地代理：arXiv与bioRxiv/medRxiv直连被干扰，`Horizon/.env` 已配置 HTTP_PROXY/HTTPS_PROXY=127.0.0.1:6864，采集前确认代理应用正在运行。

## 读取或续用

优先检查已有run目录、日期、采集窗口与实际产物。列举run时可调用：

```sh
Horizon/.venv/bin/python Horizon/skills/horizon/scripts/horizon_ops.py list_runs --horizon-path "$PWD/Horizon"
```

相对命令从项目根目录运行。不要将“现在最新的文件”直接当作“今天新采集”；明确历史复用的范围。指定run后读取 `meta.json`、`raw_items.json`、`scored_items.json`、`filtered_items.json`，已有阶段无需重跑。

## 新采集（仅用户请求本轮采集时）

用适配器各操作的 `--describe` 核对当前签名。参数写入UTF-8 JSON文件，再以 `--params-file` 传入；不要把密钥写入参数文件。

1. `validate_config`，查看缺少环境变量和警告，保持既有 `Horizon/data/config.json` 与clinical-papers。
2. `fetch_items`：传 `hours`、`config_path` 和 `sources:["rss","pubmed","biorxiv"]`（rss=arXiv三条Atom查询；pubmed、biorxiv为论文抓取器），记录实际run_id及fetch_report。sources选的是类型，不是单条订阅名称。
3. 非空raw调用 `score_items`，传实际run_id及同一config_path。检查 `processing.analysis` 的真实完整程度，不能仅凭文件或返回计数断言全部已评分。
4. `filter_items`，使用既有阈值；本项目试跑为5分，变更阈值需有理由。保留全量scored，初筛不进入 `enrich_items`。
5. 有filtered结果即可离线导出，不需要enrichment或生成发布稿。raw为空时记录实际抓取状态，保存空的scored／filtered结果时明确未执行评分，避免调用要求非空的score操作。

每次操作传同一个checkout/config/run。上游保存会使下游产物失效。既有完整运行入口可能进行深度扩展、交付或发布，不用于本项目初筛。

## 回看窗口

新采集前运行 `python3 skills/lab-paper-workflow/scripts/radar_history.py window --project-root "$PWD"`，取得建议hours和成功检查点。正常连续采集至少48小时；按距上次成功采集的时间加24小时重叠补足，周一至少96小时。尚未有可靠检查点时先回看96小时。用户明确指定时间范围时按请求处理并记录。来源覆盖只以实际记录为准，汇总“RSS Feeds成功”不能证明各订阅均成功。

重叠窗口可能重复采集和评分，但[跨日对比](cross-run.md)与事件台账控制候选重复推荐。Horizon本身的语义去重只覆盖本轮筛选，不替代跨日记忆；自带history_search依赖历史摘要，当前分阶段流程没有产生这些摘要，因此不用它承担这项职责。

本版技能不自动部署调度器，也没有逐来源补采或跨日评分缓存。按本次请求执行；定时创建仍等待用户要求。

## 独立导出

确认已形成相互一致的raw、scored、filtered及meta文件后运行：

```sh
python3 /Users/xulei/项目/搜索/蓝图论文/skills/lab-paper-workflow/scripts/export_horizon.py --run-dir "/absolute/Horizon/data/mcp-runs/RUN_ID" --report-dir "/absolute/Horizon日报"
```

实际替换路径，不将占位符当run。Horizon日报目录可已存在，每个run新增一份时间命名的TXT，旧文件不覆盖。同一run已有日报时，直接读取该文件；若再次调用脚本，会以File exists及非0退出码拒绝覆盖。导出仅读取已有结果，不联网、不调用模型、不改变Horizon或选题状态。

可读摘要包含待复核队列，全量附件保留在Horizon对应run目录，由日报指向实际路径。需要单独的结构化交接时，可用互斥参数 --output-dir 写一个新目录，其中保留可读摘要、全量精简JSON、队列和导出记录；常规日报使用单文件模式。

记录中的日期取采集时间并转换Asia/Shanghai，导出日期不能代替采集日期。低分全部保留；未评分为null及明确状态，不能写为0分。导出结果只是Horizon初筛，不声明已做OpenAI复筛、全面回源或用户内容验收。

日报的待复核队列便于浏览，不限定OpenAI复核范围。后续从全量 `scored_items.json` 读取标题与可用摘要，结合 `raw_items.json` 查看未评分或缺摘要记录，包含0—2分线索。按总控skill进行必要的轻量回源；无需因订阅摘要短而统一抓全文或重跑评分。

## 失败与续用

读取真实fetch_status：success、partial_failure、failure、not_attempted，不能把后两种拼成其他字符串后漏判。RSS可能吞掉逐源失败而汇总仍报success；pubmed/biorxiv抓取器异常时返回空并记录warning，同样检查抓取日志和逐源结果，空数据不凭success就宣布全部成功，也不推进窗口检查点。部分来源失败时如实导出已有结果及缺口，不以“0篇论文”代替失败。全量条目存在不等于全部有评分。

fetch、score、filter的上游重跑会覆盖本阶段并使下游产物失效；同一run的自定义候选文件未必随之清空，不可把它们当成仍有效。恢复时复用成功阶段，只续未完成部分。需重新fetch则建立新run；已有完整日报的历史run不重新评分或改写，规则变更后需要复筛时另存独立复核结果并注明原run和规则变化。

运行前后核对来源配置和规则目录，实验室规则通过Horizon/local-profiles/clinical-papers链接到规则/Horizon-clinical-papers。参数与日志只记录配置路径、阶段及状态，密钥保持在.env。
