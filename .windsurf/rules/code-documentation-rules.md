---
trigger: always_on
---

## Code Documentation Rules

### Module Doc String
- Whenever you make edits to a Python file, you must update the module docstring. It should appear before all of the imports.
- The first line of the module docstring should concisely describe the core purpose or functionality of the file.
- The following lines of the docstring should be indented, so they can be collapsed in code editors that support docstring folding. Subsections to be indented with 2 spaces.
- Functions/Models - Include the list of function/class names exactly as it is so it helps with search.
- The docstring should be kept up-to-date and accurately reflect any changes made to the file's logic or responsibilities, break the logic as bullet points. 
- Consistent and clear module docstrings improve code readability, maintainability, and onboarding for new contributors.

## Example docstring:
"""
This line includes summary
    . The dependancies based on imports
    . First step
    . Second step
  Functions/Clases
    . get_journery_instructions
    . check_live_location available
"""
