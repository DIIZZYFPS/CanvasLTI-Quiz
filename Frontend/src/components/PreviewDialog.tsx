import { AlertCircle, Download, Eye, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { ExportTarget } from "@/components/StatusPanel";
import type { CanvasState } from "@/hooks/useCanvasSession";
import { countErrors, formatQuestionType, pluralize, pointsLabel } from "@/lib/quiz";
import { cn } from "@/lib/utils";
import type { Question, SourceRange } from "@/types/quiz";

// Beyond this the summary would be a wall of text; the cards below still flag every error.
const MAX_LISTED_PROBLEMS = 5;

interface PreviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  quizTitle: string;
  questions: Question[];
  canvasState: CanvasState;
  /** True when the questions were pasted, so a problem can be pointed at in the textarea. */
  canShowInText: boolean;
  onExport: (target: ExportTarget) => void;
  onShowInText: (source: SourceRange) => void;
  onCloseAutoFocus?: (event: Event) => void;
}

const CANVAS_NOTES: Partial<Record<CanvasState, string>> = {
  expired: "Your Canvas session has expired. Relaunch the tool from your course to upload directly, or export the QTI file.",
  "no-course": "Couldn't tell which Canvas course this was opened from, so uploading directly isn't available.",
};

export function PreviewDialog({
  open,
  onOpenChange,
  quizTitle,
  questions,
  canvasState,
  canShowInText,
  onExport,
  onShowInText,
  onCloseAutoFocus,
}: PreviewDialogProps) {
  const total = questions.length;
  const errorCount = countErrors(questions);
  const problems = questions.map((question, index) => ({ question, index })).filter(({ question }) => question.type === "error");
  const blockedReason = errorCount > 0 ? "export-blocked-reason" : undefined;

  const jumpTo = (index: number) => {
    const card = document.getElementById(`preview-q-${index}`);
    if (!card) return;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    card.scrollIntoView({ block: "start", behavior: reduceMotion ? "auto" : "smooth" });
    card.focus({ preventScroll: true });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* `sm:max-w-3xl`, not `max-w-4xl`: the base dialog sets `sm:max-w-lg`, which silently
          beat the old unprefixed class and left the preview a cramped 512px column. */}
      <DialogContent
        className="sm:max-w-3xl max-h-[85vh] grid-rows-[auto_minmax(0,1fr)_auto]"
        onCloseAutoFocus={onCloseAutoFocus}
      >
        <DialogHeader className="text-left">
          <DialogTitle className="flex items-center gap-2 pr-6">
            <Eye className="size-5 shrink-0" aria-hidden="true" />
            <span className="truncate">Preview: {quizTitle || "Untitled quiz"}</span>
          </DialogTitle>
          <DialogDescription>Review your questions before exporting.</DialogDescription>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Badge variant="secondary">
              {total} {pluralize(total, "question")}
            </Badge>
            {errorCount > 0 ? (
              <Badge variant="destructive">
                {errorCount} {errorCount === 1 ? "needs" : "need"} fixing
              </Badge>
            ) : (
              <Badge variant="outline" className="border-success/40 text-success">
                All valid
              </Badge>
            )}
          </div>
        </DialogHeader>

        <ScrollArea className="min-h-0 pr-4">
          <div className="space-y-4">
            {errorCount > 0 && (
              <section aria-labelledby="preview-problems-title" className="space-y-3 rounded-lg border border-destructive/40 bg-destructive/5 p-4">
                <h3 id="preview-problems-title" className="flex items-center gap-2 text-sm font-semibold text-destructive-text">
                  <AlertCircle className="size-4" aria-hidden="true" />
                  {errorCount} {pluralize(errorCount, "question")} to fix before you can export
                </h3>
                <ul className="space-y-2 text-sm">
                  {problems.slice(0, MAX_LISTED_PROBLEMS).map(({ question, index }) => (
                    <li key={question.id} className="flex flex-wrap items-baseline gap-x-2">
                      <button
                        type="button"
                        onClick={() => jumpTo(index)}
                        className="rounded-sm font-medium underline underline-offset-2 hover:no-underline focus-visible:ring-[3px] focus-visible:ring-ring/50 outline-none"
                      >
                        Question {index + 1}
                      </button>
                      <span className="min-w-0 flex-1 text-foreground/80">{question.error}</span>
                    </li>
                  ))}
                </ul>
                {problems.length > MAX_LISTED_PROBLEMS && (
                  <p className="text-sm text-muted-foreground">
                    …and {problems.length - MAX_LISTED_PROBLEMS} more. Each is marked below.
                  </p>
                )}
              </section>
            )}

            {questions.map((question, index) => {
              const isError = question.type === "error";
              // Errors have no points; they used to show a bare "point" badge.
              const points = isError ? null : pointsLabel(question.points);
              return (
                <Card
                  key={question.id}
                  id={`preview-q-${index}`}
                  tabIndex={-1}
                  className={cn(
                    "border-l-4 scroll-mt-2 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
                    isError ? "border-l-destructive" : "border-l-primary"
                  )}
                >
                  <CardHeader className="pb-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex min-w-0 items-center gap-2">
                        <Badge variant="secondary" className="text-xs">
                          Question {index + 1}
                        </Badge>
                        {isError ? (
                          <Badge variant="destructive" className="text-xs">
                            Needs fixing
                          </Badge>
                        ) : (
                          <span className="truncate text-xs text-muted-foreground">{formatQuestionType(question.type)}</span>
                        )}
                      </div>
                      {points && (
                        <Badge variant="outline" className="text-xs">
                          {points}
                        </Badge>
                      )}
                    </div>
                  </CardHeader>
                  <CardContent className="pt-0 space-y-3">
                    <p className={cn("font-medium break-words", isError && "whitespace-pre-wrap")}>
                      {question.question_text || question.question}
                    </p>

                    {question.error && (
                      <div className="space-y-2 rounded border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive-text">
                        <p>{question.error}</p>
                        {canShowInText && question.source && (
                          <Button size="sm" variant="outline" onClick={() => onShowInText(question.source!)}>
                            Show in my text
                          </Button>
                        )}
                      </div>
                    )}

                    {/* Render answers if present */}
                    {Array.isArray(question.answers) && question.answers.length > 1 && (
                      <div className="space-y-1">
                        {question.answers.map((ans, optIndex: number) => {
                          const isCorrect =
                            ans.id === question.correct_answer_id ||
                            (question.correct_answer_ids && question.correct_answer_ids.includes(ans.id));
                          return (
                            <div
                              key={optIndex}
                              className={`p-2 rounded text-sm ${isCorrect ? "bg-green-400/10 border border-green-400/50" : "bg-muted/30"}`}
                            >
                              {ans.text}
                              {isCorrect && <span className="sr-only"> (correct answer)</span>}
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {/* FMB variables */}
                    {question.variables && (
                      <div className="space-y-2 mt-2">
                        <p className="text-sm font-medium text-primary">Variable Mappings:</p>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                          {Object.entries(question.variables).map(([key, vals]) => (
                            <div key={key} className="p-2 bg-muted/30 rounded text-xs">
                              <span className="font-bold">[{key}]:</span> {Array.isArray(vals) ? vals.join(", ") : vals}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Fallback for single answer */}
                    {question.answers && !question.variables && question.answers.length === 1 && (
                      <div className="text-sm">
                        <span className="font-medium text-primary">Answer: </span>
                        <span className="text-muted-foreground">
                          {question.correct_answer_id
                            ? question.answers.find((ans) => ans.id === question.correct_answer_id)?.text
                            : question.answers[0]?.text}
                        </span>
                      </div>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </ScrollArea>

        {/* Plain column on a phone (not the default reversed one, which would put the reason below
            the buttons): reason first, primary actions, then Cancel last. */}
        <DialogFooter className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-end">
          {errorCount > 0 ? (
            <p id="export-blocked-reason" className="text-sm text-destructive-text sm:mr-auto">
              Fix the {errorCount} {pluralize(errorCount, "error")} above to enable export.
            </p>
          ) : (
            CANVAS_NOTES[canvasState] && <p className="text-sm text-muted-foreground sm:mr-auto">{CANVAS_NOTES[canvasState]}</p>
          )}
          <Button variant="outline" onClick={() => onOpenChange(false)} className="order-last sm:order-none flex items-center gap-2">
            <X className="size-4" aria-hidden="true" />
            Cancel
          </Button>
          <Button
            onClick={() => onExport("qti")}
            className="flex items-center gap-2"
            disabled={errorCount > 0}
            aria-describedby={blockedReason}
          >
            <Download className="size-4" aria-hidden="true" />
            Export QTI
          </Button>
          {canvasState === "connected" && (
            <Button
              onClick={() => onExport("canvas")}
              className="flex items-center gap-2"
              disabled={errorCount > 0}
              aria-describedby={blockedReason}
            >
              <Download className="size-4" aria-hidden="true" />
              Upload to Canvas
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
