---
name: lab-paper-wechat-article
description: Use when this laboratory explicitly selects a paper (from arXiv/PubMed/bioRxiv/medRxiv candidates or a supplied paper webpage/DOI) for a 公众号 interpretation article, requests manual testing of either article entry, or asks to revise an existing WeChat稿件. A request only to assess whether a paper is worth writing does not trigger production.
---

# 实验室论文解读公众号制作

从已选论文候选或手动论文网页（abs页/PubMed页/DOI），完成可交同事排版的公众号文字、来源图与可编辑Word。两种入口共用核验与制作流程；用户要求两平台时，完成后衔接 **lab-paper-xhs-post**。

## 先确定本次请求

使用用户指定项目，默认 `/Users/xulei/项目/搜索/蓝图论文`。读取项目 `AGENTS.md`、`工作流状态.json` 与总流程中公众号相关部分。

用户明确要求制作才开始；仅整理技能或讨论工作流不触发文章。只问值不值得写时交给 **lab-paper-workflow** 做选题判断。选题已确定后直接执行，不逐环节重复确认；明确要求先看方案时停在方案。

## 两种输入归一化

| 输入 | 操作 |
| --- | --- |
| 已选候选／Horizon条目 | 从用户指定的文件与ID取该条记录；可用 `scripts/resolve_input.py --selection-file ... --selection-id ...` |
| 手动论文网页 | 直接使用用户给出的URL（arXiv abs页、PubMed页、期刊页或DOI链接）；可用同一脚本的 `--url`，多个URL重复该参数 |

脚本只整理输入，不访问网页或证明事实。显式指定的ID优先于旧的全局selected_event_id；保留全部已知来源、内容类型、用户语境及event_key。既往核验记入“继承材料”，不能冒充本次重新查阅。手动入口不依赖Horizon或候选池。

## 共用制作流程

1. **取材与回源。** 取得论文摘要、发表方、发表状态（预印本/期刊）、原始日期和可用图像；从论文页追原始出处（DOI、期刊页、补充材料、代码与数据仓库）。网页不可读时先找本地已存HTML／正文。保存关键事实与对应出处、核验时间和内部待核问题；解读以论文摘要与可回源的原文/补充材料为界，不虚构未读的全文细节。
2. **读真实few-shot。** 读取项目 `语气参考/语气偏好与参考状态.txt`。运行 `scripts/load_fewshots.py --project-root ...` 并完整读取索引指向的论文解读正文，保留读取路径；不能只读语气摘要。样例事实不带入新稿。哈希不一致时按[制作衔接](references/production.md)从本地HTML重新核对，不立即向用户索要已有文章。
3. **写稿。** 用本次核实的事实自然解释具体任务、方法或结果，有依据地表达判断。信息丰富时写细，信息少时写短；不做defensive writing，不套样例口头禅、推广或“叠甲”，不虚构亲历。few-shot里的事实不带入新稿。
4. **选图与制作。** 读取项目配图规范的公众号部分。优先真实论文页截图、原文图表及稿件原图；需要图解时使用 **baoyu-article-illustrator** 及项目EXTEND，按内容读取完整风格。普通解读不写编号式图注，必要时用简短来源。图解不伪装为网页或实测数据，公众号内不插入小红书竖版卡片，不加“AI生成”标签。
5. **文档与检查。** 必须使用 **documents:documents**，交付正文可编辑的Word及独立原图、来源。中文宋体，East Asian映射Songti SC；以Word或macOS原生预览核查中文、分页及图片。具体文件位置和检查记录见制作衔接。

## 输出与状态

唯一案例位置为 `稿件/<简短论文名>/`，名称取自本次实际论文。从实际研究内容命名，不以日期或编号替代论文名，不再新建顶层试稿／交付／image-cards目录。已有同题稿件在该案例内修订并保留必要历史，不覆盖不同论文。

本次交付结束记为“待用户审阅”，将稿件目录关联到 `选题池/事件台账.json` 中对应event_key，状态记为drafted；手动网页可新增事件，无需运行Horizon。具体记录方法见[制作衔接](references/production.md)。内部检查通过不等于用户满意，只有用户明确反馈才更新内容认可或发布状态。独立论文流程和定时启用另行处理。

## 继续小红书

用户本次要求小红书或两平台时，公众号完成后由当前执行者加载 **lab-paper-xhs-post**，传入实际公众号正文与Word路径、同一案例目录、event_key、来源和可用图片。不为转换重跑Horizon，不在已授权的平台之间重复询问。只要公众号时交付至此；用户只改小红书时直接用小红书skill，不重写公众号。两平台的制作、内容认可和发布状态分别记录，小红书派生沿用同一事件，不回退公众号已认可状态。
