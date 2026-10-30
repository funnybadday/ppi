---
version: 1
watermark:
  enabled: false
  content: ""
  position: bottom-right
preferred_style:
  name: null
  description: "按文章的信息需要选择；优先考虑editorial-infographic、scientific，不固定风格或配色。"
preferred_palette: null
language: zh
default_output_dir: illustrations-subdir
preferred_image_backend: codex-imagegen
generation_batch_size: 4
custom_styles:
  - name: lab-editorial-infographic
    description: "引用baoyu-slide-deck的editorial-infographic完整定义，配色与布局按本篇确定。"
    visual_elements: "视觉叙事、专业层级与清楚的关系图解；读取完整原定义后组装提示词。"
    typography: "专业中文标题、简洁易读的标签与图注。"
    best_for: "新闻、产业、技术解释"
  - name: lab-scientific
    description: "引用baoyu-slide-deck的scientific完整定义，按研究对象确定结构与颜色语义。"
    visual_elements: "准确的系统、结构、方法或机制图；读取完整原定义后组装提示词。"
    typography: "清楚的技术标签、符号与中文标注。"
    best_for: "方法、机制、临床试验与研究内容"
---

# 实验室项目偏好

- 公众号优先原始网页、公告或稿件截图，以及可追溯的论文图和数据图。仅在确需新增图解时启用本技能；不强制每篇新闻生成图片。
- 公众号单独选图和设计，不能直接搬用小红书3:4竖版封面或信息卡。新增图解的比例、信息量与构图按正文阅读需要确定，不继承小红书的默认比例。
- 普通公众号新闻不加“图1、图2”及论文式说明图注。必要时保留简短来源，完整链接集中在文末；来源图的原始必要标注按内容保留。
- 主流程为本技能；原定义位于 `/Users/nickychen/.agents/skills/baoyu-slide-deck/references/styles/editorial-infographic.md` 和 `scientific.md`，生成前读取完整文件。
- 按 `语气参考/配图选择与制作规范.txt` 判断配图是否帮助理解，再决定位置、图解目的、布局、风格、比例及本篇配色。简短公告少图，方法和研究按信息量展开。
- 不默认使用sketch-notes、手绘或任何一种颜色。图片独立提供并插入可编辑Word；`illustrations-subdir`便于图片与稿件保存在同一交付目录。
- 真实截图来自原页面，研究图或数据来自可核实材料。OpenAI原生图像工具负责概念和方法示意；不编造研究数字或产品界面。
- 完整提示词生成前保存，错误重新生成，不用程序修补文字。不添加AI标签；必要来源与图注按项目规范保留。
- 写稿前直接读取已下载的两篇公众号HTML和正文作为few-shot；图片方案以本次核实后的事实为依据。
