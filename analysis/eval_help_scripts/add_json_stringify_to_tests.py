

# Relative the parent directory
TEST_DIR = "./generated_unit_tests"

# The files are all JavaScript
# The idea is to change the first console.log in each test file, which
# hopefully will normalize the results without having to re-run test generation.

import os
import json
import os.path as path

