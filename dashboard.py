"""
dashboard.py — Streamlit review dashboard for the Job Discovery Assistant.

Provides filtering, sorting, score inspection, on-demand tailoring, and status updates.
"""

import json
import os
import streamlit as st

from config import load_config
from db import get_connection
from tailor import tailor_job, compile_pdf_resume
from scorer import validate_environment

st.set_page_config(page_title="Job Discovery Assistant", page_icon="💼", layout="wide")


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


def main():
    try:
        config, cv_profile = validate_environment()
    except SystemExit:
        st.error("Configuration files missing. Run parser and scrapers first.")
        st.stop()

    st.title("💼 Job Discovery & Application Assistant")

    jobs = load_jobs_from_db()
    if not jobs:
        st.info("No jobs found in database. Run scrapers first.")
        return

    # Metrics Grid
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Listings", len(jobs))
    c2.metric("Unscored Jobs", sum(1 for j in jobs if j["score"] is None))
    c3.metric("To Review", sum(1 for j in jobs if j["status"] == "to_review"))
    c4.metric("Applied", sum(1 for j in jobs if j["status"] == "applied"))
    c5.metric("Rejected", sum(1 for j in jobs if j["status"] == "rejected"))

    # Sidebar Filters
    st.sidebar.header("Filters")
    search_query = st.sidebar.text_input("🔍 Search", "")
    status_filter = st.sidebar.selectbox("Status", ["All", "to_review", "new", "applied", "rejected"])
    score_threshold = st.sidebar.slider("Min Score", 0, 100, int(config.get("scoring", {}).get("threshold", 60)))
    sources = ["All"] + sorted(list({j["source"].split(":")[0] for j in jobs}))
    source_filter = st.sidebar.selectbox("Source", sources)

    # Apply Filters
    filtered_jobs = jobs
    if search_query:
        q = search_query.lower()
        filtered_jobs = [j for j in filtered_jobs if q in j["title"].lower() or q in j["company"].lower() or (j["description_raw"] and q in j["description_raw"].lower())]
    if status_filter != "All":
        filtered_jobs = [j for j in filtered_jobs if j["status"] == status_filter]
    if source_filter != "All":
        filtered_jobs = [j for j in filtered_jobs if j["source"].startswith(source_filter)]
    filtered_jobs = [j for j in filtered_jobs if j["score"] is None or j["score"] >= score_threshold]
    filtered_jobs.sort(key=lambda x: (x["score"] is None, -(x["score"] or 0)))

    if not filtered_jobs:
        st.warning("No listings match current filters.")
        return

    st.subheader(f"Matching Postings ({len(filtered_jobs)})")
    job_options = [f"[{j['score'] or 'Unscored'}] {j['title']} at {j['company']} ({j['location']})" for j in filtered_jobs]
    selected_idx = st.selectbox("Select job to inspect:", range(len(filtered_jobs)), format_func=lambda x: job_options[x])
    job = filtered_jobs[selected_idx]

    with st.container(border=True):
        col1, col2 = st.columns([3, 1])
        with col1:
            st.header(job["title"])
            st.subheader(f"🏢 {job['company']} — 📍 {job['location']}")
        with col2:
            st.metric("Match Score", f"{job['score']}/100" if job['score'] is not None else "Unscored")
            st.caption(f"Source: `{job['source']}` | Status: `{job['status']}`")

        # Action Buttons
        a1, a2, a3, a4 = st.columns(4)
        with a1:
            st.link_button("🔗 Original Posting", job["url"], use_container_width=True)
        with a2:
            if st.button("✔️ Mark Applied", use_container_width=True):
                conn = get_connection()
                try:
                    conn.execute("UPDATE jobs SET status = 'applied' WHERE source = ? AND id = ?", (job["source"], job["id"]))
                    conn.commit()
                finally:
                    conn.close()
                st.toast("Marked as Applied!")
                st.rerun()
        with a3:
            if st.button("❌ Reject", use_container_width=True):
                conn = get_connection()
                try:
                    conn.execute("UPDATE jobs SET status = 'rejected' WHERE source = ? AND id = ?", (job["source"], job["id"]))
                    conn.commit()
                finally:
                    conn.close()
                st.toast("Job Rejected.")
                st.rerun()
        with a4:
            if st.button("⭐ Review Later", use_container_width=True):
                conn = get_connection()
                try:
                    conn.execute("UPDATE jobs SET status = 'to_review' WHERE source = ? AND id = ?", (job["source"], job["id"]))
                    conn.commit()
                finally:
                    conn.close()
                st.toast("Saved to Review.")
                st.rerun()

        # Tabs
        tab1, tab2, tab3 = st.tabs(["📊 Evaluation Details", "📝 Tailored Application Material", "📄 Job Description"])

        with tab1:
            if job["score"] is None:
                st.warning("Not yet evaluated. Run scorer.py.")
            else:
                st.info(job["reasoning"])
                s1, s2 = st.columns(2)
                with s1:
                    st.markdown("#### ✅ Strengths")
                    for s in json.loads(job["matching_strengths"] or "[]"):
                        st.markdown(f"- {s}")
                with s2:
                    st.markdown("#### ❌ Gaps")
                    for m in json.loads(job["missing_requirements"] or "[]"):
                        st.markdown(f"- {m}")

        with tab2:
            summary_val = job["tailored_summary"] or ""
            cover_val = job["cover_letter_draft"] or ""

            if not summary_val and not cover_val:
                if st.button("🪄 Generate Tailored Materials"):
                    with st.spinner("Generating with LLM..."):
                        if tailor_job(job["source"], job["id"], config, cv_profile):
                            st.success("Created!")
                            st.rerun()
            else:
                edited_summary = st.text_area("Resume Summary", summary_val, height=100)
                edited_cover = st.text_area("Cover Letter Draft", cover_val, height=250)

                b1, b2 = st.columns(2)
                with b1:
                    if st.button("💾 Save Draft", use_container_width=True):
                        conn = get_connection()
                        try:
                            conn.execute(
                                "UPDATE jobs SET tailored_summary = ?, cover_letter_draft = ? WHERE source = ? AND id = ?",
                                (edited_summary, edited_cover, job["source"], job["id"])
                            )
                            conn.commit()
                        finally:
                            conn.close()
                        st.success("Saved!")
                        st.rerun()
                with b2:
                    if st.button("📥 Export PDF Resume", use_container_width=True):
                        conn = get_connection()
                        try:
                            conn.execute(
                                "UPDATE jobs SET tailored_summary = ?, cover_letter_draft = ? WHERE source = ? AND id = ?",
                                (edited_summary, edited_cover, job["source"], job["id"])
                            )
                            conn.commit()
                        finally:
                            conn.close()
                        pdf = compile_pdf_resume(job["source"], job["id"])
                        if pdf:
                            st.session_state[f"pdf_{job['id']}"] = pdf
                            st.success(f"Compiled: {os.path.basename(pdf)}")
                            st.rerun()

                pdf_key = f"pdf_{job['id']}"
                if pdf_key in st.session_state and os.path.exists(st.session_state[pdf_key]):
                    with open(st.session_state[pdf_key], "rb") as f:
                        st.download_button("💾 Download PDF", f.read(), file_name=os.path.basename(st.session_state[pdf_key]), mime="application/pdf", use_container_width=True)

        with tab3:
            st.text(job["description_raw"] or "No description cached.")


if __name__ == "__main__":
    main()
