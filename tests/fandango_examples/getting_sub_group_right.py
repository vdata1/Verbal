import fandango

def latest_matched_r1_group(tree):
    # For debug purposes, lets print
    # all_matches is a generator btw
    all_matches = tree.find_subtrees("<r1>")
    last_match = None
    for matchh in all_matches:
        last_match = matchh # Get the last match
    return last_match

def at_least_one_r1_group(tree):
    all_matches = tree.find_subtrees("<r1>")
    return any(all_matches)  # Check if there is at least one match for <r1>

if __name__ == "__main__":
    with open("./new_nested_group_wip.fan", "r") as f:
        fan_content = f.read()

    fandango_instance = fandango.Fandango(fan_content, use_cache=False)
    result = fandango_instance.fuzz(desired_solutions=10, max_generations=10)
    print("Generated parse trees:")
    for tree in result:
        print("---")
        print("Latest matched <r1> group in this tree:")
        print(latest_matched_r1_group(tree))
        print(tree) 