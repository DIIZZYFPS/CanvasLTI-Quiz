import { AlertCircle, CheckCircle2, Eye, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { countErrors, pluralize } from "@/lib/quiz";
import type { Question } from "@/types/quiz";

export type Phase = "idle" | "parsing" | "exporting" | "error";
export type ExportTarget = "qti" | "canvas";

interface StatusPanelProps {
  phase: Phase;
  exportTarget: ExportTarget | null;
  /** 0-100, only used for the Canvas upload. */
  progress: number;
  /** The last successful syntax check, or null when there is none (or it has gone stale). */
  questions: Question[] | null;
  /** What was last exported successfully from the current preview. */
  result: ExportTarget | null;
  errorMessage: string | null;
  onReview: () => void;
}

const RESULT_TEXT: Record<ExportTarget, string> = {
  qti: "QTI package downloaded.",
  canvas: "Uploaded to Canvas. It can take a minute to appear in your course.",
};

/**
 * Shows what is happening and what happened, right under the button that caused it.
 * (It used to be a separate card in the far column, which on a phone sat below the fold,
 * so tapping the button appeared to do nothing.) It says what actually occurred: it no
 * longer claims "converted to QTI" after a syntax check, or after a Canvas upload.
 */
export function StatusPanel({ phase, exportTarget, progress, questions, result, errorMessage, onReview }: StatusPanelProps) {
  return (
    <div role="status" aria-live="polite" className="text-sm">
      <Body
        phase={phase}
        exportTarget={exportTarget}
        progress={progress}
        questions={questions}
        result={result}
        errorMessage={errorMessage}
        onReview={onReview}
      />
    </div>
  );
}

function Body({ phase, exportTarget, progress, questions, result, errorMessage, onReview }: StatusPanelProps) {
  if (phase === "parsing") {
    return (
      <Message tone="neutral" icon={<Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />}>
        Checking your questions…
      </Message>
    );
  }

  if (phase === "exporting") {
    if (exportTarget === "canvas") {
      return (
        <div className="space-y-2 rounded-lg border bg-muted/40 p-3">
          <div className="flex items-center gap-2">
            <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
            <span>Uploading to Canvas… {Math.round(progress)}%</span>
          </div>
          <Progress value={progress} aria-label="Canvas upload progress" />
        </div>
      );
    }
    return (
      <Message tone="neutral" icon={<Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />}>
        Preparing your download…
      </Message>
    );
  }

  // A failed export must not strand the user: the preview is still valid, so keep offering
  // it below the error (the message often says "you can still download the QTI file").
  const failure =
    phase === "error" && errorMessage ? (
      <Message tone="error" icon={<AlertCircle className="size-4" aria-hidden="true" />}>
        {errorMessage}
      </Message>
    ) : null;

  if (questions) {
    const total = questions.length;
    const errors = countErrors(questions);
    return (
      <div className="space-y-2">
        {failure}
        {result && (
          <Message tone="success" icon={<CheckCircle2 className="size-4" aria-hidden="true" />}>
            {RESULT_TEXT[result]}
          </Message>
        )}
        {errors > 0 ? (
          <Message
            tone="error"
            icon={<AlertCircle className="size-4" aria-hidden="true" />}
            action={
              <Button size="sm" variant="outline" onClick={onReview}>
                <Eye aria-hidden="true" /> Review problems
              </Button>
            }
          >
            {total - errors} of {total} {pluralize(total, "question")} ready, {errors} {errors === 1 ? "needs" : "need"} fixing.
          </Message>
        ) : (
          <Message
            tone={result ? "neutral" : "success"}
            icon={<CheckCircle2 className="size-4" aria-hidden="true" />}
            action={
              <Button size="sm" variant="outline" onClick={onReview}>
                <Eye aria-hidden="true" /> {result ? "Export again" : "Review & export"}
              </Button>
            }
          >
            {total} {pluralize(total, "question")} ready to export.
          </Message>
        )}
      </div>
    );
  }

  if (failure) return failure;

  return <p className="text-muted-foreground">Check your syntax to preview the questions before exporting.</p>;
}

const TONES = {
  neutral: "border-border bg-muted/40",
  success: "border-success/30 bg-success/10",
  error: "border-destructive/40 bg-destructive/10",
} as const;

function Message({
  tone,
  icon,
  action,
  children,
}: {
  tone: keyof typeof TONES;
  icon: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className={`flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border p-3 ${TONES[tone]}`}>
      <span className="mt-0.5 shrink-0 self-start">{icon}</span>
      <span className="min-w-0 flex-1 basis-48 break-words">{children}</span>
      {action}
    </div>
  );
}
