import argparse
import shutil
from pathlib import Path

#!/usr/bin/env python3
# This script moves grammars with constraints from a source directory to a target directory.
# Usage: python move_grammars_w_constraints.py <source_dir> <target_dir>
# Typical usage: python move_grammars_w_constraints.py ./generated_grammars_all ./generated_grammars 
#                (for immediate use with the rest of the evaluation runner)

def parse_args():
    parser = argparse.ArgumentParser(
        description="Move grammars with constraints from source to target directory."
    )
    parser.add_argument(
        "source_dir",
        type=Path,
        help="Source directory containing grammars",
    )
    parser.add_argument(
        "target_dir",
        type=Path,
        help="Target directory to move grammars to",
    )
    return parser.parse_args()


def move_grammars(source_dir: Path, target_dir: Path):
    if not source_dir.exists():
        raise FileNotFoundError(f"Source directory does not exist: {source_dir}")

    target_dir.mkdir(parents=True, exist_ok=True)

    subdirs = list(source_dir.iterdir())
    
    for subdir in subdirs:
        if subdir.is_dir():
            # Check if any of the grammars within the subdir have constraints (i.e. contain "where "in their content)
            has_constraints = False
            for grammar_file in subdir.glob("*.fan"):
                with grammar_file.open("r") as f:
                    content = f.read()
                    if "where " in content:
                        has_constraints = True
                        break
            if has_constraints:
                target_subdir = target_dir / subdir.name
                shutil.move(str(subdir), str(target_subdir))


def main():
    args = parse_args()
    move_grammars(args.source_dir, args.target_dir)


if __name__ == "__main__":
    main()