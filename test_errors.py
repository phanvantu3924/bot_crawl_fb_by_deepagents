import os
import sys
import time # Unused import

def calculate_sum(a, b)
    # Missing colon above (Syntax Error)
    result = a + b + undefined_variable # Undefined variable
    return result

def logic_error():
    try:
        x = 1 / 0
    except: # Bare except clause (Bad practice)
        pass

def very_long_function_name_that_exceeds_line_length_limits_and_is_generally_considered_poor_style_in_most_python_coding_standards_especially_pep8_which_recommends_shorter_lines():
    print("This line is also very long and should probably be flagged by any decent linter or AI code review tool that checks for code quality and readability.")

if __name__ == "__main__":
    print(calculate_sum(5, 10))
