import { describe, expect, it } from "vitest";
import { countErrors, formatQuestionType, pluralize, pointsLabel } from "@/lib/quiz";
import type { Question } from "@/types/quiz";

describe("pluralize", () => {
  it("uses the singular only for exactly one", () => {
    expect(pluralize(1, "question")).toBe("question");
    expect(pluralize(0, "question")).toBe("questions");
    expect(pluralize(2, "question")).toBe("questions");
  });

  it("accepts an irregular plural", () => {
    expect(pluralize(2, "quiz", "quizzes")).toBe("quizzes");
  });
});

describe("countErrors", () => {
  it("counts only the questions that failed to parse", () => {
    const questions: Question[] = [
      { id: "1", type: "multiple_choice_question" },
      { id: "2", type: "error", error: "No correct answer" },
      { id: "3", type: "error", error: "Missing options" },
    ];
    expect(countErrors(questions)).toBe(2);
    expect(countErrors([])).toBe(0);
  });
});

describe("formatQuestionType", () => {
  it.each([
    ["multiple_choice_question", "Multiple choice"],
    ["true_false_question", "True false"],
    ["fill_in_multiple_blanks_question", "Fill in multiple blanks"],
    ["essay", "Essay"],
  ])("%s -> %s", (type, label) => {
    expect(formatQuestionType(type)).toBe(label);
  });
});

describe("pointsLabel", () => {
  it("says 'point' only for exactly one", () => {
    expect(pointsLabel("1")).toBe("1 point");
    expect(pointsLabel("1.0")).toBe("1.0 point");
    expect(pointsLabel("2")).toBe("2 points");
    expect(pointsLabel("0.5")).toBe("0.5 points");
  });

  it("has nothing to show without points", () => {
    expect(pointsLabel(undefined)).toBeNull();
    expect(pointsLabel("")).toBeNull();
  });
});
