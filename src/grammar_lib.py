


def estimate_unique_strings(fandango_instance):
    # Just generate 100 inputs and see how many unique ones we get as a rough estimate of the grammar's size/complexity
    try:
        solutions = fandango_instance.fuzz(desired_solutions=100, max_generations=1)
    except Exception as e:
        print(f"Error estimating unique strings: {e}")
        solutions = []
    return len(solutions)

def num_constraints_in_grammar(fandango_instance):
    return len(fandango_instance.constraints)