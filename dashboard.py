"""
dashboard.py — Streamlit review dashboard for the Job Discovery Assistant.

Provides filtering, sorting, score visualization, full description inspection,
on-demand tailoring, and manual status updates.
"""

import os
import json
import sqlite3
import streamlit as st

from db import get_connection
from tailor import tailor_job
from scorer import validate_environment

# ---------------------------------------------------------------------------
# Page Settings & CSS Styling
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Job Discovery Assistant",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom dark-theme inspired premium CSS
st.markdown("""
<style>
    /* Global styles */
    .reportview-container {
        background-color: #0e1117;
    }
    
    /* Score Badges */
    .score-badge-high {
        background-color: #2e7d32;
        color: white;
        padding: 4px 10px;
        border-radius: 12px;
        font-weight: bold;
        font-size: 14px;
        display: inline-block;
    }
    .score-badge-medium {
        background-color: #ef6c00;
        color: white;
        padding: 4px 10px;
        border-radius: 12px;
        font-weight: bold;
        font-size: 14px;
        display: inline-block;
    }
    .score-badge-low {
        background-color: #c62828;
        color: white;
        padding: 4px 10px;
        border-radius: 12px;
        font-weight: bold;
        font-size: 14px;
        display: inline-block;
    }
    
    /* Job Card Styling */
    .job-card {
        background-color: #1e293b;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 18px;
        margin-bottom: 12px;
        box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
    }
    
    .job-card:hover {
        border-color: #475569;
        transform: translateY(-2px);
        transition: all 0.2s ease-in-out;
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# DB Helpers
# ---------------------------------------------------------------------------

def load_jobs_from_db() -> list[dict]:
    """Retrieve all jobs from the SQLite database."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT source, id, company, title, location, remote, url, "
            "description_raw, date_posted, date_fetched, score, reasoning, "
            "missing_requirements, matching_strengths, tailored_summary, "
            "cover_letter_draft, status FROM jobs"
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def update_job_status_in_db(source: str, job_id: str, new_status: str):
    """Update status of a job in the database."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE jobs SET status = ? WHERE source = ? AND id = ?",
            (new_status, source, job_id)
        )
        conn.commit()
    finally:
        conn.close()


def update_tailored_materials_in_db(source: str, job_id: str, summary: str, cover_letter: str):
    """Save manual updates to resume summary and cover letter."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE jobs SET tailored_summary = ?, cover_letter_draft = ? WHERE source = ? AND id = ?",
            (summary, cover_letter, source, job_id)
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Dashboard App
# ---------------------------------------------------------------------------

def main():
    # Load and validate configs/CV
    try:
        config, cv_profile = validate_environment()
    except SystemExit:
        st.error("Error: Configuration files missing. Run parser and scrapers first.")
        st.stop()

    st.title("💼 Job Discovery & Application Assistant")
    st.markdown("Automate your job research, score match alignment, and draft applications locally.")

    # 1. Load Data
    jobs = load_jobs_from_db()

    if not jobs:
        st.info("No jobs found in the database. Run your scrapers first to fetch jobs!")
        return

    # Metrics calculation
    total_jobs = len(jobs)
    unscored = len([j for j in jobs if j["score"] is None])
    to_review = len([j for j in jobs if j["status"] == "to_review"])
    applied = len([j for j in jobs if j["status"] == "applied"])
    rejected = len([j for j in jobs if j["status"] == "rejected"])

    # 2. Sidebar Filters
    st.sidebar.header("Filter & Search")

    search_query = st.sidebar.text_input("🔍 Search jobs, company, text", "")
    
    status_options = ["All", "to_review", "new", "applied", "rejected"]
    status_filter = st.sidebar.selectbox("📋 Status Filter", status_options, index=0)

    score_threshold = st.sidebar.slider("📊 Minimum Match Score", 0, 100, int(config.get("scoring", {}).get("threshold", 60)))

    unique_sources = sorted(list(set(j["source"].split(":")[0] for j in jobs)))
    source_options = ["All"] + unique_sources
    source_filter = st.sidebar.selectbox("🌐 API Source Filter", source_options, index=0)

    # 3. Apply Filters
    filtered_jobs = jobs

    if search_query:
        q = search_query.lower()
        filtered_jobs = [
            j for j in filtered_jobs
            if q in j["title"].lower() or q in j["company"].lower() or (j["description_raw"] and q in j["description_raw"].lower())
        ]

    if status_filter != "All":
        filtered_jobs = [j for j in filtered_jobs if j["status"] == status_filter]

    if source_filter != "All":
        filtered_jobs = [j for j in filtered_jobs if j["source"].startswith(source_filter)]

    # Filter by score (unscored jobs are kept if we are not filtering aggressively, or based on threshold)
    filtered_jobs = [
        j for j in filtered_jobs
        if j["score"] is None or j["score"] >= score_threshold
    ]

    # Sort: scored first (high to low), then unscored
    filtered_jobs.sort(key=lambda x: (x["score"] is None, -(x["score"] or 0)))

    # Main Metrics Grid
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Listings", total_jobs)
    col2.metric("Unscored Jobs", unscored)
    col3.metric("To Review (Fits)", to_review)
    col4.metric("Applied", applied)
    col5.metric("Rejected", rejected)

    st.markdown("---")

    # 4. Job Listings Display
    if not filtered_jobs:
        st.warning("No listings match the current filters. Adjust your filters in the sidebar.")
        return

    st.subheader(f"Matching Postings ({len(filtered_jobs)})")

    # Select box to choose the active job to inspect
    job_options = [
        f"[{j['score'] if j['score'] is not None else 'Unscored'}] {j['title']} at {j['company']} ({j['location']})"
        for j in filtered_jobs
    ]
    
    selected_index = st.selectbox("👉 Choose a job to inspect and edit applications:", range(len(filtered_jobs)), format_func=lambda x: job_options[x])
    selected_job = filtered_jobs[selected_index]

    # Show Detail View
    st.markdown("---")
    
    # Header columns
    head_col1, head_col2 = st.columns([3, 1])
    with head_col1:
        st.header(f"{selected_job['title']}")
        st.subheader(f"🏢 {selected_job['company']} — 📍 {selected_job['location']}")
    with head_col2:
        score = selected_job["score"]
        if score is None:
            st.markdown("### `Score: Unscored`")
        elif score >= 80:
            st.markdown(f"### <span class='score-badge-high'>Match Score: {score}/100</span>", unsafe_allow_html=True)
        elif score >= 60:
            st.markdown(f"### <span class='score-badge-medium'>Match Score: {score}/100</span>", unsafe_allow_html=True)
        else:
            st.markdown(f"### <span class='score-badge-low'>Match Score: {score}/100</span>", unsafe_allow_html=True)

        st.write(f"**Source:** `{selected_job['source']}`")
        st.write(f"**Status:** `{selected_job['status']}`")

    # Actions panel
    act_col1, act_col2, act_col3, act_col4 = st.columns(4)
    with act_col1:
        st.link_button("🔗 Open Original Posting", selected_job["url"], use_container_width=True)
    with act_col2:
        if st.button("✔️ Mark as Applied", use_container_width=True):
            update_job_status_in_db(selected_job["source"], selected_job["id"], "applied")
            st.toast("Marked as Applied!")
            st.rerun()
    with act_col3:
        if st.button("❌ Reject Job", use_container_width=True):
            update_job_status_in_db(selected_job["source"], selected_job["id"], "rejected")
            st.toast("Job Rejected.")
            st.rerun()
    with act_col4:
        if st.button("⭐ Keep / Review Later", use_container_width=True):
            update_job_status_in_db(selected_job["source"], selected_job["id"], "to_review")
            st.toast("Moved to Review list!")
            st.rerun()

    # Tabs for info
    tab1, tab2, tab3 = st.tabs(["📊 Evaluation Details", "📝 Tailored Application Material", "📄 Full Job Description"])

    with tab1:
        if selected_job["score"] is None:
            st.warning("This job has not been evaluated yet. Run scorer.py or complete pipeline execution.")
        else:
            st.markdown("#### 💡 Evaluation Reasoning")
            st.info(selected_job["reasoning"])

            # Strengths vs Missing requirements columns
            str_col1, str_col2 = st.columns(2)
            with str_col1:
                st.markdown("#### ✅ Matching Strengths")
                try:
                    strengths = json.loads(selected_job["matching_strengths"] or "[]")
                    for s in strengths:
                        st.markdown(f"- {s}")
                except Exception:
                    st.write(selected_job["matching_strengths"])
            with str_col2:
                st.markdown("#### ❌ Missing Requirements")
                try:
                    missing = json.loads(selected_job["missing_requirements"] or "[]")
                    if not missing:
                        st.write("None identified! Excellent candidate match.")
                    for m in missing:
                        st.markdown(f"- {m}")
                except Exception:
                    st.write(selected_job["missing_requirements"])

    with tab2:
        st.markdown("#### ✨ AI Tailored Application Materials")
        st.caption("Drafts are derived strictly from your CV profile without fabrication. You can edit and save changes below.")

        summary_val = selected_job["tailored_summary"] or ""
        cover_val = selected_job["cover_letter_draft"] or ""

        # Trigger button if no material exists yet
        if not summary_val and not cover_val:
            st.warning("No tailored materials generated for this listing yet.")
            if st.button("🪄 Generate Tailored Summary & Cover Letter"):
                with st.spinner("Generating materials via local Ollama..."):
                    success = tailor_job(selected_job["source"], selected_job["id"], config, cv_profile)
                    if success:
                        st.success("Application materials created!")
                        st.rerun()
                    else:
                        st.error("Failed to generate application materials. Check Ollama is running.")
        else:
            # Show and edit forms
            edited_summary = st.text_area("✍️ Tailored Resume Summary (3-4 sentences)", summary_val, height=120)
            edited_cover_letter = st.text_area("✉️ Short Cover Letter Draft", cover_val, height=350)

            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                if st.button("💾 Save Changes", use_container_width=True):
                    update_tailored_materials_in_db(selected_job["source"], selected_job["id"], edited_summary, edited_cover_letter)
                    st.success("Draft saved successfully!")
                    st.rerun()
            with btn_col2:
                if st.button("📥 Export Tailored Resume as PDF", use_container_width=True):
                    # Save changes first to ensure the PDF has the latest edited summary
                    update_tailored_materials_in_db(selected_job["source"], selected_job["id"], edited_summary, edited_cover_letter)
                    with st.spinner("Compiling and converting tailored resume to PDF..."):
                        from tailor import compile_pdf_resume
                        pdf_path = compile_pdf_resume(selected_job["source"], selected_job["id"])
                        if pdf_path:
                            st.session_state[f"pdf_path_{selected_job['id']}"] = pdf_path
                            st.success("Resume exported successfully!")
                            st.rerun()
                        else:
                            st.error("Failed to generate PDF. Make sure RenderCV is configured.")

            # Persistent download button if pdf is compiled
            pdf_state_key = f"pdf_path_{selected_job['id']}"
            if pdf_state_key in st.session_state and os.path.exists(st.session_state[pdf_state_key]):
                pdf_path = st.session_state[pdf_state_key]
                st.info(f"File saved to: `{pdf_path}`")
                with open(pdf_path, "rb") as f:
                    pdf_data = f.read()
                st.download_button(
                    label="💾 Click here to download PDF",
                    data=pdf_data,
                    file_name=os.path.basename(pdf_path),
                    mime="application/pdf",
                    use_container_width=True
                )

    with tab3:
        st.markdown("#### 📄 Original Raw Job Description")
        desc = selected_job["description_raw"]
        if desc:
            st.text(desc)
        else:
            st.info("Description details not populated. Lazy loading Greenhouse metadata. Description is fetched when scoring or tailoring.")


if __name__ == "__main__":
    main()
