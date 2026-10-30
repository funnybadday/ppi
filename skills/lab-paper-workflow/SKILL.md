---
name: lab-paper-workflow
description: Use for this laboratory's Horizon paper collection from arXiv/PubMed/bioRxiv/medRxiv, screening digests, candidate review, cross-day event tracking, and routing selected papers to WeChat interpretation and requested Xiaohongshu derivatives. Also use when only assessing whether a supplied paper URL/DOI is worth writing about.
---

# 实验室论文总控

把 arXiv、PubMed、bioRxiv、medRxiv 的公开论文整理为独立Horizon日报与编辑候选，用户选定后交给 **lab-paper-wechat-article** 做论文解读；用户要求小红书或两平台时，再由 **lab-paper-xhs-post** 从完成的公众号派生。总控管理三个skill的阶段和事件关联；新闻类资讯由蓝图宣传项目负责，本项目只处理论文。

## 项目与请求

使用用户指定的项目；默认 `/Users/xulei/项目/搜索/蓝图论文`。先读项目 `AGENTS.md`、`工作流状态.json` 和 `内容工作流与交付规范.txt`。实际阶段、已完成稿件与定时状态来自状态文件，不依赖旧聊天或某篇试稿。

| 本次请求 | 执行 |
| --- | --- |
| 采集一轮论文 | 按[Horizon操作](references/horizon-operations.md)采集（arXiv/PubMed/bioRxiv/medRxiv）、评分、筛选，先交付原始日报，再复核候选 |
| 查看已有结果／继续失败阶段 | 定位指定run和已完成产物，成功阶段复用；明确历史日期 |
| 选定Horizon条目或候选 | 用明确文件与ID定位，加载 **lab-paper-wechat-article** 继续制作 |
| 给论文网页/DOI并要求做公众号 | 直接交给 **lab-paper-wechat-article**，跳过采集和候选 |
| 只问值不值得写 | 取得实际材料，给选题判断，等待用户选择 |
| 已有公众号转小红书／改小红书 | 直接交给 **lab-paper-xhs-post**，读取指定案例，不重新采集或改公众号 |
| 同一论文做公众号和小红书 | 先 **lab-paper-wechat-article**，完成后继续 **lab-paper-xhs-post**；继承同一案例与event_key |
| 改已有公众号稿件 | 交给 **lab-paper-wechat-article**，从该案例继续 |

显式指定优先于旧selected_event_id；同名ID用候选文件、日期或明确事件消歧。子skill由当前执行者加载，不必另开聊天。

## 一轮采集的交付

1. 检查最新成功运行和回看窗口，使用既有DeepSeek配置分阶段运行。低分、未评分、失败均保留。
2. Horizon结果就绪后，用 `scripts/export_horizon.py --report-dir` 向 `Horizon日报/` 新增一个带采集时间和run标识的TXT。每轮一个，历史不覆盖；原始数据保留在run目录。复筛失败不抹掉该交付。
3. 按[跨日对比与事件台账](references/cross-run.md)生成链接对比上下文，读取事件台账。逐条审阅全量标题与可用摘要，包括0—2分及未评分；不能只读过线结果或3—4分队列。相关但材料不足的低分线索仍进入判断，原分数不篡改。
4. 对有潜力且信息不足的线索轻量回源（论文页、DOI、期刊页），确认发表状态、原始日期、具体方法与新增事实。短摘要可以作为发现入口，无须全量抓全文再评分；未取得必要材料的留待补核。
5. 按事件合并，区分首次推荐、实质更新、重复和待核。跨日同一研究没有新事实时，不重复推送；预印本修订版本须有实质变化才算更新；同一作者团队的系列工作分别判断。
6. 将TXT与结构化JSON候选放 `选题池/`，通常推荐3—5个，实际可为0。内容限事实摘要、原始日期、新增信息、推荐理由、来源和内部待核问题；不提前写平台标题、大纲或图片方案。用台账工具记录本轮处理，保留稳定event_key供新对话续用。

Horizon日报如实保留本轮结果，可含重叠条目；候选简报突出新增与更新。仅被采集不等于已经推荐，已写稿不等于已发布。台账辅助编辑判断，不把URL相似或主体相同当成语义去重。

## 交给平台制作

提供项目根目录、选定记录及其文件/ID、稳定event_key（如有）、全部已知来源、本次用户要求。网页入口提供实际URL即可，不要求先建候选。

候选阶段已读材料作为继承信息，完整取材与写作事实核验在公众号阶段完成。用户明确制作后完成回源、写稿、选图与Word；要求两平台则加载小红书子skill，传入实际公众号文件、同案例目录、event_key、来源和本次要求，继续完成封面、正文图组与发布文案。不逐环节重复确认；仅要求方案时按要求停在方案。

小红书从已完成公众号派生；仅给论文网页并要求两平台时先做公众号。仅要公众号时交付公众号即可。小红书沿用同一event_key并记独立平台状态，不新增论文候选，不改变公众号的认可或发布状态；单独改小红书从其原目录继续。两平台都保存于 `稿件/<简短论文名>/`，具体制作由各子skill执行。

## 边界与恢复

使用既有Horizon密钥和模型，不显示密钥，不调用完整CLI／daily-run.sh做富化或发布。上游阶段重跑会使下游失效，调用前先检查已有产物。
当前没有跨run评分缓存；链接对比和事件台账不保证省去重复评分。部分来源失败或订阅保留时间造成的缺口明确记录，不当成零论文；arXiv与bioRxiv/medRxiv依赖本地代理，代理未运行时相应来源失败要如实记录。
定时启用依用户明确请求与状态文件；商定时间不等于已启用。发布由用户与同事完成。
