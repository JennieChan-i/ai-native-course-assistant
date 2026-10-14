# 公开示例知识库

`course_chunks_sample.csv` 是为开源演示重新撰写的 17 条示例片段，覆盖 14 个主题。它展示与完整课程库相同的字段和检索流程，但不包含原始课程文稿。

首次运行 `setup.cmd` 时，程序会将示例片段复制到本机忽略的 `data/course_chunks.csv`，下载 Embedding 模型并建立 Chroma 索引。拥有完整资料的作者可在初始化前将同字段的正式 CSV 放到 `data/course_chunks.csv`，再运行 `setup.cmd`。

示例库上的检索结果仅能说明公开版本可运行。完整库的历史评测口径见 `evals/historical_full_summary.json`。
