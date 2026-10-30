---
version: 1
preferred_layout: null
preferred_style: null
preferred_aspect: null
language: zh
preferred_image_backend: codex-imagegen
custom_styles:
  - name: lab-editorial-infographic
    description: "项目新闻与技术解说风格，引用baoyu-slide-deck的editorial-infographic。"
    prompt_fragment: "杂志式专业信息图，干净背景，清楚的视觉叙事与字号层级，有意义的关系和流程图形；使用本次明确的配色，必要标注易于手机阅读。"
  - name: lab-scientific
    description: "项目研究与系统图解风格，引用baoyu-slide-deck的scientific。"
    prompt_fragment: "准确清楚的科学图解，线条粗细一致，结构、标签和方向表达明确；以颜色区分本次对象或步骤，不添加与研究无关的分子、细胞或公式。"
---

# 实验室项目偏好

本技能用于需要复杂结构、关系或对照的单张信息图。先选择图要解释的问题，再读取相应布局与完整风格定义，不直接使用bento-grid或craft-handmade默认方案。

风格、布局、比例与本篇配色分别确定。小红书通常采用3:4，公众号按插图位置确定；这里保留比例空值，以免把一个平台的比例套给另一个平台。

项目别名是跨模块入口，生成前分别读取 `/Users/nickychen/.agents/skills/baoyu-slide-deck/references/styles/editorial-infographic.md` 或 `scientific.md` 的完整原定义，将本次配色与布局一起组装为提示词；不能只使用上面的简短prompt_fragment。
保留来源事实和数据的含义与必要条件；图片文字可据已核实事实作中文解释，不能增添新信息或扩大结论。数据图用实际数据制作，不让生成模型虚构数值。

按本技能保存分析、结构化内容与完整提示词，再用OpenAI原生图像工具生成。文字或关系错误时修改提示词重新生成，不程序涂改。图片不添加AI标签或虚构账号水印，实际来源继续归因。

完整规则见 `语气参考/配图选择与制作规范.txt`。
