import { AxiosError, type AxiosResponse } from "axios";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import api from "@/api";
import Dashboard from "@/components/Dashboard";
import type { Question } from "@/types/quiz";

vi.mock("@/api", () => ({ default: { get: vi.fn(), post: vi.fn() } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() } }));

const get = vi.mocked(api.get);
const post = vi.mocked(api.post);

const QUIZ = "What is 2+2?\nA) 3\nB) 4\nAnswer: B";
const valid: Question[] = [
  {
    id: "q1",
    type: "multiple_choice_question",
    question_text: "What is 2+2?",
    points: "1",
    answers: [
      { id: "a1", text: "3" },
      { id: "a2", text: "4" },
    ],
    correct_answer_id: "a2",
  },
];
const withProblem: Question[] = [
  ...valid,
  { id: "q2", type: "error", question: "Broken", error: "No correct answer", source: { start: 5, end: 11 } },
];

interface Server {
  session?: { connected: boolean; course_id: string | null };
  preview?: Question[];
  progress?: Array<{ workflow_state: string; completion?: number }>;
  canvasProgressId?: string | null;
}

/** Stand in for the Flask API. Anything not described here is a 404. */
function serve({ session = { connected: false, course_id: null }, preview = valid, progress = [], canvasProgressId = "55" }: Server = {}) {
  const polls = [...progress];
  get.mockImplementation(async (url: string) => {
    if (url === "/session") return { data: { canvas: session } };
    if (url === "/proxy/progress") return { data: polls.length > 1 ? polls.shift() : polls[0] };
    throw new Error("unexpected GET " + url);
  });
  post.mockImplementation(async (url: string) => {
    if (url === "/preview") return { data: { questions: preview } };
    if (url === "/download") return { data: new Blob(["zip"]) };
    if (url === "/canvas") return { data: { progress_id: canvasProgressId } };
    throw new Error("unexpected POST " + url);
  });
}

function httpError(status: number, data: unknown = {}): AxiosError {
  const response = { data, status, statusText: "", headers: {}, config: {} } as AxiosResponse;
  return new AxiosError(`Request failed with status code ${status}`, "ERR_BAD_REQUEST", undefined, undefined, response);
}

const user = () => userEvent.setup();
const checkButton = () => screen.getByRole("button", { name: /check syntax and preview/i }) as HTMLButtonElement;
const textarea = () => screen.getByLabelText("Paste quiz content:") as HTMLTextAreaElement;
const status = () => screen.getByRole("status");

async function fill(u: ReturnType<typeof user>, { text = QUIZ, title = "Week 3" } = {}) {
  if (text) {
    await u.click(textarea());
    await u.paste(text);
  }
  if (title) await u.type(screen.getByLabelText("Quiz title"), title);
}

async function check(u: ReturnType<typeof user>) {
  await u.click(checkButton());
  return screen.findByRole("dialog");
}

beforeEach(() => {
  serve();
  URL.createObjectURL = vi.fn(() => "blob:quiz");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("checking a quiz", () => {
  it("cannot be started until there are questions and a title, and says which is missing", async () => {
    const u = user();
    render(<Dashboard />);
    expect(checkButton().disabled).toBe(true);
    expect(screen.getByText("Paste your questions to check them.")).toBeTruthy();

    await u.click(textarea());
    await u.paste(QUIZ);
    expect(checkButton().disabled).toBe(true);
    expect(screen.getByText("Give your quiz a title to continue.")).toBeTruthy();

    await u.type(screen.getByLabelText("Quiz title"), "Week 3");
    expect(checkButton().disabled).toBe(false);
    expect(screen.queryByText(/to continue|to check them/)).toBeNull();
  });

  it("sends the pasted text and title, then opens the preview", async () => {
    const u = user();
    render(<Dashboard />);
    await fill(u);
    const dialog = await check(u);

    expect(post).toHaveBeenCalledWith("/preview", { quiz_title: "Week 3", quiz_text: QUIZ });
    expect(within(dialog).getByText("Preview: Week 3")).toBeTruthy();
    expect(toast.success).toHaveBeenCalledWith("1 question ready");
  });

  it("warns, rather than celebrates, when some questions have problems", async () => {
    serve({ preview: withProblem });
    const u = user();
    render(<Dashboard />);
    await fill(u);
    await check(u);
    expect(toast.warning).toHaveBeenCalledWith("1 of 2 questions need fixing");
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("says so when nothing could be parsed, without opening an empty preview", async () => {
    serve({ preview: [] });
    const u = user();
    render(<Dashboard />);
    await fill(u);
    await u.click(checkButton());
    await waitFor(() => expect(status().textContent).toContain("No questions were found"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows the server's reason when the check fails", async () => {
    post.mockRejectedValueOnce(httpError(400, { error: "Quiz text is too long" }));
    const u = user();
    render(<Dashboard />);
    await fill(u);
    await u.click(checkButton());
    await waitFor(() => expect(status().textContent).toContain("Quiz text is too long"));
    expect(toast.error).toHaveBeenCalledWith("Quiz text is too long");
    expect(checkButton().disabled).toBe(false);
  });
});

describe("a preview only describes the input it was made from", () => {
  async function previewed() {
    const u = user();
    render(<Dashboard />);
    await fill(u);
    await check(u);
    await u.click(screen.getByRole("button", { name: /cancel/i }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(status().textContent).toContain("1 question ready to export.");
    return u;
  }

  it("is discarded when the text is edited", async () => {
    const u = await previewed();
    await u.type(textarea(), " more");
    expect(status().textContent).toContain("Check your syntax to preview");
    expect(screen.queryByRole("button", { name: /review & export/i })).toBeNull();
  });

  it("is kept when only the title changes (the title is read at export time)", async () => {
    const u = await previewed();
    await u.type(screen.getByLabelText("Quiz title"), "!");
    expect(status().textContent).toContain("1 question ready to export.");
  });

  it("is discarded when switching between pasting and uploading", async () => {
    const u = await previewed();
    await u.click(screen.getByLabelText("Upload a file"));
    expect(status().textContent).toContain("Check your syntax to preview");
    await u.click(screen.getByLabelText("Paste text"));
    expect(status().textContent).toContain("Check your syntax to preview");
  });

  it("can be reopened from the status panel", async () => {
    const u = await previewed();
    await u.click(screen.getByRole("button", { name: /review & export/i }));
    expect(await screen.findByRole("dialog")).toBeTruthy();
  });
});

describe("choosing between text and a file", () => {
  it("uses only the file when in file mode, and tells the user the text is being ignored", async () => {
    const u = user();
    render(<Dashboard />);
    await fill(u);
    await u.click(screen.getByLabelText("Upload a file"));
    expect(screen.getByText(/pasted text is kept, but only the uploaded file will be checked/i)).toBeTruthy();
    expect(screen.getByText("Choose a file to check.")).toBeTruthy();

    const file = new File([QUIZ], "quiz.txt", { type: "text/plain" });
    await u.upload(document.getElementById("file-upload") as HTMLInputElement, file);
    expect(screen.getByText("quiz.txt")).toBeTruthy();
    const dialog = await check(u);

    const [url, body] = post.mock.calls[0];
    expect(url).toBe("/preview");
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).get("file")).toBe(file);
    expect((body as FormData).get("quiz_title")).toBe("Week 3");
    expect((body as FormData).has("quiz_text")).toBe(false);
    expect(dialog).toBeTruthy();
  });

  it("remembers the file when going back to text, and says only the text will be checked", async () => {
    const u = user();
    render(<Dashboard />);
    await u.click(screen.getByLabelText("Upload a file"));
    await u.upload(document.getElementById("file-upload") as HTMLInputElement, new File(["x"], "quiz.txt"));
    await u.click(screen.getByLabelText("Paste text"));
    expect(screen.getByText(/your file "quiz.txt" is kept, but only the pasted text will be checked/i)).toBeTruthy();
  });

  it("rejects an unsupported file type", async () => {
    // The picker's `accept` filter can be bypassed ("All files", drag and drop), so the check must hold anyway.
    const u = userEvent.setup({ applyAccept: false });
    render(<Dashboard />);
    await u.click(screen.getByLabelText("Upload a file"));
    await u.upload(document.getElementById("file-upload") as HTMLInputElement, new File(["x"], "quiz.exe"));
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("Unsupported file type '.exe'"));
    expect(screen.queryByText("quiz.exe")).toBeNull();
  });

  it("shows a problem in the text only when the questions were pasted", async () => {
    serve({ preview: withProblem });
    const u = user();
    render(<Dashboard />);
    await fill(u);
    const dialog = await check(u);
    expect(within(dialog).getByRole("button", { name: "Show in my text" })).toBeTruthy();
  });

  it("selects the offending text in the textarea", async () => {
    serve({ preview: withProblem });
    const u = user();
    render(<Dashboard />);
    await fill(u);
    const dialog = await check(u);
    await u.click(within(dialog).getByRole("button", { name: "Show in my text" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(textarea()));
    expect([textarea().selectionStart, textarea().selectionEnd]).toEqual([5, 11]);
  });
});

describe("exporting a QTI file", () => {
  async function exportQti(u: ReturnType<typeof user>) {
    const dialog = await check(u);
    await u.click(within(dialog).getByRole("button", { name: /export qti/i }));
  }

  it("downloads the zip under the quiz title and reports exactly that", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const u = user();
    render(<Dashboard />);
    await fill(u);
    await exportQti(u);

    await waitFor(() => expect(status().textContent).toContain("QTI package downloaded."));
    expect(post).toHaveBeenLastCalledWith("/download", { quiz_title: "Week 3", quiz_text: QUIZ }, { responseType: "blob" });
    expect(click).toHaveBeenCalledTimes(1);
    expect(click.mock.contexts[0]).toMatchObject({ download: "Week 3.zip" });
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:quiz");
    expect(toast.success).toHaveBeenLastCalledWith("QTI package downloaded");
    click.mockRestore();
  });

  it("shows the reason from a failed download, which arrives as a blob", async () => {
    const body = new Blob([JSON.stringify({ error: "Question 2 has no correct answer" })], { type: "application/json" });
    post.mockImplementation(async (url: string) => {
      if (url === "/preview") return { data: { questions: valid } };
      throw httpError(400, body);
    });
    const u = user();
    render(<Dashboard />);
    await fill(u);
    await exportQti(u);

    await waitFor(() => expect(status().textContent).toContain("Question 2 has no correct answer"));
    // The preview is still there to try again from.
    expect(screen.getByRole("button", { name: /review & export/i })).toBeTruthy();
  });
});

describe("uploading to Canvas", () => {
  const connected = { connected: true, course_id: "4242" };

  async function uploadToCanvas(u: ReturnType<typeof user>) {
    const dialog = await check(u);
    await u.click(within(dialog).getByRole("button", { name: /upload to canvas/i }));
  }

  it("shows the connection the server reports", async () => {
    serve({ session: connected });
    render(<Dashboard />);
    expect(await screen.findByText("Canvas Connected")).toBeTruthy();
    expect(screen.getByRole("banner").textContent).toContain("4242");
  });

  it("falls back to standalone when the session can't be read", async () => {
    get.mockRejectedValue(new Error("offline"));
    render(<Dashboard />);
    await waitFor(() => expect(screen.queryByText("Canvas Connected")).toBeNull());
    expect(screen.getByRole("banner").textContent).not.toMatch(/connected/i);
  });

  it("sends nothing about the course or token, then follows the progress id", async () => {
    serve({ session: connected, progress: [{ workflow_state: "completed", completion: 100 }] });
    const u = user();
    render(<Dashboard />);
    await screen.findByText("Canvas Connected");
    await fill(u);
    await uploadToCanvas(u);

    await waitFor(() => expect(status().textContent).toContain("Uploaded to Canvas. It can take a minute"));
    expect(status().textContent).not.toMatch(/converted/i);
    expect(post).toHaveBeenLastCalledWith("/canvas", { quiz_title: "Week 3", quiz_text: QUIZ });
    expect(get).toHaveBeenCalledWith("/proxy/progress", { params: { id: "55" } });
    expect(toast.success).toHaveBeenLastCalledWith("Uploaded to Canvas");
  });

  it("shows Canvas' real progress while it works", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    serve({
      session: connected,
      progress: [
        { workflow_state: "running", completion: 50 },
        { workflow_state: "completed", completion: 100 },
      ],
    });
    const u = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<Dashboard />);
    await screen.findByText("Canvas Connected");
    await fill(u);
    await uploadToCanvas(u);

    // 30% for handing the file over, plus 70% of Canvas' own 50%.
    await waitFor(() => expect(status().textContent).toContain("Uploading to Canvas… 65%"));
    await vi.advanceTimersByTimeAsync(2000);
    await waitFor(() => expect(status().textContent).toContain("Uploaded to Canvas."));
  });

  it("reports a migration that Canvas failed to process", async () => {
    serve({ session: connected, progress: [{ workflow_state: "failed" }] });
    const u = user();
    render(<Dashboard />);
    await screen.findByText("Canvas Connected");
    await fill(u);
    await uploadToCanvas(u);
    await waitFor(() => expect(status().textContent).toContain("Canvas couldn't process the QTI package."));
    expect(status().textContent).not.toContain("Uploaded to Canvas.");
  });

  it("does not pretend to succeed when Canvas gives no progress id", async () => {
    serve({ session: connected, canvasProgressId: null });
    const u = user();
    render(<Dashboard />);
    await screen.findByText("Canvas Connected");
    await fill(u);
    await uploadToCanvas(u);
    await waitFor(() => expect(status().textContent).toContain("didn't return a progress id"));
  });

  it("treats a 401 as an expired session: says so, offers QTI, and updates the badge", async () => {
    serve({ session: connected });
    const u = user();
    render(<Dashboard />);
    await screen.findByText("Canvas Connected");
    await fill(u);

    // The token dies between the page loading and the upload.
    post.mockImplementation(async (url: string) => {
      if (url === "/preview") return { data: { questions: valid } };
      throw httpError(401, { error: "Canvas authorization is no longer valid" });
    });
    get.mockImplementation(async () => ({ data: { canvas: { connected: false, course_id: "4242" } } }));
    await uploadToCanvas(u);

    await waitFor(() => expect(status().textContent).toContain("Your Canvas session has expired"));
    expect(status().textContent).toContain("you can still download the QTI file");
    expect(await screen.findByText("Canvas session expired")).toBeTruthy();
    expect(screen.queryByText("Canvas Connected")).toBeNull();

    await u.click(screen.getByRole("button", { name: /review & export/i }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByRole("button", { name: /upload to canvas/i })).toBeNull();
    expect(within(dialog).getByRole("button", { name: /export qti/i }).hasAttribute("disabled")).toBe(false);
  });
});
