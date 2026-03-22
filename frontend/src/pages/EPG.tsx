import { useState, useMemo, useRef, useCallback } from "react"
import { toast } from "sonner"
import {
  Play,
  Download,
  Loader2,
  CheckCircle,
  Ban,
  Link,
  Copy,
  Check,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Search,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { RunHistoryTable } from "@/components/RunHistoryTable"
import { EventMatcherModal, useEventMatcher } from "@/components/EventMatcherModal"
import { useGenerationProgress } from "@/contexts/GenerationContext"
import { useDateFormat } from "@/hooks/useDateFormat"
import {
  useStats,
  useRecentRuns,
  useEPGAnalysis,
  useEPGContent,
} from "@/hooks/useEPG"
import {
  getTeamXmltvUrl,
} from "@/api/epg"

function formatDuration(ms: number | null): string {
  if (!ms) return "-"
  const seconds = Math.round(ms / 1000)
  if (seconds < 60) return `${seconds}s`
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`
}

function formatBytes(bytes: number | undefined | null): string {
  if (bytes == null || isNaN(bytes) || bytes === 0) return "0 B"
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDateRange(start: string | null, end: string | null): string {
  if (!start || !end) return "N/A"
  const formatDate = (d: string) => `${d.slice(4, 6)}/${d.slice(6, 8)}`
  return `${formatDate(start)} - ${formatDate(end)}`
}

export function EPG() {
  const { data: stats, isLoading: statsLoading, refetch: refetchStats } = useStats()
  const { data: runsData, isLoading: runsLoading, refetch: refetchRuns } = useRecentRuns(10, "full_epg")
  const { data: analysis, isLoading: analysisLoading, refetch: refetchAnalysis } = useEPGAnalysis()
  const { data: epgContent, isLoading: contentLoading } = useEPGContent(0) // 0 = no limit
  const { formatRelativeTime } = useDateFormat()

  const [isDownloading, setIsDownloading] = useState(false)
  const [copied, setCopied] = useState(false)
  const [showXmlPreview, setShowXmlPreview] = useState(false)
  const [searchTerm, setSearchTerm] = useState("")
  const [currentMatch, setCurrentMatch] = useState(0)
  const [showLineNumbers, setShowLineNumbers] = useState(true)
  const previewRef = useRef<HTMLPreElement>(null)

  // Event matcher (shared component)
  const matcher = useEventMatcher()

  // Gap highlighting state
  const [highlightedGap, setHighlightedGap] = useState<{
    afterStop: string
    beforeStart: string
    afterProgram: string
    beforeProgram: string
  } | null>(null)

  // EPG URL for IPTV apps
  const epgUrl = `${window.location.origin}${getTeamXmltvUrl()}`

  const handleCopyUrl = async () => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(epgUrl)
      } else {
        const textArea = document.createElement("textarea")
        textArea.value = epgUrl
        textArea.style.position = "fixed"
        textArea.style.left = "-999999px"
        textArea.style.top = "-999999px"
        document.body.appendChild(textArea)
        textArea.focus()
        textArea.select()
        document.execCommand("copy")
        textArea.remove()
      }
      setCopied(true)
      toast.success("URL copied to clipboard")
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.error("Failed to copy URL")
    }
  }

  // Generation progress (non-blocking toast)
  const { startGeneration, cancelGeneration, isGenerating } = useGenerationProgress()

  const handleGenerate = () => {
    startGeneration(() => {
      refetchAnalysis()
      refetchRuns()
      refetchStats()
    })
  }

  const handleDownload = async () => {
    setIsDownloading(true)
    try {
      const url = getTeamXmltvUrl()
      window.open(url, "_blank")
    } catch {
      toast.error("Failed to open XMLTV URL")
    } finally {
      setIsDownloading(false)
    }
  }

  // Search functionality for XML preview
  const searchMatches = useMemo(() => {
    if (!searchTerm || !epgContent?.content) return []
    const matches: number[] = []
    const lines = epgContent.content.split("\n")
    const searchLower = searchTerm.toLowerCase()
    lines.forEach((line, idx) => {
      if (line.toLowerCase().includes(searchLower)) {
        matches.push(idx)
      }
    })
    return matches
  }, [searchTerm, epgContent?.content])

  const scrollToMatch = useCallback((matchIndex: number) => {
    if (!previewRef.current || searchMatches.length === 0) return
    const lineNumber = searchMatches[matchIndex]
    const lineHeight = 20
    previewRef.current.scrollTop = lineNumber * lineHeight - 100
  }, [searchMatches])

  const nextMatch = () => {
    if (searchMatches.length === 0) return
    const next = (currentMatch + 1) % searchMatches.length
    setCurrentMatch(next)
    scrollToMatch(next)
  }

  const prevMatch = () => {
    if (searchMatches.length === 0) return
    const prev = (currentMatch - 1 + searchMatches.length) % searchMatches.length
    setCurrentMatch(prev)
    scrollToMatch(prev)
  }

  // Highlighted XML content
  const highlightedContent = useMemo(() => {
    if (!epgContent?.content) return ""
    const lines = epgContent.content.split("\n")

    if (highlightedGap) {
      const result: string[] = []
      let inProgramme = false
      let programmeLines: number[] = []
      let programmeType: "before" | "after" | null = null

      for (let i = 0; i < lines.length; i++) {
        const line = lines[i]
        const lineNum = showLineNumbers ? `${(i + 1).toString().padStart(4)} | ` : ""

        if (line.includes("<programme")) {
          if (line.includes(`stop="${highlightedGap.afterStop}"`)) {
            inProgramme = true
            programmeType = "before"
            programmeLines = [i]
          } else if (line.includes(`start="${highlightedGap.beforeStart}"`)) {
            inProgramme = true
            programmeType = "after"
            programmeLines = [i]
          }
        }

        if (inProgramme) {
          if (!programmeLines.includes(i)) {
            programmeLines.push(i)
          }
        }

        if (inProgramme && line.includes("</programme>")) {
          inProgramme = false
          const bgClass = programmeType === "before"
            ? "bg-red-400/30"
            : "bg-blue-400/30"

          for (const lineIdx of programmeLines) {
            const ln = showLineNumbers ? `${(lineIdx + 1).toString().padStart(4)} | ` : ""
            result.push(`<span class="${bgClass}">${ln}${escapeHtml(lines[lineIdx])}</span>`)
          }
          programmeLines = []
          programmeType = null
          continue
        }

        if (!inProgramme) {
          result.push(`${lineNum}${escapeHtml(line)}`)
        }
      }
      return result.join("\n")
    }

    return lines.map((line, idx) => {
      const lineNum = showLineNumbers ? `${(idx + 1).toString().padStart(4)} | ` : ""
      const isMatch = searchTerm && line.toLowerCase().includes(searchTerm.toLowerCase())
      const isCurrentMatch = isMatch && searchMatches[currentMatch] === idx

      if (isCurrentMatch) {
        return `<span class="bg-yellow-500/40">${lineNum}${escapeHtml(line)}</span>`
      } else if (isMatch) {
        return `<span class="bg-yellow-500/20">${lineNum}${escapeHtml(line)}</span>`
      }
      return `${lineNum}${escapeHtml(line)}`
    }).join("\n")
  }, [epgContent?.content, showLineNumbers, searchTerm, currentMatch, searchMatches, highlightedGap])

  const hasIssues = (analysis?.unreplaced_variables?.length ?? 0) > 0 ||
                   (analysis?.coverage_gaps?.length ?? 0) > 0

  return (
    <div className="space-y-2">
      <div>
        <h1 className="text-xl font-bold">EPG Management</h1>
        <p className="text-sm text-muted-foreground">Generate and manage XMLTV output</p>
      </div>

      {/* Action Bar */}
      <div className="flex flex-wrap items-center gap-3 bg-secondary border border-border rounded px-3 py-2">
        {isGenerating ? (
          <>
            <Button size="sm" disabled>
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
              Generating...
            </Button>
            <Button
              size="sm"
              variant="destructive"
              onClick={cancelGeneration}
            >
              <Ban className="h-4 w-4 mr-1" />
              Cancel
            </Button>
          </>
        ) : (
          <Button size="sm" onClick={handleGenerate}>
            <Play className="h-4 w-4 mr-1" />
            Generate
          </Button>
        )}
        {stats?.last_run && (
          <span className="text-xs text-muted-foreground">
            Last: {formatRelativeTime(stats.last_run)}
          </span>
        )}
        <div className="h-4 w-px bg-border" />
        <Button
          variant="outline"
          size="sm"
          onClick={handleDownload}
          disabled={isDownloading}
        >
          {isDownloading ? (
            <Loader2 className="h-4 w-4 mr-1 animate-spin" />
          ) : (
            <Download className="h-4 w-4 mr-1" />
          )}
          Download
        </Button>
        <div className="h-4 w-px bg-border" />
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <Link className="h-4 w-4 text-muted-foreground shrink-0" />
          <Input
            value={epgUrl}
            readOnly
            className="text-xs font-mono h-8 flex-1 min-w-0"
            onClick={(e) => e.currentTarget.select()}
          />
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0"
            onClick={handleCopyUrl}
          >
            {copied ? (
              <Check className="h-4 w-4 text-green-500" />
            ) : (
              <Copy className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>

      {/* EPG Analysis - Stats Tiles */}
      <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
        <div className="bg-secondary rounded px-3 py-2">
          <div className="text-lg font-semibold">{analysis?.channels.total ?? 0}</div>
          <div className="text-xs text-muted-foreground">Channels</div>
          {analysis && (
            <div className="text-xs text-muted-foreground">
              {analysis.channels.team_based}T / {analysis.channels.event_based}E
            </div>
          )}
        </div>
        <div className="bg-secondary rounded px-3 py-2">
          <div className="text-lg font-semibold">{analysis?.programmes.events ?? 0}</div>
          <div className="text-xs text-muted-foreground">Events</div>
        </div>
        <div className="bg-secondary rounded px-3 py-2">
          <div className="text-lg font-semibold text-blue-600">{analysis?.programmes.pregame ?? 0}</div>
          <div className="text-xs text-muted-foreground">Pregame</div>
        </div>
        <div className="bg-secondary rounded px-3 py-2">
          <div className="text-lg font-semibold text-purple-600">{analysis?.programmes.postgame ?? 0}</div>
          <div className="text-xs text-muted-foreground">Postgame</div>
        </div>
        <div className="bg-secondary rounded px-3 py-2">
          <div className="text-lg font-semibold text-orange-600">{analysis?.programmes.idle ?? 0}</div>
          <div className="text-xs text-muted-foreground">Idle</div>
        </div>
        <div className="bg-secondary rounded px-3 py-2">
          <div className="text-lg font-semibold">{analysis?.programmes.total ?? 0}</div>
          <div className="text-xs text-muted-foreground">Total</div>
          {analysis && (
            <div className="text-xs text-muted-foreground">
              {formatDateRange(analysis.date_range.start, analysis.date_range.end)}
            </div>
          )}
        </div>
      </div>

      {/* EPG Issues */}
      {analysisLoading ? (
        <div className="flex items-center justify-center py-4">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : analysis && hasIssues ? (
        <div className="border border-yellow-500/30 bg-yellow-500/10 rounded-lg p-3 space-y-2">
          <div className="flex items-center gap-2 text-yellow-600 font-medium text-sm">
            <AlertTriangle className="h-4 w-4" />
            Detected Issues
          </div>

          {analysis.unreplaced_variables.length > 0 && (
            <div>
              <div className="text-xs font-medium mb-1">
                Unreplaced Variables ({analysis.unreplaced_variables.length})
              </div>
              <div className="flex flex-wrap gap-1">
                {analysis.unreplaced_variables.map((v) => (
                  <code
                    key={v}
                    className="text-xs bg-yellow-500/20 px-1.5 py-0.5 rounded cursor-pointer hover:bg-yellow-500/40"
                    onClick={() => {
                      setSearchTerm(v)
                      setShowXmlPreview(true)
                    }}
                  >
                    {v}
                  </code>
                ))}
              </div>
            </div>
          )}

          {analysis.coverage_gaps.length > 0 && (
            <div>
              <div className="text-xs font-medium mb-1">
                Coverage Gaps ({analysis.coverage_gaps.length})
              </div>
              <div className="space-y-1 max-h-32 overflow-y-auto">
                {analysis.coverage_gaps.slice(0, 10).map((gap, idx) => (
                  <div
                    key={idx}
                    className="text-xs bg-yellow-500/20 px-2 py-1 rounded cursor-pointer hover:bg-yellow-500/40"
                    onClick={() => {
                      setSearchTerm("")
                      setHighlightedGap({
                        afterStop: gap.after_stop,
                        beforeStart: gap.before_start,
                        afterProgram: gap.after_program,
                        beforeProgram: gap.before_program,
                      })
                      setShowXmlPreview(true)
                      setTimeout(() => {
                        if (previewRef.current) {
                          const mark = previewRef.current.querySelector(".bg-red-400\\/30, .bg-blue-400\\/30")
                          if (mark) {
                            mark.scrollIntoView({ behavior: "smooth", block: "center" })
                          }
                        }
                      }, 100)
                    }}
                  >
                    <strong>{gap.channel}</strong>: {gap.gap_minutes}min gap between "{gap.after_program}" and "{gap.before_program}"
                  </div>
                ))}
                {analysis.coverage_gaps.length > 10 && (
                  <div className="text-xs text-muted-foreground">
                    ... and {analysis.coverage_gaps.length - 10} more
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      ) : analysis ? (
        <div className="border border-green-500/30 bg-green-500/10 rounded-lg p-3">
          <div className="flex items-center gap-2 text-green-600 font-medium text-sm">
            <CheckCircle className="h-4 w-4" />
            No Issues Detected
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            All template variables resolved and no coverage gaps found.
          </p>
        </div>
      ) : null}

      {/* XML Preview Toggle */}
      <Card>
        <CardHeader
          className="cursor-pointer"
          onClick={() => setShowXmlPreview(!showXmlPreview)}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CardTitle>XML Preview</CardTitle>
              {epgContent && (
                <Badge variant="secondary">
                  {epgContent.total_lines} lines | {formatBytes(epgContent.size_bytes)}
                </Badge>
              )}
            </div>
            {showXmlPreview ? (
              <ChevronUp className="h-5 w-5" />
            ) : (
              <ChevronDown className="h-5 w-5" />
            )}
          </div>
        </CardHeader>
        {showXmlPreview && (
          <CardContent>
            {contentLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : epgContent?.content ? (
              <div className="space-y-2">
                {/* Search Bar */}
                <div className="flex items-center gap-2">
                  <div className="relative flex-1">
                    <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      placeholder="Search XML..."
                      value={searchTerm}
                      onChange={(e) => {
                        setSearchTerm(e.target.value)
                        setCurrentMatch(0)
                        setHighlightedGap(null)
                      }}
                      className="pl-8"
                    />
                  </div>
                  {highlightedGap && (
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-yellow-600">
                        Gap: "{highlightedGap.afterProgram}" → "{highlightedGap.beforeProgram}"
                      </span>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setHighlightedGap(null)}
                        className="h-6 px-2 text-xs"
                      >
                        Clear
                      </Button>
                    </div>
                  )}
                  {searchMatches.length > 0 && !highlightedGap && (
                    <div className="flex items-center gap-1">
                      <span className="text-sm text-muted-foreground">
                        {currentMatch + 1}/{searchMatches.length}
                      </span>
                      <Button variant="outline" size="sm" onClick={prevMatch}>
                        Prev
                      </Button>
                      <Button variant="outline" size="sm" onClick={nextMatch}>
                        Next
                      </Button>
                    </div>
                  )}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setShowLineNumbers(!showLineNumbers)}
                  >
                    {showLineNumbers ? "Hide" : "Show"} Lines
                  </Button>
                </div>

                {/* XML Content */}
                <pre
                  ref={previewRef}
                  className="bg-muted/50 rounded-lg p-4 text-xs font-mono overflow-auto max-h-[600px]"
                  dangerouslySetInnerHTML={{ __html: highlightedContent }}
                />
              </div>
            ) : (
              <div className="text-center py-8 text-muted-foreground">
                No XML content available. Generate EPG first.
              </div>
            )}
          </CardContent>
        )}
      </Card>

      {/* Recent Runs */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Runs</CardTitle>
          <CardDescription>Latest EPG generation runs (click Matched/Failed to view details)</CardDescription>
        </CardHeader>
        <CardContent>
          {runsLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : runsData?.runs.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              No runs recorded yet. Generate EPG to see history.
            </div>
          ) : (
            <RunHistoryTable
              runs={runsData?.runs ?? []}
              onFixStream={matcher.handleOpen}
            />
          )}
        </CardContent>
      </Card>

      {/* All-time Stats */}
      <Card>
        <CardHeader>
          <CardTitle>All-Time Totals</CardTitle>
        </CardHeader>
        <CardContent>
          {statsLoading ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
              <div>
                <span className="text-muted-foreground">Total Runs:</span>{" "}
                <strong>{stats?.total_runs ?? 0}</strong>
              </div>
              <div>
                <span className="text-muted-foreground">Programmes Generated:</span>{" "}
                <strong>{stats?.totals?.programmes_generated ?? 0}</strong>
              </div>
              <div>
                <span className="text-muted-foreground">Streams Matched:</span>{" "}
                <strong>{stats?.totals?.streams_matched ?? 0}</strong>
              </div>
              <div>
                <span className="text-muted-foreground">Channels Created:</span>{" "}
                <strong>{stats?.totals?.channels_created ?? 0}</strong>
              </div>
              <div>
                <span className="text-muted-foreground">Avg Duration:</span>{" "}
                <strong>{formatDuration(stats?.avg_duration_ms ?? 0)}</strong>
              </div>
              <div>
                <span className="text-muted-foreground">Last Run:</span>{" "}
                <strong>{formatRelativeTime(stats?.last_run ?? null)}</strong>
              </div>
              <div>
                <span className="text-muted-foreground">Cache Hits:</span>{" "}
                <strong>{stats?.totals?.streams_cached ?? 0}</strong>
              </div>
              <div>
                <span className="text-muted-foreground">Channels Deleted:</span>{" "}
                <strong>{stats?.totals?.channels_deleted ?? 0}</strong>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Event Matcher Modal */}
      <EventMatcherModal
        open={matcher.open}
        onOpenChange={matcher.setOpen}
        stream={matcher.stream}
        league={matcher.league}
        onLeagueChange={matcher.setLeague}
        targetDate={matcher.targetDate}
        onTargetDateChange={matcher.setTargetDate}
        events={matcher.events}
        loading={matcher.loading}
        submitting={matcher.submitting}
        selectedEventId={matcher.selectedEventId}
        onSelectEvent={matcher.setSelectedEventId}
        onSearch={matcher.handleSearch}
        onCorrect={matcher.handleCorrect}
        onSkip={matcher.handleSkip}
      />
    </div>
  )
}

// Helper function to escape HTML
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;")
}
