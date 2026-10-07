import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { useRef, useState } from "react";
import { ClipboardPaste, FileText, FileUp, Loader2, Moon, Sun, Upload } from "lucide-react";
import axios from "axios";
import { toast } from "sonner";
import api from "@/api";
import { useTheme } from "@/components/ui/theme-provider";
import { FileUpload } from "@/components/FileUpload";
import { FormattingGuide } from "@/components/FormattingGuide";
import { CanvasStatusPill } from "@/components/CanvasStatusPill";
import { PreviewDialog } from "@/components/PreviewDialog";
import { StatusPanel, type ExportTarget, type Phase } from "@/components/StatusPanel";
import { useCanvasSession } from "@/hooks/useCanvasSession";
import { readApiError } from "@/lib/errors";
import { countErrors, pluralize } from "@/lib/quiz";
import { revealTextareaOffset } from "@/lib/textarea";
import type { Question, SourceRange } from "@/types/quiz";

type InputMode = "text" | "file";

const MAX_POLL_ATTEMPTS = 60; // ~2 minutes at one poll every 2 seconds
const POLL_INTERVAL_MS = 2000;
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const Dashboard = () => {
  const [inputMode, setInputMode] = useState<InputMode>("text");
  const [quizContent, setQuizContent] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [quizTitle, setQuizTitle] = useState("");

  // The last successful syntax check. null means "no preview", including when the input
  // has changed since and the old preview is no longer trustworthy.
  const [questions, setQuestions] = useState<Question[] | null>(null);
  const [showPreview, setShowPreview] = useState(false);

  const [phase, setPhase] = useState<Phase>("idle");
  const [exportTarget, setExportTarget] = useState<ExportTarget | null>(null);
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState<ExportTarget | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const { theme, setTheme } = useTheme();
  const canvas = useCanvasSession();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const skipFocusRestore = useRef(false);

  const busy = phase === "parsing" || phase === "exporting";
  const hasInput = inputMode === "file" ? selectedFile !== null : quizContent.trim().length > 0;
  const canCheck = hasInput && quizTitle.trim().length > 0 && !busy;

  let checkHint: string | null = null;
  if (!hasInput) checkHint = inputMode === "file" ? "Choose a file to check." : "Paste your questions to check them.";
  else if (!quizTitle.trim()) checkHint = "Give your quiz a title to continue.";

  // A preview is only valid for the exact input it was parsed from, and export re-reads the
  // *current* input. So any change to the input discards the preview; otherwise the user
  // could export questions (or errors) they never reviewed. Inputs are locked while a
  // request is in flight, so this never races one.
  const discardPreview = () => {
    if (questions === null && result === null && errorMessage === null) return;
    setQuestions(null);
    setResult(null);
    setErrorMessage(null);
    setShowPreview(false);
    if (phase === "error") setPhase("idle");
  };

  const changeMode = (mode: InputMode) => {
    setInputMode(mode);
    discardPreview();
  };

  // What the server should read: the uploaded file or the pasted text, never both.
  const buildBody = (): FormData | Record<string, string> => {
    if (inputMode === "file" && selectedFile) {
      const form = new FormData();
      form.append("file", selectedFile);
      form.append("quiz_title", quizTitle);
      return form;
    }
    return { quiz_title: quizTitle, quiz_text: quizContent };
  };

  const handleCheck = async () => {
    if (!canCheck) return;
    discardPreview();
    setPhase("parsing");
    try {
      const { data } = await api.post<{ questions: Question[] }>("/preview", buildBody());
      const parsed = data.questions ?? [];
      if (parsed.length === 0) {
        setPhase("error");
        setErrorMessage("No questions were found. Check that a blank line separates each question.");
        return;
      }
      setQuestions(parsed);
      setPhase("idle");
      setShowPreview(true);

      const bad = countErrors(parsed);
      const noun = pluralize(parsed.length, "question");
      if (bad > 0) toast.warning(`${bad} of ${parsed.length} ${noun} need fixing`);
      else toast.success(`${parsed.length} ${noun} ready`);
    } catch (err) {
      const message = await readApiError(err, "Failed to check your questions.");
      setPhase("error");
      setErrorMessage(message);
      toast.error(message);
    }
  };

  const downloadQti = async () => {
    const response = await api.post<Blob>("/download", buildBody(), { responseType: "blob" });
    const url = URL.createObjectURL(new Blob([response.data], { type: "application/zip" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${quizTitle.trim() || "quiz"}.zip`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const uploadToCanvas = async () => {
    // The course and the token come from the server-side session; nothing about either is sent.
    const response = await api.post<{ progress_id: string | null }>("/canvas", buildBody());
    const progressId = response.data.progress_id;
    if (!progressId) throw new Error("Canvas didn't return a progress id for the upload.");
    setProgress(30);

    for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt++) {
      // Polled through our server to avoid CORS; the progress id is all the client supplies.
      const { data } = await api.get("/proxy/progress", { params: { id: progressId } });
      const raw = data.completion;
      const completion = typeof raw === "number" && raw >= 0 && raw <= 100 ? raw : 0;
      setProgress(30 + completion * 0.7); // scale 0-100 into the 30-100% part of the bar

      if (data.workflow_state === "completed") return;
      if (data.workflow_state === "failed") throw new Error("Canvas couldn't process the QTI package.");
      await sleep(POLL_INTERVAL_MS);
    }
    throw new Error("Canvas is taking longer than expected. Check your course in a minute; the quiz may still appear.");
  };

  const handleExport = async (target: ExportTarget) => {
    if (busy || questions === null) return;
    setShowPreview(false);
    setPhase("exporting");
    setExportTarget(target);
    setProgress(target === "canvas" ? 10 : 0);
    setResult(null);
    setErrorMessage(null);

    try {
      if (target === "qti") await downloadQti();
      else await uploadToCanvas();
      setResult(target);
      setPhase("idle");
      toast.success(target === "qti" ? "QTI package downloaded" : "Uploaded to Canvas");
    } catch (err) {
      let message: string;
      if (axios.isAxiosError(err) && err.response?.status === 401) {
        void canvas.refresh(); // the header badge should stop claiming we're connected
        message =
          "Your Canvas session has expired. Close and relaunch the tool from your course to upload directly; you can still download the QTI file.";
      } else {
        message = await readApiError(err, "Export failed.");
      }
      setPhase("error");
      setErrorMessage(message);
      toast.error(message);
    } finally {
      setExportTarget(null);
    }
  };

  // Close the preview and select the offending question in the user's own textarea.
  const showInText = (source: SourceRange) => {
    skipFocusRestore.current = true; // don't let the dialog hand focus back to the button
    setShowPreview(false);
    requestAnimationFrame(() => {
      const textarea = textareaRef.current;
      if (!textarea) return;
      textarea.focus({ preventScroll: true });
      textarea.setSelectionRange(source.start, source.end);
      revealTextareaOffset(textarea, source.start);
    });
  };

  const handleDialogCloseAutoFocus = (event: Event) => {
    if (skipFocusRestore.current) {
      event.preventDefault();
      skipFocusRestore.current = false;
    }
  };

  // Tell people which input is in use when the other still holds something.
  let unusedInputNote: string | null = null;
  if (inputMode === "text" && selectedFile) unusedInputNote = `Your file "${selectedFile.name}" is kept, but only the pasted text will be checked.`;
  if (inputMode === "file" && quizContent.trim()) unusedInputNote = "Your pasted text is kept, but only the uploaded file will be checked.";

  return (
    <div className="min-h-screen bg-muted/40 dark:bg-background">
      {/* Header: title + toggle share the first row; on a phone the Canvas badge drops to its own row
          instead of wrapping its text, and the (then two-row) header scrolls away rather than
          sticking, so it doesn't eat a sixth of a small screen. */}
      <header className="border-b bg-card/80 backdrop-blur-sm sm:sticky sm:top-0 z-10">
        <div className="container mx-auto px-4 sm:px-6 py-4">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
            <div className="order-1 flex min-w-0 flex-1 items-center gap-3">
              <div className="w-10 h-10 shrink-0 bg-primary text-primary-foreground rounded-lg flex items-center justify-center">
                <FileText className="w-6 h-6" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <h1 className="text-xl font-bold truncate">Quiz to QTI Converter</h1>
                <p className="hidden lg:block text-sm text-muted-foreground">Convert Canvas quiz questions to QTI format</p>
              </div>
            </div>
            <div className="order-3 basis-full sm:order-2 sm:basis-auto">
              <CanvasStatusPill state={canvas.state} courseId={canvas.courseId} />
            </div>
            <Button
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              variant="ghost"
              size="icon"
              className="order-2 sm:order-3"
              aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            >
              {theme === "dark" ? <Sun className="w-4 h-4" aria-hidden="true" /> : <Moon className="w-4 h-4" aria-hidden="true" />}
            </Button>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 sm:px-6 py-8 max-w-6xl">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          <div className="lg:col-span-2 space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Upload className="w-5 h-5" aria-hidden="true" />
                  Your Questions
                </CardTitle>
                <CardDescription>Paste your quiz questions or upload a file, then check the syntax to preview them.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <InputModeSwitch mode={inputMode} onChange={changeMode} disabled={busy} />

                {inputMode === "text" ? (
                  <div className="space-y-3">
                    <label htmlFor="quiz-content" className="text-sm font-medium">
                      Paste quiz content:
                    </label>
                    <Textarea
                      id="quiz-content"
                      ref={textareaRef}
                      placeholder="Paste your quiz questions here..."
                      className="min-h-[200px]"
                      value={quizContent}
                      disabled={busy}
                      onChange={(e) => {
                        setQuizContent(e.target.value);
                        discardPreview();
                      }}
                    />
                  </div>
                ) : (
                  <FileUpload
                    file={selectedFile}
                    disabled={busy}
                    onChange={(file) => {
                      setSelectedFile(file);
                      discardPreview();
                    }}
                  />
                )}

                {unusedInputNote && <p className="text-sm text-muted-foreground">{unusedInputNote}</p>}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Quiz Details</CardTitle>
                <CardDescription>Name your quiz, then check your questions before exporting.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <label htmlFor="quiz-title" className="text-sm font-medium">
                    Quiz title
                  </label>
                  <Input
                    id="quiz-title"
                    placeholder="e.g. Week 3 Quiz"
                    required
                    aria-required="true"
                    value={quizTitle}
                    onChange={(e) => setQuizTitle(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Button
                    onClick={handleCheck}
                    disabled={!canCheck}
                    size="lg"
                    className="w-full"
                    aria-describedby={checkHint ? "check-hint" : undefined}
                  >
                    {phase === "parsing" ? (
                      <>
                        <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden="true" /> Checking…
                      </>
                    ) : (
                      "Check Syntax and Preview"
                    )}
                  </Button>
                  {checkHint && (
                    <p id="check-hint" className="text-sm text-muted-foreground">
                      {checkHint}
                    </p>
                  )}
                </div>

                <StatusPanel
                  phase={phase}
                  exportTarget={exportTarget}
                  progress={progress}
                  questions={questions}
                  result={result}
                  errorMessage={errorMessage}
                  onReview={() => setShowPreview(true)}
                />
              </CardContent>
            </Card>
          </div>

          <div className="space-y-6">
            <FormattingGuide />
          </div>
        </div>
      </main>

      {questions && (
        <PreviewDialog
          open={showPreview}
          onOpenChange={setShowPreview}
          quizTitle={quizTitle.trim()}
          questions={questions}
          canvasState={canvas.state}
          canShowInText={inputMode === "text"}
          onExport={handleExport}
          onShowInText={showInText}
          onCloseAutoFocus={handleDialogCloseAutoFocus}
        />
      )}
    </div>
  );
};

/**
 * "Paste text" / "Upload a file" as a native radio group: arrow keys move between the two and
 * screen readers announce it properly. Exactly one source is ever used, which removes the old
 * state where both could be filled in and the conflict was only reported after the fact.
 */
function InputModeSwitch({ mode, onChange, disabled }: { mode: InputMode; onChange: (mode: InputMode) => void; disabled: boolean }) {
  const options: { value: InputMode; label: string; icon: React.ReactNode }[] = [
    { value: "text", label: "Paste text", icon: <ClipboardPaste className="size-4" aria-hidden="true" /> },
    { value: "file", label: "Upload a file", icon: <FileUp className="size-4" aria-hidden="true" /> },
  ];
  return (
    <fieldset disabled={disabled} className="min-w-0">
      <legend className="sr-only">How do you want to add your questions?</legend>
      <div className="inline-flex rounded-lg bg-muted p-1">
        {options.map((option) => (
          <label key={option.value} className="relative cursor-pointer has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50">
            <input
              type="radio"
              name="input-mode"
              value={option.value}
              checked={mode === option.value}
              onChange={() => onChange(option.value)}
              className="peer sr-only"
            />
            <span className="flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium text-foreground/70 transition-colors peer-checked:bg-background peer-checked:text-foreground peer-checked:shadow-sm peer-focus-visible:ring-[3px] peer-focus-visible:ring-ring/50">
              {option.icon}
              {option.label}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export default Dashboard;
