export interface Answer {
  id: string;
  text: string;
}

// Where a question came from in the submitted text (character offsets, end exclusive).
// Only meaningful for pasted text: for uploaded files it refers to the extracted text.
export interface SourceRange {
  start: number;
  end: number;
}

// Mirrors the loosely-typed question dicts returned by parse_quiz_text()
// (app/utils/parser.py) - the fields present depend on `type`, so
// everything but the common ones is optional rather than a discriminated
// union, matching how the preview actually reads this data.
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
  source?: SourceRange;
}
