CREATE TABLE IF NOT EXISTS users (
  id INT PRIMARY KEY AUTO_INCREMENT,
  username VARCHAR(32) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_users_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS login_sessions (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  token VARCHAR(128) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at DATETIME NOT NULL,
  UNIQUE KEY uq_login_token (token),
  CONSTRAINT fk_login_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS courses (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL,
  name VARCHAR(255) NOT NULL,
  student_brief TEXT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_courses_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS documents (
  id INT PRIMARY KEY AUTO_INCREMENT,
  course_id INT NOT NULL,
  position INT NOT NULL,
  filename VARCHAR(255) NOT NULL,
  content_hash CHAR(64) NULL,
  ingest_status VARCHAR(16) NOT NULL DEFAULT 'pending',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_course_document_pos (course_id, position),
  UNIQUE KEY uq_course_content_hash (course_id, content_hash),
  CONSTRAINT fk_documents_course FOREIGN KEY (course_id) REFERENCES courses (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS pages (
  id INT PRIMARY KEY AUTO_INCREMENT,
  document_id INT NOT NULL,
  page_number INT NOT NULL,
  body TEXT NULL,
  usable TINYINT(1) NOT NULL,
  UNIQUE KEY uq_document_page (document_id, page_number),
  CONSTRAINT fk_pages_document FOREIGN KEY (document_id) REFERENCES documents (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS study_plans (
  id INT PRIMARY KEY AUTO_INCREMENT,
  course_id INT NOT NULL,
  student_brief TEXT NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'draft',
  plan_json JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_plan_course (course_id),
  CONSTRAINT fk_plans_course FOREIGN KEY (course_id) REFERENCES courses (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS plan_chapters (
  id INT PRIMARY KEY AUTO_INCREMENT,
  course_id INT NOT NULL,
  position INT NOT NULL,
  title VARCHAR(255) NOT NULL,
  UNIQUE KEY uq_plan_chapter_pos (course_id, position),
  CONSTRAINT fk_plan_chapters_course FOREIGN KEY (course_id) REFERENCES courses (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS plan_concepts (
  id INT PRIMARY KEY AUTO_INCREMENT,
  chapter_id INT NOT NULL,
  position INT NOT NULL,
  name VARCHAR(255) NOT NULL,
  UNIQUE KEY uq_plan_concept_pos (chapter_id, position),
  CONSTRAINT fk_plan_concepts_chapter FOREIGN KEY (chapter_id) REFERENCES plan_chapters (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS plan_chapter_pages (
  id INT PRIMARY KEY AUTO_INCREMENT,
  chapter_id INT NOT NULL,
  document_id INT NOT NULL,
  page_number INT NOT NULL,
  position INT NOT NULL,
  UNIQUE KEY uq_plan_chapter_page (chapter_id, document_id, page_number),
  CONSTRAINT fk_plan_pages_chapter FOREIGN KEY (chapter_id) REFERENCES plan_chapters (id) ON DELETE CASCADE,
  CONSTRAINT fk_plan_pages_document FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS exams (
  id INT PRIMARY KEY AUTO_INCREMENT,
  course_id INT NOT NULL,
  user_id INT NOT NULL,
  chapter_id INT NOT NULL,
  chapter_title VARCHAR(255) NOT NULL,
  status VARCHAR(16) NOT NULL,
  score INT NULL,
  passed TINYINT(1) NULL,
  report_json JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at DATETIME NULL,
  CONSTRAINT fk_exams_course FOREIGN KEY (course_id) REFERENCES courses (id) ON DELETE CASCADE,
  CONSTRAINT fk_exams_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS exam_questions (
  id INT PRIMARY KEY AUTO_INCREMENT,
  exam_id INT NOT NULL,
  position INT NOT NULL,
  concept_id INT NULL,
  concept_name VARCHAR(255) NOT NULL,
  kind VARCHAR(16) NOT NULL,
  prompt TEXT NOT NULL,
  options_json JSON NULL,
  answer TEXT NOT NULL,
  rubric_json JSON NULL,
  sources_json JSON NOT NULL,
  UNIQUE KEY uq_exam_question_pos (exam_id, position),
  CONSTRAINT fk_exam_questions_exam FOREIGN KEY (exam_id) REFERENCES exams (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS exam_answers (
  id INT PRIMARY KEY AUTO_INCREMENT,
  question_id INT NOT NULL,
  response TEXT NOT NULL,
  correct TINYINT(1) NOT NULL,
  points_hit INT NOT NULL,
  points_total INT NOT NULL,
  explanation TEXT NULL,
  UNIQUE KEY uq_exam_answer_question (question_id),
  CONSTRAINT fk_exam_answers_question FOREIGN KEY (question_id) REFERENCES exam_questions (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS exam_drafts (
  question_id INT PRIMARY KEY,
  response TEXT NOT NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_exam_drafts_question FOREIGN KEY (question_id) REFERENCES exam_questions (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS concept_progress (
  user_id INT NOT NULL,
  concept_id INT NOT NULL,
  level TINYINT NOT NULL,
  streak INT NOT NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, concept_id),
  CONSTRAINT fk_concept_progress_user FOREIGN KEY (user_id) REFERENCES users (id),
  CONSTRAINT fk_concept_progress_concept FOREIGN KEY (concept_id) REFERENCES plan_concepts (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS practice_sessions (
  id INT PRIMARY KEY AUTO_INCREMENT,
  course_id INT NOT NULL,
  user_id INT NOT NULL,
  chapter_id INT NOT NULL,
  chapter_title VARCHAR(255) NOT NULL,
  status VARCHAR(16) NOT NULL,
  phase VARCHAR(16) NOT NULL,
  review_round INT NOT NULL,
  review_queue_json JSON NOT NULL,
  report_json JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at DATETIME NULL,
  CONSTRAINT fk_practice_sessions_course FOREIGN KEY (course_id) REFERENCES courses (id) ON DELETE CASCADE,
  CONSTRAINT fk_practice_sessions_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS practice_questions (
  id INT PRIMARY KEY AUTO_INCREMENT,
  session_id INT NOT NULL,
  position INT NOT NULL,
  concept_id INT NULL,
  concept_name VARCHAR(255) NOT NULL,
  phase VARCHAR(16) NOT NULL,
  review_round INT NOT NULL,
  kind VARCHAR(16) NOT NULL,
  prompt TEXT NOT NULL,
  options_json JSON NULL,
  answer TEXT NOT NULL,
  rubric_json JSON NULL,
  sources_json JSON NOT NULL,
  UNIQUE KEY uq_practice_question_pos (session_id, position),
  CONSTRAINT fk_practice_questions_session FOREIGN KEY (session_id) REFERENCES practice_sessions (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS practice_answers (
  id INT PRIMARY KEY AUTO_INCREMENT,
  question_id INT NOT NULL,
  response TEXT NOT NULL,
  correct TINYINT(1) NOT NULL,
  points_hit INT NOT NULL,
  points_total INT NOT NULL,
  explanation TEXT NULL,
  UNIQUE KEY uq_practice_answer_question (question_id),
  CONSTRAINT fk_practice_answers_question FOREIGN KEY (question_id) REFERENCES practice_questions (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS qa_records (
  id INT PRIMARY KEY AUTO_INCREMENT,
  course_id INT NOT NULL,
  user_id INT NOT NULL,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  cited_pages TEXT NULL,
  web_sources TEXT NULL,
  origin VARCHAR(32) NULL,
  refused TINYINT(1) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_qa_course FOREIGN KEY (course_id) REFERENCES courses (id),
  CONSTRAINT fk_qa_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
