"""
test_remediation_suite.py — Comprehensive unit and integration verification
for P0/P1 audit remediation in Job Discovery Assistant.
"""

import os
import sys
import unittest
import pypdf

from db import compute_job_fingerprint
from retriever import check_hard_filters, compute_skill_overlap, compute_experience_score
from tailor import validate_factual_provenance, verify_pdf_ats_extractability


class TestAuditRemediation(unittest.TestCase):

    def test_fingerprint_deduplication(self):
        """Cross-source duplicate jobs must yield identical fingerprints."""
        fp1 = compute_job_fingerprint("Databricks", "Senior Data Engineer", "Bengaluru, India")
        fp2 = compute_job_fingerprint("databricks", "senior data engineer", "bengaluru")
        # Notice: c and t are identical, location in both is bengaluru
        self.assertEqual(fp1, fp2)

        # Remote vs non-remote distinction
        fp_remote = compute_job_fingerprint("Databricks", "Senior Data Engineer", "Remote - India")
        fp_remote2 = compute_job_fingerprint("Databricks", "Senior Data Engineer", "Global Remote")
        self.assertEqual(fp_remote, fp_remote2)

    def test_empty_skill_overlap_zero_score(self):
        """Empty job skills must return 0.0, not 0.8 fallback."""
        score = compute_skill_overlap({"python", "sql", "snowflake"}, [])
        self.assertEqual(score, 0.0)

        # Non-empty skills test
        score_matched = compute_skill_overlap({"python", "sql", "snowflake"}, ["Python", "AWS"])
        self.assertEqual(score_matched, 0.5)

    def test_experience_ceiling_soft_penalty(self):
        """Experience requirement of 5-7 years must pass hard filter; >7 years rejected."""
        profile = {"experience_years": 3, "preferred_locations": ["remote", "india"], "excluded_roles": []}

        # 5.5 years requirement: must PASS hard filter
        job_mid = {"title": "Data Engineer", "location": "Bengaluru", "experience_min": 5.5, "remote": False}
        passed, reason = check_hard_filters(job_mid, profile)
        self.assertTrue(passed, f"Should pass 5.5 yrs requirement, got: {reason}")

        # Compute experience score: should apply soft penalty, not 0.0
        exp_score = compute_experience_score(5.5, None, candidate_exp=3.0)
        self.assertGreater(exp_score, 0.3)
        self.assertLess(exp_score, 1.0)

        # 8 years requirement: must be REJECTED by hard filter
        job_senior = {"title": "Staff Data Engineer", "location": "Bengaluru", "experience_min": 8.0, "remote": False}
        passed, reason = check_hard_filters(job_senior, profile)
        self.assertFalse(passed)
        self.assertIn("exceeds 0-7 yr ceiling", reason)

    def test_factual_provenance_validation(self):
        """Factual provenance must catch ungrounded claims and allow grounded claims."""
        cv_profile = {"name": "Sourav Ray", "experience_years": 3}

        # 1. Grounded summary: should PASS
        grounded = (
            "Data scientist with 3 years of experience optimizing Snowflake, AWS and GCP pipelines. "
            "Led autonomous LLM agent development achieving 65% Snowflake compute reduction and 60% faster incident response."
        )
        valid, reason = validate_factual_provenance(grounded, cv_profile)
        self.assertTrue(valid, f"Expected valid, got: {reason}")

        # 2. Fabricated experience years: should FAIL
        fabricated_exp = "Data Engineer with 8+ years of production experience leading petabyte pipelines."
        valid, reason = validate_factual_provenance(fabricated_exp, cv_profile)
        self.assertFalse(valid)
        self.assertIn("Fabricated experience claim", reason)

        # 3. Inflated metrics: should FAIL
        inflated_metric = "Reduced Snowflake compute cost by 99% across 60 DBT models."
        valid, reason = validate_factual_provenance(inflated_metric, cv_profile)
        self.assertFalse(valid)
        self.assertIn("Fabricated/inflated metric", reason)

        # 4. Disallowed ungrounded technology: should FAIL
        disallowed_tech = "Implemented high-performance Rust microservices and Solidity smart contracts."
        valid, reason = validate_factual_provenance(disallowed_tech, cv_profile)
        self.assertFalse(valid)
        self.assertIn("Ungrounded technology claim", reason)

    def test_ats_pdf_validation(self):
        """Compiled PDFs must be ATS extractable and within 2 pages."""
        sample_pdf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports", "Sourav_Resume_Company_101.pdf")
        if os.path.exists(sample_pdf):
            valid, reason = verify_pdf_ats_extractability(sample_pdf, expected_name="Sourav Ray", expected_email="sroy.dgp2014@gmail.com")
            self.assertTrue(valid, f"ATS verification failed: {reason}")

    def test_upsert_jobs_rejects_empty_description_and_duplicates(self):
        """upsert_jobs must reject jobs with description < 50 chars and cross-source duplicates."""
        from scraper import upsert_jobs, normalize_job
        from db import get_connection

        empty_job = normalize_job(
            source="test_source",
            job_id="test_empty_1",
            company="Test Empty Co",
            title="Data Engineer",
            location="Bengaluru",
            remote=False,
            url="https://example.com/job1",
            description_raw="Too short",
            date_posted=None
        )
        inserted, skipped = upsert_jobs([empty_job])
        self.assertEqual(inserted, 0)
        self.assertEqual(skipped, 1)

        # Non-empty job
        long_desc = "This is a detailed job description requiring 3+ years of Python, SQL, Snowflake and Data Engineering pipelines for production analytics."
        valid_job_1 = normalize_job(
            source="greenhouse:testco",
            job_id="test_valid_1",
            company="Test Duplicate Co",
            title="Senior Data Engineer",
            location="Bengaluru",
            remote=False,
            url="https://example.com/job2",
            description_raw=long_desc,
            date_posted=None
        )
        # Duplicate job from different source (LinkedIn)
        valid_job_2 = normalize_job(
            source="linkedin",
            job_id="test_valid_2",
            company="test duplicate co",
            title="senior data engineer",
            location="bengaluru, india",
            remote=False,
            url="https://example.com/job3",
            description_raw=long_desc,
            date_posted=None
        )

        # Upsert both jobs: only the first should insert, second must be recognized as duplicate!
        inserted, skipped = upsert_jobs([valid_job_1, valid_job_2])
        self.assertEqual(inserted, 1)
        self.assertEqual(skipped, 1)

        # Clean up test rows
        conn = get_connection()
        try:
            conn.execute("DELETE FROM jobs WHERE company LIKE 'Test %'")
            conn.commit()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
