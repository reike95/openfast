#
# Copyright 2017 National Renewable Energy Laboratory
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""
    This program executes OpenFAST and a regression test for a single test case.
    The test data is contained in a git submodule, r-test, which must be initialized
    prior to running. See the r-test README or OpenFAST documentation for more info.

    Get usage with: `executeOpenfastLinearRegressionCase.py -h`
"""

import os
import sys
basepath = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.sep.join([basepath, "lib"]))
import argparse
import numpy as np
import shutil
import subprocess
import rtestlib as rtl
import openfastDrivers
import pass_fail
from errorPlotting import exportCaseSummary

##### Helper functions
excludeExt=['.out','.outb','.ech','.yaml','.sum','.log']

def file_line_count(filename):
    file_handle = open(filename, 'r')
    for i, _ in enumerate(file_handle):
        pass
    file_handle.close()
    return i + 1

def isclose(a, b, rel_tol=1e-09, abs_tol=0.0):
    return abs(a-b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)

##### Main program

### Store the python executable for future python calls
pythonCommand = sys.executable

### Verify input arguments
parser = argparse.ArgumentParser(description="Executes OpenFAST and a regression test for a single test case.")
parser.add_argument("caseName", metavar="Case-Name", type=str, nargs=1, help="The name of the test case.")
parser.add_argument("executable", metavar="OpenFAST", type=str, nargs=1, help="The path to the OpenFAST executable.")
parser.add_argument("sourceDirectory", metavar="path/to/openfast_repo", type=str, nargs=1, help="The path to the OpenFAST repository.")
parser.add_argument("buildDirectory", metavar="path/to/openfast_repo/build", type=str, nargs=1, help="The path to the OpenFAST repository build directory.")
parser.add_argument("rtol", metavar="Relative-Tolerance", type=float, nargs=1, help="Relative tolerance to allow the solution to deviate; expressed as order of magnitudes less than baseline.")
parser.add_argument("atol", metavar="Absolute-Tolerance", type=float, nargs=1, help="Absolute tolerance to allow small values to pass; expressed as order of magnitudes less than baseline.")
parser.add_argument("-p", "-plot", dest="plot", action='store_true', help="bool to include plots in failed cases")
parser.add_argument("-n", "-no-exec", dest="noExec", action='store_true', help="bool to prevent execution of the test cases")
parser.add_argument("-v", "-verbose", dest="verbose", action='store_true', help="bool to include verbose system output")

args = parser.parse_args()

caseName = args.caseName[0]
executable = args.executable[0]
sourceDirectory = args.sourceDirectory[0]
buildDirectory = args.buildDirectory[0]
rtol = args.rtol[0]
atol = args.atol[0]
plotError = args.plot
noExec = args.noExec
verbose = args.verbose

# Tolerance have not been tuned for linearization case outputs.
# This is using 1e-5 since that seemed like a decent value prior to 
# switching to relative and absolute tolerance.
rtol = 1e-5
atol = 1e-5

# validate inputs
rtl.validateExeOrExit(executable)
rtl.validateDirOrExit(sourceDirectory)
if not os.path.isdir(buildDirectory):
    os.makedirs(buildDirectory)

### Build the filesystem navigation variables for running openfast on the test case
regtests = os.path.join(sourceDirectory, "reg_tests")
lib = os.path.join(regtests, "lib")
rtest = os.path.join(regtests, "r-test")
moduleDirectory = os.path.join(rtest, "glue-codes", "openfast")
inputsDirectory = os.path.join(moduleDirectory, caseName)
targetOutputDirectory = os.path.join(inputsDirectory)
testBuildDirectory = os.path.join(buildDirectory, caseName)

# verify all the required directories exist
if not os.path.isdir(rtest):
    rtl.exitWithError("The test data directory, {}, does not exist. If you haven't already, run `git submodule update --init --recursive`".format(rtest))
if not os.path.isdir(targetOutputDirectory):
    rtl.exitWithError("The test data outputs directory, {}, does not exist. Try running `git submodule update`".format(targetOutputDirectory))
if not os.path.isdir(inputsDirectory):
    rtl.exitWithError("The test data inputs directory, {}, does not exist. Verify your local repository is up to date.".format(inputsDirectory))

# create the local output directory if it does not already exist
# and initialize it with input files for all test cases
for data in ["Ideal_Beam", "WP_Baseline"]:
    dataDir = os.path.join(buildDirectory, data)
    if not os.path.isdir(dataDir):
        rtl.copyTree(os.path.join(moduleDirectory, data), dataDir, excludeExt=excludeExt)

# Special copy for the 5MW_Baseline folder because the Windows python-only workflow may have already created data in the subfolder ServoData
dst = os.path.join(buildDirectory, "5MW_Baseline")
src = os.path.join(moduleDirectory, "5MW_Baseline")
if not os.path.isdir(dst):
    rtl.copyTree(src, dst, excludeExt=excludeExt)
else:
    names = os.listdir(src)
    for name in names:
        if name == "ServoData":
            continue
        srcname = os.path.join(src, name)
        dstname = os.path.join(dst, name)
        if os.path.isdir(srcname):
            if not os.path.isdir(dstname):
                rtl.copyTree(srcname, dstname, excludeExt=excludeExt)
        else:
            shutil.copy2(srcname, dstname)

if not os.path.isdir(testBuildDirectory):
    rtl.copyTree(inputsDirectory, testBuildDirectory, excludeExt=excludeExt)

### Run openfast on the test case
if not noExec:
    caseInputFile = os.path.join(testBuildDirectory, caseName + ".fst")
    returnCode = openfastDrivers.runOpenfastCase(caseInputFile, executable)
    if returnCode != 0:
        sys.exit(returnCode*10)

### Get a all the .lin files in the baseline directory
baselineOutFiles = [f for f in os.listdir(targetOutputDirectory) if '.lin' in f]

# these should all exist in the local outputs directory
localFiles = os.listdir(testBuildDirectory)
localOutFiles = [f for f in localFiles if f in baselineOutFiles]
if len(localOutFiles) != len(baselineOutFiles):
    print("Error in case {}: an expected local solution file does not exist.".format(caseName))
    sys.exit(1)

### test for regression
for i, f in enumerate(localOutFiles):
    local_file = os.path.join(testBuildDirectory, f)
    baseline_file = os.path.join(targetOutputDirectory, f)

    # verify both files have the same number of lines
    local_file_line_count = file_line_count(local_file)
    baseline_file_line_count = file_line_count(baseline_file)
    if local_file_line_count != baseline_file_line_count:
        print("Error in case {}: local and baseline solutions have different line counts in".format(caseName))
        print("\t{}".format(local_file))
        print("\t{}".format(baseline_file))
        sys.exit(1)

    # open both files
    local_handle = open(local_file, 'r')
    baseline_handle = open(baseline_file, 'r')

    # parse the files

    # skip the first 6 lines since they are headers and may change without conseequence
    for i in range(6):
        baseline_handle.readline()
        local_handle.readline()
    
    # the next 10 lines are simulation info; save what we need
    for i in range(11):
        b_line = baseline_handle.readline()
        l_line = local_handle.readline()
        if i == 5:
            b_num_continuous_states = int(b_line.split()[-1])
            l_num_continuous_states = int(l_line.split()[-1])
        elif i == 8:
            b_num_inputs = int(b_line.split()[-1])
            l_num_inputs = int(l_line.split()[-1])
        elif i == 9:
            b_num_outputs = int(b_line.split()[-1])
            l_num_outputs = int(l_line.split()[-1])
    
    # find the "Jacobian matrices:" line
    for i in range(local_file_line_count):
        b_line = baseline_handle.readline()
        l_line = local_handle.readline()
        if "Jacobian matrices:" in l_line:
            break
    
    # skip 1 empty/header lines
    for i in range(1):
        baseline_handle.readline()
        local_handle.readline()

    # read and compare Jacobian matrices
    for i in range(local_file_line_count):
        b_line = baseline_handle.readline()
        l_line = local_handle.readline()
        if ":" in l_line:
            continue
        if len(l_line) < 5:
            break
        b_elements = b_line.split()
        l_elements = l_line.split()
        for j, l_element in enumerate(l_elements):
            l_float = float(l_element)
            b_float = float(b_elements[j])
            if not isclose(l_float, b_float, rtol, atol):
                print(f"Failed in Jacobian matrix comparison:")
                print(f"{l_float} in {local_file}")
                print(f"{b_float} in {baseline_file}")
                sys.exit(1)

    # skip 2 empty/header lines
    for i in range(2):
        baseline_handle.readline()
        local_handle.readline()

    # read and compare Linearized state matrices
    for i in range(local_file_line_count):
        b_line = baseline_handle.readline()
        l_line = local_handle.readline()
        if ":" in l_line:
            continue
        if len(l_line) < 5:
            break
        b_elements = b_line.split()
        l_elements = l_line.split()
        for j, l_element in enumerate(l_elements):
            l_float = float(l_element)
            b_float = float(b_elements[j])
            if not isclose(l_float, b_float, rtol, atol):
                print(f"Failed in state matrix comparison: {l_float} and {b_float}")
                sys.exit(1)

    local_handle.close()
    baseline_handle.close()

# passing case
sys.exit(0)
