import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PreviewDialog } from "@/components/PreviewDialog";
import type { CanvasState } from "@/hooks/useCanvasSession";
import type { Question } from "@/types/quiz";

const multipleChoice: Question = {
  id: "q1",
  type: "multiple_choice_question",
  question_text: "What is 2+2?",
  points: "2",
  answers: [
    { id: "a1", text: "3" },
    { id: "a2", text: "4" },
  ],
  correct_answer_id: "a2",
};

const broken = (id: string, error: string, extra: Partial<Question> = {}): Question => ({
  id,
  type: "error",
  question: "Which planet is red?",
  error,
  ...extra,
});

type Props = Parameters<typeof PreviewDialog>[0];

function renderDialog(questions: Question[], overrides: Partial<Props> = {}) {
  const props: Props = {
    open: true,
    onOpenChange: vi.fn(),
    quizTitle: "Week 3",
    questions,
    canvasState: "standalone" as CanvasState,
    canShowInText: true,
    onExport: vi.fn(),
    onShowInText: vi.fn(),
    ...overrides,
  };
  render(<PreviewDialog {...props} />);
  return props;
}

const dialog = () => screen.getByRole("dialog");

describe("PreviewDialog with valid questions", () => {
  it("summarises the quiz and marks the correct answer for screen readers", () => {
    renderDialog([multipleChoice]);
    expect(within(dialog()).getByText("Preview: Week 3")).toBeTruthy();
    expect(within(dialog()).getByText("1 question")).toBeTruthy();
    expect(within(dialog()).getByText("All valid")).toBeTruthy();
    expect(within(dialog()).getByText("2 points")).toBeTruthy();
    expect(within(dialog()).getByText("Multiple choice")).toBeTruthy();
    expect(within(dialog()).getByText("(correct answer)").parentElement?.textContent).toContain("4");
  });

  it("falls back to a name for an untitled quiz", () => {
    renderDialog([multipleChoice], { quizTitle: "" });
    expect(within(dialog()).getByText("Preview: Untitled quiz")).toBeTruthy();
  });

  it("exports as QTI", async () => {
    const props = renderDialog([multipleChoice]);
    await userEvent.click(screen.getByRole("button", { name: /export qti/i }));
    expect(props.onExport).toHaveBeenCalledWith("qti");
  });

  it("closes from Cancel", async () => {
    const props = renderDialog([multipleChoice]);
    await userEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(props.onOpenChange).toHaveBeenCalledWith(false);
  });

  it("lists the variables of a fill-in-multiple-blanks question", () => {
    renderDialog([
      {
        id: "q2",
        type: "fill_in_multiple_blanks_question",
        question_text: "The [color] sky",
        variables: { color: ["blue", "azure"] },
      },
    ]);
    expect(within(dialog()).getByText("[color]:").parentElement?.textContent).toContain("blue, azure");
  });
});

describe("PreviewDialog Canvas upload", () => {
  it("offers the upload only while connected", async () => {
    const props = renderDialog([multipleChoice], { canvasState: "connected" });
    await userEvent.click(screen.getByRole("button", { name: /upload to canvas/i }));
    expect(props.onExport).toHaveBeenCalledWith("canvas");
  });

  it.each(["standalone", "loading"] as CanvasState[])("does not offer it when %s", (canvasState) => {
    renderDialog([multipleChoice], { canvasState });
    expect(screen.queryByRole("button", { name: /upload to canvas/i })).toBeNull();
    expect(screen.getByRole("button", { name: /export qti/i })).toBeTruthy();
  });

  it("explains an expired session instead of silently dropping the button", () => {
    renderDialog([multipleChoice], { canvasState: "expired" });
    expect(screen.queryByRole("button", { name: /upload to canvas/i })).toBeNull();
    expect(dialog().textContent).toMatch(/canvas session has expired/i);
  });

  it("explains when the course could not be determined", () => {
    renderDialog([multipleChoice], { canvasState: "no-course" });
    expect(dialog().textContent).toMatch(/couldn't tell which canvas course/i);
  });
});

describe("PreviewDialog with problems", () => {
  const questions = [multipleChoice, broken("q2", "No correct answer marked", { source: { start: 10, end: 40 } })];

  it("blocks both exports and says why", () => {
    renderDialog(questions, { canvasState: "connected" });
    const reason = document.getElementById("export-blocked-reason");
    expect(reason?.textContent).toBe("Fix the 1 error above to enable export.");
    for (const name of [/export qti/i, /upload to canvas/i]) {
      const button = screen.getByRole("button", { name }) as HTMLButtonElement;
      expect(button.disabled).toBe(true);
      expect(button.getAttribute("aria-describedby")).toBe("export-blocked-reason");
    }
  });

  it("summarises the problems at the top", () => {
    renderDialog(questions);
    const summary = screen.getByRole("heading", { name: /1 question to fix before you can export/i }).closest("section")!;
    expect(within(summary).getByRole("button", { name: "Question 2" })).toBeTruthy();
    expect(summary.textContent).toContain("No correct answer marked");
    expect(within(dialog()).getByText("1 needs fixing")).toBeTruthy();
  });

  it("does not show a points badge on a question that has none", () => {
    renderDialog([broken("q1", "Missing options")]);
    expect(within(dialog()).queryByText(/point/i)).toBeNull();
  });

  it("jumps to the offending question and focuses it", async () => {
    const scrollIntoView = vi.spyOn(Element.prototype, "scrollIntoView");
    renderDialog(questions);
    await userEvent.click(screen.getByRole("button", { name: "Question 2" }));
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "start", behavior: "smooth" });
    expect(document.activeElement?.id).toBe("preview-q-1");
    scrollIntoView.mockRestore();
  });

  it("lists at most five problems and counts the rest", () => {
    const many = Array.from({ length: 7 }, (_, i) => broken(`e${i}`, `Problem ${i + 1}`));
    renderDialog(many);
    const summary = screen.getByRole("heading", { name: /7 questions to fix/i }).closest("section")!;
    expect(within(summary).getAllByRole("button")).toHaveLength(5);
    expect(summary.textContent).toContain("…and 2 more. Each is marked below.");
  });

  it("points at the problem in the user's own text, but only for pasted text", async () => {
    const props = renderDialog(questions);
    await userEvent.click(screen.getByRole("button", { name: "Show in my text" }));
    expect(props.onShowInText).toHaveBeenCalledWith({ start: 10, end: 40 });
  });

  it("has no 'Show in my text' for an uploaded file, whose offsets are not in any textarea", () => {
    renderDialog(questions, { canShowInText: false });
    expect(screen.queryByRole("button", { name: "Show in my text" })).toBeNull();
  });
});
