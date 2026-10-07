import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { StatusPanel } from "@/components/StatusPanel";
import type { Question } from "@/types/quiz";

const good = (id: string): Question => ({ id, type: "multiple_choice_question", question_text: "Q" });
const bad = (id: string): Question => ({ id, type: "error", error: "No correct answer" });

type Props = Parameters<typeof StatusPanel>[0];

function renderPanel(overrides: Partial<Props> = {}) {
  const props: Props = {
    phase: "idle",
    exportTarget: null,
    progress: 0,
    questions: null,
    result: null,
    errorMessage: null,
    onReview: vi.fn(),
    ...overrides,
  };
  render(<StatusPanel {...props} />);
  return props;
}

describe("StatusPanel", () => {
  it("is a polite live region, so changes are announced", () => {
    renderPanel();
    expect(screen.getByRole("status").getAttribute("aria-live")).toBe("polite");
  });

  it("tells a new user what to do first", () => {
    renderPanel();
    expect(screen.getByRole("status").textContent).toMatch(/check your syntax to preview/i);
  });

  it("shows that it is checking", () => {
    renderPanel({ phase: "parsing" });
    expect(screen.getByRole("status").textContent).toContain("Checking your questions");
  });

  it("shows a real percentage while uploading to Canvas", () => {
    renderPanel({ phase: "exporting", exportTarget: "canvas", progress: 64.4 });
    expect(screen.getByRole("status").textContent).toContain("Uploading to Canvas… 64%");
    expect(screen.getByRole("progressbar", { name: "Canvas upload progress" })).toBeTruthy();
  });

  it("shows no percentage for a download, which has none to report", () => {
    renderPanel({ phase: "exporting", exportTarget: "qti" });
    expect(screen.getByRole("status").textContent).toContain("Preparing your download");
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("offers review and export once every question is valid", async () => {
    const props = renderPanel({ questions: [good("1"), good("2")] });
    expect(screen.getByRole("status").textContent).toContain("2 questions ready to export.");
    await userEvent.click(screen.getByRole("button", { name: "Review & export" }));
    expect(props.onReview).toHaveBeenCalledTimes(1);
  });

  it("uses the singular for one question", () => {
    renderPanel({ questions: [good("1")] });
    expect(screen.getByRole("status").textContent).toContain("1 question ready to export.");
  });

  it("counts the problems and offers to review them", async () => {
    const props = renderPanel({ questions: [good("1"), bad("2"), bad("3")] });
    expect(screen.getByRole("status").textContent).toContain("1 of 3 questions ready, 2 need fixing.");
    await userEvent.click(screen.getByRole("button", { name: "Review problems" }));
    expect(props.onReview).toHaveBeenCalledTimes(1);
  });

  it("says 'needs' for a single problem", () => {
    renderPanel({ questions: [good("1"), bad("2")] });
    expect(screen.getByRole("status").textContent).toContain("1 needs fixing");
  });

  it.each([
    ["qti", "QTI package downloaded."],
    ["canvas", "Uploaded to Canvas. It can take a minute to appear in your course."],
  ] as const)("reports what was actually done after a %s export", (result, text) => {
    renderPanel({ questions: [good("1")], result });
    const status = screen.getByRole("status").textContent ?? "";
    expect(status).toContain(text);
    expect(status).not.toMatch(/converted/i);
    expect(screen.getByRole("button", { name: "Export again" })).toBeTruthy();
  });

  it("keeps the preview reachable under a failed export", async () => {
    const props = renderPanel({
      phase: "error",
      errorMessage: "Your Canvas session has expired. You can still download the QTI file.",
      questions: [good("1")],
    });
    const status = screen.getByRole("status").textContent ?? "";
    expect(status).toContain("Your Canvas session has expired");
    await userEvent.click(screen.getByRole("button", { name: "Review & export" }));
    expect(props.onReview).toHaveBeenCalledTimes(1);
  });

  it("shows a failed check on its own when there is no preview", () => {
    renderPanel({ phase: "error", errorMessage: "No questions were found." });
    expect(screen.getByRole("status").textContent).toContain("No questions were found.");
    expect(screen.queryByRole("button")).toBeNull();
  });
});
