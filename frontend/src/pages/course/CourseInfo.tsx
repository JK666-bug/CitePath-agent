import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { FileText } from 'lucide-react'

import type {
  CourseDetail,
  Material,
  MaterialInventory,
} from './types'

import { decodeBrief } from '../courseEditor/brief'

import MaterialPicker, {
  fileKey,
} from '../courseEditor/MaterialPicker'

import {
  deleteMaterial,
  duplicateMessage,
  uploadMaterial,
  getDocumentInventory,
  restoreMaterial,
} from './api'

import { useStudy } from '../../shared/StudyProvider'
import { messageOf } from '../../shared/request'
import { prettyDate } from '../../shared/format'

import {
  Modal,
  Notice,
} from '../../shared/components/UI'

export default function CourseInfo({
  courseId,
  course,
}: {
  courseId: string
  course: CourseDetail
}) {
  const {
    loadCourse,
    refreshCourses,
  } = useStudy()

  const config =
    decodeBrief(course.student_brief)

  const demo = courseId === 'demo'

  const [files, setFiles] =
    useState<File[]>([])

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] =
    useState('')
  const [inventory, setInventory] = useState<MaterialInventory[]>([])

  useEffect(() => {
    let cancelled = false
    if (!demo) void getDocumentInventory(course.id).then((result) => {
      if (!cancelled) setInventory(result.documents)
    }).catch((reason) => { if (!cancelled) setError(messageOf(reason)) })
    return () => { cancelled = true }
  }, [course.id, course.documents, demo])

  const [remove, setRemove] =
    useState<Material | null>(null)

  async function reload() {
    await loadCourse(course.id)
    await refreshCourses()
  }

  async function upload(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()

    if (busy || demo) return

    setError('')
    setMessage('')

    if (
      !files.length ||
      files.some(
        (file) =>
          !file.name
            .toLowerCase()
            .endsWith('.pdf') ||
          !file.size,
      )
    ) {
      setError(
        'Choose one or more non-empty PDF files.',
      )
      return
    }

    setBusy(true)
    const duplicates: string[] = []
    let saved = 0
    let restored = 0

    try {
      for (const file of files) {
        setMessage(
          `Uploading and processing ${file.name}…`,
        )

        const result = await uploadMaterial(
          course.id,
          file,
        )

        if (result.restored) {
          restored += 1
        } else if (result.duplicate) {
          duplicates.push(
            duplicateMessage(
              file.name,
              result.filename,
            ),
          )
        } else {
          saved += 1
        }

        setFiles((current) =>
          current.filter(
            (item) =>
              fileKey(item) !==
              fileKey(file),
          ),
        )
      }

      const parts: string[] = []
      if (restored) parts.push(`Restored ${restored} archived material(s) with their original document IDs. Saved tasks, questions and scores remain linked.`)

      if (saved > 0) {
        parts.push(
          'Materials saved. Open the Plan tab to generate a schedule from these PDFs and your note.',
        )
      }

      if (duplicates.length) {
        parts.push(duplicates.join(' '))
      }

      setMessage(parts.join(' '))
    } catch (reason) {
      setMessage('')

      setError(
        `${messageOf(reason)} Check the material list before manually retrying; a failed response may still have saved a file.`,
      )
    } finally {
      try {
        await reload()
      } catch (reason) {
        setError(messageOf(reason))
      }

      setBusy(false)
    }
  }

  async function confirmDelete() {
    if (!remove || busy || demo) return

    setBusy(true)
    setError('')
    setMessage('')

    try {
      await deleteMaterial(
        course.id,
        remove.id,
      )

      await reload()

      setMessage(
        'Material archived and excluded from new planning and questions. Original source references and learning history remain saved; restore it below when needed.',
      )
    } catch (reason) {
      setError(messageOf(reason))
    } finally {
      setBusy(false)
      setRemove(null)
    }
  }

  async function restore(material: MaterialInventory) {
    if (busy || demo) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await restoreMaterial(course.id, material.id)
      await reload()
      setInventory((await getDocumentInventory(course.id)).documents)
      setMessage(`Restored ${material.filename} as Document ID ${material.id}. Existing source references, tasks and scores are unchanged.`)
    } catch (reason) {
      setError(`${messageOf(reason)} Restoration did not finish. Upload the exact original PDF to retry; historical document IDs cannot be reassigned.`)
      try { setInventory((await getDocumentInventory(course.id)).documents) } catch { /* Keep the retained archive list available. */ }
    } finally { setBusy(false) }
  }

  return (
    <div className="stack">
      <section className="panel">
        <h2>Course settings</h2>

        <dl className="course-facts">
          <div>
            <dt>Learning deadline</dt>
            <dd>
              {prettyDate(
                config.deadline,
                true,
              )}
            </dd>
          </div>

          <div>
            <dt>Finish early by</dt>
            <dd>
              {config.deadline
                ? `${config.earlyDays} days`
                : 'Not set'}
            </dd>
          </div>

          <div>
            <dt>Materials</dt>
            <dd>
              {course.documents.length}
              {' '}PDFs
            </dd>
          </div>
        </dl>

        <h3>Goals and study note</h3>

        <p className="course-note">
          {config.note ||
            'No additional note.'}
        </p>
      </section>

      {error && (
        <Notice tone="error">
          {error}
        </Notice>
      )}

      {message && (
        <Notice>{message}</Notice>
      )}

      <section className="panel">
        <h2>Course materials</h2>

        {course.documents.length ? (
          <ul className="materials-list">
            {course.documents.map(
              (material) => (
                <li key={material.id}>
                  <FileText
                    size={18}
                    strokeWidth={1.4}
                  />

                  <div>
                    <strong>
                      {demo ? material.filename : (
                        <a href={`/api/courses/${courseId}/documents/${material.id}/file`} target="_blank" rel="noreferrer">
                          {material.filename}
                        </a>
                      )}
                    </strong>

                    <p>
                      Material {material.position}
                      {' · '}Document ID {material.id}
                      {' · '}
                      {material.page_count}
                      {' '}pages
                      {' · '}
                      {material.usable_page_count}
                      {' '}usable pages
                    </p>
                    {material.ingest_error && (
                      <p className="field-error">{material.ingest_error}</p>
                    )}
                    {material.ingest_status === 'failed' && (
                      <p>Upload the same PDF again to retry processing.</p>
                    )}
                  </div>

                  <span className="badge">
                    {material.ingest_status ===
                    'complete'
                      ? 'Ready'
                      : material.ingest_status ===
                          'pending'
                        ? 'Processing'
                        : 'Unavailable'}
                  </span>

                  <button
                    className="button small danger"
                    disabled={busy || demo}
                    onClick={() =>
                      setRemove(material)
                    }
                  >
                    Remove from course
                  </button>
                </li>
              ),
            )}
          </ul>
        ) : (
          <p className="muted">
            No materials uploaded yet.
          </p>
        )}

        {demo ? (
          <p className="muted small">
            Sample PDF references are
            illustrative. This demo does not
            contain real PDF files.
          </p>
        ) : (
          <form
            className="stack"
            onSubmit={upload}
            noValidate
          >
            <MaterialPicker
              files={files}
              onChange={setFiles}
              disabled={busy}
            />

            <div className="actions">
              <button
                className="button"
                disabled={
                  busy || !files.length
                }
              >
                {busy
                  ? 'Processing materials…'
                  : 'Upload materials'}
              </button>

              <small className="muted">
                Only upload status is
                available; no analysis
                percentage is estimated.
              </small>
            </div>
          </form>
        )}
      </section>

      {!demo && inventory.some((material) => !material.active) && (
        <section className="panel stack">
          <h2>Archived materials</h2>
          <p className="muted small">Archived PDFs stay available to their saved source references. They are excluded from new plans and questions until restored. Deleting the entire course permanently removes its retained files and records.</p>
          <ul className="materials-list">
            {inventory.filter((material) => !material.active).map((material) => (
              <li key={material.id}>
                <FileText size={18} strokeWidth={1.4} />
                <div>
                  <strong>{material.original_pdf_available ? <a href={`/api/courses/${courseId}/documents/${material.id}/file`} target="_blank" rel="noreferrer">{material.filename}</a> : material.filename}</strong>
                  <p>Document ID {material.id} · {material.page_count} pages · Archived {material.removed_at}</p>
                  {material.ingest_error && <p className="field-error">{material.ingest_error}</p>}
                  {!material.original_pdf_available && <p>Original PDF unavailable. Upload the exact same PDF to recover the retained document identity.</p>}
                  {!material.sha256 && <p>This legacy identity has no original hash and cannot be reassigned to another upload.</p>}
                </div>
                <span className="badge">Archived</span>
                <button className="button small secondary" disabled={busy || !material.original_pdf_available || !material.sha256} onClick={() => void restore(material)}>Restore material</button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <Modal
        open={Boolean(remove)}
        title="Remove material from course?"
        closeable={!busy}
        onClose={() => setRemove(null)}
      >
        <p>
          Archive {remove?.filename}? It will be excluded from new planning and questions.
          The original PDF, source ID and learning history stay saved and can be restored.
        </p>

        <div className="actions">
          <button
            className="button danger"
            disabled={busy}
            onClick={confirmDelete}
          >
            {busy
              ? 'Archiving…'
              : 'Remove from course'}
          </button>

          <button
            className="button secondary"
            disabled={busy}
            onClick={() => setRemove(null)}
          >
            Cancel
          </button>
        </div>
      </Modal>
    </div>
  )
}
