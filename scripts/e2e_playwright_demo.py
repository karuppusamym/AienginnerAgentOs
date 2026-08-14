#!/usr/bin/env python3
"""
DataPilot End-to-End Playwright Demo Script
=============================================
This script performs a comprehensive E2E test of the DataPilot UI.
It logs in, performs workflows, takes screenshots, and records a video.

Usage:
    python scripts/e2e_playwright_demo.py
"""

from playwright.sync_api import sync_playwright, expect
import time
import os
from pathlib import Path

# Config
WEB_URL = "http://localhost:3001"
API_URL = "http://localhost:8000"
ADMIN_EMAIL = "admin@datapilot.local"
ADMIN_PASS = "ChangeMe123!"

SCREENSHOT_DIR = Path("docs/screenshots/workflows")
VIDEO_DIR = Path("docs/videos")

SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_DIR.mkdir(parents=True, exist_ok=True)

def wait_and_screenshot(page, name):
    page.wait_for_timeout(2000) # Give UI time to render and settle
    page.screenshot(path=str(SCREENSHOT_DIR / f"{name}.png"), full_page=True)
    assert (SCREENSHOT_DIR / f"{name}.png").exists(), f"File {name}.png was not created!"
    print(f"[Screenshot] Captured screenshot: {name}.png")

def run_demo():
    print("Starting Playwright E2E Demo...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            record_video_dir=str(VIDEO_DIR),
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()

        # Step 1: Login
        print("Step 1: Navigating to login...")
        page.goto(WEB_URL)
        page.fill('input[type="email"]', ADMIN_EMAIL)
        page.fill('input[type="password"]', ADMIN_PASS)
        wait_and_screenshot(page, "01_login_screen")
        page.click('button:has-text("Sign in")')
        page.wait_for_timeout(3000)
        print("✅ Login successful")

        # Step 2: File Upload / Ingestion
        print("Step 2: File Ingestion Page")
        page.goto(f"{WEB_URL}/files")
        wait_and_screenshot(page, "02_file_upload_page")

        # Step 3: Catalog Search
        print("Step 3: Catalog Search")
        page.goto(f"{WEB_URL}/catalog")
        wait_and_screenshot(page, "03_catalog_search")

        # Step 4: SQL Workspace
        print("Step 4: SQL Workspace")
        page.goto(f"{WEB_URL}/workspace")
        wait_and_screenshot(page, "04_sql_workspace")

        # Step 5: Agent Jobs
        print("Step 5: Agent Jobs")
        page.goto(f"{WEB_URL}/jobs")
        wait_and_screenshot(page, "05_agent_jobs")

        # Step 6: Approvals
        print("Step 6: Approvals")
        page.goto(f"{WEB_URL}/approvals")
        wait_and_screenshot(page, "06_approvals")

        # Step 7: Data Quality
        print("Step 7: Data Quality")
        page.goto(f"{WEB_URL}/quality")
        wait_and_screenshot(page, "07_data_quality")

        # Step 8: Pipelines
        print("Step 8: Pipelines")
        page.goto(f"{WEB_URL}/pipelines")
        wait_and_screenshot(page, "08_pipelines")

        # Step 9: Admin Security
        print("Step 9: Security Dashboard")
        page.goto(f"{WEB_URL}/admin/security")
        wait_and_screenshot(page, "09_security_dashboard")

        # Step 10: Admin Connectors
        print("Step 10: Connectors")
        page.goto(f"{WEB_URL}/admin/connectors")
        wait_and_screenshot(page, "10_connectors")
        
        # Step 11: Query Tools
        print("Step 11: Query Tools")
        page.goto(f"{WEB_URL}/admin/query-tools")
        wait_and_screenshot(page, "11_query_tools")

        # Close and save video
        context.close()
        browser.close()
        
        print(f"✅ Demo complete. Videos saved in {VIDEO_DIR}")

if __name__ == "__main__":
    run_demo()
