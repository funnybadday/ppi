---
version: 1
watermark:
  enabled: false
  content: ""
  position: bottom-right
preferred_style:
  name: null
  description: "按内容选择。用户认可editorial-infographic、scientific及多种布局；读取完整原定义，不固定配色、手绘或notion。"
preferred_layout: null
language: zh
preferred_image_backend: codex-imagegen
generation_batch_size: 4
custom_styles:
  - name: lab-editorial-infographic
    description: "引用baoyu-slide-deck中的editorial-infographic完整定义，按本篇主题调整配色。"
    visual_elements: "清楚的视觉叙事、专业图文层级、有语义的关系和流程；生成前读取完整原定义。"
    typography: "专业中文标题层级与易读标注，适配手机阅读。"
    best_for: "新闻、产业合作、产品能力与技术解说"
  - name: lab-scientific
    description: "引用baoyu-slide-deck中的scientific完整定义，按本篇对象及过程确定颜色含义。"
    visual_elements: "准确标注、清楚方向、结构与方法流程；生成前读取完整原定义。"
    typography: "清楚的专业中文标题、标签与技术标注。"
    best_for: "研究方法、技术系统、机制及临床试验流程"
---

# 实验室项目偏好

这些偏好仅在用户另行要求小红书时使用，不触发公众号流程附带制作。当前已认可新闻分页由 `skills/lab-paper-xhs-post/SKILL.md` 管理，正文通过HTML/CSS渲染；本宝玉技能用于另需信息卡片时。读取 `语气参考/小红书偏好.txt`，图片真实性与检查沿用 `语气参考/配图选择与制作规范.txt`。

- `lab-editorial-infographic` 原定义：`/Users/nickychen/.agents/skills/baoyu-slide-deck/references/styles/editorial-infographic.md`。
- `lab-scientific` 原定义：`/Users/nickychen/.agents/skills/baoyu-slide-deck/references/styles/scientific.md`。
- 可补充的布局定义：`/Users/nickychen/.agents/skills/baoyu-slide-deck/references/layouts.md`，以及 `baoyu-infographic/references/layouts/` 中对应文件。
- 项目别名用于注册跨模块风格。生成前将完整原定义和本次布局写入方案与提示词；描述字段不是完整提示词。
- 另行选择信息卡片形式时使用本技能；不接管新闻正文连续分页。通常采用3:4竖图，图数随信息量决定；各页按内容选布局，同组保持字体、线条和颜色语义一致。
- 配色逐篇决定。原定义中的示例颜色可以结合主题调整；不把某次案例的配色设为全局偏好。
- 各图包含具体事件、任务、方法或结果，不用空泛判断或内部评估问题填页。正文专业、简洁，不娱乐化，不做defensive writing。
- 使用当前原生OpenAI图像工具，不另接图片API。先保存完整提示词，首图生成后作为后续图片的直接参照。
- 不添加AI标签或虚构账号水印；实际资料与数据保留必要来源及完整链接。优先遵循项目来源要求，不能因原风格不含页脚而移除必要归因。
