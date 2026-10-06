import { useCallback, useEffect, useMemo, useRef } from 'react'
import { useMutation, useQueries, useQueryClient } from '@tanstack/react-query'
import { documentsApi, jobsApi, wordFilesApi, type WordFileUpdateRequest } from '../services/api'
import { mapWordFileRefusal } from '../services/mappers'
import { projectKeys, useDocuments } from './useProjects'
import { notifKeys } from './useNotifications'
import { useExportReadiness } from './useReview'
import { toast } from '../components/ui/Toast'
import { ApiError } from '../lib/http'
import { cap, compNames, componentNamer, refusalSentence, type Wording } from '../lib/wordFiles'
import { useAuthStore } from '../store/auth'
import { useWordFilesStore, type PendingDownload } from '../store/wordFiles'
import type { ExportReadiness } from '../types'

/* Word file updates (docs/design/WORD_FILE_UPDATES.md): start one (POST V/reexport), follow it
   through R9, and say when it ends — a toast, the bell, the download that waited for it. The
   rules and the words are in lib/wordFiles.ts. */

const ACTIVE = ['queued', 'running']

/** What a download that waited for an update fetches: one document's Word file, or the version's
 *  zip. */
export type WaitingDownload = Omit<PendingDownload, 'projectId'>

/** A waiting download, fetched; a failure said (as useDownloadDoc / useDownloadAll, but one
 *  function for the project, so an effect can depend on it). */
function useDownload(projectId: string) {
  return useCallback(async (d: WaitingDownload) => {
    try {
      if (d.docId) await documentsApi.download(projectId, d.docId, d.fileName)
      else if (d.versionId) await documentsApi.downloadAll(projectId, d.versionId, d.fileName)
    } catch (e) {
      toast.error('Download failed', `${d.fileName}: ${(e as Error).message}`)
    }
  }, [projectId])
}

export { readinessPollMs } from '../lib/wordFiles'

/** What to update, and what to download once it is done (a download's *Corrected file*, Download
 *  all's *Corrected files*). */
export interface WordFileUpdateInput {
  request: WordFileUpdateRequest
  download?: WaitingDownload
}

/** Start an update. Started or joined: R9 follows it (the banners say *Updating…*). Nothing out of
 *  date: said, or the download goes at once. Refused: why, in one sentence, and R9 read again. */
export function useUpdateWordFiles(projectId: string, versionId: string, words: Wording) {
  const qc = useQueryClient()
  const download = useDownload(projectId)
  const addPending = useWordFilesStore((s) => s.addPending)
  const refresh = () => {
    // R9 for the version and each document (A15 keys sit under it); the Overview lists the job.
    qc.invalidateQueries({ queryKey: projectKeys.exportReadiness(projectId, versionId) })
    qc.invalidateQueries({ queryKey: projectKeys.runs(projectId) })
  }
  return useMutation({
    mutationFn: (v: WordFileUpdateInput) => wordFilesApi.update(projectId, versionId, v.request),
    onSuccess: (start, v) => {
      refresh()
      if (!start.jobId || start.status === 'up_to_date') {
        if (v.download) void download(v.download)
        else toast.info('Nothing is out of date now.')
        return
      }
      // The download waits for the job it started, or joined; a document's knows its component.
      if (v.download) {
        addPending(start.jobId, {
          projectId, ...v.download,
          components: v.download.docId ? v.download.components ?? v.request.components : undefined,
        })
      }
    },
    onError: (e: Error, v) => {
      const rebuild = v.request.scope === 'all'
      if (e instanceof ApiError && e.status === 409 && (e.code === 'REEXPORT_RUNNING' || e.code === 'VERSION_BUSY')) {
        refresh()
        toast.info(refusalSentence({ code: e.code, ...mapWordFileRefusal(e.extra) }, words, rebuild))
        return
      }
      if (e instanceof ApiError && e.status === 403) {
        // Beyond a developer's reach from here: a document of that component reaches it.
        const refused = e.code === 'NOT_YOUR_DOCUMENTS' ? mapWordFileRefusal(e.extra).components : []
        toast.error('Not updated.', refused.length
          ? `Open ${compNames(refused.map(words.nameOf))} to update ${refused.length === 1 ? 'it' : 'them'}.`
          : e.message)
        return
      }
      toast.error('Not updated.', e.message)
    },
  })
}

/** A version's Word files, as the Documents page and the Generation banner read them: R9, the
 *  version's documents (who reviews which: a developer's reach), the words the screens use, and
 *  who is signed in. The documents read is the Documents page's own (same key). */
export function useVersionWordFiles(projectId: string, versionId: string | undefined, versionTag: string) {
  const meId = useAuthStore((s) => s.user?.id ?? '')
  const { data: readiness, isError: readinessFailed } = useExportReadiness(projectId, versionId)
  const { data: docList } = useDocuments(projectId, versionId ? { versionId } : undefined)
  const outOfDate = readiness?.outOfDate
  const words: Wording = useMemo(
    () => ({ versionTag, nameOf: componentNamer(docList ?? [], outOfDate ?? []) }),
    [versionTag, docList, outOfDate])
  const docs = useMemo(() => docList ?? [], [docList])
  const myDocIds = useMemo(
    () => docs.filter((d) => !!meId && d.reviewer?.userId === meId).map((d) => d.id), [docs, meId])
  return { readiness, readinessFailed, docs, words, meId, myDocIds }
}

/** The components an update of this version just wrote ("Word files updated · Download"). */
export function useJustUpdated(versionId: string | undefined): string[] | null {
  return useWordFilesStore((s) => (versionId ? s.justUpdated[versionId] ?? null : null))
}

/** What the watcher keeps of the newest update between two reads of R9. */
interface UpdateSeen {
  jobId: string
  status: string
  rebuild: boolean
  components: string[]
  componentsFailed: string[]
  error: string | null
  /** The signed-in user started it. */
  mine: boolean
}

const reason = (error: string | null): string => {
  const why = (error ?? '').trim().replace(/[.\s]+$/, '')
  return why ? `${cap(why)}.` : ''
}

/** Watch R9 for the end of an update (mount once per page, on the version-wide R9): the pages,
 *  the downloads and the review reads are read again, the bell too; its end is said — written to
 *  anyone watching, failed only to its starter (to anyone else the files are simply out of date).
 *  A partly failed update says both, as its starter's two notifications do: "Word files updated"
 *  for the written components, "Update failed" for the rest. An update that ended between two
 *  reads — R9 already names the next one — is read by its own job. A cancelled update tells
 *  nobody. Downloads that wait for an update follow their own job (useWaitingDownloads). */
export function useWordFilesWatcher(
  projectId: string, versionId: string, readiness: ExportReadiness | undefined,
  opts: { meId: string; words: Wording },
) {
  const qc = useQueryClient()
  const markUpdated = useWordFilesStore((s) => s.markUpdated)
  useWaitingDownloads(projectId, readiness)
  const prev = useRef<UpdateSeen | null>(null)
  const x = readiness?.reexport
  const jobId = x?.jobId
  const status = x?.status
  const rebuild = !!x && (x.scope === 'all' || x.scope == null)
  const comps = (x?.components ?? []).join('\n')
  const failedComps = (x?.componentsFailed ?? []).join('\n')
  const error = x?.errorMessage ?? null
  const mine = !!opts.meId && x?.startedBy?.userId === opts.meId
  const { versionTag, nameOf } = opts.words

  useEffect(() => {
    const now: UpdateSeen | null = jobId && status ? {
      jobId, status, rebuild, mine, error,
      components: comps ? comps.split('\n') : [],
      componentsFailed: failedComps ? failedComps.split('\n') : [],
    } : null
    const was = prev.current
    prev.current = now
    if (!was || !ACTIVE.includes(was.status)) return
    if (now?.jobId === was.jobId && ACTIVE.includes(now.status)) return

    // An update ended: what it wrote changes the pages, the downloads and the review reads.
    function announce(s: UpdateSeen) {
      qc.invalidateQueries({ queryKey: projectKeys.documentsAll(projectId) })
      qc.invalidateQueries({ queryKey: projectKeys.review(projectId, versionId) })
      qc.invalidateQueries({ queryKey: projectKeys.versionComponents(projectId, versionId) })
      qc.invalidateQueries({ queryKey: projectKeys.runs(projectId) })
      qc.invalidateQueries({ queryKey: notifKeys.all })
      const failed = new Set(s.componentsFailed)
      const written = s.components.filter((c) => !failed.has(c))
      if (s.status === 'complete') {
        if (written.length || !failed.size) {
          markUpdated(versionId, written)
          const all = s.rebuild && !failed.size
          toast.success(all ? 'Word files rebuilt.' : 'Word files updated.', all ? versionTag : compNames(written.map(nameOf)))
        }
        if (failed.size && s.mine) {
          const why = reason(s.error)
          toast.error('Update failed.', `${compNames([...failed].map(nameOf))}${why ? ` — ${why}` : '.'}`)
        }
      } else if (s.status === 'failed' && s.mine) {
        toast.error(s.rebuild ? 'Rebuild failed.' : 'Update failed.', reason(s.error) || undefined)
      }
    }

    if (now?.jobId === was.jobId) announce(now)
    else {
      // It ended between two reads, and R9 names the next update now: read it by its own job.
      jobsApi.get(projectId, was.jobId)
        .then((j) => announce({ ...was, status: j.status, error: j.errorMessage, componentsFailed: [] }))
        .catch(() => announce({ ...was, status: 'unknown' }))
    }
  }, [jobId, status, rebuild, comps, failedComps, error, mine, versionTag, nameOf, projectId, versionId, qc, markUpdated])
}

/** The downloads that wait for an update (a *Corrected file*, Download all's *Corrected files*),
 *  each following its own job (`GET /jobs/{id}`), not R9's newest update: one ended between two
 *  reads still downloads. Written: it downloads — a document's file only when its component did
 *  not fail in a partly failed update (R9 says which, while that update is the newest). Failed or
 *  cancelled: it is dropped (the failure is said elsewhere). */
function useWaitingDownloads(projectId: string, readiness: ExportReadiness | undefined) {
  const download = useDownload(projectId)
  const pending = useWordFilesStore((s) => s.pending)
  const takePending = useWordFilesStore((s) => s.takePending)
  const jobIds = Object.keys(pending).filter((id) => pending[id].some((d) => d.projectId === projectId))
  const jobs = useQueries({
    queries: jobIds.map((id) => ({
      queryKey: [...projectKeys.job(projectId), id, 'status'],
      queryFn: () => jobsApi.get(projectId, id),
      refetchInterval: (q: { state: { data?: { status: string } } }): number | false =>
        (q.state.data && !ACTIVE.includes(q.state.data.status) ? false : 2500),
    })),
  })
  const ended = jobs.map((j, i) => (j.data && !ACTIVE.includes(j.data.status) ? `${jobIds[i]}:${j.data.status}` : ''))
    .filter(Boolean).join(',')
  const x = readiness?.reexport
  const failedNow = x ? `${x.jobId}:${(x.componentsFailed ?? []).join('|')}` : ''

  useEffect(() => {
    if (!ended) return
    const [newest, failedList] = failedNow.split(':')
    for (const e of ended.split(',')) {
      const [id, status] = e.split(':')
      const list = takePending(id)
      if (status !== 'complete') continue
      const failed = new Set(id === newest && failedList ? failedList.split('|') : [])
      for (const d of list) {
        if (d.components?.some((c) => failed.has(c))) continue
        void download(d)
      }
    }
  }, [ended, failedNow, takePending, download])
}
