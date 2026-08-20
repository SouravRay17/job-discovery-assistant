"""
dashboard.py — Streamlit review dashboard for the Retrieval-First Job Discovery Assistant.

Displays:
  - End-to-end Pipeline Metrics (Scraped -> Normalized -> Indexed -> Retrieved -> Reranked -> AI Reviewed)
  - Transparent Score Breakdown (Semantic, BM25, Skill Match, Cross-Encoder, Gemini Review)
  - Recommendation Filters (APPLY, MAYBE, SKIP)
  - On-Demand Tailoring & LaTeX Typeset PDF Resumes
"""

import json
import os
import streamlit as st

from config import load_config, CV_PATH
from db import get_connection, init_db
from tailor import tailor_job, compile_pdf_resume
from retriever import load_candidate_profile

st.set_page_config(page_title="Job Discovery Assistant", page_icon="💼", layout="wide")


def load_data_from_db() -> tuple[list[dict], dict]:
    """Retrieve scored candidates joined with normalized job data from SQLite."""
    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT 
                c.id as score_entry_id, c.candidate_id, c.source, c.job_id,
                c.semantic_score, c.bm25_score, c.required_skill_score, c.preferred_skill_score,
                c.role_score, c.experience_score, c.hybrid_retrieval_score, c.reranker_score,
                c.mmr_selected, c.llm_score, c.recommendation, c.match_reason,
                c.strengths, c.skill_gaps, c.critical_gap, c.tailored_summary,
                c.cover_letter_draft, c.status as app_status, c.notified_email,
                j.company, j.title, j.location, j.remote, j.url,
                j.description_raw, j.search_text, j.required_skills, j.preferred_skills,
                j.role_family, j.domain, j.experience_min, j.experience_max, j.remote_type
            FROM candidate_job_scores c
            JOIN jobs j ON c.source = j.source AND c.job_id = j.id
            ORDER BY COALESCE(c.llm_score, 0) DESC, c.reranker_score DESC, c.hybrid_retrieval_score DESC
        """)
        scored_jobs = [dict(row) for row in cursor.fetchall()]

        # Summary counts
        total_raw = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        total_normalized = conn.execute("SELECT COUNT(*) FROM jobs WHERE normalized_at IS NOT NULL").fetchone()[0]
        total_indexed = conn.execute("SELECT COUNT(*) FROM jobs WHERE indexed_at IS NOT NULL").fetchone()[0]
        total_retrieved = conn.execute("SELECT COUNT(*) FROM candidate_job_scores").fetchone()[0]
        total_reranked = conn.execute("SELECT COUNT(*) FROM candidate_job_scores WHERE reranker_score IS NOT NULL").fetchone()[0]
        total_reviewed = conn.execute("SELECT COUNT(*) FROM candidate_job_scores WHERE llm_score IS NOT NULL").fetchone()[0]
        total_applied = conn.execute("SELECT COUNT(*) FROM candidate_job_scores WHERE status = 'applied'").fetchone()[0]
        total_rejected = conn.execute("SELECT COUNT(*) FROM candidate_job_scores WHERE status = 'rejected'").fetchone()[0]

        stats = {
            "total_raw": total_raw,
            "total_normalized": total_normalized,
            "total_indexed": total_indexed,
            "total_retrieved": total_retrieved,
            "total_reranked": total_reranked,
            "total_reviewed": total_reviewed,
            "total_applied": total_applied,
            "total_rejected": total_rejected,
        }
        return scored_jobs, stats
    finally:
        conn.close()


def main():
    init_db()
    try:
        cv_profile = load_candidate_profile()
        config = load_config()
    except Exception as e:
        st.error(f"Configuration or profile error: {e}")
        st.stop()

    st.title("💼 Job Discovery Assistant — Retrieval-First Engine")

    scored_jobs, stats = load_data_from_db()

    # Metrics Funnel Bar
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Scraped Jobs", stats["total_raw"])
    c2.metric("Indexed", stats["total_indexed"])
    c3.metric("Retrieved", stats["total_retrieved"])
    c4.metric("Reranked", stats["total_reranked"])
    c5.metric("AI Reviewed", stats["total_reviewed"])
    c6.metric("Applied", stats["total_applied"])

    if not scored_jobs:
        st.info("No candidates retrieved yet. Run the pipeline (run_pipeline.py or retriever.py) to ingest and rank jobs.")
        return

    # Sidebar Filters
    st.sidebar.header("🎯 Filters")
    search_query = st.sidebar.text_input("🔍 Keyword Search", "")
    rec_filter = st.sidebar.selectbox("Recommendation", ["All", "APPLY", "MAYBE", "SKIP"])
    status_filter = st.sidebar.selectbox("Status", ["All", "ai_reviewed", "reranked", "retrieved", "applied", "rejected"])
    min_score = st.sidebar.slider("Min Match Score", 0, 100, 0)
    sources = ["All"] + sorted(list({j["source"].split(":")[0] for j in scored_jobs}))
    source_filter = st.sidebar.selectbox("Source", sources)
    mmr_only = st.sidebar.checkbox("Show MMR Diversified (Top Picks) Only", value=False)

    # Filter Logic
    filtered = scored_jobs
    if search_query:
        q = search_query.lower()
        filtered = [
            j for j in filtered
            if q in j["title"].lower() or q in j["company"].lower()
            or q in (j["role_family"] or "").lower() or q in (j["domain"] or "").lower()
            or q in (j["required_skills"] or "").lower()
        ]
    if rec_filter != "All":
        filtered = [j for j in filtered if (j["recommendation"] or "").upper() == rec_filter]
    if status_filter != "All":
        filtered = [j for j in filtered if j["app_status"] == status_filter]
    if source_filter != "All":
        filtered = [j for j in filtered if j["source"].startswith(source_filter)]
    if min_score > 0:
        filtered = [j for j in filtered if (j["llm_score"] or int((j["reranker_score"] or 0) * 100)) >= min_score]
    if mmr_only:
        filtered = [j for j in filtered if j.get("mmr_selected") == 1]

    if not filtered:
        st.warning("No jobs match the selected filter criteria.")
        return

    st.subheader(f"Curated Matches ({len(filtered)})")

    # Format Job Selector
    def format_job_option(item):
        score_display = item["llm_score"] if item["llm_score"] is not None else f"Rerank:{int((item['reranker_score'] or 0)*100)}"
        rec_display = f"[{item['recommendation']}] " if item.get("recommendation") else ""
        return f"{rec_display}[{score_display}/100] {item['title']} at {item['company']} ({item['location']})"

    selected_idx = st.selectbox(
        "Select job to inspect:",
        range(len(filtered)),
        format_func=lambda x: format_job_option(filtered[x])
    )
    job = filtered[selected_idx]

    # Main Card
    with st.container(border=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            st.header(job["title"])
            st.subheader(f"🏢 {job['company']} &nbsp;|&nbsp; 📍 {job['location']} ({job['remote_type']})")
            st.caption(f"Role Family: **{job['role_family']}** &nbsp;|&nbsp; Domain: **{job['domain']}** &nbsp;|&nbsp; Source: `{job['source']}`")
        with col2:
            display_score = int((job["final_composite_score"] or (job["llm_score"] / 100.0 if job["llm_score"] else (job["reranker_score"] or 0))) * 100)
            st.metric("Blended Match Score", f"{display_score}/100")
            rec_val = job.get("recommendation") or "PENDING"
            badge_color = "green" if rec_val == "APPLY" else ("orange" if rec_val == "MAYBE" else "gray")
            st.markdown(f"Recommendation: **:{badge_color}[{rec_val}]**")

        # Ground Truth Rating / Feedback Loop
        st.markdown("##### 🏷️ Label Relevance Ground Truth (Feedback Loop)")
        f1, f2, f3, f4, f5, f6 = st.columns([1, 1, 1, 1, 1, 2])
        current_rating = job.get("user_rating")

        def save_user_rating(rating: int, feedback_label: str):
            conn = get_connection()
            try:
                from datetime import datetime, timezone
                conn.execute(
                    "UPDATE candidate_job_scores SET user_rating = ?, user_feedback = ?, labeled_at = ? WHERE source = ? AND job_id = ?",
                    (rating, feedback_label, datetime.now(timezone.utc).isoformat(), job["source"], job["job_id"])
                )
                conn.commit()
            finally:
                conn.close()

        with f1:
            if st.button("⭐ 1 Irrelevant", use_container_width=True, type="primary" if current_rating == 1 else "secondary"):
                save_user_rating(1, "irrelevant")
                st.toast("Saved: 1★ Irrelevant")
                st.rerun()
        with f2:
            if st.button("⭐⭐ 2 Weak", use_container_width=True, type="primary" if current_rating == 2 else "secondary"):
                save_user_rating(2, "weak")
                st.toast("Saved: 2★ Weak")
                st.rerun()
        with f3:
            if st.button("⭐⭐⭐ 3 Reasonable", use_container_width=True, type="primary" if current_rating == 3 else "secondary"):
                save_user_rating(3, "reasonable")
                st.toast("Saved: 3★ Reasonable")
                st.rerun()
        with f4:
            if st.button("⭐⭐⭐⭐ 4 Strong", use_container_width=True, type="primary" if current_rating == 4 else "secondary"):
                save_user_rating(4, "strong")
                st.toast("Saved: 4★ Strong Target")
                st.rerun()
        with f5:
            if st.button("⭐⭐⭐⭐⭐ 5 Gold", use_container_width=True, type="primary" if current_rating == 5 else "secondary"):
                save_user_rating(5, "excellent")
                st.toast("Saved: 5★ Gold Opportunity")
                st.rerun()
        with f6:
            if current_rating:
                st.caption(f"Current ground truth: **{current_rating}★ ({job.get('user_feedback', '')})**")
            else:
                st.caption("Not yet labeled for evaluation benchmark.")

        # Action Buttons
        a1, a2, a3, a4 = st.columns(4)
        with a1:
            if job["url"]:
                st.link_button("🔗 Apply on Company Site", job["url"], use_container_width=True)
            else:
                st.button("🔗 No Direct URL", disabled=True, use_container_width=True)
        with a2:
            if st.button("✔️ Mark Applied", use_container_width=True):
                conn = get_connection()
                try:
                    conn.execute("UPDATE candidate_job_scores SET status = 'applied' WHERE source = ? AND job_id = ?", (job["source"], job["job_id"]))
                    conn.commit()
                finally:
                    conn.close()
                st.toast("Marked as Applied!")
                st.rerun()
        with a3:
            if st.button("❌ Reject", use_container_width=True):
                conn = get_connection()
                try:
                    conn.execute("UPDATE candidate_job_scores SET status = 'rejected' WHERE source = ? AND job_id = ?", (job["source"], job["job_id"]))
                    conn.commit()
                finally:
                    conn.close()
                st.toast("Job marked as Rejected.")
                st.rerun()
        with a4:
            if st.button("⭐ Save to Review", use_container_width=True):
                conn = get_connection()
                try:
                    conn.execute("UPDATE candidate_job_scores SET status = 'ai_reviewed' WHERE source = ? AND job_id = ?", (job["source"], job["job_id"]))
                    conn.commit()
                finally:
                    conn.close()
                st.toast("Saved to Review.")
                st.rerun()

        # Tabs
        tab1, tab2, tab3 = st.tabs(["📊 Evaluation & Alignment Details", "📝 Tailored Application Materials", "📄 Structured Metadata & Raw JD"])

        # Tab 1: Score Breakdown
        with tab1:
            if job["match_reason"]:
                st.info(f"**AI Strategic Reasoning:** {job['match_reason']}")

            if job.get("critical_gap"):
                st.error("⚠️ Critical deal-breaker gap detected by strategic review.")

            s1, s2 = st.columns(2)
            with s1:
                st.markdown("#### ✅ Matching Strengths")
                strengths = json.loads(job["strengths"] or "[]")
                if strengths:
                    for s in strengths:
                        st.markdown(f"- {s}")
                else:
                    st.caption("No strengths evaluated yet.")
            with s2:
                st.markdown("#### ⚠️ Unmet Requirements / Skill Gaps")
                gaps = json.loads(job["skill_gaps"] or "[]")
                if gaps:
                    for g in gaps:
                        st.markdown(f"- {g}")
                else:
                    st.caption("No critical gaps identified.")

            st.divider()
            st.markdown("#### 🔬 Transparent Multi-Stage Alignment Breakdown")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Dense Semantic Similarity", f"{int((job['semantic_score'] or 0)*100)}%")
            m2.metric("BM25 Keyword Alignment", f"{int((job['bm25_score'] or 0)*100)}%")
            m3.metric("Required Skills Match", f"{int((job['required_skill_score'] or 0)*100)}%")
            m4.metric("Preferred Skills Match", f"{int((job['preferred_skill_score'] or 0)*100)}%")

            m5, m6, m7, m8 = st.columns(4)
            m5.metric("Role Family Match", f"{int((job['role_score'] or 0)*100)}%")
            m6.metric("Hybrid Retrieval Composite", f"{int((job['hybrid_retrieval_score'] or 0)*100)}%")
            m7.metric("Cross-Encoder Reranker", f"{int((job['reranker_score'] or 0)*100)}%")
            m8.metric("Blended Final Score (25/35/40)", f"{int((job['final_composite_score'] or 0)*100)}%")

        # Tab 2: Tailored Materials
        with tab2:
            summary_val = job["tailored_summary"] or ""
            cover_val = job["cover_letter_draft"] or ""

            if not summary_val and not cover_val:
                if st.button("🪄 Generate Tailored Summary & Cover Letter"):
                    with st.spinner("Generating tailored application with Gemini AI..."):
                        if tailor_job(job["source"], job["job_id"], config, cv_profile):
                            st.success("Application materials created!")
                            st.rerun()
            else:
                edited_summary = st.text_area("ATS Tailored Professional Summary", summary_val, height=120)
                edited_cover = st.text_area("Tailored Cover Letter Draft", cover_val, height=250)

                b1, b2 = st.columns(2)
                with b1:
                    if st.button("💾 Save Draft Edits", use_container_width=True):
                        conn = get_connection()
                        try:
                            conn.execute(
                                "UPDATE candidate_job_scores SET tailored_summary = ?, cover_letter_draft = ? WHERE source = ? AND job_id = ?",
                                (edited_summary, edited_cover, job["source"], job["job_id"])
                            )
                            conn.commit()
                        finally:
                            conn.close()
                        st.success("Draft saved successfully!")
                        st.rerun()
                with b2:
                    if st.button("📥 Compile LaTeX PDF Resume", use_container_width=True):
                        conn = get_connection()
                        try:
                            conn.execute(
                                "UPDATE candidate_job_scores SET tailored_summary = ?, cover_letter_draft = ? WHERE source = ? AND job_id = ?",
                                (edited_summary, edited_cover, job["source"], job["job_id"])
                            )
                            conn.commit()
                        finally:
                            conn.close()
                        pdf = compile_pdf_resume(job["source"], job["job_id"])
                        if pdf:
                            st.session_state[f"pdf_{job['job_id']}"] = pdf
                            st.success(f"Compiled PDF: {os.path.basename(pdf)}")
                            st.rerun()

                pdf_key = f"pdf_{job['job_id']}"
                if pdf_key in st.session_state and os.path.exists(st.session_state[pdf_key]):
                    with open(st.session_state[pdf_key], "rb") as f:
                        st.download_button(
                            "💾 Download Compiled PDF Resume",
                            f.read(),
                            file_name=os.path.basename(st.session_state[pdf_key]),
                            mime="application/pdf",
                            use_container_width=True
                        )

        # Tab 3: Structured Metadata & Raw JD
        with tab3:
            st.markdown("#### Structured Search Representation")
            st.code(job["search_text"] or "No search document generated.", language="text")

            st.markdown("#### Required Skills Extracted")
            req_list = json.loads(job["required_skills"] or "[]")
            if req_list:
                st.write(", ".join(f"`{s}`" for s in req_list))
            else:
                st.write("None extracted.")

            st.markdown("#### Raw Job Description")
            st.text(job["description_raw"] or "No raw description cached.")


if __name__ == "__main__":
    main()
