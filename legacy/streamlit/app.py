import sqlite3  # 导入 sqlite3，用来读取第 10 阶段的 SQLite 日志数据库

import sys  # 导入 sys，用来动态追加 Python 模块搜索路径

from pathlib import Path  # 导入 Path，用来处理项目中的目录和文件路径

from typing import Any  # 导入 Any，用来给通用辅助函数补充类型提示

import streamlit as st  # 导入 Streamlit，用来快速搭建本地 Web Demo


BASE_DIR = Path(__file__).resolve().parent  # 历史快照：原始位置为 12_Web_Demo

PROJECT_ROOT = BASE_DIR.parent  # 原版依赖阶段式项目目录；本快照不作为当前启动入口

AGENT_DIR = PROJECT_ROOT / "09_Agent与Skill路由"  # 拼接第 9 阶段 Agent 主控目录路径

LOG_DB_PATH = PROJECT_ROOT / "10_SQL日志与Badcase分析" / "agent_logs.db"  # 拼接第 10 阶段 SQLite 日志数据库路径

if str(AGENT_DIR) not in sys.path:  # 如果第 9 阶段目录还没有加入 Python 搜索路径
    sys.path.append(str(AGENT_DIR))  # 就把它加入搜索路径，这样后面才能直接导入 agent_controller.py


try:  # 尝试直接导入第 9 阶段 agent_controller.py 中的 run_agent 函数
    from agent_controller import run_agent  # 优先直接复用核心函数，而不是再走 subprocess

    IMPORT_AGENT_ERROR = ""  # 如果导入成功，就把导入错误信息记为空字符串
except Exception as import_error:  # 如果导入失败，就把错误记录下来，页面里给用户看
    run_agent = None  # 导入失败时，把 run_agent 设为 None，避免后面直接调用时报错

    IMPORT_AGENT_ERROR = str(import_error)  # 保存导入失败原因，便于页面提示排查


def safe_text(value: Any, default: str = "不适用") -> str:  # 定义函数：把任意值安全转成适合页面展示的文本
    if value is None:  # 如果值是 None
        return default  # 返回默认占位文本

    text = str(value).strip()  # 先把值转成字符串，并去掉首尾空格

    if text == "":  # 如果转成字符串后仍然为空
        return default  # 返回默认占位文本

    return text  # 否则返回真正可展示的文本


def get_connection() -> sqlite3.Connection:  # 定义函数：创建 SQLite 数据库连接
    connection = sqlite3.connect(LOG_DB_PATH)  # 连接第 10 阶段的 agent_logs.db 数据库文件

    connection.row_factory = sqlite3.Row  # 把查询结果设置成 Row 格式，方便通过字段名读取数据

    return connection  # 返回数据库连接对象


def load_recent_logs(limit: int = 5) -> list[dict[str, Any]]:  # 定义函数：读取最近几条 Agent 调用日志
    if not LOG_DB_PATH.exists():  # 如果日志数据库文件不存在
        return []  # 直接返回空列表，页面里会显示“暂无日志”

    connection = get_connection()  # 创建数据库连接

    cursor = connection.cursor()  # 创建游标，用来执行 SQL 查询

    cursor.execute(  # 执行查询最近日志的 SQL 语句
        """
        SELECT
            created_at,
            user_input,
            intent,
            skill_name,
            status,
            has_sources,
            feedback_type
        FROM agent_call_logs
        ORDER BY created_at DESC, log_id DESC
        LIMIT ?;
        """,
        (limit,),
    )  # 查询结束

    rows = cursor.fetchall()  # 取出全部查询结果

    connection.close()  # 查询结束后关闭数据库连接

    return [dict(row) for row in rows]  # 把 Row 结果转换成普通字典列表，方便 Streamlit 展示


def execute_agent(user_input: str) -> dict[str, Any]:  # 定义函数：执行 Agent，并统一返回页面需要的结构
    if run_agent is None:  # 如果 run_agent 没有导入成功
        return {  # 返回一个错误结构，页面不会崩掉
            "user_input": user_input,  # 记录用户输入
            "route_result": {},  # 路由结果留空
            "skill_result": {  # 构造错误态 Skill 结果
                "status": "error",  # 标记为错误状态
                "skill": "agent_controller",  # 标记错误来源是 Agent 主控导入失败
                "answer": "当前无法调用 Agent，请先检查 agent_controller.py 是否可被导入。",  # 给页面一个清晰错误提示
                "error_message": IMPORT_AGENT_ERROR,  # 把真实导入错误带回页面展示
            },
            "log_id": "",  # 此时没有新的日志 ID
            "log_write_error": "",  # 此时没有单独的日志写入错误信息
        }  # 返回错误结构结束

    try:  # 尝试直接执行第 9 阶段的 run_agent 函数
        result = run_agent(user_input)  # 调用 Agent 主控函数

        if isinstance(result, dict):  # 如果返回结果本身已经是字典
            return result  # 直接返回这个结果
    except Exception as error:  # 如果调用 run_agent 的过程中抛出异常
        return {  # 返回统一错误结构，避免页面崩溃
            "user_input": user_input,  # 记录用户输入
            "route_result": {},  # 路由结果留空
            "skill_result": {  # 构造错误态 Skill 结果
                "status": "error",  # 标记执行失败
                "skill": "agent_controller",  # 标记错误来源
                "answer": "Agent 执行失败，请检查环境变量、模型调用链路或依赖是否完整。",  # 给用户看的人类可读提示
                "error_message": str(error),  # 保存真实错误信息，便于排查
            },
            "log_id": "",  # 这里没有保证能拿到日志 ID
            "log_write_error": "",  # 这里先留空
        }  # 返回错误结构结束

    return {  # 如果 run_agent 返回了非字典结果，就兜底包装成统一结构
        "user_input": user_input,  # 记录用户输入
        "route_result": {},  # 路由结果留空
        "skill_result": {  # 构造兜底 Skill 结果
            "status": "error",  # 标记为错误
            "skill": "agent_controller",  # 标记来源
            "answer": "Agent 返回结果结构异常，当前无法正常解析。",  # 给用户可读的错误提示
            "error_message": safe_text(type(result).__name__, default="unknown_result_type"),  # 记录返回结果类型，便于排查
        },
        "log_id": "",  # 没有日志 ID
        "log_write_error": "",  # 没有单独日志错误
    }  # 返回兜底结构结束


def render_result(result: dict[str, Any]) -> None:  # 定义函数：把 Agent 返回结果渲染到页面上
    route_result = result.get("route_result", {}) or {}  # 取出路由结果；如果为空就回退成空字典

    skill_result = result.get("skill_result", {}) or {}  # 取出 Skill 结果；如果为空就回退成空字典

    st.subheader("调用结果")  # 在页面上显示结果区标题

    st.markdown(f"**用户输入：** {safe_text(result.get('user_input', ''))}")  # 展示用户输入内容

    st.markdown(f"**最终回答：** {safe_text(skill_result.get('answer', ''))}")  # 展示 Agent 最终回答

    st.markdown(f"**intent：** {safe_text(route_result.get('intent', ''))}")  # 展示 Router 识别出的意图

    st.markdown(f"**target_skill：** {safe_text(route_result.get('target_skill', ''))}")  # 展示 Router 判断的目标 Skill

    st.markdown(f"**confidence：** {safe_text(route_result.get('confidence', ''))}")  # 展示 Router 置信度

    st.markdown(f"**route_reason：** {safe_text(route_result.get('reason', ''))}")  # 展示 Router 判断原因

    st.markdown(f"**skill_name：** {safe_text(skill_result.get('skill', skill_result.get('skill_name', '')))}")  # 展示实际执行的 Skill 名称

    st.markdown(f"**rewritten_query：** {safe_text(skill_result.get('rewritten_query', ''))}")  # 展示 Query 改写结果

    st.markdown(f"**sources / 参考来源：** {safe_text(skill_result.get('sources', skill_result.get('source_documents', '')))}")  # 展示来源信息

    st.markdown(f"**status：** {safe_text(skill_result.get('status', ''))}")  # 展示 Skill 执行状态

    st.markdown(f"**error_message：** {safe_text(skill_result.get('error_message', ''))}")  # 如果有错误信息，就展示；没有则显示“不适用”

    st.markdown(f"**log_id：** {safe_text(result.get('log_id', ''))}")  # 展示本次调用写入的日志 ID

    st.markdown(f"**log_write_error：** {safe_text(result.get('log_write_error', ''))}")  # 如果日志写入出错，也展示出来


def render_recent_logs() -> None:  # 定义函数：在页面底部展示最近 5 条日志
    st.subheader("最近 5 条 Agent 调用日志")  # 显示日志区标题

    recent_logs = load_recent_logs(limit=5)  # 读取最近 5 条日志

    if not recent_logs:  # 如果日志列表为空
        st.info("当前没有可展示的日志记录。请先在页面中发起一次 Agent 调用，或检查日志数据库是否存在。")  # 给出友好提示

        return  # 直接结束当前渲染函数

    for index, log in enumerate(recent_logs, start=1):  # 依次遍历每条日志记录
        with st.expander(f"第 {index} 条 | {safe_text(log.get('created_at', ''))} | {safe_text(log.get('status', ''))}", expanded=index == 1):  # 用折叠面板展示每条日志
            st.markdown(f"**created_at：** {safe_text(log.get('created_at', ''))}")  # 展示日志创建时间

            st.markdown(f"**user_input：** {safe_text(log.get('user_input', ''))}")  # 展示用户输入

            st.markdown(f"**intent：** {safe_text(log.get('intent', ''))}")  # 展示日志中的意图字段

            st.markdown(f"**skill_name：** {safe_text(log.get('skill_name', ''))}")  # 展示执行的 Skill 名称

            st.markdown(f"**status：** {safe_text(log.get('status', ''))}")  # 展示执行状态

            st.markdown(f"**has_sources：** {safe_text(log.get('has_sources', ''))}")  # 展示是否带来源

            st.markdown(f"**feedback_type：** {safe_text(log.get('feedback_type', ''))}")  # 展示反馈类型


st.set_page_config(page_title="AI 产品经理课程智能学习助手 Demo", page_icon="📘", layout="wide")  # 设置页面标题、图标和整体布局

st.title("AI 产品经理课程智能学习助手 Demo")  # 显示页面主标题

st.markdown(  # 展示页面说明，让用户知道这个 Demo 支持哪些能力
    """
本 Demo 当前支持以下能力：

- 课程知识问答
- 学习路径规划
- 面试题生成
- PRD 点评
- 简历优化
- Badcase 反馈记录
"""
)  # 页面说明结束

if IMPORT_AGENT_ERROR:  # 如果一开始导入 agent_controller.py 就失败了
    st.warning(f"当前 Agent 导入失败：{IMPORT_AGENT_ERROR}")  # 在页面顶部给出警告，提示用户先修复导入问题

user_input = st.text_area("请输入你的问题或需求：", height=180, placeholder="例如：RAG 是什么？或者：帮我出 5 道 Agent 面试题")  # 创建多行输入框，让用户输入问题

submit_clicked = st.button("提交问题", type="primary")  # 创建“提交问题”按钮

if submit_clicked:  # 如果用户点击了提交按钮
    if user_input.strip() == "":  # 如果输入内容为空
        st.warning("请输入问题后再提交。")  # 给出友好提示，提醒用户先输入内容
    else:  # 如果输入内容不为空
        with st.spinner("Agent 正在处理中，请稍候..."):  # 在调用 Agent 时显示加载提示
            agent_result = execute_agent(user_input=user_input.strip())  # 执行 Agent，并拿到完整结果

        render_result(agent_result)  # 把 Agent 返回结果渲染到页面上

st.divider()  # 在主调用区域和日志区域之间插入一条分隔线

render_recent_logs()  # 在页面底部展示最近 5 条 Agent 调用日志
