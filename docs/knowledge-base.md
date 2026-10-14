# 知识库处理与检索

当前应用读取 9 个字段：`chunk_id`、`chunk_text`、`doc_id`、`doc_name`、`topic`、`subtopic`、`content_type`、`suitable_questions`、`chunk_order`。`chunk_id` 用于引用和溯源，文稿与主题字段用于知识库浏览和分层评测。

原项目的完整库由 14 份课程整理稿清洗、切片和标注后形成 877 条正式切片。原始 Word/音频未包含在此仓库；完整切片也保留在作者本机。公开版的 17 条片段是重新撰写的演示文本，覆盖 14 个主题，不是原课文摘录。

初始化脚本先读取本机 `data/course_chunks.csv`；若不存在，则复制 `examples/course_chunks_sample.csv`。脚本校验字段、唯一 ID 和非空正文，下载或读取本地 `BAAI/bge-small-zh-v1.5`，为每条正文生成 512 维向量，并建立 cosine 距离的 Chroma collection。数据版本记录为 CSV SHA-256。

检索时使用同一 Embedding 模型编码 Query，从 Chroma 取 Top-K 片段。生成回答后只接受本次检索得到的 chunk ID；未知引用显示“引用未验证”。在网页“课程知识库 → 语义检索实验”可单独观察检索结果。

拥有合法使用权的完整 CSV 可放在 `data/course_chunks.csv`，运行 `setup.cmd` 后脚本会按该 CSV 建立本地索引。`data/` 和 `models/` 被 Git 忽略。更换数据集后应重新运行准备脚本，并为对应数据集单独保存评测结果。
