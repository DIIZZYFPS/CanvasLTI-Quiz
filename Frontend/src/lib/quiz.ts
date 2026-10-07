import type { Question } from "@/types/quiz";

export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return count === 1 ? singular : plural;
}

export function countErrors(questions: Question[]): number {
  return questions.filter((q) => q.type === "error").length;
}

/** "multiple_choice_question" -> "Multiple choice" */
export function formatQuestionType(type: string): string {
  const words = type.replace(/_question$/, "").replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** "1" -> "1 point", "2" -> "2 points", "0.5" -> "0.5 points"; null when there is nothing to show. */
export function pointsLabel(points?: string): string | null {
  if (points === undefined || points === "") return null;
  return `${points} ${Number(points) === 1 ? "point" : "points"}`;
}
