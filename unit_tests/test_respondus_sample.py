import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.utils.parser import parse_quiz_text

# Formerly unit_tests/verify_respondus.py: a script that printed this sample's parse for a
# human to eyeball (pytest never collected it). Now it asserts what it used to print.
SAMPLE = """
1. What is the capital of France?
*a) Paris
b) London
c) Berlin
point 2

Type: TF
2. The earth is flat.
True
*False

Type: E
Points: 5
3. Explain the theory of relativity.

4. Standard format still works?
A) Yes
B) No
Answer: A
"""


def test_mixed_respondus_and_core_sample():
    questions = parse_quiz_text(SAMPLE)

    assert [q["type"] for q in questions] == [
        "multiple_choice_question", "true_false_question", "essay_question", "multiple_choice_question",
    ]
    assert [q["points"] for q in questions] == ["2", "1", "5", "1"]
    assert [q["question_text"] for q in questions] == [
        "What is the capital of France?",
        "The earth is flat.",
        "Explain the theory of relativity.",
        "Standard format still works?",
    ]

    def correct_text(q):
        return next(a["text"] for a in q["answers"] if a["id"] == q["correct_answer_id"])

    assert correct_text(questions[0]) == "Paris"
    assert correct_text(questions[1]) == "False"
    assert correct_text(questions[3]) == "Yes"
