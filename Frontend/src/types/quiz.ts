export interface Answer {
  id: string;
  text: string;
}

// Mirrors the loosely-typed question dicts returned by parse_quiz_text()
// (app/utils/parser.py) - the fields present depend on `type`, so
// everything but the common ones is optional rather than a discriminated
// union, matching how Dashboard.tsx actually reads this data.
export interface Question {
  id: string;
  type: string;
  question_text?: string;
  question?: string;
  points?: string;
  error?: string;
  answers?: Answer[];
  correct_answer_id?: string;
  correct_answer_ids?: string[];
  variables?: Record<string, string[]>;
}
