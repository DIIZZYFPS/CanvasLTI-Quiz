from app.utils.parser import parse_quiz_text
import json

respondus_text = """
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

result = parse_quiz_text(respondus_text)
print(json.dumps(result, indent=2))
