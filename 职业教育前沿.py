import streamlit as st
import requests
import re
import json
import os
from datetime import datetime, timedelta
import pandas as pd
import altair as alt

# ================== Supabase 配置（建议改用 st.secrets） ==================
SUPABASE_URL = "https://iacgpiciqwreyaylxxmf.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlhY2dwaWNpcXdyZXlheWx4eG1mIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA5ODY3OTQsImV4cCI6MjA5NjU2Mjc5NH0.tS4m3l8EdzrJb05m6OfLMMRdG2YeGvHyJPS9NIcETFM"

# ================== 页面配置 ==================
st.set_page_config(page_title="AI故障导师", layout="wide")

# ================== AI 配置 ==================
AI_API_KEY = "sk-ZzoqSJIZWpA6sczyjZMXJoSupG3luegm"
AI_API_URL = "https://token.sensenova.cn/v1/chat/completions"
AI_MODEL = "deepseek-v4-flash"

ADMIN_PASSWORD = "admin123"

# ================== Supabase 请求函数 ==================
def supabase_request(method, endpoint, payload=None):
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    try:
        resp = requests.request(method, url, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        if resp.text.strip():
            return resp.json()
        else:
            return []
    except Exception as e:
        st.error(f"请求失败: {e}")
        raise e

# ================== 一次性获取所有平台数据（缓存） ==================
@st.cache_data(ttl=30, show_spinner=False)
def get_all_platform_data():
    endpoint = "student_logs?select=student_name,time,type,result"
    try:
        data = supabase_request("GET", endpoint)
        return data
    except:
        return []

def format_time(iso_time):
    """将 UTC 时间（ISO字符串）转换为北京时间（UTC+8）并格式化为本地时间"""
    try:
        if iso_time.endswith('Z'):
            iso_time = iso_time[:-1] + '+00:00'
        dt = datetime.fromisoformat(iso_time)
        dt_beijing = dt + timedelta(hours=8)
        return dt_beijing.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return iso_time[:19] if len(iso_time) >= 19 else iso_time

# ================== 基于缓存数据的统计函数 ==================
def get_global_stats():
    data = get_all_platform_data()
    total_ops = len(data)
    rule_checks = sum(1 for r in data if r.get("type") == "规则检查")
    ai_calls = sum(1 for r in data if r.get("type") == "AI诊断")
    error_counts = {}
    for r in data:
        if r.get("type") == "规则检查" and "⚠️" in r.get("result", ""):
            lines = r["result"].split("\n")
            for line in lines:
                if line.startswith("- "):
                    desc = line[2:].split("：")[0]
                    error_counts[desc] = error_counts.get(desc, 0) + 1
    top_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    return {
        "total_ops": total_ops,
        "rule_checks": rule_checks,
        "ai_calls": ai_calls,
        "top_errors": top_errors
    }

def get_student_activity():
    data = get_all_platform_data()
    activity = {}
    for r in data:
        name = r.get("student_name")
        if name:
            chinese_name = re.search(r'[\u4e00-\u9fff]+$', name)
            display_name = chinese_name.group(0) if chinese_name else name
            activity[display_name] = activity.get(display_name, 0) + 1
    df = pd.DataFrame(list(activity.items()), columns=["学生", "操作次数"])
    return df.sort_values("操作次数", ascending=False) if not df.empty else pd.DataFrame(columns=["学生", "操作次数"])

def get_latest_activity():
    data = get_all_platform_data()
    if not data:
        return None, None
    latest = max(data, key=lambda x: x.get("time", ""))
    student = latest.get("student_name")
    raw_time = latest.get("time", "")
    formatted_time = format_time(raw_time)
    return student, formatted_time

# ================== 其他数据库操作 ==================
def load_log(student_name):
    endpoint = f"student_logs?student_name=eq.{student_name}&order=time.asc"
    try:
        data = supabase_request("GET", endpoint)
        for r in data:
            if "time" in r:
                r["time"] = format_time(r["time"])
        return data
    except:
        return []

def save_log(student_name, log_entry):
    record = {
        "student_name": student_name,
        "time": datetime.utcnow().isoformat() + "Z",
        "program": log_entry.get("program", ""),
        "io_desc": log_entry.get("io_desc", ""),
        "type": log_entry["type"],
        "result": log_entry["result"]
    }
    try:
        supabase_request("POST", "student_logs", record)
        st.cache_data.clear()
    except Exception as e:
        st.error(f"保存记录失败：{e}")

def delete_log(student_name):
    endpoint = f"student_logs?student_name=eq.{student_name}"
    try:
        supabase_request("DELETE", endpoint)
        st.cache_data.clear()
    except:
        pass

def get_all_students():
    data = get_all_platform_data()
    students = list(set([r.get("student_name") for r in data if r.get("student_name")]))
    return students

# ================== 规则检查 ==================
def rule_based_check(instruction_text):
    warnings = []
    out_devices = re.findall(r'OUT\s+(\w+)', instruction_text, re.IGNORECASE)
    seen = {}
    for dev in out_devices:
        seen[dev] = seen.get(dev, 0) + 1
    for dev, count in seen.items():
        if count > 1:
            warnings.append(f"双线圈警告：软元件 {dev} 被输出了 {count} 次，可能造成逻辑混乱。")
    has_ld_x0 = bool(re.search(r'LD\s+X0', instruction_text, re.IGNORECASE))
    has_out_y0 = bool(re.search(r'OUT\s+Y0', instruction_text, re.IGNORECASE))
    has_or_y0 = bool(re.search(r'OR\s+Y0', instruction_text, re.IGNORECASE))
    if has_ld_x0 and has_out_y0 and not has_or_y0:
        warnings.append("疑似自锁缺失：检测到 X0 启动 Y0 但未发现 OR Y0，请检查是否需要自锁。")
    return warnings

def ai_diagnose(instruction_text, student_question, io_desc=""):
    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json"
    }
    system_prompt = (
        "你是一位 PLC 故障诊断导师。请用简洁的**分点**形式给出排查思路。"
        "每点不超过两句话，总回复控制在200字以内。不要提供完整代码，鼓励学生自己思考。"
    )
    user_content = f"指令表：\n{instruction_text}\n"
    if io_desc:
        user_content += f"I/O 说明：{io_desc}\n"
    user_content += f"学生问题：{student_question}"
    data = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.7,
        "max_tokens": 300
    }
    try:
        resp = requests.post(AI_API_URL, headers=headers, json=data, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        reply = result["choices"][0]["message"]["content"]
        if len(reply) > 250:
            reply = reply[:250] + "..."
        reply = re.sub(r'\*\*(.*?)\*\*', r'\1', reply)
        if not reply.strip():
            reply = "AI 诊断返回了空内容，请稍后重试。"
        return reply
    except Exception as e:
        return f"AI 调用失败：{str(e)}"

def ai_compare_progress(history_summary):
    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json"
    }
    system_prompt = (
        "你是一位职教学习分析师。请根据学生最近几次PLC实训的操作记录，"
        "用第三人称（例如“该生”、“该同学”）客观评价该生的学习情况。"
        "先指出其进步和值得肯定的地方，再指出薄弱点，最后给出具体改进建议。"
        "不要使用“你”字，不要写安慰性语句。回复控制在150字以内。"
    )
    data = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"学生历史实训记录摘要：\n{history_summary}"}
        ],
        "temperature": 0.7,
        "max_tokens": 300
    }
    try:
        resp = requests.post(AI_API_URL, headers=headers, json=data, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        reply = result["choices"][0]["message"]["content"]
        if len(reply) > 200:
            reply = reply[:200] + "..."
        reply = re.sub(r'\*\*(.*?)\*\*', r'\1', reply)
        if not reply.strip():
            reply = "AI 评价返回空内容，请稍后重试。"
        return reply
    except Exception as e:
        return f"AI 对比评价生成失败：{str(e)}"

def get_learning_resources(warnings):
    error_key = "双线圈"
    if any("双线圈" in w for w in warnings):
        error_key = "双线圈 输出 冲突"
    elif any("自锁" in w for w in warnings):
        error_key = "PLC 自锁 电路"
    else:
        error_key = "PLC 编程 常见错误"
    bilibili_url = f"https://search.bilibili.com/all?keyword={error_key.replace(' ', '+')}"
    gongkong_url = "https://bbs.gongkong.com/product/plc.htm"
    siemens_url = "https://1847.siemens.com.cn/"
    return {
        "bilibili": bilibili_url,
        "gongkong": gongkong_url,
        "siemens": siemens_url
    }

def show_learning_resources(warnings):
    if not warnings:
        return
    st.markdown("---")
    st.markdown("### 📚 学习资源推荐")
    urls = get_learning_resources(warnings)
    left, right = st.columns(2, gap="medium")
    with left:
        st.markdown("#### 🎥 针对性学习链接")
        keyword = warnings[0].split('：')[0] if warnings and '：' in warnings[0] else "PLC 故障"
        st.markdown(f"- [B站搜索：{keyword}]({urls['bilibili']})")
        st.markdown(f"- [中国工控网 PLC论坛]({urls['gongkong']})")
        st.markdown(f"- [西门子1847工业学习平台]({urls['siemens']})")
        st.caption("点击链接可访问相关技术社区或课程")
    with right:
        st.markdown("#### 📖 编程规范")
        if any("双线圈" in w for w in warnings):
            st.markdown("""
            - **避免双线圈**：同一线圈在一个扫描周期内只能输出一次
            - **使用辅助继电器**：用 M 中间继电器暂存，最后统一输出
            - **SET/RST 替代**：用置位/复位指令代替重复 OUT
            """)
        elif any("自锁" in w for w in warnings):
            st.markdown("""
            - **自锁电路**：确保有 OR 自身触点
            - **启动优先**：启动信号应为短信号，自锁保持
            """)
        else:
            st.markdown("""
            - **规范注释**：每个网络添加功能说明
            - **模块化编程**：将复杂逻辑拆分为子程序
            """)

# ================== 学情报告 ==================
def generate_report(student_name, log):
    st.subheader(f"📋 {student_name} 的学情分析报告")
    if not log:
        st.info("暂无有效操作记录。")
        return

    log = [r for r in log if "AI 调用失败" not in r["result"]]
    total_ops = len(log)
    rule_checks = sum(1 for r in log if r["type"] == "规则检查")
    ai_calls = sum(1 for r in log if r["type"] == "AI诊断")

    st.markdown("### 📌 本次操作记录")
    show_log = []
    for r in log[-10:]:
        result_text = r["result"].strip() if r["result"] else "（无详细内容）"
        show_log.append({
            "时间": r["time"],
            "类型": r["type"],
            "结果摘要": result_text
        })
    df_log = pd.DataFrame(show_log)
    st.data_editor(
        df_log,
        use_container_width=True,
        hide_index=True,
        disabled=True,
        column_config={
            "时间": st.column_config.TextColumn(width="medium"),
            "类型": st.column_config.TextColumn(width="small"),
            "结果摘要": st.column_config.TextColumn(width="large"),
        }
    )

    left_col, right_col = st.columns(2, gap="large")

    with left_col:
        st.markdown("### 📊 统计概览")
        c1, c2, c3 = st.columns(3)
        c1.metric("总交互次数", total_ops)
        c2.metric("规则检查", rule_checks)
        c3.metric("AI诊断", ai_calls)

        st.markdown("### 🤖 AI 评价")
        cache_key = f"ai_eval_{student_name}_{len(log)}"
        if cache_key not in st.session_state:
            if len(log) >= 2:
                summary_parts = []
                for i, r in enumerate(log[-10:]):
                    short = r["result"][:60] + "..." if len(r["result"]) > 60 else r["result"]
                    summary_parts.append(f"第{i+1}次[{r['type']}]：{short}")
                history_summary = "\n".join(summary_parts)
                with st.spinner("AI 正在分析..."):
                    comment = ai_compare_progress(history_summary)
                    st.session_state[cache_key] = comment
            else:
                st.session_state[cache_key] = "至少需要两次有效操作才能生成评价。"
        st.info(st.session_state[cache_key])

        st.markdown("### ⚠️ 错误类型分析")
        error_counts = {}
        for r in log:
            if r["type"] == "规则检查" and "⚠️" in r["result"]:
                lines = r["result"].split("\n")
                for line in lines:
                    if line.startswith("- "):
                        desc = line[2:].split("：")[0]
                        error_counts[desc] = error_counts.get(desc, 0) + 1
        if error_counts:
            df_err = pd.DataFrame([{"错误类型": k, "出现次数": v} for k, v in error_counts.items()])
            st.dataframe(df_err, use_container_width=True, hide_index=True)
        else:
            st.info("暂无规则错误统计。")

        # ========== 进步趋势（综合评分，所有规则检查，强制整数刻度） ==========
        st.markdown("### 📉 进步趋势")
        rule_checks_all = [r for r in log if r["type"] == "规则检查"]
        if len(rule_checks_all) >= 2:
            trend_data = []
            for idx, r in enumerate(rule_checks_all):
                if "⚠️" in r["result"]:
                    warn_count = r["result"].count("- ")
                else:
                    warn_count = 0
                score = max(0, 100 - warn_count * 20)
                trend_data.append({"操作序号": idx + 1, "综合评分": score})
            df_trend = pd.DataFrame(trend_data)
            df_trend["操作序号"] = df_trend["操作序号"].astype(int)
            # 强制 x 轴显示所有整数刻度
            max_seq = df_trend["操作序号"].max()
            line = alt.Chart(df_trend).mark_line(point=True).encode(
                x=alt.X("操作序号:Q",
                        scale=alt.Scale(domain=(1, max_seq)),
                        axis=alt.Axis(title="操作序号", labelAngle=0,
                                      values=list(range(1, max_seq + 1)),
                                      format="d")),
                y=alt.Y("综合评分:Q", scale=alt.Scale(domain=(0, 100)), title="综合评分"),
                tooltip=["操作序号", "综合评分"]
            ).properties(height=300, title="综合评分趋势（满分100，每警告扣20分）")
            st.altair_chart(line, use_container_width=True)
            st.caption("分数越高代表越少警告，表示进步。")
        else:
            st.info("至少需要2次规则检查记录才能显示评分趋势。")

    with right_col:
        st.markdown("### 👥 学生快速切换")
        all_students = get_all_students()
        if all_students:
            selected_other = st.selectbox(
                "查看其他学生报告",
                all_students,
                index=all_students.index(student_name) if student_name in all_students else 0,
                key="selected_student"
            )
            if selected_other != student_name:
                st.session_state.current_report_student = selected_other
                st.rerun()
        else:
            st.info("暂无其他学生记录。")

        st.markdown("### 📊 全平台统计")
        global_stats = get_global_stats()
        col_g1, col_g2, col_g3 = st.columns(3)
        col_g1.metric("全校总交互", global_stats["total_ops"])
        col_g2.metric("全校规则检查", global_stats["rule_checks"])
        col_g3.metric("全校AI诊断", global_stats["ai_calls"])

        st.markdown("#### 🔥 常见错误 TOP 5")
        if global_stats["top_errors"]:
            top_df = pd.DataFrame(global_stats["top_errors"], columns=["错误类型", "出现次数"])
            st.dataframe(top_df, use_container_width=True, hide_index=True)
        else:
            st.info("暂无错误统计。")

        st.markdown("### 📊 学生活跃度")
        activity_df = get_student_activity()
        if not activity_df.empty:
            bars = alt.Chart(activity_df).mark_bar(size=20).encode(
                x=alt.X("学生:N", sort=None, axis=alt.Axis(labelAngle=0, title="学生")),
                y=alt.Y("操作次数:Q", title="操作次数"),
                tooltip=["学生", "操作次数"]
            ).properties(height=300).interactive()
            st.altair_chart(bars, use_container_width=True)
        else:
            st.info("暂无学生活动记录")

        st.markdown("### 📅 最近实训动态")
        latest_student, latest_time = get_latest_activity()
        if latest_student:
            st.markdown(f"**最后操作学生**：{latest_student}")
            st.markdown(f"**操作时间**：{latest_time}")
        else:
            st.markdown("暂无任何实训记录")

    if st.button("🔙 返回后台管理"):
        st.session_state.page = "admin"
        st.rerun()

# ================== 后台管理 ==================
def admin_page():
    st.title("🔐 后台管理 - 学生学情记录")
    if "admin_authed" not in st.session_state:
        st.session_state.admin_authed = False

    if not st.session_state.admin_authed:
        pwd = st.text_input("请输入管理员密码", type="password")
        if st.button("进入后台"):
            if pwd == ADMIN_PASSWORD:
                st.session_state.admin_authed = True
                st.rerun()
            else:
                st.error("密码错误")
        return

    students = get_all_students()
    if not students:
        st.info("暂无学生记录。")
        if st.button("返回主界面"):
            st.session_state.admin_authed = False
            st.session_state.page = "main"
            st.rerun()
        return

    if "current_report_student" not in st.session_state:
        st.session_state.current_report_student = students[0] if students else None

    selected = st.selectbox(
        "选择学生查看报告",
        students,
        index=students.index(st.session_state.current_report_student) if st.session_state.current_report_student in students else 0
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("查看学情报告"):
            st.session_state.current_report_student = selected
            st.session_state.page = "report"
            st.rerun()
    with col2:
        if st.button("删除该学生所有记录"):
            delete_log(selected)
            st.success(f"已删除 {selected} 的记录")
            st.rerun()

    if st.button("退出后台"):
        st.session_state.admin_authed = False
        st.session_state.page = "main"
        st.rerun()

# ================== 主界面 ==================
def main_page():
    if "student" not in st.session_state or not st.session_state.student:
        with st.container():
            st.markdown("<h2 style='text-align: center;'>🤖 AI故障导师</h2>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: center;'>请输入你的班级姓名开始实训</p>", unsafe_allow_html=True)
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                student_input = st.text_input("班级姓名", placeholder="例如：23电信师1黄永豪", key="login_input")
                if st.button("进入系统", use_container_width=True):
                    if student_input.strip():
                        st.session_state.student = student_input.strip()
                        st.session_state.log = load_log(st.session_state.student)
                        st.rerun()
                    else:
                        st.warning("姓名不能为空")
        st.stop()

    st.title("🤖 AI故障导师——PLC 梯形图诊断助手")
    st.markdown("**中职 PLC 实训辅助·职教前沿课题原型**")

    col_top1, col_top2 = st.columns([0.9, 0.1])
    with col_top2:
        if st.button("🔧", help="后台管理"):
            st.session_state.page = "admin"
            st.rerun()

    st.info(f"当前学生：{st.session_state.student}  |  历史记录条数：{len(st.session_state.log)}")

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("📥 输入你的梯形图（指令表）")
        default_code = "LD X0\nOR Y0\nANI X1\nOUT Y0\nLD X2\nOUT Y0\nEND"
        instruction_input = st.text_area("请粘贴 GX Developer 指令表程序", value=default_code, height=200)
        io_description = st.text_input("I/O 说明（可选）", placeholder="例如：X0-启动，X1-停止，X2-急停，Y0-电机")
        student_query = st.text_area("你有什么疑惑？", placeholder="例如：电机为什么无法自锁？", height=80)

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            btn_rule = st.button("🔍 规则快速检查")
        with col_btn2:
            btn_ai = st.button("🧠 AI 智能诊断")

    with col2:
        st.subheader("📋 诊断报告")
        output_area = st.empty()

        if btn_rule:
            with st.spinner("正在执行规则检查..."):
                warnings = rule_based_check(instruction_input)
                if not warnings:
                    result_msg = "✅ 未发现常见基础错误（规则检查）。"
                    output_area.success(result_msg)
                else:
                    result_msg = "⚠️ 发现以下问题：\n" + "\n".join([f"- {w}" for w in warnings])
                    output_area.warning(result_msg)
            if warnings:
                show_learning_resources(warnings)
            else:
                show_learning_resources(["通用"])
            record = {
                "program": instruction_input,
                "io_desc": io_description,
                "type": "规则检查",
                "result": result_msg
            }
            save_log(st.session_state.student, record)
            st.session_state.log = load_log(st.session_state.student)

        if btn_ai:
            if not student_query.strip():
                output_area.warning("请在上方输入你的疑问，再点击 AI 诊断。")
            else:
                with st.spinner("AI 导师正在分析你的程序，请稍候..."):
                    reply = ai_diagnose(instruction_input, student_query, io_description)
                    if not reply or reply.strip() == "":
                        reply = "AI 诊断未返回有效内容，请稍后重试。"
                    output_area.markdown(reply)
                warnings = rule_based_check(instruction_input)
                if warnings:
                    show_learning_resources(warnings)
                else:
                    show_learning_resources(["通用"])
                if "AI 调用失败" not in reply and reply.strip() != "AI 诊断未返回有效内容，请稍后重试。":
                    record = {
                        "program": instruction_input,
                        "io_desc": io_description,
                        "type": "AI诊断",
                        "result": reply
                    }
                    save_log(st.session_state.student, record)
                    st.session_state.log = load_log(st.session_state.student)
                else:
                    st.warning("AI 诊断未能生成有效结果，请稍后重试。")

    st.caption("广东技术师范大学 · 职业教育前沿课程设计 | AI+PLC 轻量化教学方案原型")

# ================== 页面路由 ==================
if "page" not in st.session_state:
    st.session_state.page = "main"

if st.session_state.page == "admin":
    admin_page()
elif st.session_state.page == "report":
    student = st.session_state.get("current_report_student")
    if student:
        log = load_log(student)
        generate_report(student, log)
    else:
        st.error("未选择学生，请返回后台重新选择。")
        if st.button("返回后台"):
            st.session_state.page = "admin"
            st.rerun()
else:
    main_page()