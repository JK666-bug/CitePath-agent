import { request } from '../../shared/request'

type Options = { token: string; new_documents: { id: number }[]; blocked_documents: { state: string; reason: string }[] }
export async function analyzeNewDocuments(courseId: number) {
  const options = await request<Options>(`/api/courses/${courseId}/chapters/options`)
  if (!options.new_documents.length) {
    if (options.blocked_documents?.some(item => item.state === 'unplanned')) throw new Error('New PDFs are not ready for chapter analysis. Check the material list and upload again.')
    return 0
  }
  await request(`/api/courses/${courseId}/chapters/rebuild`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token: options.token, document_ids: options.new_documents.map(x => x.id), confirmed: false }),
  })
  return options.new_documents.length
}
