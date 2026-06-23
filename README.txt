test — how to run

1. Double-click run.bat. First time takes a minute to set up; after that it is fast.
   A browser tab opens automatically.

2. Step 1 - Reference: paste the path to the Reference folder. Press Enter.

3. Step 2 - Tested: paste a tested folder path, click "Add this tested folder".
   Repeat for every tested item.

4. Step 3 - Results: see PASS/FAIL and the accuracy for each tested item.
   Click "Export report" to save test_report.html + summary.csv.

5. Step 4 - Strength overlay: visual check. Drag to zoom; render a sharp window if needed.

To close: close the browser tab and the black window.

------------------------------------------------------------
SETUP NOTES
- Double-click run.bat. It builds a local .venv on first run.
- It installs from the bundled wheelhouse folder first (no internet
  needed IF the machine's Python is 3.13). If those wheels do not match,
  it falls back to pip's normal index (needs pip access).
- Requires Python 3 (3.13 recommended for fully-offline install).
