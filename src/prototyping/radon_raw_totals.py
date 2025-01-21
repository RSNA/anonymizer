# run: radon raw -i "tests,docs,src/anonymizer/prototyping" . > radon_results.txt
# then run this script to get totals
from pprint import pprint

totals = {
    "LOC": 0,  # Lines of Code
    "LLOC": 0,  # Logical Lines of Code
    "SLOC": 0,  # Source Lines of Code
    "Comments": 0,  # Number of comment lines
    "Multi": 0,  # Number of lines with multi-line strings
    "Blank": 0,  # Number of blank lines
    "Single comments": 0,  # Number of single-line comments
}

with open("./radon_results.txt", "r") as file:
    lines = file.readlines()
    for line in lines:
        line = line.strip()  # Remove whitespace
        for metric in totals:
            if line.startswith(metric + ":"):
                value = int(line.split(":")[1].strip())
                totals[metric] += value

pprint(totals, sort_dicts=False)
