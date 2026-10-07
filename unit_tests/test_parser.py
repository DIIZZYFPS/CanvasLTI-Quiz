import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.utils.parser import parse_quiz_text


def _only(questions):
    assert len(questions) == 1, f"expected exactly 1 question, got {len(questions)}: {questions}"
    return questions[0]


# --- Core Format: Multiple Choice / Multiple Answers ---

def test_core_mc_single_answer():
    text = "What is 2+2?\nA) 3\nB) 4\nC) 5\nAnswer: B"
    q = _only(parse_quiz_text(text))
    assert q["type"] == "multiple_choice_question"
    assert q["question_text"] == "What is 2+2?"
    correct = next(a for a in q["answers"] if a["id"] == q["correct_answer_id"])
    assert correct["text"] == "4"


def test_core_mc_multiple_answers_via_star():
    text = "Select the even numbers:\n*A) 2\nB) 3\n*C) 4\nAnswer: A, C"
    q = _only(parse_quiz_text(text))
    assert q["type"] == "multiple_answers_question"
    assert len(q["correct_answer_ids"]) == 2


def test_core_mc_insufficient_options_errors():
    text = "Pick one:\nA) Only option\nAnswer: A"
    q = _only(parse_quiz_text(text))
    assert q["type"] == "error"


# --- Core Format: True/False ---

def test_core_tf_explicit_prefix():
    text = "TF: The Earth is round.\nAnswer: True"
    q = _only(parse_quiz_text(text))
    assert q["type"] == "true_false_question"
    assert q["question_text"] == "The Earth is round."


def test_core_tf_hint_suffix():
    text = "The sky is blue (T/F)\nAnswer: True"
    q = _only(parse_quiz_text(text))
    assert q["type"] == "true_false_question"


def test_core_tf_implicit_no_prefix():
    """Regression test: plain declarative statements ending in
    'Answer: True'/'Answer: False' with no TF: prefix and no (T/F) hint
    must still be recognized as True/False questions."""
    text = (
        "SQLite supports full outer join operations natively in all "
        "legacy versions. (1 point) Answer: False"
    )
    q = _only(parse_quiz_text(text))
    assert q["type"] == "true_false_question"
    assert q["points"] == "1"
    false_answer = next(a for a in q["answers"] if a["text"] == "False")
    assert q["correct_answer_id"] == false_answer["id"]


def test_core_tf_implicit_true():
    text = "In Git, git rebase creates a new commit history. Answer: True"
    q = _only(parse_quiz_text(text))
    assert q["type"] == "true_false_question"
    true_answer = next(a for a in q["answers"] if a["text"] == "True")
    assert q["correct_answer_id"] == true_answer["id"]


# --- Core Format: Short Answer ---

def test_core_sa_explicit_prefix():
    text = "SA: What year did WWII end?\nAnswer: 1945"
    q = _only(parse_quiz_text(text))
    assert q["type"] == "short_answer_question"
    assert q["answers"][0]["text"] == "1945"


def test_core_sa_implicit_no_prefix():
    """Regression test: a plain question ending in 'Answer: ...' with no
    options, no blank, and no SA:/[Short Answer] tag must still be parsed
    as a short-answer question instead of erroring out."""
    text = (
        "What command-line tool is used to package React applications "
        "for production inside Vite? (1 point)\nAnswer: vite build"
    )
    q = _only(parse_quiz_text(text))
    assert q["type"] == "short_answer_question"
    assert q["answers"][0]["text"] == "vite build"
    assert q["points"] == "1"


def test_core_sa_implicit_answer_with_special_chars():
    text = (
        "What decorator is used in FastAPI to handle asynchronous HTTP "
        'GET requests at the route /items? (1 point)\nAnswer: @app.get("/items")'
    )
    q = _only(parse_quiz_text(text))
    assert q["type"] == "short_answer_question"
    assert q["answers"][0]["text"] == '@app.get("/items")'


# --- Core Format: Essay ---

def test_core_essay():
    text = "Essay: Explain the causes of World War I.\nPoints: 10"
    q = _only(parse_quiz_text(text))
    assert q["type"] == "essay_question"
    assert q["points"] == "10"


# --- Core Format: Fill in Multiple Blanks ---

def test_core_fmb_auto_blank():
    text = "The capital of [France] is [Paris]."
    q = _only(parse_quiz_text(text))
    assert q["type"] == "fill_in_multiple_blanks_question"
    assert q["variables"]["France"] == ["France"]
    assert q["variables"]["Paris"] == ["Paris"]


def test_core_fmb_mapped_synonyms():
    text = "The [color] jumped over the [animal].\nAnswers: color: red, animal: dog"
    q = _only(parse_quiz_text(text))
    assert q["type"] == "fill_in_multiple_blanks_question"
    assert q["variables"]["color"] == ["red"]
    assert q["variables"]["animal"] == ["dog"]


# --- Respondus Format ---

def test_respondus_mc():
    text = "Type: MC\nWhat is the capital of France?\n*A) Paris\nB) London\nC) Berlin"
    q = _only(parse_quiz_text(text))
    assert q["type"] == "multiple_choice_question"


def test_respondus_tf():
    text = "Type: TF\nThe earth is flat.\nTrue\n*False"
    q = _only(parse_quiz_text(text))
    assert q["type"] == "true_false_question"
    false_answer = next(a for a in q["answers"] if a["text"] == "False")
    assert q["correct_answer_id"] == false_answer["id"]


def test_respondus_essay():
    text = "Type: E\nPoints: 5\nExplain the theory of relativity."
    q = _only(parse_quiz_text(text))
    assert q["type"] == "essay_question"
    assert q["points"] == "5"


def test_respondus_mr_multi_select():
    text = "Type: MR\nSelect all primes:\n*A) 2\nB) 4\n*C) 3"
    q = _only(parse_quiz_text(text))
    assert q["type"] == "multiple_answers_question"
    assert len(q["correct_answer_ids"]) == 2


# --- Block splitting ---

def test_multiple_blocks_require_blank_line_separator():
    text = (
        "TF: The Earth is round.\nAnswer: True"
        "\n\n"
        "SA: What year did WWII end?\nAnswer: 1945"
    )
    questions = parse_quiz_text(text)
    assert len(questions) == 2
    assert questions[0]["type"] == "true_false_question"
    assert questions[1]["type"] == "short_answer_question"


# --- Brackets in question text (regression) ---------------------------------
# The fill-in-multiple-blanks check used to run first and treat *any* [brackets]
# as blanks, which broke the documented [Essay]/[Short Answer] tags and any
# question mentioning something like arr[0].

def test_bracket_short_answer_tag_is_short_answer_not_fmb():
    q = _only(parse_quiz_text("What is 2+2? [Short Answer]\nAnswer: 4"))
    assert q["type"] == "short_answer_question"
    assert q["answers"][0]["text"] == "4"
    assert "[Short Answer]" not in q["question_text"]


def test_bracket_essay_tag_at_end_is_essay_not_fmb():
    """The formatting guide documents ending a question with [Essay]."""
    q = _only(parse_quiz_text("Explain recursion. [Essay]"))
    assert q["type"] == "essay_question"
    assert "[Essay]" not in q["question_text"]


def test_bracket_essay_prefix_with_brackets_in_text():
    q = _only(parse_quiz_text("Essay: Describe how arr[0] differs from arr[1]."))
    assert q["type"] == "essay_question"


def test_bracket_in_mc_stem_stays_multiple_choice():
    text = "What does arr[0] return in JavaScript?\nA) The first element\nB) The last element\nAnswer: A"
    q = _only(parse_quiz_text(text))
    assert q["type"] == "multiple_choice_question"
    correct = next(a for a in q["answers"] if a["id"] == q["correct_answer_id"])
    assert correct["text"] == "The first element"


def test_bracket_in_multi_answer_stem_stays_multiple_answers():
    text = "Which of these index list[0]?\nA) list[0]\nB) list[1]\nC) first(list)\nAnswer: A, C"
    q = _only(parse_quiz_text(text))
    assert q["type"] == "multiple_answers_question"
    assert len(q["correct_answer_ids"]) == 2


def test_bracket_in_tf_stem_stays_true_false():
    q = _only(parse_quiz_text("TF: In Python, a list is written [1, 2].\nAnswer: True"))
    assert q["type"] == "true_false_question"


def test_bracket_in_short_answer_stem_without_tag():
    q = _only(parse_quiz_text("What does arr[0] return?\nAnswer: the first element"))
    assert q["type"] == "short_answer_question"
    assert q["answers"][0]["text"] == "the first element"


def test_bracket_points_marker_is_not_a_blank():
    q = _only(parse_quiz_text("What is a list? [Points: 2]\nAnswer: a sequence"))
    assert q["type"] == "short_answer_question"
    assert q["points"] == "2"


def test_fmb_typo_in_variable_name_still_gets_helpful_error():
    """A mistyped variable must keep producing the specific FMB error rather
    than silently falling through to a short-answer question."""
    q = _only(parse_quiz_text("The [colour] sky.\nAnswers: color: blue"))
    assert q["type"] == "error"
    assert "colour" in q["error"]


def test_respondus_fmb_still_parses():
    q = _only(parse_quiz_text("Type: FMB\nThe [a] is red.\na = Roses"))
    assert q["type"] == "fill_in_multiple_blanks_question"
    assert q["variables"]["a"] == ["Roses"]


def test_unbalanced_brackets_do_not_blow_up_runtime():
    """Regression: `\\[([^\\]]+)\\]` was quadratic on runs of '[' (40k chars took
    seconds; 160k about a minute) on an unauthenticated endpoint."""
    import time
    for payload in ("[" * 200_000, "[a" * 100_000, "Type: FMB\n" + "[" * 100_000):
        start = time.perf_counter()
        parse_quiz_text(payload)
        assert time.perf_counter() - start < 2.0
