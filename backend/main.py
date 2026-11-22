import hashlib
import os
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Literal

from agent.exam import open_exam, save_exam_drafts, start_exam, submit_exam
from agent.practice import answer_practice, open_practice, start_practice
from agent.llm import ping
from agent.qa import answer_question, delete_question_tab, list_questions
from db.auth import authenticate, close_session, open_session, register_user, user_from_token
from db.courses import (
    create_course,
    update_course_settings,
    delete_course,
    delete_document_rows,
    get_course,
    list_courses,
    owns_document,
)
from db.exam_cases import delete_exam_case, list_exam_cases, save_exam_case
from db.plans import complete_task, ensure_plan_storage, get_plan
from db.practice import list_chapter_reports
from db.uploads import existing_upload, save_document
from ingest.pdf_reader import read_pdf
from vector.segments import delete_segments
from agent.chapterization import rebuild_chapters
from db.chapterization import (
    ChapterizationConflict,
    chapterization_options,
)
from db import scheduling
from agent.planner import run_planner

app = FastAPI(title="CitePath")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_BRIEF_LENGTH = 10000
COOKIE = "citepath_session"


class AuthBody(BaseModel):
    username: str = Field(max_length=32)
    password: str = Field(max_length=72)


class CourseBody(BaseModel):
    name: str = Field(max_length=255)
    student_brief: str = Field(max_length=MAX_BRIEF_LENGTH)


class CourseSettingsBody(BaseModel):
    startDate: str = Field(default="", max_length=10)
    name: str = Field(max_length=255)
    note: str = Field(default="", max_length=9000)
    deadline: str = Field(default="", max_length=10)
    earlyDays: int = Field(default=0, ge=0, le=365)
    events: list[dict] = Field(default_factory=list, max_length=100)


class QuestionBody(BaseModel):
    question: str = Field(max_length=2000)
    document_ids: list[int] = Field(default_factory=list, max_length=40)
    tab_id: str | None = Field(default=None, max_length=64)
    include_web: bool = False


class PlanWindow(BaseModel):
    start: str = Field(max_length=10)
    end: str = Field(max_length=10)
    note: str = Field(default="", max_length=9000)
    document_ids: list[int] = Field(default_factory=list, max_length=40)


class ChapterRebuildBody(BaseModel):
    token: str = Field(min_length=64, max_length=64)
    document_ids: list[int] = Field(default_factory=list, max_length=40)
    confirmed: bool = False


class ScheduleBody(BaseModel):
    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    profile: dict | None = None
    mode: Literal["agent", "baseline"] | None = None


class SchedulingRequirementsBody(BaseModel):
    profile: dict


class ExamAnswer(BaseModel):
    question_id: int
    response: str = Field(default="", max_length=5000)


class ExamSubmit(BaseModel):
    answers: list[ExamAnswer] = Field(default_factory=list, max_length=40)


class PracticeAnswer(BaseModel):
    question_id: int
    response: str = Field(default="", max_length=5000)


class PracticePrefs(BaseModel):
    requirements: str = Field(default="", max_length=2000)
    difficulty: str = Field(default="default", max_length=16)
    similar_to_cases: bool = False
    preferred_kind: str = Field(default="any", max_length=16)
    question_count: int | None = Field(default=None, ge=1, le=40)
    case_document_ids: list[int] = Field(default_factory=list, max_length=40)


class NotesBody(BaseModel):
    brief: str = Field(default="", max_length=2000)
    document_ids: list[int] = Field(default_factory=list, max_length=40)
    mode: str = Field(default="notes", max_length=16)
    paper_size: str = Field(default="a4", max_length=16)
    sides: str = Field(default="single", max_length=16)
    type_size: str = Field(default="medium", max_length=16)


def current_user(request: Request) -> dict:
    user = user_from_token(request.cookies.get(COOKIE))
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in first")
    return user


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/agent/ping")
def agent_ping():
    try:
        reply = ping()
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="The model request failed") from error
    return {"reply": reply}


@app.post("/api/register")
def register(body: AuthBody, response: Response):
    try:
        user = register_user(body.username, body.password)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    _set_session(response, open_session(user["id"]))
    return user


@app.post("/api/login")
def login(body: AuthBody, response: Response):
    user = authenticate(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    _set_session(response, open_session(user["id"]))
    return user


@app.post("/api/logout")
def logout(request: Request, response: Response):
    close_session(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return user


@app.get("/api/courses")
def courses(user: dict = Depends(current_user)):
    return {"courses": list_courses(user["id"])}


@app.post("/api/courses")
def add_course(body: CourseBody, user: dict = Depends(current_user)):
    name = body.name.strip()
    brief = body.student_brief.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Enter a course name")
    if not brief:
        raise HTTPException(status_code=400, detail="Write your goals and dates")
    return create_course(user["id"], name, brief)


@app.delete("/api/courses/{course_id}")
def remove_course(course_id: int, user: dict = Depends(current_user)):
    ensure_plan_storage()
    document_ids = delete_course(user["id"], course_id)
    if document_ids is None:
        raise HTTPException(status_code=404, detail="Course not found")
    from db.pdf_store import delete_course_pdfs

    delete_course_pdfs(course_id)
    for document_id in document_ids:
        try:
            delete_segments(document_id)
        except Exception:
            pass
    return {"ok": True}


@app.get("/api/courses/{course_id}")
def course_detail(course_id: int, user: dict = Depends(current_user)):
    course = get_course(user["id"], course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


@app.put("/api/courses/{course_id}/settings")
def update_settings(course_id: int, body: CourseSettingsBody, user: dict = Depends(current_user)):
    try:
        update_course_settings(user["id"], course_id, body.name, body.note, body.deadline, body.earlyDays, body.events, body.startDate)
        return get_course(user["id"], course_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/courses/{course_id}/documents")
async def add_document(
    course_id: int,
    file: UploadFile = File(...),
    user: dict = Depends(current_user),
):
    if get_course(user["id"], course_id) is None:
        raise HTTPException(status_code=404, detail="Course not found")
    filename = _pdf_filename(file.filename)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The PDF is empty")
    digest = hashlib.sha256(data).hexdigest()
    existing = existing_upload(course_id, digest)
    if existing is not None:
        return existing
    try:
        pages = read_pdf(data)
    except Exception as error:
        raise HTTPException(status_code=400, detail="This PDF could not be read") from error
    if not pages:
        raise HTTPException(status_code=400, detail="This PDF has no pages")
    return save_document(course_id, filename, pages, digest, pdf_bytes=data)


@app.get("/api/courses/{course_id}/documents/{document_id}/file")
def document_file(
    course_id: int,
    document_id: int,
    user: dict = Depends(current_user),
):
    from db.pdf_store import read_pdf_bytes
    from fastapi.responses import Response as FastResponse

    if not owns_document(user["id"], course_id, document_id):
        raise HTTPException(status_code=404, detail="Material not found")
    data = read_pdf_bytes(course_id, document_id)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail="Original PDF is not stored. Re-upload this file on Course information.",
        )
    course = get_course(user["id"], course_id)
    filename = "material.pdf"
    if course is not None:
        for item in course.get("documents") or []:
            if int(item["id"]) == document_id:
                filename = item["filename"]
                break
    return FastResponse(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "private, max-age=60",
        },
    )


@app.get("/api/courses/{course_id}/documents/{document_id}/segments")
def document_segments(
    course_id: int,
    document_id: int,
    user: dict = Depends(current_user),
):
    from vector.segments import COLLECTION, segments_for

    if not owns_document(user["id"], course_id, document_id):
        raise HTTPException(status_code=404, detail="Material not found")
    course = get_course(user["id"], course_id)
    filename = "material.pdf"
    if course is not None:
        for item in course.get("documents") or []:
            if int(item["id"]) == document_id:
                filename = str(item.get("filename") or filename)
                break
    try:
        rows = segments_for(document_id)
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail="Vector index is unavailable. Check that Milvus is running.",
        ) from error
    segments = [
        {
            "document_id": int(row.get("document_id") or document_id),
            "page_number": int(row.get("page_number") or 0),
            "chunk_index": int(row.get("chunk_index") or 0),
            "chapter": str(row.get("chapter") or ""),
            "text": str(row.get("text") or ""),
            "bridge_to": int(row.get("bridge_to") or 0),
        }
        for row in rows
    ]
    return {
        "collection": COLLECTION,
        "document_id": document_id,
        "filename": filename,
        "count": len(segments),
        "segments": segments,
    }


@app.delete("/api/courses/{course_id}/documents/{document_id}")
def remove_document(
    course_id: int,
    document_id: int,
    user: dict = Depends(current_user),
):
    try:
        delete_document_rows(user["id"], course_id, document_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    try:
        delete_segments(document_id)
    except Exception:
        pass
    return {"ok": True}


@app.post("/api/courses/{course_id}/notes")
def create_notes(course_id: int, body: NotesBody, user: dict = Depends(current_user)):
    from agent.notes import generate_notes_pdf
    from fastapi.responses import Response as FastResponse
    from urllib.parse import quote

    try:
        pdf, filename = generate_notes_pdf(
            user["id"],
            course_id,
            body.brief,
            body.document_ids,
            body.mode,
            body.paper_size,
            body.sides,
            body.type_size,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Course not found") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="Could not generate notes") from error
    encoded = quote(filename)
    return FastResponse(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded}",
        },
    )


@app.get("/api/courses/{course_id}/exam-cases")
def course_exam_cases(course_id: int, user: dict = Depends(current_user)):
    try:
        return {"cases": list_exam_cases(user["id"], course_id)}
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Course not found") from error


@app.post("/api/courses/{course_id}/exam-cases")
async def add_exam_case(
    course_id: int,
    file: UploadFile = File(...),
    answer_mode: str = Form("none"),
    answer_file: UploadFile | None = File(None),
    user: dict = Depends(current_user),
):
    if get_course(user["id"], course_id) is None:
        raise HTTPException(status_code=404, detail="Course not found")
    filename = _pdf_filename(file.filename)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The PDF is empty")
    digest = hashlib.sha256(data).hexdigest()
    try:
        pages = read_pdf(data)
    except Exception as error:
        raise HTTPException(status_code=400, detail="This PDF could not be read") from error
    if not pages:
        raise HTTPException(status_code=400, detail="This PDF has no pages")
    answer_filename = None
    answer_pages = None
    answer_hash = None
    answer_data = None
    if answer_file is not None and answer_file.filename:
        answer_filename = _pdf_filename(answer_file.filename)
        answer_data = await answer_file.read()
        if not answer_data:
            raise HTTPException(status_code=400, detail="The answer PDF is empty")
        answer_hash = hashlib.sha256(answer_data).hexdigest()
        try:
            answer_pages = read_pdf(answer_data)
        except Exception as error:
            raise HTTPException(status_code=400, detail="This answer PDF could not be read") from error
        if not answer_pages:
            raise HTTPException(status_code=400, detail="This answer PDF has no pages")
    try:
        return save_exam_case(
            user["id"],
            course_id,
            filename,
            pages,
            digest,
            answer_mode,
            answer_filename,
            answer_pages,
            answer_hash,
            pdf_bytes=data,
            answer_pdf_bytes=answer_data,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.delete("/api/courses/{course_id}/exam-cases/{document_id}")
def remove_exam_case(
    course_id: int,
    document_id: int,
    user: dict = Depends(current_user),
):
    try:
        delete_exam_case(user["id"], course_id, document_id)
    except LookupError as error:
        detail = "Course not found" if str(error) == "Course not found" else "Exam case not found"
        raise HTTPException(status_code=404, detail=detail) from error
    return {"ok": True}


@app.get("/api/courses/{course_id}/plan")
def course_plan(course_id: int, user: dict = Depends(current_user)):
    try:
        scheduling.repair_tasks(user["id"], course_id)
        return get_plan(user["id"], course_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Course not found") from error


@app.get("/api/courses/{course_id}/workflow")
def course_workflow(course_id: int, user: dict = Depends(current_user)):
    try:
        return scheduling.workflow_status(user["id"], course_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except (ValueError, ChapterizationConflict) as error:
        raise HTTPException(409, str(error)) from error


@app.post("/api/courses/{course_id}/tasks/repair")
def repair_course_tasks(course_id: int, preview: bool = True, user: dict = Depends(current_user)):
    try:
        return scheduling.repair_tasks(user["id"], course_id, preview=preview)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@app.put("/api/courses/{course_id}/schedule/requirements")
def update_scheduling_requirements(course_id: int, body: SchedulingRequirementsBody, user: dict = Depends(current_user)):
    try:
        return {"profile": scheduling.save_requirements(user["id"], course_id, body.profile)}
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@app.get("/api/courses/{course_id}/schedule/runs")
def scheduling_runs(course_id: int, user: dict = Depends(current_user)):
    try:
        return {"runs": scheduling.recent_runs(user["id"], course_id)}
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@app.get("/api/courses/{course_id}/plan/versions")
def plan_versions(course_id: int, user: dict = Depends(current_user)):
    try:
        return {"versions": scheduling.plan_history(user["id"], course_id)}
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@app.get("/api/courses/{course_id}/plan/versions/{version}")
def plan_version(course_id: int, version: int, user: dict = Depends(current_user)):
    try:
        return scheduling.historical_plan(user["id"], course_id, version)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@app.post("/api/courses/{course_id}/schedule")
def schedule_course(course_id: int, body: ScheduleBody, user: dict = Depends(current_user)):
    try:
        profile, mode = body.profile, body.mode
        if profile is None:
            profile, saved_mode = scheduling.saved_schedule_preferences(user["id"], course_id)
            mode = mode or saved_mode
        return run_planner(user["id"], course_id, body.request_id, profile, mode or "agent")
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except LookupError as error:
        raise HTTPException(404, str(error)) from error

@app.post("/api/courses/{course_id}/plan")
def create_plan(
    course_id: int,
    body: PlanWindow,
    user: dict = Depends(current_user),
):
    if get_course(user["id"], course_id) is None:
        raise HTTPException(
            status_code=404,
            detail="Course not found",
        )

    raise HTTPException(
        status_code=409,
        detail=(
            "Use Rebuild chapters to manage chapters. "
            "Daily scheduling is a separate operation."
        ),
    )

@app.get("/api/courses/{course_id}/chapters/options")
def get_chapterization_options(
    course_id: int,
    user: dict = Depends(current_user),
):
    try:
        return chapterization_options(user["id"], course_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ChapterizationConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/courses/{course_id}/chapters/rebuild")
def rebuild_course_chapters(
    course_id: int,
    body: ChapterRebuildBody,
    user: dict = Depends(current_user),
):
    try:
        return rebuild_chapters(
            user_id=user["id"],
            course_id=course_id,
            token=body.token,
            document_ids=body.document_ids,
            confirmed=body.confirmed,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ChapterizationConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=(
                "Could not rebuild chapters. "
                "The existing chapters were preserved."
            ),
        ) from error


@app.post("/api/courses/{course_id}/plan/tasks/{task_id}/complete")
def finish_task(course_id: int, task_id: str, user: dict = Depends(current_user)):
    try:
        return complete_task(user["id"], course_id, task_id)
    except LookupError as error:
        detail = "Course not found" if str(error) == "Course not found" else "Task not found"
        raise HTTPException(status_code=404, detail=detail) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/courses/{course_id}/chapters/{chapter_id}/exams")
def create_exam(course_id: int, chapter_id: int, user: dict = Depends(current_user)):
    try:
        return start_exam(user["id"], course_id, chapter_id)
    except LookupError as error:
        detail = "Course not found" if str(error) == "Course not found" else "Chapter not found"
        raise HTTPException(status_code=404, detail=detail) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="Could not create an exam") from error


@app.get("/api/courses/{course_id}/exams/{exam_id}")
def course_exam(course_id: int, exam_id: int, user: dict = Depends(current_user)):
    try:
        return open_exam(user["id"], course_id, exam_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Exam not found") from error


@app.post("/api/courses/{course_id}/exams/{exam_id}/drafts")
def save_course_exam_drafts(
    course_id: int,
    exam_id: int,
    body: ExamSubmit,
    user: dict = Depends(current_user),
):
    try:
        return save_exam_drafts(
            user["id"],
            course_id,
            exam_id,
            [item.model_dump() for item in body.answers],
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Exam not found") from error


@app.post("/api/courses/{course_id}/exams/{exam_id}/submit")
def submit_course_exam(
    course_id: int,
    exam_id: int,
    body: ExamSubmit,
    user: dict = Depends(current_user),
):
    try:
        return submit_exam(
            user["id"],
            course_id,
            exam_id,
            [item.model_dump() for item in body.answers],
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Exam not found") from error
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="Could not grade this exam") from error


@app.post("/api/courses/{course_id}/chapters/{chapter_id}/practice")
def create_practice(
    course_id: int,
    chapter_id: int,
    body: PracticePrefs | None = None,
    user: dict = Depends(current_user),
):
    prefs = body.model_dump() if body is not None else None
    try:
        return start_practice(user["id"], course_id, chapter_id, prefs)
    except LookupError as error:
        detail = "Course not found" if str(error) == "Course not found" else "Chapter not found"
        raise HTTPException(status_code=404, detail=detail) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="Could not start practice") from error


@app.get("/api/courses/{course_id}/practice/{session_id}")
def course_practice(course_id: int, session_id: int, user: dict = Depends(current_user)):
    try:
        return open_practice(user["id"], course_id, session_id)
    except LookupError as error:
        detail = "Practice not found" if str(error) == "Practice not found" else "Chapter not found"
        if str(error) == "Course not found":
            detail = "Course not found"
        raise HTTPException(status_code=404, detail=detail) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="Could not start practice") from error


@app.post("/api/courses/{course_id}/practice/{session_id}/answer")
def answer_course_practice(
    course_id: int,
    session_id: int,
    body: PracticeAnswer,
    user: dict = Depends(current_user),
):
    try:
        return answer_practice(
            user["id"],
            course_id,
            session_id,
            body.question_id,
            body.response,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Practice not found") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="Could not grade this practice question") from error


@app.get("/api/courses/{course_id}/chapters/{chapter_id}/reports")
def chapter_reports(course_id: int, chapter_id: int, user: dict = Depends(current_user)):
    try:
        return list_chapter_reports(user["id"], course_id, chapter_id)
    except LookupError as error:
        detail = "Course not found" if str(error) == "Course not found" else "Chapter not found"
        raise HTTPException(status_code=404, detail=detail) from error


@app.get("/api/courses/{course_id}/questions")
def course_questions(course_id: int, user: dict = Depends(current_user)):
    try:
        return list_questions(user["id"], course_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Course not found") from error


@app.post("/api/courses/{course_id}/questions")
def create_question(
    course_id: int,
    body: QuestionBody,
    user: dict = Depends(current_user),
):
    try:
        return answer_question(
            user["id"],
            course_id,
            body.question,
            body.document_ids,
            body.tab_id,
            body.include_web,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Course not found") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="Could not answer") from error


@app.delete("/api/courses/{course_id}/questions/tabs/{tab_id}")
def remove_question_tab(
    course_id: int,
    tab_id: str,
    user: dict = Depends(current_user),
):
    try:
        delete_question_tab(user["id"], course_id, tab_id)
        return {"ok": True}
    except LookupError as error:
        detail = "Course not found" if str(error) == "Course not found" else "Chat not found"
        raise HTTPException(status_code=404, detail=detail) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _set_session(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=14 * 24 * 3600,
        path="/",
    )


def _pdf_filename(name: str | None) -> str:
    cleaned = os.path.basename(name or "").strip()
    if not cleaned or Path(cleaned).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Upload a PDF file")
    return cleaned[:255]
