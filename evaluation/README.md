# CitePath Evaluation Guide

The browser procedures below use one course and can be run in sequence. Start the application, open [CitePath](http://127.0.0.1:5173/), and sign in with a test account. [Setup and launch](../README.md#2-setup-and-launch)

## 1. Initial schedule

1. Select **New course**. Enter `Python File Handling` as the course name. Set the start date to today, the deadline to three weeks from today, and the early completion offset to 0 days.
2. Under **Course materials**, upload the [Files chapter PDF](../data/py4e-chapter-07-files.pdf). Select **Save course**. When chapter analysis finishes, select **Set daily schedule**.
3. Set the daily study budget to **60 minutes** and select all seven days of the week. Select **Chapter order** and the **Fixed rules** planning method, then select **Save settings**.
4. Open **Course information** and select **Review daily plan**. Review the proposed schedule, select **Apply schedule**, and open **View calendar**.

**Pass criterion** The calendar shows tasks for the course with a total allocation of at most 60 minutes on each scheduled day.

## 2. Changed availability

1. On the course's **Plan** page, mark a **Read** task as **Done** and record its date.
2. Identify a date with unfinished work. Open **Course information → Edit → Days off**, select that date, choose **Add date**, and then select **Save settings**.
3. Select **Replan remaining tasks**, review the updated schedule, and select **Apply schedule**.

**Pass criterion** The unfinished tasks move off the new day off. The completed reading task retains its status and original date.

## 3. Insufficient study time

1. Leave some tasks unfinished. Open **Course information → Edit** and set the start date and deadline to today with an early completion offset of 0 days. Make sure today is an enabled study day and remove it from **Days off** if necessary.
2. Set the daily study budget to **1 minute**, save the settings, and select **Replan remaining tasks**.

**Pass criterion** The application reports insufficient study time and preserves the last published calendar. **Edit study settings** reopens the settings form so the user can change the constraints.

### Stale schedule preview

Restore the deadline to three weeks from today and remove the test day off. Set the daily budget to 65 minutes, save it, and open a preview. In a second tab, change the budget for the same course to 70 minutes and save it. Return to the first tab and select **Apply schedule**. The application should request a new preview and preserve the published calendar.

## Automated API verification

Start the application and run the following command from the repository root. Use a test database. The script creates an account and course, calls the configured model provider, and attempts to delete the course when the run ends.

```bash
backend/.venv/bin/python -B evaluation/verify_application.py --output evaluation/local-application.json
```

The acceptance suite uses `Fixed rules` for the scheduling checks. It also checks empty PDF rejection, practice and exam generation, and reading Q&A. In the reading case, it asks what happens to existing contents when a file is opened in write mode `w`. A correct answer states that the contents are cleared or truncated and cites page 9 of the sample PDF, which is printed page 87. [Scenario inputs](scenarios.json) · [Verification script](verify_application.py)

## Recorded acceptance results

The following results were recorded on 24 November 2026 for `CitePath-G41-20261124` using a test instance with MySQL 8.4.13, Milvus 3.0.3, and the live DeepSeek `deepseek-flash` model at temperature 0. The table describes automated API checks.

| Scenario | Observed outcome |
| --- | --- |
| Initial schedule | The 12-page sample generated 3 chapters and 6 tasks. The assigned study time was 60, 60, and 1 minute across three days. |
| Changed availability | Pending work moved off 24 November. The completed reading task kept its original date. |
| Insufficient study time | Remaining tasks required 101 minutes. The application reported a shortfall of 100 minutes and preserved the calendar. |
| Stale schedule preview | Applying the preview returned HTTP 409 and requested a new preview. The published calendar was preserved. |
| Chapter exam | The first attempt returned HTTP 400. The recorded rerun generated 8 questions. |

- The rerun passed all 13 checks, including the expected rejections of invalid input. [Rerun record](results/application.json)
- The initial run recorded the exam generation failure. It also flagged the full-PDF answer because the original assertion matched English wording. Manual review confirmed that the Chinese answer and citation were correct. The assertion was revised to accept both languages, and the rerun passed. [Initial run record](results/application-initial.json)
- The setup log records 175 passing backend tests and a successful frontend build. The evaluation used cached packages and model weights. First-time setup duration depends on download speed. [Setup and test log](results/setup-and-tests.log)

Additional manual checks include uploading the [Dictionaries chapter](../data/py4e-chapter-09-dictionaries.pdf) to test incremental chapter analysis and task preservation, creating a second course with the [Conditional Probability reading](../data/mit-18-05-reading-03-conditional-probability.pdf) to check that schedules remain course-specific, and submitting a chapter exam to check grading. These checks are outside the recorded API acceptance run.

## AI planner comparison

The rule-based scheduler and AI planner used the same synthetic chapter fixtures and study constraints. Each configuration ran once per scenario. The times are individual observations. In the weak chapter scenario, the live AI planner chose to inspect the chapter's learning report. Both methods stopped when there was insufficient study time.

| Scenario | Fixed rules | AI planner |
| --- | --- | --- |
| Sufficient study time | Saved, 34 ms | Saved, 5.879 s |
| Insufficient study time | Stopped, 24 ms | Stopped, 22 ms |
| Weak chapter | Saved, 32 ms | Inspected the learning report and saved, 4.711 s |
| Completed reading task | Preserved the completed task, 33 ms | Preserved the completed task, 4.451 s |

The task identity audit recorded a change in total task count in two cases because an inactive legacy review task was removed from the fixture. The reading and practice task IDs were preserved. [Comparison script](../backend/tools/evaluate_planner.py) · [Rerun commands](../README.md#3-evaluation) · [Live model trace](results/planner-live.json) · [Model double trace](results/planner-mock.json) · [Task identity audit](results/planner-fixture-identities.json)
