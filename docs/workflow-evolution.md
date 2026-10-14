# 项目阶段与当前实现

作者提供的项目经历顺序是：先在 Dify 搭建低代码 Workflow Demo，验证意图识别、分类、知识库检索与多分支回答；随后用 Python 实现 Router、Skill、RAG 与 SQLite 日志，并用 Streamlit 做早期网页；目前 GitHub 展示版使用 React + FastAPI，在本机调用百炼模型。

本仓库的 `legacy/streamlit/` 留存早期代码快照。当前可运行入口在仓库根目录，其五类 Skill 通过学习助手中的功能标签或自动路由触发。Dify Workflow 的 DSL、节点截图及运行记录未包含在本次整理的文件中，因此这里只记录作者提供的阶段说明，不展示无法核验的 Dify 节点细节。

历史阶段使用过 qwen-flash 的表述；公开展示版 `.env.example` 默认 qwen3.8-flash。模型选择以实际运行配置为准。
